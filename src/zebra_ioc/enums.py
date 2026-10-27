"""
Enumerations for some register values.
"""

import enum


class Prescaler(enum.IntEnum):
    """Time prescaler register values.

    These are the raw values written to the prescaler registers (PC_TSPRE,
    PULSE1-4_PRE), not the resulting clock divisor. They match ZRVL/ONVL/TWVL
    in the legacy zebraRegisterWritePrescaler.template, and all three fit in
    the 16-bit register.
    """

    TEN_SECONDS = 50000
    SECONDS = 5000
    MILLISECONDS = 5


class SourceSelection(enum.IntEnum):
    """Source selection for gate/pulse."""

    POSITION = 0
    TIME = 1
    EXTERNAL = 2


class ArmSelection(enum.IntEnum):
    """Arm source selection."""

    SOFTWARE = 0
    EXTERNAL = 1


class Direction(enum.IntEnum):
    """Position compare direction."""

    POSITIVE = 0
    NEGATIVE = 1


class EncoderSelection(enum.IntEnum):
    """Encoder selection for position compare."""

    ENC1 = 0
    ENC2 = 1
    ENC3 = 2
    ENC4 = 3
    ENC1234_SUM = 4
