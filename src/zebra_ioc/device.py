"""Framework independent Zebra device.

Owns the connection, the register access, the interrupt monitoring task and
the capture buffer. It knows nothing about EPICS, so it can be driven from a
plain script, a test, or the soft IOC in ``ioc.py``.

The split matters: everything above this line is EPICS, everything below is
the Zebra. Swapping the control system should not touch this file.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from .capture import CaptureBuffer
from .interrupts import InterruptHandler, PositionCompareData
from .protocol import ZebraProtocol
from .registers import (
    REGISTERS_32BIT_BY_NAME,
    REGISTERS_BY_NAME,
    SysBus,
)
from .transport import ZebraTransport

logger = logging.getLogger(__name__)

SYS_STAT1_LO = 0xF2
SYS_STAT1_HI = 0xF3
SYS_STAT2_LO = 0xF4
SYS_STAT2_HI = 0xF5

DEFAULT_CAPTURE_POINTS = 100000
"""Matches NELM in the legacy areaDetector driver."""


class ZebraDevice:
    """A connected Zebra.

    Registers are addressed by their legacy names (``PC_GATE_START``,
    ``AND1_INP1``), which are the names in the manual and in every existing
    piece of Zebra client code.

    Callbacks let a control system layer react to things the device reports
    asynchronously - captured points and system bus changes - without this
    module knowing what a PV is.
    """

    def __init__(
        self,
        port: str,
        capture_points: int = DEFAULT_CAPTURE_POINTS,
        poll_period: float = 0.3,
    ):
        """Initialize the device.

        Args:
            port: Serial device, 'tcp://host:port', or 'sim://name'
            capture_points: Capacity of the position compare capture arrays
            poll_period: Seconds between system bus status polls
        """
        self.port = port
        self.poll_period = poll_period

        self.capture = CaptureBuffer(capture_points)
        self.interrupts = InterruptHandler()

        self._transport: ZebraTransport | None = None
        self._protocol: ZebraProtocol | None = None
        self._interrupt_task: asyncio.Task | None = None
        self._poll_task: asyncio.Task | None = None

        self.sys_stat1 = 0
        self.sys_stat2 = 0

        self._on_capture_start: list[Callable[[], Awaitable[None]]] = []
        self._on_capture_point: list[
            Callable[[PositionCompareData], Awaitable[None]]
        ] = []
        self._on_capture_end: list[Callable[[], Awaitable[None]]] = []
        self._on_sys_stat: list[Callable[[int, int], Awaitable[None]]] = []

        self.interrupts.on_reset(self._handle_reset)
        self.interrupts.on_data(self._handle_data)
        self.interrupts.on_end(self._handle_end)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        """True if the transport is open."""
        return self._transport is not None and self._transport.connected

    async def connect(self) -> None:
        """Open the connection and start background tasks."""
        self._transport = ZebraTransport(self.port)
        await self._transport.connect()
        self._protocol = ZebraProtocol(self._transport)

        # The interrupt parser needs to know which fields are captured before
        # it can split a data message into them
        bit_cap = await self.read_register("PC_BIT_CAP")
        self.interrupts.set_bit_cap(bit_cap)

        self._interrupt_task = asyncio.create_task(self._monitor_interrupts())
        self._poll_task = asyncio.create_task(self._poll_sys_stat())

        logger.info(f"Connected to Zebra on {self.port}")

    async def disconnect(self) -> None:
        """Stop background tasks and close the connection."""
        for task in (self._interrupt_task, self._poll_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._interrupt_task = None
        self._poll_task = None

        if self._transport:
            await self._transport.disconnect()
        self._transport = None
        self._protocol = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
        return False

    # ------------------------------------------------------------------
    # Registers
    # ------------------------------------------------------------------

    def _require_protocol(self) -> ZebraProtocol:
        if self._protocol is None:
            raise RuntimeError("Not connected to Zebra")
        return self._protocol

    async def read_register(self, name: str) -> int:
        """Read a register by its legacy name.

        32-bit registers (those in REGISTERS_32BIT_BY_NAME) are read as a
        low/high pair automatically.

        Args:
            name: Register name, e.g. 'PC_GATE_START'

        Returns:
            Register value

        Raises:
            KeyError: If the name is not a known register
        """
        protocol = self._require_protocol()

        if name in REGISTERS_32BIT_BY_NAME:
            reg = REGISTERS_32BIT_BY_NAME[name]
            return await protocol.read_register_32bit(reg.address_lo, reg.address_hi)

        return await protocol.read_register(REGISTERS_BY_NAME[name].address)

    async def write_register(self, name: str, value: int) -> None:
        """Write a register by its legacy name.

        Args:
            name: Register name, e.g. 'PC_GATE_START'
            value: Value to write

        Raises:
            KeyError: If the name is not a known register
        """
        protocol = self._require_protocol()

        if name in REGISTERS_32BIT_BY_NAME:
            reg = REGISTERS_32BIT_BY_NAME[name]
            await protocol.write_register_32bit(
                reg.address_lo, reg.address_hi, value
            )
            return

        await protocol.write_register(REGISTERS_BY_NAME[name].address, value)

        if name == "PC_BIT_CAP":
            # The interrupt parser splits each data message according to this
            # mask, so it has to learn about the change at the same time the
            # hardware does, or every subsequent point fails to parse
            self.interrupts.set_bit_cap(value)

    async def arm(self) -> None:
        """Arm position compare.

        Re-reads PC_BIT_CAP first, so a mask changed out of band - restored
        from flash, or set by another client - is picked up rather than
        corrupting the whole capture.
        """
        self.interrupts.set_bit_cap(await self.read_register("PC_BIT_CAP"))
        await self.write_register("PC_ARM", 1)

    async def disarm(self) -> None:
        """Disarm position compare."""
        await self.write_register("PC_DISARM", 1)

    async def save_to_flash(self) -> None:
        """Write the current register set to non-volatile memory."""
        await self._require_protocol().flash_command("S")

    async def load_from_flash(self) -> None:
        """Restore the register set saved in non-volatile memory."""
        await self._require_protocol().flash_command("L")

    async def configure(self, settings: dict[str, int]) -> None:
        """Write several registers in one go.

        Args:
            settings: Mapping of register name to value
        """
        for name, value in settings.items():
            await self.write_register(name, value)

    def sys_bus_bit(self, signal: SysBus | int) -> bool:
        """Current state of one system bus signal.

        Args:
            signal: SysBus member or bus index 0-63

        Returns:
            True if the signal is currently high
        """
        index = int(signal)
        if index < 32:
            return bool((self.sys_stat1 >> index) & 1)
        return bool((self.sys_stat2 >> (index - 32)) & 1)

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def on_capture_start(self, callback) -> None:
        """Register a coroutine called when a capture begins (PR)."""
        self._on_capture_start.append(callback)

    def on_capture_point(self, callback) -> None:
        """Register a coroutine called with each captured point."""
        self._on_capture_point.append(callback)

    def on_capture_end(self, callback) -> None:
        """Register a coroutine called when a capture ends (PX)."""
        self._on_capture_end.append(callback)

    def on_sys_stat(self, callback) -> None:
        """Register a coroutine called with (sys_stat1, sys_stat2) each poll."""
        self._on_sys_stat.append(callback)

    async def _handle_reset(self) -> None:
        self.capture.reset()
        for callback in self._on_capture_start:
            await callback()

    async def _handle_data(self, data: PositionCompareData) -> None:
        self.capture.append(data)
        for callback in self._on_capture_point:
            await callback(data)

    async def _handle_end(self) -> None:
        for callback in self._on_capture_end:
            await callback()

    # ------------------------------------------------------------------
    # Background tasks
    # ------------------------------------------------------------------

    async def _monitor_interrupts(self) -> None:
        """Read unsolicited P messages and dispatch them."""
        try:
            while self._transport and self._transport.connected:
                try:
                    message = await self._transport.read_interrupt(timeout=0.1)
                except TimeoutError:
                    await asyncio.sleep(0.01)
                    continue

                try:
                    await self.interrupts.handle_message(message)
                except ValueError as e:
                    logger.error(f"Bad interrupt message: {e}")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Interrupt monitor stopped")
            raise

    async def _poll_sys_stat(self) -> None:
        """Poll the two system bus status registers."""
        try:
            while self._transport and self._transport.connected:
                try:
                    protocol = self._require_protocol()
                    self.sys_stat1 = await protocol.read_register_32bit(
                        SYS_STAT1_LO, SYS_STAT1_HI
                    )
                    self.sys_stat2 = await protocol.read_register_32bit(
                        SYS_STAT2_LO, SYS_STAT2_HI
                    )
                    for callback in self._on_sys_stat:
                        await callback(self.sys_stat1, self.sys_stat2)
                except Exception as e:
                    logger.error(f"System status poll failed: {e}")

                await asyncio.sleep(self.poll_period)
        except asyncio.CancelledError:
            raise
