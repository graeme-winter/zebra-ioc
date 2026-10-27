"""EPICS record layer for the Zebra.

Builds the whole PV interface from the register tables in ``registers.py``
rather than from a hand written list. The Zebra's register map is very
regular - four each of AND, OR, GATE, PULSE and DIV, eight outputs - so the
records generate from a loop, which is exactly what the legacy driver does
with EPICS template substitution.

PV names are the legacy ALL_CAPS names, so that existing Zebra client code
(ophyd devices, bluesky plans, CS-Studio screens, scripts) works against this
IOC unmodified.

Record shapes:

===================  =========================================================
Register type        Records
===================  =========================================================
RW, 16 or 32 bit     ``<NAME>`` longout, ``<NAME>_RBV`` longin
MUX                  ``<NAME>`` longout, ``<NAME>_RBV`` longin,
                     ``<NAME>_STR`` stringin with the system bus signal name
RO                   ``<NAME>`` longin
CMD                  ``<NAME>`` action (bo)
===================  =========================================================

Plus the position compare capture waveforms, the 64 system bus bits, and a
handful of IOC level status PVs that have no register behind them.
"""

import logging

import numpy as np
from softioc import builder

from .capture import ALL_FIELDS
from .device import ZebraDevice
from .registers import (
    REGISTERS_32BIT_BY_NAME,
    REGISTERS_BY_NAME,
    RegisterType,
    SysBus,
)

logger = logging.getLogger(__name__)

#: Registers whose low/high halves are exposed only as the 32-bit pair.
#: Listing them individually would give two PVs that fight over one value.
_HIDDEN_HALVES = {"SYS_STAT1", "SYS_STAT2", "PC_NUM_CAP"}

#: Capture array PV names, keyed by the CaptureBuffer field name.
CAPTURE_PVS = {
    "time": "PC_TIME",
    "enc1": "PC_ENC1",
    "enc2": "PC_ENC2",
    "enc3": "PC_ENC3",
    "enc4": "PC_ENC4",
    "sys1": "PC_SYS1",
    "sys2": "PC_SYS2",
    "div1": "PC_DIV1",
    "div2": "PC_DIV2",
    "div3": "PC_DIV3",
    "div4": "PC_DIV4",
}

#: Capture fields that also get a scalar "most recent value" PV, as
#: PC_<NAME>_LAST. These are the ones the legacy Diamond driver defines; it
#: has no _LAST for the timestamp or the system bus, so neither do we.
LAST_VALUE_FIELDS = ("enc1", "enc2", "enc3", "enc4", "div1", "div2", "div3", "div4")

#: Seconds between capture array updates while a capture is running.
#: Publishing per point would put one CA update on the wire per captured
#: point, which at a few kHz is not something to do to a network.
DEFAULT_FLUSH_PERIOD = 0.2

_SYS_BUS_NAMES = {int(signal): signal.name for signal in SysBus}


def _hidden_half_addresses() -> set[int]:
    """Addresses that belong to a 32-bit pair we expose only as a pair."""
    addresses = set()
    for name in _HIDDEN_HALVES:
        reg = REGISTERS_32BIT_BY_NAME[name]
        addresses.add(reg.address_lo)
        addresses.add(reg.address_hi)
    return addresses


