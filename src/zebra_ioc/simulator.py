"""Zebra hardware simulator for testing without real hardware.

Simulates the Zebra serial protocol, allowing testing and development without
physical hardware. Responds to register read/write commands and can generate
position compare interrupt messages.
"""

import asyncio
import logging
import random
from collections.abc import Callable

logger = logging.getLogger(__name__)


class ZebraSimulator:
    """Software simulator for Zebra hardware.

    Implements the Zebra serial protocol for testing. Maintains simulated
    register state and generates position compare interrupts when armed.
    """

    def __init__(self):
        """Initialize simulator with default register values."""
        # Simulated register memory (256 registers, 16-bit each)
        self.memory: dict[int, int] = {}
        for addr in range(256):
            self.memory[addr] = 0

        # Set some default values
        self.memory[0xF0] = 0x0020  # SYS_VER - firmware version
        self.memory[0xF1] = 0x0000  # SYS_STATERR - no errors
        self.memory[0x89] = 5  # PC_TSPRE - default prescaler
        for addr in range(0x4C, 0x50):  # PULSE1-4_PRE - default prescaler
            self.memory[addr] = 5

        # Position compare state
        self._armed = False
        self._pc_counter = 0
        self._pc_task: asyncio.Task | None = None

        # Callback for sending messages (set by transport)
        self._send_callback: Callable[[str], None] | None = None

    def _update_sys_stat(self) -> None:
        """Recompute the system bus status registers from the configuration.

        A partial model: soft inputs drive their own bus signals, and the
        AND and OR blocks are evaluated from their INP/ENA/INV registers.
        The timing blocks (GATE, PULSE, DIV) are not modelled, so their bus
        signals stay low. Enough to exercise routing, not a substitute for
        hardware.
        """
        bus = dict.fromkeys(range(64), False)

        # Soft inputs: SOFT_IN register bits 0-3 drive bus signals 60-63
        soft_in = self.memory.get(0x7F, 0)
        for i in range(4):
            bus[60 + i] = bool((soft_in >> i) & 1)

        # AND1-4 are bus 32-35, OR1-4 are bus 36-39
        for block in range(4):
            for kind, inv_base, ena_base, inp_base, out_base in (
                ("and", 0x00, 0x04, 0x08, 32),
                ("or", 0x18, 0x1C, 0x20, 36),
            ):
                inv = self.memory.get(inv_base + block, 0)
                ena = self.memory.get(ena_base + block, 0)
                if not ena:
                    continue

                values = []
                for i in range(4):
                    if not (ena >> i) & 1:
                        continue
                    source = self.memory.get(inp_base + block * 4 + i, 0)
                    value = bus.get(source, False)
                    if (inv >> i) & 1:
                        value = not value
                    values.append(value)

                if values:
                    bus[out_base + block] = (
                        all(values) if kind == "and" else any(values)
                    )

        stat1 = sum(1 << i for i in range(32) if bus[i])
        stat2 = sum(1 << i for i in range(32) if bus[32 + i])

        self.memory[0xF2] = stat1 & 0xFFFF
        self.memory[0xF3] = (stat1 >> 16) & 0xFFFF
        self.memory[0xF4] = stat2 & 0xFFFF
        self.memory[0xF5] = (stat2 >> 16) & 0xFFFF

    def set_send_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback function for sending messages to host.

        Args:
            callback: Function to call with message strings
        """
        self._send_callback = callback

    async def process_command(self, command: str) -> str:
        """Process a command and return response.

        Args:
            command: Command string (without line terminator)

        Returns:
            Response string (without line terminator)
        """
        command = command.strip()

        # Flash save command
        if command == "S":
            await asyncio.sleep(0.01)  # Simulate flash write time
            logger.debug("Simulator: Flash save")
            return "SOK"

        # Flash load command
        if command == "L":
            await asyncio.sleep(0.01)  # Simulate flash read time
            logger.debug("Simulator: Flash load")
            return "LOK"

        # Read register command: R<AA>
        if command.startswith("R") and len(command) == 3:
            if 0xF2 <= int(command[1:3], 16) <= 0xF5:
                self._update_sys_stat()
            try:
                addr = int(command[1:3], 16)
                if addr in self.memory:
                    value = self.memory[addr]
                    logger.debug(f"Simulator: Read reg 0x{addr:02X} = 0x{value:04X}")
                    return f"R{addr:02X}{value:04X}"
                else:
                    logger.warning(f"Simulator: Invalid read address 0x{addr:02X}")
                    return f"E1R{addr:02X}"
            except ValueError:
                return "E0"

        # Write register command: W<AA><VVVV>
        if command.startswith("W") and len(command) == 7:
            try:
                addr = int(command[1:3], 16)
                value = int(command[3:7], 16)

                if addr not in self.memory:
                    logger.warning(f"Simulator: Invalid write address 0x{addr:02X}")
                    return f"E1W{addr:02X}"

                # Reject writes to read-only registers (0xF0-0xF7)
                if 0xF0 <= addr <= 0xF7:
                    logger.warning(
                        f"Simulator: Cannot write to read-only register 0x{addr:02X}"
                    )
                    return f"E1W{addr:02X}"

                self.memory[addr] = value
                logger.debug(f"Simulator: Write reg 0x{addr:02X} = 0x{value:04X}")

                # Handle special registers
                write_response = f"W{addr:02X}OK"

                # PC_ARM (0x8B) - Start position compare
                if addr == 0x8B and value == 1:
                    logger.info("Simulator: Position compare armed")
                    self._armed = True
                    self._pc_counter = 0
                    # Send PR (reset buffers) as interrupt message via callback
                    if self._send_callback:
                        self._send_callback("PR")
                    # Start generating position compare data
                    if self._pc_task is None or self._pc_task.done():
                        self._pc_task = asyncio.create_task(
                            self._generate_position_compare()
                        )

                # PC_DISARM (0x8C) - Stop position compare
                elif addr == 0x8C and value == 1:
                    logger.info("Simulator: Position compare disarmed")
                    self._armed = False
                    # Send PX (end of acquisition) as interrupt message via callback
                    if self._send_callback:
                        self._send_callback("PX")
                    if self._pc_task and not self._pc_task.done():
                        self._pc_task.cancel()

                return write_response

            except ValueError:
                return "E0"

        # Unknown command
        logger.warning(f"Simulator: Unknown command '{command}'")
        return "E0"

    async def _generate_position_compare(self) -> None:
        """Background task to generate position compare interrupt messages."""
        try:
            while self._armed:
                # Generate a position compare message
                timestamp = self._pc_counter * 50  # Increment by 50 each time
                message = f"P{timestamp:08X}"

                # Check which data to capture (PC_BIT_CAP register 0x9F)
                bit_cap = self.memory.get(0x9F, 0)

                # Generate simulated data for each enabled capture bit
                for bit in range(10):
                    if (bit_cap >> bit) & 1:
                        # Generate random simulated data
                        if bit < 4:  # Encoders (signed 32-bit)
                            # Simulate encoder position incrementing
                            base = self._pc_counter * 100
                            noise = random.randint(-10, 10)
                            value = (base + noise) & 0xFFFFFFFF
                        elif bit < 6:  # System bus (unsigned 32-bit bit field)
                            # Simulate random system bus state
                            value = random.randint(0, 0xFFFFFFFF)
                        else:  # Dividers (unsigned 32-bit)
                            # Simulate divider counts
                            value = self._pc_counter * 10
                        message += f"{value:08X}"

                # Send the interrupt message via callback
                if self._send_callback:
                    self._send_callback(message)

                self._pc_counter += 1

                # Update PC_NUM_CAP registers (0xF6/0xF7)
                self.memory[0xF6] = self._pc_counter & 0xFFFF  # Low 16 bits
                self.memory[0xF7] = (self._pc_counter >> 16) & 0xFFFF  # High 16 bits

                # Generate data at ~10Hz
                await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.debug("Simulator: Position compare generation cancelled")
            raise

    def reset(self) -> None:
        """Reset simulator to initial state."""
        self._armed = False
        self._pc_counter = 0
        if self._pc_task and not self._pc_task.done():
            self._pc_task.cancel()

        # Reset registers to defaults
        for addr in range(256):
            self.memory[addr] = 0
        self.memory[0xF0] = 0x0020
        self.memory[0xF1] = 0x0000
        self.memory[0x89] = 5
