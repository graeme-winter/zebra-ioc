"""Zebra register definitions and system bus signal mapping.

This module provides a complete register abstraction layer for the Zebra hardware,
including:
- Complete register definitions from zebraRegs.h
- Register type classification (RW, RO, Cmd, Mux)
- System bus signal mapping (64 signals)
- Bidirectional lookup (name ↔ address)
- 32-bit register pair handling

Reference: https://github.com/DiamondLightSource/zebra/blob/fastcs-experiment/zebraApp/src/zebraRegs.h
"""

from dataclasses import dataclass
from enum import Enum, IntEnum, auto


class RegisterType(Enum):
    """Register type classification.

    - RW: Read-Write configuration register
    - RO: Read-Only status register
    - CMD: Command register (write-only, triggers actions)
    - MUX: Multiplexer register (selects from 64-signal system bus)
    """

    RW = auto()  # Read-Write
    RO = auto()  # Read-Only
    CMD = auto()  # Command (write-only)
    MUX = auto()  # Multiplexer (system bus selection)


@dataclass(frozen=True)
class Register:
    """Definition of a single Zebra register.

    Attributes:
        name: Register name (e.g., 'AND1_INP1')
        address: Register address (0x00-0xFF)
        reg_type: Register type (RW, RO, CMD, MUX)
        description: Optional description of register purpose
    """

    name: str
    address: int
    reg_type: RegisterType
    description: str = ""

    def __post_init__(self):
        """Validate register address is in valid range."""
        if not 0 <= self.address <= 0xFF:
            raise ValueError(
                f"Register address {self.address:#04x} out of range [0x00-0xFF]"
            )


@dataclass(frozen=True)
class Register32:
    """Definition of a 32-bit register pair (LO/HI).

    Attributes:
        name: Combined register name (e.g., 'DIV1_DIV')
        address_lo: Low 16-bit register address
        address_hi: High 16-bit register address
        reg_type: Register type (typically RW or RO)
        description: Optional description of register purpose
    """

    name: str
    address_lo: int
    address_hi: int
    reg_type: RegisterType
    description: str = ""

    def __post_init__(self):
        """Validate register addresses are in valid range."""
        if not 0 <= self.address_lo <= 0xFF:
            raise ValueError(f"LO register address {self.address_lo:#04x} out of range")
        if not 0 <= self.address_hi <= 0xFF:
            raise ValueError(f"HI register address {self.address_hi:#04x} out of range")


# =============================================================================
# System Bus Signal Definitions (64 signals, indices 0-63)
# =============================================================================


class SysBus(IntEnum):
    """Constants for system bus signal indices.

    Provides convenient access to system bus indices without needing
    to look them up by name. Values are 0-63.
    """

    DISCONNECT = 0

    # Input signals
    IN1_TTL = 1
    IN1_NIM = 2
    IN1_LVDS = 3
    IN2_TTL = 4
    IN2_NIM = 5
    IN2_LVDS = 6
    IN3_TTL = 7
    IN3_OC = 8
    IN3_LVDS = 9
    IN4_TTL = 10
    IN4_CMP = 11
    IN4_PECL = 12

    # Encoder inputs
    IN5_ENCA = 13
    IN5_ENCB = 14
    IN5_ENCZ = 15
    IN5_CONN = 16
    IN6_ENCA = 17
    IN6_ENCB = 18
    IN6_ENCZ = 19
    IN6_CONN = 20
    IN7_ENCA = 21
    IN7_ENCB = 22
    IN7_ENCZ = 23
    IN7_CONN = 24
    IN8_ENCA = 25
    IN8_ENCB = 26
    IN8_ENCZ = 27
    IN8_CONN = 28

    # Position compare signals
    PC_ARM = 29
    PC_GATE = 30
    PC_PULSE = 31

    # Logic gate outputs
    AND1 = 32
    AND2 = 33
    AND3 = 34
    AND4 = 35
    OR1 = 36
    OR2 = 37
    OR3 = 38
    OR4 = 39

    # Gate generator outputs
    GATE1 = 40
    GATE2 = 41
    GATE3 = 42
    GATE4 = 43

    # Divider outputs
    DIV1_OUTD = 44
    DIV2_OUTD = 45
    DIV3_OUTD = 46
    DIV4_OUTD = 47
    DIV1_OUTN = 48
    DIV2_OUTN = 49
    DIV3_OUTN = 50
    DIV4_OUTN = 51

    # Pulse generator outputs
    PULSE1 = 52
    PULSE2 = 53
    PULSE3 = 54
    PULSE4 = 55

    # Quadrature outputs
    QUAD_OUTA = 56
    QUAD_OUTB = 57

    # Clocks
    CLOCK_1KHZ = 58
    CLOCK_1MHZ = 59

    # Software inputs
    SOFT_IN1 = 60
    SOFT_IN2 = 61
    SOFT_IN3 = 62
    SOFT_IN4 = 63


