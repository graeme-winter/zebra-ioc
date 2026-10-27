"""Interrupt message handling for Zebra position compare data.

The Zebra sends asynchronous interrupt messages starting with 'P' when
position compare events occur:

- PR: Reset buffers, start of acquisition
- P<TTTTTTTT><EEEEEEEE>...: Timestamp and data fields
- PX: End of acquisition

The number and meaning of data fields depends on PC_BIT_CAP register:
- Bit 0: Encoder 1 (signed 32-bit)
- Bit 1: Encoder 2 (signed 32-bit)
- Bit 2: Encoder 3 (signed 32-bit)
- Bit 3: Encoder 4 (signed 32-bit)
- Bit 4: System Bus 1 (unsigned 32-bit, signals 0-31)
- Bit 5: System Bus 2 (unsigned 32-bit, signals 32-63)
- Bit 6: Divider 1 count (unsigned 32-bit)
- Bit 7: Divider 2 count (unsigned 32-bit)
- Bit 8: Divider 3 count (unsigned 32-bit)
- Bit 9: Divider 4 count (unsigned 32-bit)
"""

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PositionCompareData:
    """Position compare capture data point.

    Contains timestamp and up to 10 data fields (4 encoders, 2 system bus,
    4 dividers) depending on PC_BIT_CAP configuration.
    """

    timestamp: int  # 32-bit timestamp counter
    encoder1: int | None = None  # Signed 32-bit encoder count
    encoder2: int | None = None
    encoder3: int | None = None
    encoder4: int | None = None
    sysbus1: int | None = None  # Unsigned 32-bit bus state (signals 0-31)
    sysbus2: int | None = None  # Unsigned 32-bit bus state (signals 32-63)
    div1: int | None = None  # Unsigned 32-bit divider count
    div2: int | None = None
    div3: int | None = None
    div4: int | None = None


