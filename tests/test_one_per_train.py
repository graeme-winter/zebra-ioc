"""Tests for one-pulse-per-train, the helper and examples/08_one_per_train.py."""

import importlib.util
import pathlib

import pytest

from zebra_ioc import SysBus, ZebraDevice
from zebra_ioc.pulse_train import duration_ticks, one_pulse_per_train_registers

_PATH = (
    pathlib.Path(__file__).parent.parent / "examples" / "08_one_per_train.py"
)
_spec = importlib.util.spec_from_file_location("one_per_train", _PATH)
example = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(example)

PREFIX = "TEST:ZEBRA:"


def _is_analogue(name: str) -> bool:
    """True if the IOC serves this register as an ao, which carries the
    full 32 bit range rather than a signed int32."""
    from zebra_ioc.registers import REGISTERS_32BIT_BY_NAME

    return name in REGISTERS_32BIT_BY_NAME


class TestDurationTicks:
    """The prescaler arithmetic the timestamp and pulse registers share."""

    @pytest.mark.parametrize(
        "duration_us,expected",
        [
            (2.0, (5, "ms", 20)),
            (500.0, (5, "ms", 5000)),
            (6553.5, (5, "ms", 65535)),  # the last that fits at the finest
            (6554.0, (5000, "s", 66)),  # steps up
            (500_000.0, (5000, "s", 5000)),
            (6_553_500.0, (5000, "s", 65535)),
            (10_000_000.0, (50000, "10s", 10000)),
        ],
    )
    def test_prescaler_selection(self, duration_us, expected):
        prescaler, label, ticks, _ = duration_ticks(duration_us)
        assert (prescaler, label, ticks) == expected

    def test_below_resolution_raises(self):
        with pytest.raises(ValueError, match="resolution"):
            duration_ticks(0.01)

    def test_beyond_range_raises(self):
        with pytest.raises(ValueError, match="maximum"):
            duration_ticks(100_000_000.0)

    def test_non_positive_raises(self):
        with pytest.raises(ValueError, match="positive"):
            duration_ticks(0)


class TestOnePulsePerTrainRegisters:
    """Two PULSE blocks: one to swallow, one to shape."""

    def test_full_chain(self):
        settings, achieved = one_pulse_per_train_registers(
            "IN1_TTL", train_us=500_000, width_us=10
        )
        assert settings == {
            "PULSE1_INP": int(SysBus.IN1_TTL),
            "PULSE1_PRE": 5000,  # 100us tick for the long dead time
            "PULSE1_DLY": 0,
            "PULSE1_WID": 5000,  # 500ms
            "PULSE2_INP": int(SysBus.PULSE1),
            "PULSE2_PRE": 5,  # 0.1us tick for the short output
            "PULSE2_DLY": 0,
            "PULSE2_WID": 100,  # 10us
            "OUT1_TTL": int(SysBus.PULSE2),
        }
        assert achieved["dead_time_us"] == pytest.approx(500_000)
        assert achieved["width_us"] == pytest.approx(10)

    def test_the_output_comes_from_the_shaping_block(self):
        """Driving the output from the dead time block would give a pulse as
        wide as the whole train, which is the thing being avoided."""
        settings, _ = one_pulse_per_train_registers("IN1_TTL", 500_000)
        assert settings["OUT1_TTL"] == int(SysBus.PULSE2)
        assert settings["OUT1_TTL"] != int(SysBus.PULSE1)

    def test_shaping_block_is_fed_from_the_dead_time_block(self):
        settings, _ = one_pulse_per_train_registers("IN1_TTL", 500_000)
        assert settings["PULSE2_INP"] == int(SysBus.PULSE1)

    def test_alternate_blocks(self):
        settings, _ = one_pulse_per_train_registers(
            "IN2_TTL", 500_000, gate_block=3, shape_block=4
        )
        assert settings["PULSE3_INP"] == int(SysBus.IN2_TTL)
        assert settings["PULSE4_INP"] == int(SysBus.PULSE3)
        assert settings["OUT1_TTL"] == int(SysBus.PULSE4)

    def test_several_outputs(self):
        settings, achieved = one_pulse_per_train_registers(
            "IN1_TTL", 500_000, out=["OUT1_TTL", "OUT2_TTL"]
        )
        assert settings["OUT1_TTL"] == settings["OUT2_TTL"] == int(SysBus.PULSE2)
        assert achieved["outputs"] == ["OUT1_TTL", "OUT2_TTL"]

    def test_same_block_twice_raises(self):
        """One block cannot both swallow and shape."""
        with pytest.raises(ValueError, match="must differ"):
            one_pulse_per_train_registers(
                "IN1_TTL", 500_000, gate_block=1, shape_block=1
            )

    @pytest.mark.parametrize("block", [0, 5])
    def test_bad_block_raises(self, block):
        with pytest.raises(ValueError, match="must be 1-4"):
            one_pulse_per_train_registers("IN1_TTL", 500_000, gate_block=block)

    def test_width_longer_than_dead_time_raises(self):
        """The output would still be high when the next train arrives."""
        with pytest.raises(ValueError, match="shorter than"):
            one_pulse_per_train_registers("IN1_TTL", 1000, width_us=2000)

    def test_unknown_signal_raises(self):
        with pytest.raises(ValueError, match="not a system bus signal"):
            one_pulse_per_train_registers("NOT_A_SIGNAL", 500_000)

    def test_train_beyond_range_raises(self):
        with pytest.raises(ValueError, match="maximum"):
            one_pulse_per_train_registers("IN1_TTL", train_us=100_000_000)


