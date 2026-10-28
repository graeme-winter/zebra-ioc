"""Tests for the inline MD3 to Eiger configuration.

See docs/md3-eiger-inline.md. The properties worth pinning down are that the
three records cover the same pulses, that nothing escapes to the detector
outside a run, and that teardown happens in an order that cannot lose pulses.
"""

import importlib.util
import pathlib

import pytest

from zebra_ioc import SysBus, ZebraDevice
from zebra_ioc.pulse_train import md3_eiger_registers

_PATH = pathlib.Path(__file__).parent.parent / "examples" / "09_md3_eiger.py"
_spec = importlib.util.spec_from_file_location("md3_eiger", _PATH)
example = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(example)

PREFIX = "TEST:ZEBRA:"


class TestRegisters:
    """The configuration the doc describes."""

    def test_everything_hangs_off_the_run_gate(self):
        """Detector pulse, count and timestamps must see the same pulses.

        If any of the three were fed straight from the connector it would
        record pulses from outside the run, and the three records would
        disagree.
        """
        settings, _ = md3_eiger_registers()
        gated = int(SysBus.AND1)
        assert settings["PULSE1_INP"] == gated
        assert settings["DIV1_INP"] == gated
        assert settings["PC_PULSE_INP"] == gated

    def test_the_run_gate_is_the_input_anded_with_a_soft_input(self):
        settings, _ = md3_eiger_registers()
        assert settings["AND1_INP1"] == int(SysBus.IN1_TTL)
        assert settings["AND1_INP2"] == int(SysBus.SOFT_IN1)
        assert settings["AND1_ENA"] == 0b0011
        assert settings["AND1_INV"] == 0

    def test_capture_is_externally_triggered(self):
        """Position mode would tie capture to an encoder; time mode would
        sample on a clock. Neither records when a pulse actually arrived."""
        settings, _ = md3_eiger_registers()
        assert settings["PC_PULSE_SEL"] == 2
        assert settings["PC_GATE_SEL"] == 2

    def test_never_self_disarms(self):
        """Teardown is explicit; a gate count would end the run early."""
        settings, _ = md3_eiger_registers()
        assert settings["PC_GATE_NGATE"] == 0

    def test_counter_is_captured_alongside_the_timestamp(self):
        settings, _ = md3_eiger_registers()
        assert settings["PC_BIT_CAP"] == 1 << 6  # DIV1
        assert settings["DIV1_DIV"] == 0xFFFFFFFF

    def test_detector_is_driven_by_the_shaping_block(self):
        """Driving it from the dead time block would send the detector a
        pulse as wide as the whole train."""
        settings, _ = md3_eiger_registers()
        assert settings["OUT1_TTL"] == int(SysBus.PULSE2)
        assert settings["OUT2_TTL"] == int(SysBus.PULSE2)

    def test_timestamp_resolution_and_wrap_are_reported(self):
        _, achieved = md3_eiger_registers(tspre=5)
        assert achieved["timestamp_tick_us"] == pytest.approx(0.1)
        assert achieved["timestamp_wrap_s"] == pytest.approx(429.4967296)

        _, achieved = md3_eiger_registers(tspre=5000)
        assert achieved["timestamp_tick_us"] == pytest.approx(100.0)

    def test_blocks_can_be_moved(self):
        settings, _ = md3_eiger_registers(
            counter_block=3, gate_block=3, shape_block=4, logic_block=2
        )
        assert settings["DIV3_INP"] == int(SysBus.AND2)
        assert settings["PC_BIT_CAP"] == 1 << 8
        assert settings["OUT1_TTL"] == int(SysBus.PULSE4)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"source": "NOT_A_SIGNAL"},
            {"run_gate": "NOT_A_SIGNAL"},
            {"counter_block": 0},
            {"logic_block": 9},
            {"tspre": 42},
        ],
    )
    def test_bad_arguments_raise(self, kwargs):
        with pytest.raises(ValueError):
            md3_eiger_registers(**kwargs)


class FakeChannelAccess:
    """caget and caput backed by a device rather than a CA server."""

    def __init__(self, device: ZebraDevice, connected: bool = True):
        self.device = device
        self.connected = connected
        # PVs the IOC derives rather than reading from a register
        self.derived: dict[str, int] = {
            "PC_CAPTURE_MAX": 250000,
            "PC_NUM_DOWN": 0,
            "PC_CAPTURING": 0,
            "PC_OVERFLOW": 0,
        }
        self.puts: list[tuple[str, int]] = []

    async def caget(self, pv: str, timeout: float = 5.0, count=None, **kwargs):
        name = pv[len(PREFIX) :]
        if name == "CONNECTED":
            return int(self.connected)
        if name == "STATUS":
            return "Connected" if self.connected else "Disconnected"
        if name in self.derived or name.endswith("_LAST"):
            return self.derived.get(name, 0)
        if name.endswith("_RBV"):
            return await self.device.read_register(name[: -len("_RBV")])
        return await self.device.read_register(name)

    async def caput(self, pv: str, value, timeout: float = 5.0, **kwargs):
        name = pv[len(PREFIX) :]
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


class TestProcedure:
    async def test_setup_shuts_the_gate_before_wiring_anything(self, ca):
        """A half written configuration must not be able to fire the
        detector."""
        assert await example.main(args("setup")) == 0
        assert ca.puts[0] == ("SOFT_IN", 0)

    async def test_setup_resets_before_arming(self, ca):
        """SYS_RESET zeroes the counters but also disarms, so doing it after
        the arm would leave the capture disarmed."""
        await example.main(args("setup"))
        names = [name for name, _ in ca.puts]
        assert names.index("SYS_RESET") < names.index("PC_ARM")

    async def test_setup_leaves_the_gate_shut(self, ca):
        await example.main(args("setup"))
        assert await ca.device.read_register("SOFT_IN") == 0

    async def test_start_opens_the_gate(self, ca):
        await example.main(args("setup"))
        await example.main(args("start"))
        assert await ca.device.read_register("SOFT_IN") & 1

    async def test_stop_closes_the_gate_before_disarming(self, ca):
        """The other order would leave pulses reaching the detector while no
        longer being recorded."""
        await example.main(args("setup"))
        await example.main(args("start"))
        ca.puts.clear()

        assert await example.main(args("stop")) == 0

        names = [name for name, _ in ca.puts]
        assert names.index("SOFT_IN") < names.index("PC_DISARM")
        assert ("SOFT_IN", 0) in ca.puts

    async def test_status_reports_without_writing(self, ca):
        await example.main(args("setup"))
        ca.puts.clear()
        assert await example.main(args("status")) == 0
        assert ca.puts == []

    async def test_results_with_no_points(self, ca, capsys):
        assert await example.main(args("results")) == 0
        assert "No points captured" in capsys.readouterr().out

    async def test_bad_configuration_writes_nothing(self, ca):
        """A request that cannot be met must leave the box untouched rather
        than half configured."""
        assert await example.main(args("setup", "--train-ms", "0.0001")) == 1
        assert ca.puts == []

    async def test_disconnected_ioc_is_caught(self, ca):
        ca.connected = False
        assert await example.main(args("setup")) == 1
        assert ca.puts == []