class InterruptHandler:
    """Handles asynchronous interrupt messages from Zebra.

    Monitors serial port for 'P' messages, parses position compare data,
    and dispatches to registered callbacks.
    """

    # Interrupt message patterns
    RESET_PATTERN = re.compile(r"^PR$")
    END_PATTERN = re.compile(r"^PX$")
    DATA_PATTERN = re.compile(r"^P([0-9A-F]{8})(.*)$")

    def __init__(self, bit_cap: int = 0):
        """Initialize interrupt handler.

        Args:
            bit_cap: PC_BIT_CAP register value (which fields are captured)
        """
        self.bit_cap = bit_cap
        self._reset_callbacks: list[Callable[[], Awaitable[None]]] = []
        self._data_callbacks: list[
            Callable[[PositionCompareData], Awaitable[None]]
        ] = []
        self._end_callbacks: list[Callable[[], Awaitable[None]]] = []

    def set_bit_cap(self, bit_cap: int) -> None:
        """Update PC_BIT_CAP configuration.

        Args:
            bit_cap: New PC_BIT_CAP register value
        """
        self.bit_cap = bit_cap
        logger.debug(f"Updated PC_BIT_CAP to {bit_cap:#06x}")

    def clear_callbacks(self) -> None:
        """Remove all registered callbacks.

        Useful for testing or when re-initializing the handler.
        """
        self._reset_callbacks.clear()
        self._data_callbacks.clear()
        self._end_callbacks.clear()

    def on_reset(
        self, callback: Callable[[], Awaitable[None]]
    ) -> Callable[[], Awaitable[None]]:
        """Register callback for acquisition reset (PR message).

        Args:
            callback: Async function called on reset

        Returns:
            The callback (for use as decorator)
        """
        self._reset_callbacks.append(callback)
        return callback

    def on_data(
        self, callback: Callable[[PositionCompareData], Awaitable[None]]
    ) -> Callable[[PositionCompareData], Awaitable[None]]:
        """Register callback for data capture (P<data> message).

        Args:
            callback: Async function called with each data point

        Returns:
            The callback (for use as decorator)
        """
        self._data_callbacks.append(callback)
        return callback

    def on_end(
        self, callback: Callable[[], Awaitable[None]]
    ) -> Callable[[], Awaitable[None]]:
        """Register callback for acquisition end (PX message).

        Args:
            callback: Async function called on end

        Returns:
            The callback (for use as decorator)
        """
        self._end_callbacks.append(callback)
        return callback

    async def handle_message(self, message: str) -> bool:
        """Parse and dispatch interrupt message.

        Args:
            message: Raw message line from Zebra

        Returns:
            True if message was an interrupt, False otherwise

        Raises:
            ValueError: If interrupt message format invalid
        """
        if not message.startswith("P"):
            return False  # Not an interrupt

        # Check for reset message
        if self.RESET_PATTERN.match(message):
            logger.debug("Position compare reset (PR)")
            await self._dispatch_reset()
            return True

        # Check for end message
        if self.END_PATTERN.match(message):
            logger.debug("Position compare complete (PX)")
            await self._dispatch_end()
            return True

        # Parse data message
        match = self.DATA_PATTERN.match(message)
        if not match:
            raise ValueError(f"Invalid interrupt message format: {message!r}")

        timestamp_str, data_str = match.groups()
        timestamp = int(timestamp_str, 16)

        # Parse data fields based on bit_cap
        data = self._parse_data_fields(timestamp, data_str)
        logger.debug(f"Position compare data: ts={timestamp:#010x}")

        await self._dispatch_data(data)
        return True

    def _parse_data_fields(self, timestamp: int, data_str: str) -> PositionCompareData:
        """Parse data fields from interrupt message.

        Args:
            timestamp: Parsed timestamp value
            data_str: Remaining hex data string

        Returns:
            Parsed data point

        Raises:
            ValueError: If data string length doesn't match bit_cap
        """
        data = PositionCompareData(timestamp=timestamp)

        # Each enabled bit adds 8 hex chars (32 bits)
        num_fields = bin(self.bit_cap).count("1")
        expected_len = num_fields * 8

        if len(data_str) != expected_len:
            raise ValueError(
                f"Data length mismatch: expected {expected_len} chars "
                f"for bit_cap {self.bit_cap:#06x}, got {len(data_str)}"
            )

        # Parse fields in order of bit position
        offset = 0

        # Field mapping: (bit, field_name, is_signed)
        field_map = [
            (0, "encoder1", True),
            (1, "encoder2", True),
            (2, "encoder3", True),
            (3, "encoder4", True),
            (4, "sysbus1", False),
            (5, "sysbus2", False),
            (6, "div1", False),
            (7, "div2", False),
            (8, "div3", False),
            (9, "div4", False),
        ]

        for bit, field_name, is_signed in field_map:
            if self.bit_cap & (1 << bit):
                # Extract 8 hex chars (32 bits)
                hex_str = data_str[offset : offset + 8]
                offset += 8

                # Parse as unsigned 32-bit
                unsigned_value = int(hex_str, 16)

                # Convert to signed if needed
                if is_signed:
                    # Two's complement for signed 32-bit
                    if unsigned_value >= 0x80000000:
                        value = unsigned_value - 0x100000000
                    else:
                        value = unsigned_value
                else:
                    value = unsigned_value

                setattr(data, field_name, value)

        return data

    async def _dispatch_reset(self) -> None:
        """Call all reset callbacks."""
        for callback in self._reset_callbacks:
            try:
                await callback()
            except Exception as e:
                logger.error(f"Error in reset callback: {e}", exc_info=True)

    async def _dispatch_data(self, data: PositionCompareData) -> None:
        """Call all data callbacks.

        Args:
            data: Parsed data point
        """
        for callback in self._data_callbacks:
            try:
                await callback(data)
            except Exception as e:
                logger.error(f"Error in data callback: {e}", exc_info=True)

    async def _dispatch_end(self) -> None:
        """Call all end callbacks."""
        for callback in self._end_callbacks:
            try:
                await callback()
            except Exception as e:
                logger.error(f"Error in end callback: {e}", exc_info=True)