def signal_index_to_name(index: int) -> str:
    """Convert system bus signal index to name.

    Args:
        index: Signal index (0-63)

    Returns:
        Signal name

    Raises:
        ValueError: If index out of range
    """
    if not 0 <= index <= len(SysBus) - 1:
        raise ValueError(f"Signal index must be 0-63, got {index}")
    return SysBus(index).name


# =============================================================================
# 16-bit Register Definitions
# =============================================================================

# The registers are grouped by function for clarity

_REGISTERS: tuple[Register, ...] = (
    # -------------------------------------------------------------------------
    # AND Gate Configuration (AND1-AND4)
    # -------------------------------------------------------------------------
    # Inversion registers (bitfield: bits 0-3 control inversion of inputs 1-4)
    Register("AND1_INV", 0x00, RegisterType.RW, "AND1 input inversion mask"),
    Register("AND2_INV", 0x01, RegisterType.RW, "AND2 input inversion mask"),
    Register("AND3_INV", 0x02, RegisterType.RW, "AND3 input inversion mask"),
    Register("AND4_INV", 0x03, RegisterType.RW, "AND4 input inversion mask"),
    # Enable registers (bitfield: bits 0-3 enable inputs 1-4)
    Register("AND1_ENA", 0x04, RegisterType.RW, "AND1 input enable mask"),
    Register("AND2_ENA", 0x05, RegisterType.RW, "AND2 input enable mask"),
    Register("AND3_ENA", 0x06, RegisterType.RW, "AND3 input enable mask"),
    Register("AND4_ENA", 0x07, RegisterType.RW, "AND4 input enable mask"),
    # AND gate input multiplexers (select from 64 system bus signals)
    Register("AND1_INP1", 0x08, RegisterType.MUX, "AND1 input 1 source"),
    Register("AND1_INP2", 0x09, RegisterType.MUX, "AND1 input 2 source"),
    Register("AND1_INP3", 0x0A, RegisterType.MUX, "AND1 input 3 source"),
    Register("AND1_INP4", 0x0B, RegisterType.MUX, "AND1 input 4 source"),
    Register("AND2_INP1", 0x0C, RegisterType.MUX, "AND2 input 1 source"),
    Register("AND2_INP2", 0x0D, RegisterType.MUX, "AND2 input 2 source"),
    Register("AND2_INP3", 0x0E, RegisterType.MUX, "AND2 input 3 source"),
    Register("AND2_INP4", 0x0F, RegisterType.MUX, "AND2 input 4 source"),
    Register("AND3_INP1", 0x10, RegisterType.MUX, "AND3 input 1 source"),
    Register("AND3_INP2", 0x11, RegisterType.MUX, "AND3 input 2 source"),
    Register("AND3_INP3", 0x12, RegisterType.MUX, "AND3 input 3 source"),
    Register("AND3_INP4", 0x13, RegisterType.MUX, "AND3 input 4 source"),
    Register("AND4_INP1", 0x14, RegisterType.MUX, "AND4 input 1 source"),
    Register("AND4_INP2", 0x15, RegisterType.MUX, "AND4 input 2 source"),
    Register("AND4_INP3", 0x16, RegisterType.MUX, "AND4 input 3 source"),
    Register("AND4_INP4", 0x17, RegisterType.MUX, "AND4 input 4 source"),
    # -------------------------------------------------------------------------
    # OR Gate Configuration (OR1-OR4)
    # -------------------------------------------------------------------------
    # Inversion registers
    Register("OR1_INV", 0x18, RegisterType.RW, "OR1 input inversion mask"),
    Register("OR2_INV", 0x19, RegisterType.RW, "OR2 input inversion mask"),
    Register("OR3_INV", 0x1A, RegisterType.RW, "OR3 input inversion mask"),
    Register("OR4_INV", 0x1B, RegisterType.RW, "OR4 input inversion mask"),
    # Enable registers
    Register("OR1_ENA", 0x1C, RegisterType.RW, "OR1 input enable mask"),
    Register("OR2_ENA", 0x1D, RegisterType.RW, "OR2 input enable mask"),
    Register("OR3_ENA", 0x1E, RegisterType.RW, "OR3 input enable mask"),
    Register("OR4_ENA", 0x1F, RegisterType.RW, "OR4 input enable mask"),
    # OR gate input multiplexers
    Register("OR1_INP1", 0x20, RegisterType.MUX, "OR1 input 1 source"),
    Register("OR1_INP2", 0x21, RegisterType.MUX, "OR1 input 2 source"),
    Register("OR1_INP3", 0x22, RegisterType.MUX, "OR1 input 3 source"),
    Register("OR1_INP4", 0x23, RegisterType.MUX, "OR1 input 4 source"),
    Register("OR2_INP1", 0x24, RegisterType.MUX, "OR2 input 1 source"),
    Register("OR2_INP2", 0x25, RegisterType.MUX, "OR2 input 2 source"),
    Register("OR2_INP3", 0x26, RegisterType.MUX, "OR2 input 3 source"),
    Register("OR2_INP4", 0x27, RegisterType.MUX, "OR2 input 4 source"),
    Register("OR3_INP1", 0x28, RegisterType.MUX, "OR3 input 1 source"),
    Register("OR3_INP2", 0x29, RegisterType.MUX, "OR3 input 2 source"),
    Register("OR3_INP3", 0x2A, RegisterType.MUX, "OR3 input 3 source"),
    Register("OR3_INP4", 0x2B, RegisterType.MUX, "OR3 input 4 source"),
    Register("OR4_INP1", 0x2C, RegisterType.MUX, "OR4 input 1 source"),
    Register("OR4_INP2", 0x2D, RegisterType.MUX, "OR4 input 2 source"),
    Register("OR4_INP3", 0x2E, RegisterType.MUX, "OR4 input 3 source"),
    Register("OR4_INP4", 0x2F, RegisterType.MUX, "OR4 input 4 source"),
    # -------------------------------------------------------------------------
    # Gate Generator Configuration (GATE1-GATE4)
    # -------------------------------------------------------------------------
    # Trigger inputs (set output high)
    Register("GATE1_INP1", 0x30, RegisterType.MUX, "GATE1 trigger input"),
    Register("GATE2_INP1", 0x31, RegisterType.MUX, "GATE2 trigger input"),
    Register("GATE3_INP1", 0x32, RegisterType.MUX, "GATE3 trigger input"),
    Register("GATE4_INP1", 0x33, RegisterType.MUX, "GATE4 trigger input"),
    # Reset inputs (set output low)
    Register("GATE1_INP2", 0x34, RegisterType.MUX, "GATE1 reset input"),
    Register("GATE2_INP2", 0x35, RegisterType.MUX, "GATE2 reset input"),
    Register("GATE3_INP2", 0x36, RegisterType.MUX, "GATE3 reset input"),
    Register("GATE4_INP2", 0x37, RegisterType.MUX, "GATE4 reset input"),
    # -------------------------------------------------------------------------
    # Pulse Divider Configuration (DIV1-DIV4)
    # Note: DIVn_DIV registers are 32-bit (LO/HI pairs) - see _REGISTERS_32BIT
    # -------------------------------------------------------------------------
    Register("DIV1_DIVLO", 0x38, RegisterType.RW, "DIV1 divisor low 16 bits"),
    Register("DIV1_DIVHI", 0x39, RegisterType.RW, "DIV1 divisor high 16 bits"),
    Register("DIV2_DIVLO", 0x3A, RegisterType.RW, "DIV2 divisor low 16 bits"),
    Register("DIV2_DIVHI", 0x3B, RegisterType.RW, "DIV2 divisor high 16 bits"),
    Register("DIV3_DIVLO", 0x3C, RegisterType.RW, "DIV3 divisor low 16 bits"),
    Register("DIV3_DIVHI", 0x3D, RegisterType.RW, "DIV3 divisor high 16 bits"),
    Register("DIV4_DIVLO", 0x3E, RegisterType.RW, "DIV4 divisor low 16 bits"),
    Register("DIV4_DIVHI", 0x3F, RegisterType.RW, "DIV4 divisor high 16 bits"),
    # Divider input multiplexers
    Register("DIV1_INP", 0x40, RegisterType.MUX, "DIV1 input source"),
    Register("DIV2_INP", 0x41, RegisterType.MUX, "DIV2 input source"),
    Register("DIV3_INP", 0x42, RegisterType.MUX, "DIV3 input source"),
    Register("DIV4_INP", 0x43, RegisterType.MUX, "DIV4 input source"),
    # -------------------------------------------------------------------------
    # Pulse Generator Configuration (PULSE1-PULSE4)
    # -------------------------------------------------------------------------
    # Pulse delay (time from trigger to pulse start)
    Register("PULSE1_DLY", 0x44, RegisterType.RW, "PULSE1 delay"),
    Register("PULSE2_DLY", 0x45, RegisterType.RW, "PULSE2 delay"),
    Register("PULSE3_DLY", 0x46, RegisterType.RW, "PULSE3 delay"),
    Register("PULSE4_DLY", 0x47, RegisterType.RW, "PULSE4 delay"),
    # Pulse width
    Register("PULSE1_WID", 0x48, RegisterType.RW, "PULSE1 width"),
    Register("PULSE2_WID", 0x49, RegisterType.RW, "PULSE2 width"),
    Register("PULSE3_WID", 0x4A, RegisterType.RW, "PULSE3 width"),
    Register("PULSE4_WID", 0x4B, RegisterType.RW, "PULSE4 width"),
    # Pulse prescaler (time unit selection)
    Register("PULSE1_PRE", 0x4C, RegisterType.RW, "PULSE1 prescaler"),
    Register("PULSE2_PRE", 0x4D, RegisterType.RW, "PULSE2 prescaler"),
    Register("PULSE3_PRE", 0x4E, RegisterType.RW, "PULSE3 prescaler"),
    Register("PULSE4_PRE", 0x4F, RegisterType.RW, "PULSE4 prescaler"),
    # Pulse input multiplexers
    Register("PULSE1_INP", 0x50, RegisterType.MUX, "PULSE1 input source"),
    Register("PULSE2_INP", 0x51, RegisterType.MUX, "PULSE2 input source"),
    Register("PULSE3_INP", 0x52, RegisterType.MUX, "PULSE3 input source"),
    Register("PULSE4_INP", 0x53, RegisterType.MUX, "PULSE4 input source"),
    # Output polarity control (bitfield)
    Register("POLARITY", 0x54, RegisterType.RW, "Output polarity control"),
    # -------------------------------------------------------------------------
    # Quadrature Encoder
    # -------------------------------------------------------------------------
    Register("QUAD_DIR", 0x55, RegisterType.MUX, "Quadrature direction input"),
    Register("QUAD_STEP", 0x56, RegisterType.MUX, "Quadrature step input"),
    # -------------------------------------------------------------------------
    # External Position Compare Inputs
    # -------------------------------------------------------------------------
    Register("PC_ARM_INP", 0x57, RegisterType.MUX, "External arm input"),
    Register("PC_GATE_INP", 0x58, RegisterType.MUX, "External gate input"),
    Register("PC_PULSE_INP", 0x59, RegisterType.MUX, "External pulse input"),
    # -------------------------------------------------------------------------
    # Output Multiplexers (OUT1-OUT8)
    # -------------------------------------------------------------------------
    # OUT1: TTL, NIM, LVDS outputs
    Register("OUT1_TTL", 0x60, RegisterType.MUX, "OUT1 TTL output source"),
    Register("OUT1_NIM", 0x61, RegisterType.MUX, "OUT1 NIM output source"),
    Register("OUT1_LVDS", 0x62, RegisterType.MUX, "OUT1 LVDS output source"),
    # OUT2: TTL, NIM, LVDS outputs
    Register("OUT2_TTL", 0x63, RegisterType.MUX, "OUT2 TTL output source"),
    Register("OUT2_NIM", 0x64, RegisterType.MUX, "OUT2 NIM output source"),
    Register("OUT2_LVDS", 0x65, RegisterType.MUX, "OUT2 LVDS output source"),
    # OUT3: TTL, OC (open collector), LVDS outputs
    Register("OUT3_TTL", 0x66, RegisterType.MUX, "OUT3 TTL output source"),
    Register("OUT3_OC", 0x67, RegisterType.MUX, "OUT3 open collector source"),
    Register("OUT3_LVDS", 0x68, RegisterType.MUX, "OUT3 LVDS output source"),
    # OUT4: TTL, NIM, PECL outputs
    Register("OUT4_TTL", 0x69, RegisterType.MUX, "OUT4 TTL output source"),
    Register("OUT4_NIM", 0x6A, RegisterType.MUX, "OUT4 NIM output source"),
    Register("OUT4_PECL", 0x6B, RegisterType.MUX, "OUT4 PECL output source"),
    # OUT5-OUT8: Encoder outputs (ENCA, ENCB, ENCZ, CONN)
    Register("OUT5_ENCA", 0x6C, RegisterType.MUX, "OUT5 encoder A source"),
    Register("OUT5_ENCB", 0x6D, RegisterType.MUX, "OUT5 encoder B source"),
    Register("OUT5_ENCZ", 0x6E, RegisterType.MUX, "OUT5 encoder Z source"),
    Register("OUT5_CONN", 0x6F, RegisterType.MUX, "OUT5 connect enable source"),
    Register("OUT6_ENCA", 0x70, RegisterType.MUX, "OUT6 encoder A source"),
    Register("OUT6_ENCB", 0x71, RegisterType.MUX, "OUT6 encoder B source"),
    Register("OUT6_ENCZ", 0x72, RegisterType.MUX, "OUT6 encoder Z source"),
    Register("OUT6_CONN", 0x73, RegisterType.MUX, "OUT6 connect enable source"),
    Register("OUT7_ENCA", 0x74, RegisterType.MUX, "OUT7 encoder A source"),
    Register("OUT7_ENCB", 0x75, RegisterType.MUX, "OUT7 encoder B source"),
    Register("OUT7_ENCZ", 0x76, RegisterType.MUX, "OUT7 encoder Z source"),
    Register("OUT7_CONN", 0x77, RegisterType.MUX, "OUT7 connect enable source"),
    Register("OUT8_ENCA", 0x78, RegisterType.MUX, "OUT8 encoder A source"),
    Register("OUT8_ENCB", 0x79, RegisterType.MUX, "OUT8 encoder B source"),
    Register("OUT8_ENCZ", 0x7A, RegisterType.MUX, "OUT8 encoder Z source"),
    Register("OUT8_CONN", 0x7B, RegisterType.MUX, "OUT8 connect enable source"),
    # -------------------------------------------------------------------------
    # Divider First Pulse Control
    # -------------------------------------------------------------------------
    Register("DIV_FIRST", 0x7C, RegisterType.RW, "Divider first pulse behavior"),
    # -------------------------------------------------------------------------
    # System Control
    # -------------------------------------------------------------------------
    Register("SYS_RESET", 0x7E, RegisterType.CMD, "System reset command"),
    Register("SOFT_IN", 0x7F, RegisterType.RW, "Software inputs (bits 0-3)"),
    # -------------------------------------------------------------------------
    # Position Counter Load Commands
    # -------------------------------------------------------------------------
    Register("POS1_SETLO", 0x80, RegisterType.CMD, "Load encoder 1 low 16 bits"),
    Register("POS1_SETHI", 0x81, RegisterType.CMD, "Load encoder 1 high 16 bits"),
    Register("POS2_SETLO", 0x82, RegisterType.CMD, "Load encoder 2 low 16 bits"),
    Register("POS2_SETHI", 0x83, RegisterType.CMD, "Load encoder 2 high 16 bits"),
    Register("POS3_SETLO", 0x84, RegisterType.CMD, "Load encoder 3 low 16 bits"),
    Register("POS3_SETHI", 0x85, RegisterType.CMD, "Load encoder 3 high 16 bits"),
    Register("POS4_SETLO", 0x86, RegisterType.CMD, "Load encoder 4 low 16 bits"),
    Register("POS4_SETHI", 0x87, RegisterType.CMD, "Load encoder 4 high 16 bits"),
    # -------------------------------------------------------------------------
    # Position Compare Configuration
    # -------------------------------------------------------------------------
    Register("PC_ENC", 0x88, RegisterType.RW, "Encoder selection (0-4)"),
    Register("PC_TSPRE", 0x89, RegisterType.RW, "Timestamp prescaler"),
    Register("PC_ARM_SEL", 0x8A, RegisterType.RW, "Arm source (0=soft, 1=ext)"),
    Register("PC_ARM", 0x8B, RegisterType.CMD, "Software arm command"),
    Register("PC_DISARM", 0x8C, RegisterType.CMD, "Software disarm command"),
    Register(
        "PC_GATE_SEL", 0x8D, RegisterType.RW, "Gate source (0=pos, 1=time, 2=ext)"
    ),
    # Gate parameters (32-bit pairs - see _REGISTERS_32BIT)
    Register("PC_GATE_STARTLO", 0x8E, RegisterType.RW, "Gate start low 16 bits"),
    Register("PC_GATE_STARTHI", 0x8F, RegisterType.RW, "Gate start high 16 bits"),
    Register("PC_GATE_WIDLO", 0x90, RegisterType.RW, "Gate width low 16 bits"),
    Register("PC_GATE_WIDHI", 0x91, RegisterType.RW, "Gate width high 16 bits"),
    Register("PC_GATE_NGATELO", 0x92, RegisterType.RW, "Number of gates low 16 bits"),
    Register("PC_GATE_NGATEHI", 0x93, RegisterType.RW, "Number of gates high 16 bits"),
    Register("PC_GATE_STEPLO", 0x94, RegisterType.RW, "Gate step low 16 bits"),
    Register("PC_GATE_STEPHI", 0x95, RegisterType.RW, "Gate step high 16 bits"),
    # Pulse source selection
    Register(
        "PC_PULSE_SEL", 0x96, RegisterType.RW, "Pulse source (0=pos, 1=time, 2=ext)"
    ),
    # Pulse parameters (32-bit pairs - see _REGISTERS_32BIT)
    Register("PC_PULSE_STARTLO", 0x97, RegisterType.RW, "Pulse start low 16 bits"),
    Register("PC_PULSE_STARTHI", 0x98, RegisterType.RW, "Pulse start high 16 bits"),
    Register("PC_PULSE_WIDLO", 0x99, RegisterType.RW, "Pulse width low 16 bits"),
    Register("PC_PULSE_WIDHI", 0x9A, RegisterType.RW, "Pulse width high 16 bits"),
    Register("PC_PULSE_STEPLO", 0x9B, RegisterType.RW, "Pulse step low 16 bits"),
    Register("PC_PULSE_STEPHI", 0x9C, RegisterType.RW, "Pulse step high 16 bits"),
    Register("PC_PULSE_MAXLO", 0x9D, RegisterType.RW, "Max pulses low 16 bits"),
    Register("PC_PULSE_MAXHI", 0x9E, RegisterType.RW, "Max pulses high 16 bits"),
    # Capture selection and direction
    Register("PC_BIT_CAP", 0x9F, RegisterType.RW, "Capture bit mask (10 bits)"),
    Register("PC_DIR", 0xA0, RegisterType.RW, "Direction (0=pos, 1=neg)"),
    # Pulse delay (32-bit pair)
    Register("PC_PULSE_DLYLO", 0xA1, RegisterType.RW, "Pulse delay low 16 bits"),
    Register("PC_PULSE_DLYHI", 0xA2, RegisterType.RW, "Pulse delay high 16 bits"),
    # -------------------------------------------------------------------------
    # Status Registers (Read-Only)
    # -------------------------------------------------------------------------
    Register("SYS_VER", 0xF0, RegisterType.RO, "Firmware version"),
    Register("SYS_STATERR", 0xF1, RegisterType.RO, "System state/error flags"),
    Register("SYS_STAT1LO", 0xF2, RegisterType.RO, "System bus status bits 0-15"),
    Register("SYS_STAT1HI", 0xF3, RegisterType.RO, "System bus status bits 16-31"),
    Register("SYS_STAT2LO", 0xF4, RegisterType.RO, "System bus status bits 32-47"),
    Register("SYS_STAT2HI", 0xF5, RegisterType.RO, "System bus status bits 48-63"),
    Register("PC_NUM_CAPLO", 0xF6, RegisterType.RO, "Capture count low 16 bits"),
    Register("PC_NUM_CAPHI", 0xF7, RegisterType.RO, "Capture count high 16 bits"),
)


