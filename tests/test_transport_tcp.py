"""Tests for the TCP transport path.

A serial device server is just a TCP socket carrying the same line based ASCII
protocol, so these tests stand up a tiny asyncio server that answers register
reads and can push unsolicited interrupt messages.
"""

import asyncio

import pytest

from zebra_ioc.transport import ZebraTransport, parse_tcp_endpoint


class FakeZebraServer:
    """Minimal TCP server speaking enough of the Zebra protocol to test with."""

    def __init__(self):
        self.memory = {0xF0: 0x0020}
        self.received: list[str] = []
        self._server: asyncio.Server | None = None
        self._writer: asyncio.StreamWriter | None = None
        self.host = "127.0.0.1"
        self.port = 0

    async def start(self) -> str:
        self._server = await asyncio.start_server(
            self._handle_client, self.host, 0
        )
        self.port = self._server.sockets[0].getsockname()[1]
        return f"tcp://{self.host}:{self.port}"

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def send_interrupt(self, message: str) -> None:
        """Push an unsolicited message, as the Zebra does when armed."""
        assert self._writer is not None
        self._writer.write((message + "\n").encode("ascii"))
        await self._writer.drain()

    async def _handle_client(self, reader, writer):
        self._writer = writer
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                command = line.decode("ascii").strip()
                self.received.append(command)
                response = self._reply(command)
                if response is not None:
                    writer.write((response + "\n").encode("ascii"))
                    await writer.drain()
        finally:
            # Server.wait_closed() blocks until every connection is closed, so
            # the handler must close its own side or teardown hangs
            self._writer = None
            writer.close()

    def _reply(self, command: str) -> str | None:
        if command.startswith("R") and len(command) == 3:
            addr = int(command[1:3], 16)
            return f"R{addr:02X}{self.memory.get(addr, 0):04X}"
        if command.startswith("W") and len(command) == 7:
            addr = int(command[1:3], 16)
            self.memory[addr] = int(command[3:7], 16)
            return f"W{addr:02X}OK"
        return None


@pytest.fixture
async def server():
    fake = FakeZebraServer()
    url = await fake.start()
    yield fake, url
    await fake.stop()


class TestParseTcpEndpoint:
    """The connection string decides serial vs TCP vs simulator."""

    def test_explicit_scheme(self):
        assert parse_tcp_endpoint("tcp://172.23.241.3:7012") == (
            "172.23.241.3",
            7012,
        )

    def test_bare_host_port(self):
        assert parse_tcp_endpoint("zebra01:7012") == ("zebra01", 7012)

    def test_serial_device_is_not_tcp(self):
        assert parse_tcp_endpoint("/dev/ttyUSB0") is None

    def test_serial_by_id_path_is_not_tcp(self):
        # This one contains a colon, so it must be rejected on the path
        # separator rather than on the colon count
        assert parse_tcp_endpoint("/dev/serial/by-id/usb-FTDI:1") is None

    def test_windows_com_port_is_not_tcp(self):
        assert parse_tcp_endpoint("COM3") is None

    def test_malformed_explicit_endpoint_raises(self):
        with pytest.raises(ValueError):
            parse_tcp_endpoint("tcp://nohostport")


class TestTcpTransport:
    """End to end behaviour over a real socket."""

    async def test_connect_and_disconnect(self, server):
        _, url = server
        transport = ZebraTransport(url)
        assert transport.is_tcp
        assert not transport.is_simulation

        await transport.connect()
        assert transport.connected
        await transport.disconnect()
        assert not transport.connected

    async def test_register_read_round_trip(self, server):
        fake, url = server
        async with ZebraTransport(url) as transport:
            await transport.write_line("RF0")
            assert await transport.read_line(timeout=2.0) == "RF00020"
        assert fake.received == ["RF0"]

    async def test_interrupts_do_not_land_in_responses(self, server):
        """A capture arriving mid-command must not be read as its response."""
        fake, url = server
        async with ZebraTransport(url) as transport:
            await transport.write_line("RF0")
            assert await transport.read_line(timeout=2.0) == "RF00020"

            await fake.send_interrupt("PR")
            await fake.send_interrupt("P0000000A00000064")

            assert await transport.read_interrupt(timeout=2.0) == "PR"
            assert (
                await transport.read_interrupt(timeout=2.0)
                == "P0000000A00000064"
            )

            # The response queue was left untouched by the interrupts
            await transport.write_line("R7F")
            assert await transport.read_line(timeout=2.0) == "R7F0000"

    async def test_write_after_disconnect_raises(self, server):
        _, url = server
        transport = ZebraTransport(url)
        await transport.connect()
        await transport.disconnect()
        with pytest.raises(RuntimeError):
            await transport.write_line("RF0")

    async def test_connect_refused(self):
        # Port 1 on loopback is not listening
        transport = ZebraTransport("tcp://127.0.0.1:1")
        with pytest.raises(OSError):
            await transport.connect()
