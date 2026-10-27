"""Zebra serial protocol implementation.

This module implements the text-based serial protocol for Zebra hardware,
building on top of the ZebraTransport layer to provide register read/write
operations and command/response parsing.

Protocol format:
- Read register: R<AA> -> R<AA><VVVV>
- Write register: W<AA><VVVV> -> W<AA>OK
- Save to flash: S -> SOK
- Load from flash: L -> LOK
- Error: E0 (malformed), E1R<AA> (read error), E1W<AA> (write error)

Where:
- <AA> = 2-digit hex register address (00-FF)
- <VVVV> = 4-digit hex value (0000-FFFF, 16-bit)
"""

import asyncio
import logging
import re
from typing import Literal

from .transport import ZebraTransport

logger = logging.getLogger(__name__)


class ProtocolError(Exception):
    """Base exception for protocol-level errors."""

    pass


class MalformedResponseError(ProtocolError):
    """Raised when response doesn't match expected format."""

    pass


class RegisterError(ProtocolError):
    """Raised when register operation fails (E1 response)."""

    pass


class ZebraProtocol:
    """Zebra serial protocol handler.

    Provides high-level register read/write operations and command execution
    using the Zebra text-based serial protocol. Handles response parsing,
    error detection, and verification.
    """

    # Response format patterns
    READ_RESPONSE_PATTERN = re.compile(r"^R([0-9A-F]{2})([0-9A-F]{4})$")
    WRITE_RESPONSE_PATTERN = re.compile(r"^W([0-9A-F]{2})OK$")
    ERROR_PATTERN = re.compile(r"^E([01])([RW])?([0-9A-F]{2})?$")

    def __init__(self, transport: ZebraTransport):
        """Initialize protocol handler.

        Args:
            transport: Connected ZebraTransport instance
        """
        self.transport = transport
        # Lock to serialize all register operations - serial requires strict
        # request-response pairing, only one operation at a time
        self._lock = asyncio.Lock()

    async def _read_register_unlocked(self, address: int) -> int:
        """Read a 16-bit register value without acquiring lock.

        Internal method - caller must hold self._lock.

        Args:
            address: Register address (0x00-0xFF)

        Returns:
            Register value (0x0000-0xFFFF)

        Raises:
            ValueError: If address out of range
            ProtocolError: If read fails or response invalid
        """
        if not 0 <= address <= 0xFF:
            raise ValueError(
                f"Register address {address:#04x} out of range [0x00-0xFF]"
            )

        # Send read command: R<AA>
        command = f"R{address:02X}"
        logger.debug(f"Reading register {address:#04x}")

        await self.transport.write_line(command)

        # Get response: R<AA><VVVV> or error
        response = await self.transport.read_line()
        return self._parse_read_response(address, response)

    async def read_register(self, address: int) -> int:
        """Read a 16-bit register value.

        Args:
            address: Register address (0x00-0xFF)

        Returns:
            Register value (0x0000-0xFFFF)

        Raises:
            ValueError: If address out of range
            ProtocolError: If read fails or response invalid
        """
        # Acquire lock to ensure atomic read operation (command + response)
        async with self._lock:
            return await self._read_register_unlocked(address)

    async def _write_register_unlocked(self, address: int, value: int) -> None:
        """Write a 16-bit value to a register without acquiring lock.

        Internal method - caller must hold self._lock.

        Args:
            address: Register address (0x00-0xFF)
            value: Value to write (0x0000-0xFFFF)

        Raises:
            ValueError: If address or value out of range
            ProtocolError: If write fails
        """
        if not 0 <= address <= 0xFF:
            raise ValueError(
                f"Register address {address:#04x} out of range [0x00-0xFF]"
            )
        if not 0 <= value <= 0xFFFF:
            raise ValueError(
                f"Register value {value:#06x} out of range [0x0000-0xFFFF]"
            )

        # Send write command: W<AA><VVVV>
        command = f"W{address:02X}{value:04X}"
        logger.debug(f"Writing {value:#06x} to register {address:#04x}")

        await self.transport.write_line(command)

        # Get response: W<AA>OK or error
        response = await self.transport.read_line()
        self._parse_write_response(address, response)

    async def write_register(
        self, address: int, value: int, verify: bool = True
    ) -> int:
        """Write a 16-bit value to a register.

        Args:
            address: Register address (0x00-0xFF)
            value: Value to write (0x0000-0xFFFF)
            verify: If True, read back value to verify write

        Returns:
            Verified value if verify=True, else written value

        Raises:
            ValueError: If address or value out of range
            ProtocolError: If write fails or verification mismatch
        """
        # Acquire lock to ensure atomic write+verify operation
        async with self._lock:
            await self._write_register_unlocked(address, value)

            # Optionally verify by reading back (still under lock)
            if verify:
                readback = await self._read_register_unlocked(address)
                if readback != value:
                    logger.warning(
                        f"Write verification mismatch at {address:#04x}: "
                        f"wrote {value:#06x}, read {readback:#06x}"
                    )
                return readback

            return value

    async def read_register_32bit(self, address_lo: int, address_hi: int) -> int:
        """Read a 32-bit value from LO/HI register pair.

        Args:
            address_lo: Address of low 16 bits
            address_hi: Address of high 16 bits

        Returns:
            32-bit value (HI << 16 | LO)
        """
        # Hold lock for entire 32-bit read to prevent interleaving
        async with self._lock:
            lo = await self._read_register_unlocked(address_lo)
            hi = await self._read_register_unlocked(address_hi)
            value = (hi << 16) | lo

            logger.debug(
                f"Read 32-bit value {value:#010x} from "
                f"[{address_hi:#04x}:{address_lo:#04x}]"
            )
            return value

    async def write_register_32bit(
        self,
        address_lo: int,
        address_hi: int,
        value: int,
        verify: bool = True,
    ) -> int:
        """Write a 32-bit value to LO/HI register pair.

        Writes LO register first, then HI register.

        Args:
            address_lo: Address of low 16 bits
            address_hi: Address of high 16 bits
            value: 32-bit value to write
            verify: If True, read back to verify

        Returns:
            Verified value if verify=True, else written value

        Raises:
            ValueError: If value out of range
        """
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError(f"32-bit value {value:#010x} out of range")

        lo = value & 0xFFFF
        hi = (value >> 16) & 0xFFFF

        logger.debug(
            f"Writing 32-bit value {value:#010x} to "
            f"[{address_hi:#04x}:{address_lo:#04x}]"
        )

        # Hold lock for entire 32-bit write+verify to prevent interleaving
        async with self._lock:
            # Write LO then HI
            await self._write_register_unlocked(address_lo, lo)
            await self._write_register_unlocked(address_hi, hi)

            # Optionally verify
            if verify:
                lo_readback = await self._read_register_unlocked(address_lo)
                hi_readback = await self._read_register_unlocked(address_hi)
                readback = (hi_readback << 16) | lo_readback
                if readback != value:
                    logger.warning(
                        f"32-bit write verification mismatch at "
                        f"[{address_hi:#04x}:{address_lo:#04x}]: "
                        f"wrote {value:#010x}, read {readback:#010x}"
                    )
                return readback

        return value

    async def flash_command(
        self, command: Literal["S", "L"], timeout: float = 1.0
    ) -> None:
        """Execute a flash storage command.

        Args:
            command: 'S' to save, 'L' to load
            timeout: Command timeout (flash ops can be slow)

        Raises:
            ProtocolError: If command fails
        """
        if command not in ("S", "L"):
            raise ValueError(f"Invalid flash command: {command!r}")

        # Acquire lock to ensure atomic flash operation (command + response)
        async with self._lock:
            logger.info(f"Executing flash command: {command}")
            await self.transport.write_line(command)

            # Expect <CMD>OK response
            response = await self.transport.read_line(timeout=timeout)
            expected = f"{command}OK"

            if response != expected:
                self._check_error_response(response)
                raise MalformedResponseError(f"Expected {expected!r}, got {response!r}")

            logger.info(f"Flash command {command} succeeded")

    def _parse_read_response(self, address: int, response: str) -> int:
        """Parse read command response.

        Args:
            address: Expected register address
            response: Response string from Zebra

        Returns:
            Register value

        Raises:
            ProtocolError: If response invalid or indicates error
        """
        # Check for error response first
        self._check_error_response(response)

        # Parse read response: R<AA><VVVV>
        match = self.READ_RESPONSE_PATTERN.match(response)
        if not match:
            raise MalformedResponseError(f"Invalid read response format: {response!r}")

        addr_str, value_str = match.groups()
        response_addr = int(addr_str, 16)
        value = int(value_str, 16)

        # Verify address matches
        if response_addr != address:
            raise MalformedResponseError(
                f"Address mismatch: expected {address:#04x}, got {response_addr:#04x}"
            )

        logger.debug(f"Read {value:#06x} from register {address:#04x}")
        return value

    def _parse_write_response(self, address: int, response: str) -> None:
        """Parse write command response.

        Args:
            address: Expected register address
            response: Response string from Zebra

        Raises:
            ProtocolError: If response invalid or indicates error
        """
        # Check for error response first
        self._check_error_response(response)

        # Parse write response: W<AA>OK
        match = self.WRITE_RESPONSE_PATTERN.match(response)
        if not match:
            raise MalformedResponseError(f"Invalid write response format: {response!r}")

        addr_str = match.group(1)
        response_addr = int(addr_str, 16)

        # Verify address matches
        if response_addr != address:
            raise MalformedResponseError(
                f"Address mismatch: expected {address:#04x}, got {response_addr:#04x}"
            )

        logger.debug(f"Write to register {address:#04x} succeeded")

    def _check_error_response(self, response: str) -> None:
        """Check if response is an error and raise appropriate exception.

        Args:
            response: Response string to check

        Raises:
            ProtocolError: If response indicates an error
        """
        match = self.ERROR_PATTERN.match(response)
        if not match:
            return  # Not an error response

        error_type, command, address_str = match.groups()

        if error_type == "0":
            # E0 - Malformed command
            raise MalformedResponseError("Zebra reports malformed command (E0)")
        else:
            # E1R<AA> or E1W<AA> - Register error
            addr = int(address_str, 16) if address_str else None
            operation = "read" if command == "R" else "write"

            raise RegisterError(
                f"Register {operation} error at {addr:#04x} (E1{command}{address_str})"
            )
