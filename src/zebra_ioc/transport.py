"""Asyncio transport for Zebra hardware communication.

The Zebra speaks the same line based ASCII protocol however it is reached, so
this module hides the three ways of getting at one:

- ``/dev/ttyUSB0`` (or ``COM3``) - a directly attached serial port
- ``tcp://host:port`` (or bare ``host:port``) - a serial device server, which
  is how a Zebra in a rack is usually reached
- ``sim://name`` - the in-process simulator, for development without hardware
"""

import asyncio
import logging

try:
    import aioserial
except ImportError:
    aioserial = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

TCP_SCHEME = "tcp://"
SIM_SCHEME = "sim://"


def parse_tcp_endpoint(port: str) -> tuple[str, int] | None:
    """Parse a connection string as a TCP endpoint.

    Accepts ``tcp://host:port`` explicitly, and bare ``host:port`` as a
    convenience. A string containing a path separator is treated as a serial
    device, so ``/dev/serial/by-id/...`` is never mistaken for an endpoint.

    Args:
        port: Connection string

    Returns:
        ``(host, port)`` if this is a TCP endpoint, otherwise None

    Raises:
        ValueError: If the string is explicitly tcp:// but malformed
    """
    explicit = port.startswith(TCP_SCHEME)
    endpoint = port[len(TCP_SCHEME) :] if explicit else port

    if not explicit:
        # Bare host:port only - anything path-like is a serial device
        if "/" in endpoint or "\\" in endpoint or endpoint.count(":") != 1:
            return None

    host, _, port_str = endpoint.rpartition(":")
    if not host or not port_str.isdigit():
        if explicit:
            raise ValueError(
                f"Malformed TCP endpoint {port!r}, expected tcp://host:port"
            )
        return None

    return host, int(port_str)


