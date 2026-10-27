"""Unit tests for Zebra register definitions.

Tests cover:
- Register type enumeration
- Individual register definitions
- 32-bit register pairs
- System bus signal mapping
- Lookup functions (name ↔ address)
- Type-specific accessors
"""

import pytest

from zebra_ioc.registers import (
    REGISTERS_BY_ADDRESS,
    REGISTERS_BY_NAME,
    RegAddr,
    Register,
    Register32,
    RegisterType,
    SysBus,
    get_all_registers,
    get_all_registers_32bit,
    get_register,
    get_register_32bit,
    is_command_register,
    is_mux_register,
    is_readonly_register,
    signal_index_to_name,
)

# =============================================================================
# Register Type Tests
# =============================================================================


class TestRegisterType:
    """Tests for RegisterType enumeration."""

    def test_register_types_exist(self):
        """Test that all expected register types exist."""
        assert RegisterType.RW is not None
        assert RegisterType.RO is not None
        assert RegisterType.CMD is not None
        assert RegisterType.MUX is not None

    def test_register_types_are_unique(self):
        """Test that register types have unique values."""
        types = [RegisterType.RW, RegisterType.RO, RegisterType.CMD, RegisterType.MUX]
        values = [t.value for t in types]
        assert len(values) == len(set(values))


# =============================================================================
# Register Definition Tests
# =============================================================================


class TestRegister:
    """Tests for Register dataclass."""

    def test_register_creation(self):
        """Test basic register creation."""
        reg = Register("TEST_REG", 0x10, RegisterType.RW, "Test register")
        assert reg.name == "TEST_REG"
        assert reg.address == 0x10
        assert reg.reg_type == RegisterType.RW
        assert reg.description == "Test register"

    def test_register_frozen(self):
        """Test that Register is immutable (frozen dataclass)."""
        reg = Register("TEST_REG", 0x10, RegisterType.RW)
        with pytest.raises(AttributeError):
            reg.name = "NEW_NAME"  # type: ignore[misc]

    def test_register_invalid_address_too_low(self):
        """Test that negative addresses raise ValueError."""
        with pytest.raises(ValueError, match="out of range"):
            Register("TEST_REG", -1, RegisterType.RW)

    def test_register_invalid_address_too_high(self):
        """Test that addresses > 0xFF raise ValueError."""
        with pytest.raises(ValueError, match="out of range"):
            Register("TEST_REG", 0x100, RegisterType.RW)

    def test_register_boundary_addresses(self):
        """Test that boundary addresses are valid."""
        reg_low = Register("LOW", 0x00, RegisterType.RW)
        reg_high = Register("HIGH", 0xFF, RegisterType.RW)
        assert reg_low.address == 0x00
        assert reg_high.address == 0xFF


class TestRegister32:
    """Tests for Register32 dataclass (32-bit register pairs)."""

    def test_register32_creation(self):
        """Test basic 32-bit register creation."""
        reg = Register32("TEST_32", 0x10, 0x11, RegisterType.RW, "Test 32-bit")
        assert reg.name == "TEST_32"
        assert reg.address_lo == 0x10
        assert reg.address_hi == 0x11
        assert reg.reg_type == RegisterType.RW
        assert reg.description == "Test 32-bit"

    def test_register32_frozen(self):
        """Test that Register32 is immutable."""
        reg = Register32("TEST_32", 0x10, 0x11, RegisterType.RW)
        with pytest.raises(AttributeError):
            reg.name = "NEW_NAME"  # type: ignore[misc]

    def test_register32_invalid_lo_address(self):
        """Test that invalid LO address raises ValueError."""
        with pytest.raises(ValueError, match="LO register"):
            Register32("TEST", 0x100, 0x11, RegisterType.RW)

    def test_register32_invalid_hi_address(self):
        """Test that invalid HI address raises ValueError."""
        with pytest.raises(ValueError, match="HI register"):
            Register32("TEST", 0x10, 0x100, RegisterType.RW)


# =============================================================================
# System Bus Signal Tests
# =============================================================================


class TestSystemBusSignals:
    """Tests for system bus signal definitions."""

    def test_system_bus_has_64_signals(self):
        """Test that system bus has exactly 64 signals."""
        assert len(SysBus) == 64

    def test_system_bus_first_signal_is_disconnect(self):
        """Test that index 0 is DISCONNECT."""
        assert SysBus.DISCONNECT == 0

    def test_signal_index_to_name_valid(self):
        """Test converting valid indices to names."""
        assert signal_index_to_name(0) == "DISCONNECT"
        assert signal_index_to_name(1) == "IN1_TTL"
        assert signal_index_to_name(32) == "AND1"
        assert signal_index_to_name(63) == "SOFT_IN4"

    def test_signal_index_to_name_invalid(self):
        """Test that invalid indices raise ValueError."""
        with pytest.raises(ValueError, match="Signal index must be 0-63"):
            signal_index_to_name(-1)
        with pytest.raises(ValueError, match="Signal index must be 0-63"):
            signal_index_to_name(64)


