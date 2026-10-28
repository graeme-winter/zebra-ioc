"""Tests for pulse counting: the _LAST PVs and examples/07_pulse_counting.py.

As in the other example tests, caget and caput are replaced with functions
backed by a real ZebraDevice against the simulator, so the script's own logic
is exercised without needing a CA server.
"""

import importlib.util
import pathlib

import pytest
from softioc import builder

from zebra_ioc import SysBus, ZebraDevice
from zebra_ioc.device import ZebraDevice as Device
from zebra_ioc.interrupts import PositionCompareData
from zebra_ioc.ioc import LAST_VALUE_FIELDS, ZebraIOC

_PATH = (
    pathlib.Path(__file__).parent.parent / "examples" / "07_pulse_counting.py"
)
_spec = importlib.util.spec_from_file_location("pulse_counting", _PATH)
example = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(example)

PREFIX = "TEST:ZEBRA:"


def _is_analogue(name: str) -> bool:
    """True if the IOC serves this register as an ao, which carries the
    full 32 bit range rather than a signed int32."""
    from zebra_ioc.registers import REGISTERS_32BIT_BY_NAME

    return name in REGISTERS_32BIT_BY_NAME


class TestLastValuePvs:
    """The scalar counter PVs, which is what a caget actually reads."""

    @pytest.fixture
    def ioc(self):
        builder.ClearRecords()
        builder.SetDeviceName("TEST:ZEBRA")
        ioc = ZebraIOC(Device("sim://test", capture_points=10))
        yield ioc
        builder.ClearRecords()

    def test_legacy_names(self, ioc):
        """These match the legacy Diamond driver, which has no _LAST for
        the timestamp or the system bus."""
        names = {n.removeprefix("TEST:ZEBRA:") for n in ioc.record_names()}
        for field in LAST_VALUE_FIELDS:
            assert f"PC_{field.upper()}_LAST" in names
        assert "PC_TIME_LAST" not in names
        assert "PC_SYS1_LAST" not in names

    async def test_tracks_the_most_recent_point(self, ioc):
        await ioc.device._handle_reset()
        for value in (10, 20, 30):
            await ioc.device._handle_data(
                PositionCompareData(timestamp=0, div1=value)
            )
        assert ioc._last_values["div1"].get() == 30

    async def test_keeps_tracking_after_the_buffer_fills(self, ioc):
        """A counter that silently freezes is worse than one that stops
        being archived, so the scalar comes from the point, not the buffer."""
        await ioc.device._handle_reset()
        for value in range(1, 26):  # capacity is 10
            await ioc.device._handle_data(
                PositionCompareData(timestamp=0, div1=value)
            )

        assert ioc.device.capture.overflowed
        assert ioc.device.capture.count == 10
        assert ioc._last_values["div1"].get() == 25

    async def test_reset_on_a_new_capture(self, ioc):
        await ioc.device._handle_reset()
        await ioc.device._handle_data(PositionCompareData(timestamp=0, div1=99))
        assert ioc._last_values["div1"].get() == 99

        await ioc.device._handle_reset()
        assert ioc._last_values["div1"].get() == 0

    async def test_unselected_fields_stay_put(self, ioc):
        """A point with no encoder data must not zero the encoder PVs."""
        await ioc.device._handle_reset()
        await ioc.device._handle_data(
            PositionCompareData(timestamp=0, encoder1=42)
        )
        await ioc.device._handle_data(PositionCompareData(timestamp=0, div1=7))
        assert ioc._last_values["enc1"].get() == 42


class FakeChannelAccess:
    """caget and caput backed by a device, with the _LAST PVs simulated."""

    def __init__(self, device: ZebraDevice, connected: bool = True):
        self.device = device
        self.connected = connected
        self.last: dict[str, int] = {}
        self.puts: list[tuple[str, int]] = []

    async def caget(self, pv: str, timeout: float = 5.0, **kwargs):
        name = pv[len(PREFIX) :]
        if name == "CONNECTED":
            return int(self.connected)
        if name == "STATUS":
            return "Connected" if self.connected else "Disconnected"
        if name.endswith("_LAST"):
            return self.last.get(name, 0)
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


def args(command: str, *extra):
    return example.parse_args([PREFIX, command, *extra])


