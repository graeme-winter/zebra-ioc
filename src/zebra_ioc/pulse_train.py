"""Work out the registers for a free running pulse train.

Builds an arbitrary frequency, arbitrary width pulse train from the Zebra's
own 1 MHz clock:

    CLOCK_1MHZ --> DIVn (divide by N) --> PULSEn (fixed width) --> output

Two blocks are needed rather than one. The divider sets the repetition rate:
its counter runs 0 to N-1 and emits on OUTD once every N input edges. But the
pulses a divider emits keep the width of the clock that fed them, so they
would all be 500ns however slow the rate; the pulse block reshapes each one.

This is pure arithmetic over register values with no IO, so the same result
can be written over serial or over Channel Access.
"""

CLOCK_HZ = 1_000_000
"""The internal clock this divides down (SysBus.CLOCK_1MHZ)."""

#: PULSE prescalers: (register value, label, tick in microseconds). The width
#: register counts in units of a ten thousandth of the selected time unit, so
#: the ms prescaler ticks at 0.1us and tops out at 6.5535ms.
PRESCALERS = (
    (5, "ms", 0.1),
    (5000, "s", 100.0),
    (50000, "10s", 1000.0),
)

MAX_TICKS = 65535
"""PULSE_DLY and PULSE_WID are 16 bit."""


def divider(freq_hz: float) -> tuple[int, float]:
    """Work out the DIV divisor, and the rate it actually gives.

    Args:
        freq_hz: Requested repetition rate

    Returns:
        (divisor, actual frequency in Hz). The two differ whenever the rate
        does not divide the clock exactly.

    Raises:
        ValueError: If the rate is not reachable from the clock
    """
    if not 0 < freq_hz <= CLOCK_HZ:
        raise ValueError(f"Frequency must be between 0 and {CLOCK_HZ / 1e6:g}MHz")

    div = round(CLOCK_HZ / freq_hz)
    if div < 1:
        raise ValueError(f"{freq_hz:g}Hz is faster than the clock")

    return div, CLOCK_HZ / div


def pulse_width(
    freq_hz: float,
    duty: float | None = None,
    width_us: float | None = None,
) -> tuple[int, str, int, float]:
    """Work out the PULSE prescaler and width register values.

    Picks the finest prescaler the requested width fits in. A 50% duty cycle
    below about 76Hz overflows the width register at the millisecond
    prescaler, which would otherwise be a cliff in the middle of the useful
    range.

    Args:
        freq_hz: Repetition rate
        duty: Duty cycle in percent. Defaults to 50 if no width is given
        width_us: Explicit pulse width in microseconds, overriding duty

    Returns:
        (prescaler register value, prescaler label, width register value,
        actual width in microseconds)

    Raises:
        ValueError: If the width is unachievable at this frequency
    """
    period_us = 1e6 / freq_hz

    if width_us is None:
        width_us = period_us * (50.0 if duty is None else duty) / 100.0

    if width_us <= 0:
        raise ValueError("Pulse width must be positive")

    # A PULSE block flags an error if a new edge arrives while it is still
    # producing, so the width has to fit inside the period
    if width_us >= period_us:
        raise ValueError(
            f"Width {width_us:.3f}us does not fit in the "
            f"{period_us:.3f}us period at {freq_hz:g}Hz"
        )

    for prescaler, label, tick_us in PRESCALERS:
        ticks = round(width_us / tick_us)
        if 1 <= ticks <= MAX_TICKS:
            return prescaler, label, ticks, ticks * tick_us

    finest = PRESCALERS[0][2]
    if width_us < finest:
        raise ValueError(f"Width {width_us:.3f}us is below the {finest}us resolution")

    coarsest_max = MAX_TICKS * PRESCALERS[-1][2] / 1e6
    raise ValueError(f"Width {width_us:.3f}us exceeds the {coarsest_max:g}s maximum")


def pulse_train_registers(
    freq_hz: float,
    duty: float | None = None,
    width_us: float | None = None,
    out: str = "OUT1_TTL",
    block: int = 1,
) -> tuple[dict[str, int], dict[str, float | str | int]]:
    """Build the register settings for a free running pulse train.

    Args:
        freq_hz: Requested repetition rate
        duty: Duty cycle in percent. Defaults to 50 if no width is given
        width_us: Explicit pulse width in microseconds, overriding duty
        out: Output register to drive, e.g. 'OUT1_TTL'
        block: Which DIV and PULSE block pair to use, 1-4

    Returns:
        (settings, achieved) where settings maps register name to value and
        achieved describes what the hardware will actually produce

    Raises:
        ValueError: If the request cannot be met, or block is out of range
    """
    if not 1 <= block <= 4:
        raise ValueError(f"Block must be 1-4, got {block}")

    # Imported here so the module stays usable without the register tables
    from .registers import SysBus

    div, actual_freq = divider(freq_hz)
    prescaler, label, ticks, actual_width = pulse_width(actual_freq, duty, width_us)

    div_outd = SysBus[f"DIV{block}_OUTD"]
    pulse_out = SysBus[f"PULSE{block}"]

    settings = {
        f"DIV{block}_INP": int(SysBus.CLOCK_1MHZ),
        f"DIV{block}_DIV": div,
        f"PULSE{block}_INP": int(div_outd),
        f"PULSE{block}_PRE": prescaler,
        f"PULSE{block}_DLY": 0,
        f"PULSE{block}_WID": ticks,
        out: int(pulse_out),
    }

    achieved = {
        "frequency_hz": actual_freq,
        "width_us": actual_width,
        "duty_percent": 100.0 * actual_width / (1e6 / actual_freq),
        "divisor": div,
        "prescaler": label,
        "chain": f"CLOCK_1MHZ -> DIV{block} (/{div}) -> PULSE{block} -> {out}",
    }

    return settings, achieved