# =============================================================================
# SysBus Constants Tests
# =============================================================================


class TestSysBusConstants:
    """Tests for SysBus class constants."""

    def test_sysbus_disconnect(self):
        """Test DISCONNECT constant."""
        assert SysBus.DISCONNECT == 0

    def test_sysbus_logic_gates(self):
        """Test logic gate output constants."""
        assert SysBus.AND1 == 32
        assert SysBus.AND2 == 33
        assert SysBus.AND3 == 34
        assert SysBus.AND4 == 35
        assert SysBus.OR1 == 36
        assert SysBus.OR2 == 37
        assert SysBus.OR3 == 38
        assert SysBus.OR4 == 39

    def test_sysbus_soft_inputs(self):
        """Test software input constants."""
        assert SysBus.SOFT_IN1 == 60
        assert SysBus.SOFT_IN2 == 61
        assert SysBus.SOFT_IN3 == 62
        assert SysBus.SOFT_IN4 == 63

    def test_sysbus_matches_signal_list(self):
        """Test that SysBus constants match SysBus indices."""
        assert signal_index_to_name(SysBus.DISCONNECT) == "DISCONNECT"
        assert signal_index_to_name(SysBus.AND1) == "AND1"
        assert signal_index_to_name(SysBus.PULSE1) == "PULSE1"
        assert signal_index_to_name(SysBus.CLOCK_1MHZ) == "CLOCK_1MHZ"


# =============================================================================
# Register Lookup Tests
# =============================================================================


class TestRegisterLookup:
    """Tests for register lookup functions."""

    def test_registers_by_name_not_empty(self):
        """Test that register name lookup dict is populated."""
        assert len(REGISTERS_BY_NAME) > 0

    def test_registers_by_address_not_empty(self):
        """Test that register address lookup dict is populated."""
        assert len(REGISTERS_BY_ADDRESS) > 0

    def test_get_register_by_name(self):
        """Test getting register by name."""
        reg = get_register("SYS_VER")
        assert reg.name == "SYS_VER"
        assert reg.address == 0xF0
        assert reg.reg_type == RegisterType.RO

    def test_get_register_by_address(self):
        """Test getting register by address."""
        reg = get_register(0xF0)
        assert reg.name == "SYS_VER"
        assert reg.address == 0xF0

    def test_get_register_invalid_name(self):
        """Test that invalid name raises KeyError."""
        with pytest.raises(KeyError, match="Unknown register name"):
            get_register("INVALID_REG")

    def test_get_register_invalid_address(self):
        """Test that invalid address raises KeyError."""
        with pytest.raises(KeyError, match="Unknown register address"):
            get_register(0xFE)  # Unused address

    def test_get_register_32bit_valid(self):
        """Test getting 32-bit register pair by name."""
        reg = get_register_32bit("DIV1_DIV")
        assert reg.name == "DIV1_DIV"
        assert reg.address_lo == 0x38
        assert reg.address_hi == 0x39
        assert reg.reg_type == RegisterType.RW

    def test_get_register_32bit_invalid(self):
        """Test that invalid 32-bit register name raises KeyError."""
        with pytest.raises(KeyError, match="Unknown 32-bit register"):
            get_register_32bit("INVALID_32BIT")


# =============================================================================
# RegAddr Constants Tests
# =============================================================================


class TestRegAddrConstants:
    """Tests for RegAddr class constants."""

    def test_regaddr_system_registers(self):
        """Test system register address constants."""
        assert RegAddr.SYS_VER == 0xF0
        assert RegAddr.SYS_STATERR == 0xF1
        assert RegAddr.SYS_RESET == 0x7E
        assert RegAddr.SOFT_IN == 0x7F

    def test_regaddr_position_compare(self):
        """Test position compare register address constants."""
        assert RegAddr.PC_ENC == 0x88
        assert RegAddr.PC_TSPRE == 0x89
        assert RegAddr.PC_ARM == 0x8B
        assert RegAddr.PC_DISARM == 0x8C

    def test_regaddr_matches_register_definitions(self):
        """Test that RegAddr constants match register definitions."""
        assert get_register("SYS_VER").address == RegAddr.SYS_VER
        assert get_register("PC_ARM").address == RegAddr.PC_ARM
        assert get_register("PC_BIT_CAP").address == RegAddr.PC_BIT_CAP


# =============================================================================
# Type-Specific Accessor Tests
# =============================================================================


