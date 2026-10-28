"""Tests for the generated EPICS record interface.

These check the PV surface without starting a CA server. The point of the
whole exercise is that the PV names match the legacy Diamond driver, so that
is what is asserted hardest here.
"""

import pathlib

import pytest
from softioc import builder

from zebra_ioc.device import ZebraDevice
from zebra_ioc.ioc import ZebraIOC


@pytest.fixture
def record_types():
    """Map PV name (prefix stripped) to its EPICS record type."""
    import re

    from softioc import builder as b

    b.ClearRecords()
    b.SetDeviceName("TEST:ZEBRA")
    ZebraIOC(ZebraDevice("sim://test", capture_points=100))
    b.WriteRecords("/tmp/zebra_ioc_test.db")
    db = pathlib.Path("/tmp/zebra_ioc_test.db").read_text()
    b.ClearRecords()
    return {
        m.group(2).removeprefix("TEST:ZEBRA:"): m.group(1)
        for m in re.finditer(r'record\((\w+),\s*"([^"]+)"\)', db)
    }


@pytest.fixture
def pv_names():
    """Build the record set once and return the fully qualified PV names.

    softioc keeps a process-global record registry, so it is cleared first
    and the device is never connected - only the record shapes matter.
    """
    builder.ClearRecords()
    builder.SetDeviceName("TEST:ZEBRA")
    device = ZebraDevice("sim://test", capture_points=100)
    ioc = ZebraIOC(device)
    names = {name.removeprefix("TEST:ZEBRA:") for name in ioc.record_names()}
    builder.ClearRecords()
    return names


class TestLegacyPvNames:
    """Existing Zebra client code must work against this IOC unmodified."""

    @pytest.mark.parametrize(
        "pv",
        [
            # The registers a rotation scan sets
            "PC_ENC",
            "PC_DIR",
            "PC_TSPRE",
            "PC_ARM_SEL",
            "PC_GATE_SEL",
            "PC_GATE_START",
            "PC_GATE_WID",
            "PC_GATE_NGATE",
            "PC_PULSE_SEL",
            "PC_PULSE_START",
            "PC_PULSE_WID",
            "PC_PULSE_STEP",
            "PC_BIT_CAP",
            # Arm and disarm
            "PC_ARM",
            "PC_DISARM",
            # Capture arrays
            "PC_TIME",
            "PC_ENC1",
            "PC_ENC4",
            "PC_SYS1",
            "PC_DIV1",
            # Logic, timing and output blocks
            "AND1_INP1",
            "AND4_ENA",
            "OR1_INV",
            "GATE1_INP1",
            "PULSE1_DLY",
            "DIV1_DIV",
            "OUT1_TTL",
            "OUT8_ENCA",
            # System
            "SYS_VER",
            "SYS_RESET",
        ],
    )
    def test_legacy_pv_exists(self, pv_names, pv):
        assert pv in pv_names

    def test_no_pascal_case_leaked_in(self, pv_names):
        """A regression guard against drifting back to framework naming."""
        assert "PcGateStart" not in pv_names
        assert "Pc:GateStart" not in pv_names


class TestRecordShapes:
    """Each register type gets the records its type calls for."""

    def test_writable_register_has_a_readback(self, pv_names):
        assert "PC_GATE_WID" in pv_names
        assert "PC_GATE_WID_RBV" in pv_names

    def test_mux_register_has_a_signal_name(self, pv_names):
        assert "OUT1_TTL" in pv_names
        assert "OUT1_TTL_RBV" in pv_names
        assert "OUT1_TTL_STR" in pv_names

    def test_command_register_has_no_readback(self, pv_names):
        assert "PC_ARM" in pv_names
        assert "PC_ARM_RBV" not in pv_names

    def test_read_only_register_has_no_demand_pair(self, pv_names):
        assert "SYS_VER" in pv_names
        assert "SYS_VER_RBV" not in pv_names

    def test_32bit_halves_are_not_exposed_separately(self, pv_names):
        """Two PVs fighting over one value would be worse than none."""
        assert "PC_NUM_CAP" not in pv_names or "PC_NUM_CAPLO" not in pv_names
        assert "SYS_STAT1LO" not in pv_names
        assert "SYS_STAT2HI" not in pv_names

    def test_system_bus_bits_are_named_after_their_signals(self, pv_names):
        assert "SYS_BUS_SOFT_IN1" in pv_names
        assert "SYS_BUS_PC_GATE" in pv_names
        assert "SYS_BUS_AND1" in pv_names
        # DISCONNECT is a routing choice, not a signal
        assert "SYS_BUS_DISCONNECT" not in pv_names

    def test_ioc_status_pvs(self, pv_names):
        assert {"CONNECTED", "STATUS", "PC_CAPTURING"} <= pv_names

    def test_flash_commands_exist(self, pv_names):
        """Save and restore are wire commands, not registers, so they are
        easy to leave out by accident."""
        assert {"STORE", "RESTORE"} <= pv_names

    def test_capture_status_pvs(self, pv_names):
        assert {"PC_NUM_DOWN", "PC_CAPTURE_MAX", "PC_OVERFLOW"} <= pv_names


class TestRecordTypesCoverTheRegisterRange:
    """EPICS LONG is a signed int32, which is narrower than some registers."""

    @pytest.mark.parametrize(
        "pv", ["DIV1_DIV", "DIV4_DIV", "PC_GATE_START", "PC_PULSE_STEP"]
    )
    def test_32bit_registers_are_analogue(self, record_types, pv):
        """DIV<n>_DIV goes to 4294967295, which a longout cannot carry.

        A caput of 0xFFFFFFFF to a longout fails outright with an overflow,
        so counting configurations that set the divisor high enough never to
        wrap could not be written at all.
        """
        assert record_types[pv] == "ao"
        assert record_types[f"{pv}_RBV"] == "ai"

    def test_divider_counters_are_analogue(self, record_types):
        """Captured divider counts are unsigned 32-bit as well."""
        for n in range(1, 5):
            assert record_types[f"PC_DIV{n}_LAST"] == "ai"

    def test_encoder_counters_stay_integer(self, record_types):
        """Encoder positions are signed 32-bit and fit a longin exactly."""
        for n in range(1, 5):
            assert record_types[f"PC_ENC{n}_LAST"] == "longin"

    @pytest.mark.parametrize("pv", ["AND1_ENA", "OUT1_TTL", "PULSE1_WID"])
    def test_16bit_registers_stay_integer(self, record_types, pv):
        assert record_types[pv] == "longout"