class ZebraTransport:
    """Asyncio transport for Zebra hardware.

    Provides line based communication with a Zebra over serial, TCP or the
    simulator. Handles connection management and routes unsolicited position
    compare interrupt messages away from command responses.

    Real connections use:

    - 115200 baud, 8N1, no flow control (serial only)
    - Newline (\\\\n) line termination
    - ASCII text protocol
    """

    BAUD_RATE = 115200
    TIMEOUT = 1.0
    CONNECT_TIMEOUT = 5.0

    def __init__(self, port: str):
        """Initialize transport for the given connection string.

        Args:
            port: Serial device ('/dev/ttyUSB0', 'COM3'), TCP endpoint
                  ('tcp://host:port' or 'host:port'), or 'sim://name'
        """
        self.port = port
        self._is_simulation = port.startswith(SIM_SCHEME)

        self._tcp_endpoint = (
            None if self._is_simulation else parse_tcp_endpoint(port)
        )
        self._is_tcp = self._tcp_endpoint is not None

        self._serial: aioserial.AioSerial | None = None  # type: ignore[name-defined]
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False

        # Message routing queues (for real hardware)
        self._response_queue: asyncio.Queue[str] = asyncio.Queue()
        self._interrupt_queue: asyncio.Queue[str] = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None

        # Simulation mode components
        self._simulator = None
        self._sim_interrupt_queue: asyncio.Queue[str] | None = None
        self._sim_last_response: str | None = None

        if not self._is_simulation and not self._is_tcp and aioserial is None:
            raise ImportError(
                "aioserial is required for serial communication. "
                "Install with: pip install aioserial"
            )

    @property
    def is_tcp(self) -> bool:
        """True if this transport connects over TCP."""
        return self._is_tcp

    @property
    def is_simulation(self) -> bool:
        """True if this transport uses the in-process simulator."""
        return self._is_simulation

    async def connect(self) -> None:
        """Open the connection to the Zebra or simulator.

        Raises:
            SerialException: If a serial connection fails
            OSError: If a TCP connection fails
            TimeoutError: If a TCP connection is not established in time
        """
        if self._connected:
            logger.warning(f"Already connected to {self.port}")
            return

        if self._is_simulation:
            await self._connect_simulation()
        elif self._is_tcp:
            await self._connect_tcp()
        else:
            await self._connect_serial()

    async def _connect_simulation(self) -> None:
        """Start the in-process simulator."""
        # Import simulator locally to avoid dependency
        from .simulator import ZebraSimulator

        logger.info(f"Starting Zebra simulator for {self.port}")
        self._simulator = ZebraSimulator()
        self._sim_interrupt_queue = asyncio.Queue()

        # Set callback for simulator to send interrupt messages
        def send_interrupt(message: str):
            if self._sim_interrupt_queue:
                self._sim_interrupt_queue.put_nowait(message)

        self._simulator.set_send_callback(send_interrupt)

        self._connected = True
        logger.info(f"Simulator ready for {self.port}")

    async def _connect_tcp(self) -> None:
        """Open a TCP connection to a serial device server."""
        assert self._tcp_endpoint is not None
        host, tcp_port = self._tcp_endpoint

        logger.info(f"Connecting to Zebra at {host}:{tcp_port}")

        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(host, tcp_port),
            timeout=self.CONNECT_TIMEOUT,
        )

        self._connected = True
        self._reader_task = asyncio.create_task(self._read_and_route_messages())

        logger.info(f"Connected to Zebra at {host}:{tcp_port}")

    async def _connect_serial(self) -> None:
        """Open a serial connection."""
        logger.info(f"Connecting to Zebra on {self.port} at {self.BAUD_RATE} baud")

        self._serial = aioserial.AioSerial(  # type: ignore[union-attr]
            port=self.port,
            baudrate=self.BAUD_RATE,
            bytesize=aioserial.EIGHTBITS,  # type: ignore[union-attr]
            parity=aioserial.PARITY_NONE,  # type: ignore[union-attr]
            stopbits=aioserial.STOPBITS_ONE,  # type: ignore[union-attr]
            timeout=self.TIMEOUT,
        )

        self._connected = True
        self._reader_task = asyncio.create_task(self._read_and_route_messages())

        logger.info(f"Connected to Zebra on {self.port}")

    async def disconnect(self) -> None:
        """Close the connection or stop the simulator."""
        if not self._connected:
            return

        logger.info(f"Disconnecting from {self.port}")

        if self._is_simulation:
            if self._simulator:
                self._simulator.reset()
                self._simulator = None
            self._sim_interrupt_queue = None
            self._sim_last_response = None
        else:
            # Stop reader task
            if self._reader_task:
                self._reader_task.cancel()
                try:
                    await self._reader_task
                except asyncio.CancelledError:
                    pass
                self._reader_task = None

            if self._writer:
                self._writer.close()
                try:
                    await self._writer.wait_closed()
                except (OSError, asyncio.CancelledError):
                    pass
                self._writer = None
                self._reader = None

            if self._serial:
                self._serial.close()
                self._serial = None

        self._connected = False
        logger.info("Disconnected from Zebra")

    @property
    def connected(self) -> bool:
        """Check if transport is connected."""
        if self._is_simulation:
            return self._connected and self._simulator is not None
        elif self._is_tcp:
            return self._connected and self._writer is not None
        else:
            return self._connected and self._serial is not None

    async def _readline_bytes(self) -> bytes:
        """Read one line from the underlying connection."""
        if self._is_tcp:
            return await self._reader.readline()  # type: ignore[union-attr]
        return await self._serial.readline_async()  # type: ignore[union-attr]

    async def _write_bytes(self, data: bytes) -> None:
        """Write bytes to the underlying connection."""
        if self._is_tcp:
            self._writer.write(data)  # type: ignore[union-attr]
            await self._writer.drain()  # type: ignore[union-attr]
        else:
            await self._serial.write_async(data)  # type: ignore[union-attr]

    async def _read_and_route_messages(self) -> None:
        """Background task to read from the connection and route messages.

        Routes messages based on first character:
        - Messages starting with 'P' go to interrupt queue
        - All other messages go to response queue
        """
        try:
            while self._connected:
                try:
                    line_bytes = await self._readline_bytes()

                    if not line_bytes:
                        # readline returns empty on a closed TCP connection
                        if self._is_tcp:
                            logger.error("Connection closed by remote end")
                            break
                        continue

                    # Decode and strip newline
                    line = line_bytes.decode("ascii").rstrip("\r\n")

                    if not line:  # Empty line, skip
                        continue

                    # Route based on message type
                    if line.startswith("P"):
                        # Interrupt message
                        logger.debug(f"RX (interrupt): {line!r}")
                        await self._interrupt_queue.put(line)
                    else:
                        # Command response
                        logger.debug(f"RX: {line!r}")
                        await self._response_queue.put(line)

                except Exception as e:
                    if self._connected:
                        logger.error(f"Error in reader task: {e}")
                    break

        except asyncio.CancelledError:
            logger.debug("Reader task cancelled")
            raise

    async def write_line(self, data: str) -> None:
        """Write a line of text to the Zebra or simulator.

        Automatically appends newline terminator.

        Args:
            data: ASCII text command (without newline)

        Raises:
            RuntimeError: If not connected
        """
        if not self.connected:
            raise RuntimeError("Not connected to Zebra")

        logger.debug(f"TX: {data!r}")

        if self._is_simulation:
            # Process command and store response for next read_line
            if self._simulator:
                response = await self._simulator.process_command(data)
                # Store response to be returned by next read_line() call
                self._sim_last_response = response
        else:
            await self._write_bytes((data + "\n").encode("ascii"))

    async def read_line(self, timeout: float | None = None) -> str:
        """Read a line of text from the Zebra or simulator.

        Reads until newline terminator, which is stripped from result.
        In simulation mode, returns the last command response.

        Args:
            timeout: Read timeout in seconds (uses default if None)

        Returns:
            Received line without newline terminator

        Raises:
            RuntimeError: If not connected
            TimeoutError: If read times out
        """
        if not self.connected:
            raise RuntimeError("Not connected to Zebra")

        if timeout is None:
            timeout = self.TIMEOUT

        try:
            if self._is_simulation:
                # Return the stored response from last write_line
                if self._sim_last_response is not None:
                    line = self._sim_last_response
                    self._sim_last_response = None
                    logger.debug(f"RX: {line!r}")
                else:
                    raise RuntimeError(
                        "No response available - write_line must be called first"
                    )
            else:
                # Read from response queue (populated by reader task)
                line = await asyncio.wait_for(
                    self._response_queue.get(),
                    timeout=timeout,
                )

            return line

        except TimeoutError:
            logger.error(f"Read timeout after {timeout}s")
            raise

    async def read_interrupt(self, timeout: float | None = None) -> str:
        """Read an interrupt message (simulation or real hardware).

        This method reads asynchronous interrupt messages like PR, PX, P<data>.

        Args:
            timeout: Read timeout in seconds (uses default if None)

        Returns:
            Interrupt message without newline terminator

        Raises:
            RuntimeError: If not connected
            TimeoutError: If read times out
        """
        if not self.connected:
            raise RuntimeError("Not connected to Zebra")

        if timeout is None:
            timeout = self.TIMEOUT

        try:
            if self._is_simulation:
                # Only read from interrupt queue
                if self._sim_interrupt_queue:
                    line = await asyncio.wait_for(
                        self._sim_interrupt_queue.get(), timeout=timeout
                    )
                    logger.debug(f"RX (interrupt): {line!r}")
                else:
                    raise RuntimeError("Simulator not properly initialized")
            else:
                # Read from interrupt queue (populated by reader task)
                line = await asyncio.wait_for(
                    self._interrupt_queue.get(),
                    timeout=timeout,
                )

            return line

        except TimeoutError:
            # Timeouts are normal for interrupt monitoring
            raise

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
        return False