# =============================================================================
# 32-bit Register Pair Definitions
# =============================================================================

_REGISTERS_32BIT: tuple[Register32, ...] = (
    # Divider divisors
    Register32("DIV1_DIV", 0x38, 0x39, RegisterType.RW, "DIV1 divisor (32-bit)"),
    Register32("DIV2_DIV", 0x3A, 0x3B, RegisterType.RW, "DIV2 divisor (32-bit)"),
    Register32("DIV3_DIV", 0x3C, 0x3D, RegisterType.RW, "DIV3 divisor (32-bit)"),
    Register32("DIV4_DIV", 0x3E, 0x3F, RegisterType.RW, "DIV4 divisor (32-bit)"),
    # Position counter loads
    Register32("POS1_SET", 0x80, 0x81, RegisterType.CMD, "Load encoder 1 position"),
    Register32("POS2_SET", 0x82, 0x83, RegisterType.CMD, "Load encoder 2 position"),
    Register32("POS3_SET", 0x84, 0x85, RegisterType.CMD, "Load encoder 3 position"),
    Register32("POS4_SET", 0x86, 0x87, RegisterType.CMD, "Load encoder 4 position"),
    # Gate parameters
    Register32(
        "PC_GATE_START", 0x8E, 0x8F, RegisterType.RW, "Gate start position/time"
    ),
    Register32("PC_GATE_WID", 0x90, 0x91, RegisterType.RW, "Gate width"),
    Register32("PC_GATE_NGATE", 0x92, 0x93, RegisterType.RW, "Number of gates"),
    Register32("PC_GATE_STEP", 0x94, 0x95, RegisterType.RW, "Gate step size"),
    # Pulse parameters
    Register32(
        "PC_PULSE_START", 0x97, 0x98, RegisterType.RW, "Pulse start position/time"
    ),
    Register32("PC_PULSE_WID", 0x99, 0x9A, RegisterType.RW, "Pulse width"),
    Register32("PC_PULSE_STEP", 0x9B, 0x9C, RegisterType.RW, "Pulse step size"),
    Register32("PC_PULSE_MAX", 0x9D, 0x9E, RegisterType.RW, "Maximum number of pulses"),
    Register32("PC_PULSE_DLY", 0xA1, 0xA2, RegisterType.RW, "Pulse delay"),
    # Status (32-bit read-only)
    Register32("SYS_STAT1", 0xF2, 0xF3, RegisterType.RO, "System bus 0-31 status"),
    Register32("SYS_STAT2", 0xF4, 0xF5, RegisterType.RO, "System bus 32-63 status"),
    Register32(
        "PC_NUM_CAP", 0xF6, 0xF7, RegisterType.RO, "Position compare capture count"
    ),
)