class TestSetup:
    async def test_configures_a_free_running_counter(self, ca):
        assert await example.main(args("setup")) == 0

        assert await ca.device.read_register("DIV1_INP") == int(SysBus.IN1_TTL)
        assert await ca.device.read_register("DIV1_DIV") == 0xFFFFFFFF

    async def test_captures_the_divider_not_an_encoder(self, ca):
        await example.main(args("setup"))
        assert await ca.device.read_register("PC_BIT_CAP") == 1 << 6

    async def test_samples_on_time_not_position(self, ca):
        """Counting has nothing to do with where an axis is."""
        await example.main(args("setup"))
        assert await ca.device.read_register("PC_GATE_SEL") == 1
        assert await ca.device.read_register("PC_PULSE_SEL") == 1

    async def test_sample_interval_is_in_timestamp_ticks(self, ca):
        """PC_PULSE_STEP counts PC_TSPRE ticks, not milliseconds.

        With TSPRE=5000 the tick is 100us, so 250ms is 2500 ticks. Writing
        250 here would sample ten times faster than asked.
        """
        await example.main(args("setup", "--sample-ms", "250"))
        assert await ca.device.read_register("PC_TSPRE") == 5000
        assert await ca.device.read_register("PC_PULSE_STEP") == 2500

    async def test_default_sample_interval(self, ca):
        await example.main(args("setup"))
        assert await ca.device.read_register("PC_PULSE_STEP") == 1000

    async def test_arms_the_capture(self, ca):
        await example.main(args("setup"))
        assert ("PC_ARM", 1) in ca.puts

    async def test_alternate_block_and_input(self, ca):
        await example.main(args("setup", "--block", "3", "--input", "PULSE1"))

        assert await ca.device.read_register("DIV3_INP") == int(SysBus.PULSE1)
        assert await ca.device.read_register("PC_BIT_CAP") == 1 << 8
        assert await ca.device.read_register("DIV1_INP") != int(SysBus.PULSE1)

    async def test_unknown_input_writes_nothing(self, ca):
        assert await example.main(args("setup", "--input", "NOT_A_SIGNAL")) == 1
        assert ca.puts == []

    @pytest.mark.parametrize("block", ["0", "5"])
    async def test_bad_block_writes_nothing(self, ca, block):
        assert await example.main(args("setup", "--block", block)) == 1
        assert ca.puts == []


class TestBlockCollision:
    """DIV blocks are a shared resource and there are only four."""

    async def test_refuses_a_block_already_feeding_a_pulse_generator(self, ca):
        """This is exactly what breaks after running example 5 or 6, which
        use DIV1 to generate a pulse train."""
        await ca.device.configure(
            {
                "DIV1_INP": int(SysBus.CLOCK_1MHZ),
                "PULSE1_INP": int(SysBus.DIV1_OUTD),
            }
        )
        ca.puts.clear()

        assert await example.main(args("setup")) == 1
        assert ca.puts == []

    async def test_another_block_is_fine(self, ca):
        await ca.device.configure(
            {
                "DIV1_INP": int(SysBus.CLOCK_1MHZ),
                "PULSE1_INP": int(SysBus.DIV1_OUTD),
            }
        )
        assert await example.main(args("setup", "--block", "2")) == 0
        assert await ca.device.read_register("DIV2_DIV") == 0xFFFFFFFF
        # the pulse train is untouched
        assert await ca.device.read_register("DIV1_INP") == int(
            SysBus.CLOCK_1MHZ
        )

    async def test_force_overrides(self, ca):
        await ca.device.configure({"PULSE1_INP": int(SysBus.DIV1_OUTD)})
        assert await example.main(args("setup", "--force")) == 0
        assert await ca.device.read_register("DIV1_DIV") == 0xFFFFFFFF


class TestGating:
    async def test_gate_is_opened_for_as_long_as_possible(self, ca):
        """A 16 bit gate width gives 6.5s at the 100us tick, after which the
        capture ends and the counter freezes with no error anywhere. The
        register is 32 bit, which is 119 hours."""
        await example.main(args("setup"))
        assert await ca.device.read_register("PC_GATE_WID") == 0xFFFFFFFF
        assert await ca.device.read_register("PC_GATE_NGATE") == 1

    async def test_gate_width_survives_the_wire(self, ca):
        """0xFFFFFFFF only reaches the hardware because PC_GATE_WID is served
        as an ao; a longout would reject it outright."""
        await example.main(args("setup"))
        assert ("PC_GATE_WID", 0xFFFFFFFF) in ca.puts


class TestZeroAndRead:
    async def test_zero_resets_and_rearms(self, ca):
        await example.main(args("setup"))
        ca.puts.clear()

        assert await example.main(args("zero")) == 0

        names = [name for name, _ in ca.puts]
        assert names.index("SYS_RESET") < names.index("PC_ARM")
        assert "PC_DISARM" in names

    async def test_read_returns_the_counter_pv(self, ca, capsys):
        ca.last["PC_DIV1_LAST"] = 4321
        assert await example.main(args("read")) == 0
        assert capsys.readouterr().out.strip() == "4321"

    async def test_read_follows_the_block(self, ca, capsys):
        ca.last["PC_DIV2_LAST"] = 77
        assert await example.main(args("read", "--block", "2")) == 0
        assert capsys.readouterr().out.strip() == "77"

    async def test_stop_disarms(self, ca):
        assert await example.main(args("stop")) == 0
        assert ("PC_DISARM", 1) in ca.puts

    async def test_disconnected_ioc_is_caught(self, ca):
        ca.connected = False
        assert await example.main(args("setup")) == 1
        assert ca.puts == []