class ZebraIOC:
    """Builds and services the Zebra's EPICS records.

    Create it before ``softioc.iocInit``, then call ``start`` once the event
    loop is running.
    """

    def __init__(
        self,
        device: ZebraDevice,
        flush_period: float = DEFAULT_FLUSH_PERIOD,
    ):
        """Create the records.

        Args:
            device: The Zebra to serve. Need not be connected yet.
            flush_period: Minimum seconds between capture array updates
        """
        self.device = device
        self._flush_period = flush_period
        self._last_flush = 0.0

        self._records: list[object] = []
        self._readbacks: dict[str, object] = {}
        self._mux_strings: dict[str, object] = {}
        self._arrays: dict[str, object] = {}

        self._build_register_records()
        self._build_capture_records()
        self._build_sys_bus_records()
        self._build_status_records()
        self._build_command_records()

        device.on_capture_start(self._on_capture_start)
        device.on_capture_point(self._on_capture_point)
        device.on_capture_end(self._on_capture_end)
        device.on_sys_stat(self._on_sys_stat)

        logger.info(f"Created {builder.CountRecords()} records")

    # ------------------------------------------------------------------
    # Record construction
    # ------------------------------------------------------------------

    def _track(self, record):
        """Remember a record so record_names() can report it."""
        self._records.append(record)
        return record

    def _make_setter(self, name: str):
        """Build the on_update coroutine for a writable register."""

        async def setter(value: int) -> None:
            try:
                await self.device.write_register(name, int(value))
            except Exception as e:
                logger.error(f"Write to {name} failed: {e}")
                return
            await self._update_readback(name, int(value))

        return setter

    def _make_command(self, name: str):
        """Build the on_update coroutine for a command register."""

        async def action(_value) -> None:
            try:
                await self.device.write_register(name, 1)
                logger.info(f"{name} issued")
            except Exception as e:
                logger.error(f"Command {name} failed: {e}")

        return action

    def _add_writable(self, name: str) -> None:
        """Add the demand/readback pair for one writable register."""
        self._readbacks[name] = self._track(
            builder.longIn(f"{name}_RBV", initial_value=0)
        )
        self._track(
            builder.longOut(
                name,
                initial_value=0,
                always_update=True,
                on_update=self._make_setter(name),
            )
        )

    def _build_register_records(self) -> None:
        """Generate records for every register in the tables."""
        hidden = _hidden_half_addresses()

        # 32-bit pairs first, so their halves can be skipped below
        pair_addresses = set()
        for name, reg in REGISTERS_32BIT_BY_NAME.items():
            pair_addresses.add(reg.address_lo)
            pair_addresses.add(reg.address_hi)
            if name in _HIDDEN_HALVES:
                continue  # exposed as capture/status PVs instead
            self._add_writable(name)

        for name, reg in REGISTERS_BY_NAME.items():
            if reg.address in hidden or reg.address in pair_addresses:
                continue

            match reg.reg_type:
                case RegisterType.CMD:
                    self._track(
                        builder.Action(name, on_update=self._make_command(name))
                    )
                case RegisterType.RO:
                    self._readbacks[name] = self._track(
                        builder.longIn(name, initial_value=0)
                    )
                case RegisterType.MUX:
                    self._add_writable(name)
                    self._mux_strings[name] = self._track(
                        builder.stringIn(
                            f"{name}_STR", initial_value="DISCONNECT"
                        )
                    )
                case _:
                    self._add_writable(name)

    def _build_capture_records(self) -> None:
        """Waveforms and counters for the position compare capture."""
        length = self.device.capture.max_points

        for field, _, dtype in ALL_FIELDS:
            self._arrays[field] = self._track(
                builder.WaveformIn(
                    CAPTURE_PVS[field],
                    np.zeros(length, dtype=dtype),
                )
            )

        # Scalar "most recent value" PVs. Updated straight from each
        # captured point rather than from the buffer, so they keep tracking
        # even after the buffer fills - a counter that silently freezes is
        # worse than one that stops being archived.
        self._last_values = {}
        for field in LAST_VALUE_FIELDS:
            self._last_values[field] = self._track(
                builder.longIn(f"{CAPTURE_PVS[field]}_LAST", initial_value=0)
            )

        self.pc_num_down = self._track(
            builder.longIn("PC_NUM_DOWN", initial_value=0)
        )
        self.pc_capture_max = self._track(
            builder.longIn("PC_CAPTURE_MAX", initial_value=length)
        )
        self.pc_overflow = self._track(
            builder.boolIn("PC_OVERFLOW", ZNAM="Ok", ONAM="Overflow")
        )

    def _build_sys_bus_records(self) -> None:
        """One bi record per system bus signal, named after the signal."""
        self._sys_bits = {}
        for signal in SysBus:
            index = int(signal)
            if index == 0:
                continue  # DISCONNECT is not a real signal
            self._sys_bits[index] = self._track(
                builder.boolIn(f"SYS_BUS_{signal.name}", ZNAM="Low", ONAM="High")
            )

    def _build_command_records(self) -> None:
        """Commands that are protocol level, not register writes.

        Saving and restoring flash are the 'S' and 'L' wire commands, so
        they have no register in the tables and would otherwise get no PV.
        """

        async def store(_value) -> None:
            try:
                await self.device.save_to_flash()
                self.status_msg.set("Saved to flash")
            except Exception as e:
                logger.error(f"Save to flash failed: {e}")

        async def restore(_value) -> None:
            try:
                await self.device.load_from_flash()
                self.status_msg.set("Loaded from flash")
            except Exception as e:
                logger.error(f"Load from flash failed: {e}")
                return
            await self.read_all()

        self._track(builder.Action("STORE", on_update=store))
        self._track(builder.Action("RESTORE", on_update=restore))

    def _build_status_records(self) -> None:
        """IOC level status, with no register behind it."""
        self.connected = self._track(
            builder.boolIn("CONNECTED", ZNAM="Disconnected", ONAM="Connected")
        )
        self.status_msg = self._track(
            builder.stringIn("STATUS", initial_value="Starting")
        )
        self.pc_capturing = self._track(
            builder.boolIn("PC_CAPTURING", ZNAM="Idle", ONAM="Capturing")
        )

    def record_names(self) -> list[str]:
        """Every PV this IOC creates, fully qualified.

        Useful for checking the interface without starting a CA server.
        """
        return sorted(str(record) for record in self._records)

    # ------------------------------------------------------------------
    # Runtime
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect to the Zebra and prime every readback.

        Call this once the event loop is running, after ``softioc.iocInit``.
        """
        await self.device.connect()
        self.connected.set(True)
        self.status_msg.set(f"Connected to {self.device.port}")
        await self.read_all()

    async def stop(self) -> None:
        """Disconnect from the Zebra."""
        await self.device.disconnect()
        self.connected.set(False)
        self.status_msg.set("Disconnected")

    async def read_all(self) -> None:
        """Read every register back from the hardware into its readback PV.

        Run at startup so the PVs reflect the box rather than zeros. The
        Zebra holds its configuration in volatile memory, so whatever was
        there before the IOC started is still the live configuration.
        """
        for name in self._readbacks:
            try:
                value = await self.device.read_register(name)
            except Exception as e:
                logger.error(f"Initial read of {name} failed: {e}")
                continue
            await self._update_readback(name, value)

        logger.info(f"Read back {len(self._readbacks)} registers")

    async def _update_readback(self, name: str, value: int) -> None:
        """Push a register value into its readback PV and any derived PV."""
        readback = self._readbacks.get(name)
        if readback is not None:
            readback.set(value)

        mux_string = self._mux_strings.get(name)
        if mux_string is not None:
            mux_string.set(_SYS_BUS_NAMES.get(value, f"UNKNOWN({value})"))

    # ------------------------------------------------------------------
    # Device callbacks
    # ------------------------------------------------------------------

    async def _on_capture_start(self) -> None:
        self._last_flush = 0.0
        for record in self._last_values.values():
            record.set(0)
        self.pc_capturing.set(True)
        self.status_msg.set("Capturing")
        await self._publish_capture(force=True)

    async def _on_capture_point(self, data) -> None:
        for field, attribute, _ in ALL_FIELDS:
            record = self._last_values.get(field)
            if record is None:
                continue
            value = getattr(data, attribute)
            if value is not None:
                record.set(int(value))

        await self._publish_capture()

    async def _on_capture_end(self) -> None:
        await self._publish_capture(force=True)
        self.pc_capturing.set(False)
        self.status_msg.set(f"Capture complete: {self.device.capture.count} points")

    async def _on_sys_stat(self, sys_stat1: int, sys_stat2: int) -> None:
        for index, record in self._sys_bits.items():
            if index < 32:
                record.set(bool((sys_stat1 >> index) & 1))
            else:
                record.set(bool((sys_stat2 >> (index - 32)) & 1))

    async def _publish_capture(self, force: bool = False) -> None:
        """Push the capture buffer into the waveform PVs, rate limited."""
        import time

        now = time.monotonic()
        if not force and now - self._last_flush < self._flush_period:
            return
        self._last_flush = now

        for field, values in self.device.capture.arrays().items():
            self._arrays[field].set(values)

        self.pc_num_down.set(self.device.capture.count)
        self.pc_overflow.set(self.device.capture.overflowed)