# =============================================================================
# Lookup Dictionaries (built at module load time)
# =============================================================================

# Map register name to Register object
REGISTERS_BY_NAME: dict[str, Register] = {reg.name: reg for reg in _REGISTERS}

# Map register address to Register object
REGISTERS_BY_ADDRESS: dict[int, Register] = {reg.address: reg for reg in _REGISTERS}

# Map 32-bit register name to Register32 object
REGISTERS_32BIT_BY_NAME: dict[str, Register32] = {
    reg.name: reg for reg in _REGISTERS_32BIT
}


def get_register(name_or_address: str | int) -> Register:
    """Get a register definition by name or address.

    Args:
        name_or_address: Register name (str) or address (int)

    Returns:
        Register definition

    Raises:
        KeyError: If register not found
    """
    if isinstance(name_or_address, str):
        if name_or_address not in REGISTERS_BY_NAME:
            raise KeyError(f"Unknown register name: {name_or_address!r}")
        return REGISTERS_BY_NAME[name_or_address]
    else:
        if name_or_address not in REGISTERS_BY_ADDRESS:
            raise KeyError(f"Unknown register address: {name_or_address:#04x}")
        return REGISTERS_BY_ADDRESS[name_or_address]


def get_register_32bit(name: str) -> Register32:
    """Get a 32-bit register pair definition by name.

    Args:
        name: Register name (e.g., 'DIV1_DIV', 'PC_GATE_START')

    Returns:
        Register32 definition

    Raises:
        KeyError: If register not found
    """
    if name not in REGISTERS_32BIT_BY_NAME:
        raise KeyError(f"Unknown 32-bit register: {name!r}")
    return REGISTERS_32BIT_BY_NAME[name]