class FakeChannelAccess:
    """caget and caput backed by a device rather than a CA server."""

    def __init__(self, device: ZebraDevice, connected: bool = True):
        self.device = device
        self.connected = connected
        self.puts: list[tuple[str, int]] = []

    async def caget(self, pv: str, timeout: float = 5.0, **kwargs):
        name = pv[len(PREFIX) :]
        if name == "CONNECTED":
            return int(self.connected)
        if name == "STATUS":
            return "Connected" if self.connected else "Disconnected"
        return await self.device.read_register(name)

    async def caput(self, pv: str, value, timeout: float = 5.0, **kwargs):
        name = pv[len(PREFIX) :]
        # Channel Access carries integers as a signed int32. Reject anything
        # that would not survive the wire, so a test cannot pass on a value
        # a real caput would refuse
        if isinstance(value, int) and not -(2**31) <= value < 2**31:
            if not _is_analogue(name):
                raise OverflowError(
                    f"{value} out of bounds for int32 ({name})"
                )
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


def args(*extra):
    return example.parse_args([PREFIX, *extra])


class TestExample:
    async def test_writes_both_blocks(self, ca):
        assert await example.main(args("--train-ms", "500")) == 0

        assert await ca.device.read_register("PULSE1_WID") == 5000
        assert await ca.device.read_register("PULSE2_INP") == int(SysBus.PULSE1)
        assert await ca.device.read_register("OUT1_TTL") == int(SysBus.PULSE2)

    async def test_output_width(self, ca):
        await example.main(args("--train-ms", "500", "--width-us", "2"))
        assert await ca.device.read_register("PULSE2_WID") == 20

    async def test_monitor_output(self, ca):
        await example.main(args("--monitor", "OUT2_TTL"))
        assert await ca.device.read_register("OUT2_TTL") == int(SysBus.PULSE2)

    async def test_stop_clears_both_outputs(self, ca):
        assert await example.main(args("--monitor", "OUT2_TTL", "--stop")) == 0
        assert ca.puts == [
            ("OUT1_TTL", int(SysBus.DISCONNECT)),
            ("OUT2_TTL", int(SysBus.DISCONNECT)),
        ]

    async def test_impossible_request_writes_nothing(self, ca):
        assert await example.main(args("--train-ms", "0.001")) == 1
        assert ca.puts == []

    async def test_disconnected_ioc_is_caught(self, ca):
        ca.connected = False
        assert await example.main(args()) == 1
        assert ca.puts == []
