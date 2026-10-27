"""Tests for examples/06_square_wave_epics.py.

The example talks to a running IOC over Channel Access, which is awkward to
stand up in a test. Instead its caget and caput are replaced with functions
backed by a real ZebraDevice against the simulator, so the script's own logic
- which registers it writes, how it checks the readbacks, how it fails - is
exercised end to end without a CA server.
"""

import importlib.util
import pathlib

import pytest

from zebra_ioc import SysBus, ZebraDevice

_PATH = (
    pathlib.Path(__file__).parent.parent
    / "examples"
    / "06_square_wave_epics.py"
)
_spec = importlib.util.spec_from_file_location("square_wave_epics", _PATH)
example = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(example)

PREFIX = "TEST:ZEBRA:"


class FakeChannelAccess:
    """caget and caput backed by a ZebraDevice instead of a CA server."""

    def __init__(self, device: ZebraDevice, connected: bool = True):
        self.device = device
        self.connected = connected
        self.puts: list[tuple[str, int]] = []

    def _strip(self, pv: str) -> str:
        assert pv.startswith(PREFIX), pv
        return pv[len(PREFIX) :]

    async def caget(self, pv: str, timeout: float = 5.0, **kwargs):
        name = self._strip(pv)

        if name == "CONNECTED":
            return int(self.connected)
        if name == "STATUS":
            return "Connected" if self.connected else "Disconnected"
        if name.endswith("_STR"):
            value = await self.device.read_register(name[: -len("_STR")])
            return SysBus(value).name
        if name.endswith("_RBV"):
            return await self.device.read_register(name[: -len("_RBV")])
        return await self.device.read_register(name)

    async def caput(self, pv: str, value, timeout: float = 5.0, **kwargs):
        name = self._strip(pv)
        self.puts.append((name, int(value)))
        await self.device.write_register(name, int(value))


@pytest.fixture
async def ca(monkeypatch):
    device = ZebraDevice("sim://test", poll_period=0.05)
    await device.connect()
    fake = FakeChannelAccess(device)
    monkeypatch.setattr(example, "caget", fake.caget)
    monkeypatch.setattr(example, "caput", fake.caput)
    yield fake
    await device.disconnect()


def args(**overrides):
    """Build an args namespace with the example's own defaults applied."""
    argv = [PREFIX]
    for key, value in overrides.items():
        flag = "--" + key.replace("_", "-")
        argv += [flag] if value is True else [flag, str(value)]
    return example.parse_args(argv)


class TestWritesTheRightRegisters:
    async def test_default_is_a_1khz_square(self, ca):
        assert await example.main(args()) == 0

        written = dict(ca.puts)
        assert written["DIV1_INP"] == int(SysBus.CLOCK_1MHZ)
        assert written["DIV1_DIV"] == 1000
        assert written["PULSE1_INP"] == int(SysBus.DIV1_OUTD)
        assert written["PULSE1_WID"] == 5000  # 500us at the ms prescaler
        assert written["PULSE1_DLY"] == 0
        assert written["OUT1_TTL"] == int(SysBus.PULSE1)

    async def test_registers_actually_reach_the_device(self, ca):
        await example.main(args(freq=2500, width_us=5))
        assert await ca.device.read_register("DIV1_DIV") == 400
        assert await ca.device.read_register("PULSE1_WID") == 50

    async def test_alternate_output_and_block(self, ca):
        await example.main(args(out="OUT3_TTL", block=2))

        written = dict(ca.puts)
        assert written["OUT3_TTL"] == int(SysBus.PULSE2)
        assert written["PULSE2_INP"] == int(SysBus.DIV2_OUTD)
        assert "DIV1_DIV" not in written

    async def test_stop_disconnects_the_output(self, ca):
        assert await example.main(args(stop=True)) == 0
        assert ca.puts == [("OUT1_TTL", int(SysBus.DISCONNECT))]


class TestFailsLoudly:
    async def test_unreachable_width_writes_nothing(self, ca):
        """A bad request must not leave half a configuration on the box."""
        assert await example.main(args(freq=1000, width_us=2000)) == 1
        assert ca.puts == []

    async def test_bad_frequency_writes_nothing(self, ca):
        assert await example.main(args(freq=2_000_000)) == 1
        assert ca.puts == []

    async def test_disconnected_ioc_is_caught(self, ca):
        """An IOC with no Zebra accepts every caput and reports success."""
        ca.connected = False
        assert await example.main(args()) == 1
        assert ca.puts == []