def get_all_registers(reg_type: RegisterType | None = None) -> list[Register]:
    """Get all register definitions, optionally filtered by type.

    Args:
        reg_type: If specified, only return registers of this type

    Returns:
        List of Register objects
    """
    if reg_type is None:
        return list(_REGISTERS)
    return [reg for reg in _REGISTERS if reg.reg_type == reg_type]


def get_all_registers_32bit(reg_type: RegisterType | None = None) -> list[Register32]:
    """Get all 32-bit register pair definitions, optionally filtered by type.

    Args:
        reg_type: If specified, only return registers of this type

    Returns:
        List of Register32 objects
    """
    if reg_type is None:
        return list(_REGISTERS_32BIT)
    return [reg for reg in _REGISTERS_32BIT if reg.reg_type == reg_type]


def is_mux_register(address: int) -> bool:
    """Check if a register address is a multiplexer (system bus selection).

    Args:
        address: Register address

    Returns:
        True if register is a MUX type
    """
    reg = REGISTERS_BY_ADDRESS.get(address)
    return reg is not None and reg.reg_type == RegisterType.MUX


def is_readonly_register(address: int) -> bool:
    """Check if a register address is read-only.

    Args:
        address: Register address

    Returns:
        True if register is read-only
    """
    reg = REGISTERS_BY_ADDRESS.get(address)
    return reg is not None and reg.reg_type == RegisterType.RO