class TestTypeAccessors:
    """Tests for type-specific register accessor functions."""

    def test_is_mux_register_true(self):
        """Test is_mux_register returns True for MUX registers."""
        assert is_mux_register(0x08) is True  # AND1_INP1
        assert is_mux_register(0x60) is True  # OUT1_TTL

    def test_is_mux_register_false(self):
        """Test is_mux_register returns False for non-MUX registers."""
        assert is_mux_register(0x00) is False  # AND1_INV (RW)
        assert is_mux_register(0xF0) is False  # SYS_VER (RO)
        assert is_mux_register(0x8B) is False  # PC_ARM (CMD)

    def test_is_readonly_register_true(self):
        """Test is_readonly_register returns True for RO registers."""
        assert is_readonly_register(0xF0) is True  # SYS_VER
        assert is_readonly_register(0xF1) is True  # SYS_STATERR
        assert is_readonly_register(0xF6) is True  # PC_NUM_CAPLO

    def test_is_readonly_register_false(self):
        """Test is_readonly_register returns False for non-RO registers."""
        assert is_readonly_register(0x00) is False  # AND1_INV (RW)
        assert is_readonly_register(0x08) is False  # AND1_INP1 (MUX)
        assert is_readonly_register(0x8B) is False  # PC_ARM (CMD)

    def test_is_command_register_true(self):
        """Test is_command_register returns True for CMD registers."""
        assert is_command_register(0x7E) is True  # SYS_RESET
        assert is_command_register(0x8B) is True  # PC_ARM
        assert is_command_register(0x8C) is True  # PC_DISARM
        assert is_command_register(0x80) is True  # POS1_SETLO

    def test_is_command_register_false(self):
        """Test is_command_register returns False for non-CMD registers."""
        assert is_command_register(0x00) is False  # AND1_INV (RW)
        assert is_command_register(0xF0) is False  # SYS_VER (RO)
        assert is_command_register(0x08) is False  # AND1_INP1 (MUX)


# =============================================================================
# Get All Registers Tests
# =============================================================================


class TestGetAllRegisters:
    """Tests for get_all_registers functions."""

    def test_get_all_registers_returns_list(self):
        """Test that get_all_registers returns a list."""
        regs = get_all_registers()
        assert isinstance(regs, list)
        assert len(regs) > 0

    def test_get_all_registers_all_are_register_type(self):
        """Test that all items are Register objects."""
        regs = get_all_registers()
        for reg in regs:
            assert isinstance(reg, Register)

    def test_get_all_registers_filtered_by_type(self):
        """Test filtering registers by type."""
        ro_regs = get_all_registers(RegisterType.RO)
        assert all(reg.reg_type == RegisterType.RO for reg in ro_regs)
        assert len(ro_regs) > 0

        mux_regs = get_all_registers(RegisterType.MUX)
        assert all(reg.reg_type == RegisterType.MUX for reg in mux_regs)
        assert len(mux_regs) > 0

    def test_get_all_registers_32bit_returns_list(self):
        """Test that get_all_registers_32bit returns a list."""
        regs = get_all_registers_32bit()
        assert isinstance(regs, list)
        assert len(regs) > 0

    def test_get_all_registers_32bit_all_are_register32_type(self):
        """Test that all items are Register32 objects."""
        regs = get_all_registers_32bit()
        for reg in regs:
            assert isinstance(reg, Register32)


# =============================================================================
# Specific Register Verification Tests
# =============================================================================