def is_command_register(address: int) -> bool:
    """Check if a register address is a command (write-only) register.

    Args:
        address: Register address

    Returns:
        True if register is a command register
    """
    reg = REGISTERS_BY_ADDRESS.get(address)
    return reg is not None and reg.reg_type == RegisterType.CMD


# =============================================================================
# Constants for commonly used register addresses
# =============================================================================


class RegAddr:
    """Constants for commonly used register addresses.

    Provides convenient access to register addresses without needing
    to look them up by name.
    """

    # System
    SYS_RESET = 0x7E
    SOFT_IN = 0x7F
    SYS_VER = 0xF0
    SYS_STATERR = 0xF1

    # System bus status
    SYS_STAT1LO = 0xF2
    SYS_STAT1HI = 0xF3
    SYS_STAT2LO = 0xF4
    SYS_STAT2HI = 0xF5

    # Position compare
    PC_ENC = 0x88
    PC_TSPRE = 0x89
    PC_ARM_SEL = 0x8A
    PC_ARM = 0x8B
    PC_DISARM = 0x8C
    PC_GATE_SEL = 0x8D
    PC_PULSE_SEL = 0x96
    PC_BIT_CAP = 0x9F
    PC_DIR = 0xA0
    PC_NUM_CAPLO = 0xF6
    PC_NUM_CAPHI = 0xF7

    # Gate parameters
    PC_GATE_STARTLO = 0x8E
    PC_GATE_STARTHI = 0x8F
    PC_GATE_WIDLO = 0x90
    PC_GATE_WIDHI = 0x91
    PC_GATE_NGATELO = 0x92
    PC_GATE_NGATEHI = 0x93
    PC_GATE_STEPLO = 0x94
    PC_GATE_STEPHI = 0x95

    # Pulse parameters
    PC_PULSE_STARTLO = 0x97
    PC_PULSE_STARTHI = 0x98
    PC_PULSE_WIDLO = 0x99
    PC_PULSE_WIDHI = 0x9A
    PC_PULSE_STEPLO = 0x9B
    PC_PULSE_STEPHI = 0x9C
    PC_PULSE_MAXLO = 0x9D
    PC_PULSE_MAXHI = 0x9E
    PC_PULSE_DLYLO = 0xA1
    PC_PULSE_DLYHI = 0xA2