class TestSpecificRegisters:
    """Tests to verify specific register definitions match zebraRegs.h."""

    def test_and_gate_registers(self):
        """Test AND gate register definitions."""
        # Inversion registers
        assert get_register("AND1_INV").address == 0x00
        assert get_register("AND2_INV").address == 0x01
        assert get_register("AND3_INV").address == 0x02
        assert get_register("AND4_INV").address == 0x03

        # Enable registers
        assert get_register("AND1_ENA").address == 0x04
        assert get_register("AND2_ENA").address == 0x05

        # Input muxes
        assert get_register("AND1_INP1").address == 0x08
        assert get_register("AND1_INP1").reg_type == RegisterType.MUX

    def test_or_gate_registers(self):
        """Test OR gate register definitions."""
        assert get_register("OR1_INV").address == 0x18
        assert get_register("OR1_ENA").address == 0x1C
        assert get_register("OR1_INP1").address == 0x20

    def test_gate_generator_registers(self):
        """Test gate generator register definitions."""
        assert get_register("GATE1_INP1").address == 0x30
        assert get_register("GATE1_INP2").address == 0x34

    def test_divider_registers(self):
        """Test divider register definitions."""
        assert get_register("DIV1_DIVLO").address == 0x38
        assert get_register("DIV1_DIVHI").address == 0x39
        assert get_register("DIV1_INP").address == 0x40

        # 32-bit pair
        div1 = get_register_32bit("DIV1_DIV")
        assert div1.address_lo == 0x38
        assert div1.address_hi == 0x39

    def test_pulse_generator_registers(self):
        """Test pulse generator register definitions."""
        assert get_register("PULSE1_DLY").address == 0x44
        assert get_register("PULSE1_WID").address == 0x48
        assert get_register("PULSE1_PRE").address == 0x4C
        assert get_register("PULSE1_INP").address == 0x50

    def test_output_mux_registers(self):
        """Test output multiplexer register definitions."""
        assert get_register("OUT1_TTL").address == 0x60
        assert get_register("OUT1_NIM").address == 0x61
        assert get_register("OUT1_LVDS").address == 0x62
        assert get_register("OUT3_OC").address == 0x67  # OUT3 has OC not NIM

    def test_position_compare_registers(self):
        """Test position compare register definitions."""
        assert get_register("PC_ENC").address == 0x88
        assert get_register("PC_TSPRE").address == 0x89
        assert get_register("PC_ARM").address == 0x8B
        assert get_register("PC_ARM").reg_type == RegisterType.CMD
        assert get_register("PC_DISARM").address == 0x8C
        assert get_register("PC_BIT_CAP").address == 0x9F

    def test_status_registers(self):
        """Test status register definitions."""
        assert get_register("SYS_VER").address == 0xF0
        assert get_register("SYS_VER").reg_type == RegisterType.RO
        assert get_register("SYS_STATERR").address == 0xF1
        assert get_register("PC_NUM_CAPLO").address == 0xF6
        assert get_register("PC_NUM_CAPHI").address == 0xF7

    def test_32bit_position_compare_parameters(self):
        """Test 32-bit position compare parameter register pairs."""
        gate_start = get_register_32bit("PC_GATE_START")
        assert gate_start.address_lo == 0x8E
        assert gate_start.address_hi == 0x8F

        pulse_step = get_register_32bit("PC_PULSE_STEP")
        assert pulse_step.address_lo == 0x9B
        assert pulse_step.address_hi == 0x9C

        pc_num_cap = get_register_32bit("PC_NUM_CAP")
        assert pc_num_cap.address_lo == 0xF6
        assert pc_num_cap.address_hi == 0xF7
        assert pc_num_cap.reg_type == RegisterType.RO


# =============================================================================
# Register Count and Coverage Tests
# =============================================================================


class TestRegisterCoverage:
    """Tests to verify comprehensive register coverage."""

    def test_expected_number_of_mux_registers(self):
        """Test that we have expected number of MUX registers.

        Based on zebraRegs.h, there should be many MUX registers for:
        - AND/OR gate inputs (32 total: 4 gates × 4 inputs × 2 types)
        - GATE inputs (8 total: 4 gates × 2 inputs)
        - DIV inputs (4 total)
        - PULSE inputs (4 total)
        - Quad inputs (2 total)
        - PC external inputs (3 total)
        - Output muxes (28 total: 4 + 4 + 4 + 4 + 4×3)
        """
        mux_regs = get_all_registers(RegisterType.MUX)
        # Should have at least 70 MUX registers
        assert len(mux_regs) >= 70

    def test_expected_number_of_readonly_registers(self):
        """Test that we have expected RO registers."""
        ro_regs = get_all_registers(RegisterType.RO)
        # SYS_VER, SYS_STATERR, SYS_STAT1LO/HI, SYS_STAT2LO/HI, PC_NUM_CAPLO/HI
        assert len(ro_regs) >= 8

    def test_expected_number_of_command_registers(self):
        """Test that we have expected CMD registers."""
        cmd_regs = get_all_registers(RegisterType.CMD)
        # SYS_RESET, PC_ARM, PC_DISARM, POS1-4_SETLO/HI
        assert len(cmd_regs) >= 10

    def test_no_duplicate_addresses(self):
        """Test that no two registers share the same address."""
        addresses = [reg.address for reg in get_all_registers()]
        assert len(addresses) == len(set(addresses)), (
            "Duplicate register addresses found"
        )

    def test_no_duplicate_names(self):
        """Test that no two registers share the same name."""
        names = [reg.name for reg in get_all_registers()]
        assert len(names) == len(set(names)), "Duplicate register names found"

    def test_32bit_registers_have_valid_component_addresses(self):
        """Test that 32-bit registers reference valid component registers."""
        for reg32 in get_all_registers_32bit():
            # Check LO register exists
            lo_reg = get_register(reg32.address_lo)
            assert lo_reg is not None, f"LO register {reg32.address_lo:#04x} not found"

            # Check HI register exists
            hi_reg = get_register(reg32.address_hi)
            assert hi_reg is not None, f"HI register {reg32.address_hi:#04x} not found"
