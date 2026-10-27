#!/usr/bin/env python3
"""Example 5: put a TTL pulse train on an output.

Builds an arbitrary frequency, arbitrary width pulse train out of the
Zebra's own 1 MHz clock and sends it to a TTL output, which is the quickest
way to check a cable, a scope setup, or a detector's trigger input without
needing a signal generator.

The chain is:

    CLOCK_1MHZ --> DIV1 (divide by N) --> PULSE1 (fixed width) --> OUT1_TTL

DIV1 sets the repetition rate: its counter runs 0 to N-1 and emits on OUTD
once every N input edges, so the rate is 1 MHz / N. The pulses that come out
of a DIV block keep the width of the clock that fed them, so PULSE1 reshapes
each one to the width you asked for. Delay is zero.

    python examples/05_square_wave.py                       # 1 kHz square
    python examples/05_square_wave.py --freq 100 --duty 10  # 100 Hz, 10%
    python examples/05_square_wave.py --freq 5000 --width-us 2
    python examples/05_square_wave.py --out OUT3_TTL
    python examples/05_square_wave.py --stop

The configuration persists after the script exits - the Zebra holds it in
volatile memory until it loses power or you change it. Use --stop to
disconnect the output again.
"""

import argparse
import asyncio
import sys

from zebra_ioc import SysBus, ZebraDevice

CLOCK_HZ = 1_000_000
"""The internal clock this example divides down (SysBus.CLOCK_1MHZ)."""

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


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Put a TTL pulse train on a Zebra output",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "port",
        nargs="?",
        default="sim://zebra01",
        help="Serial device, tcp://host:port, or sim://name",
    )
    parser.add_argument(
        "--freq", type=float, default=1000.0, help="Repetition rate in Hz"
    )
    width = parser.add_mutually_exclusive_group()
    width.add_argument(
        "--duty", type=float, help="Duty cycle in percent (default: 50)"
    )
    width.add_argument(
        "--width-us", type=float, help="Pulse width in microseconds"
    )
    parser.add_argument(
        "--out",
        default="OUT1_TTL",
        help="Output register to drive, e.g. OUT1_TTL, OUT3_NIM",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Disconnect the output instead of configuring it",
    )
    return parser.parse_args(argv)


def pulse_width(freq_hz: float, duty: float | None, width_us: float | None):
    """Work out the PULSE prescaler and width register values.

    Picks the finest prescaler the requested width fits in, so a long pulse
    at a low rate still works rather than running off the end of the 16 bit
    width register.

    Args:
        freq_hz: Repetition rate
        duty: Duty cycle in percent, or None
        width_us: Explicit pulse width in microseconds, or None

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
    coarsest_max = MAX_TICKS * PRESCALERS[-1][2] / 1e6
    if width_us < finest:
        raise ValueError(
            f"Width {width_us:.3f}us is below the {finest}us resolution"
        )
    raise ValueError(
        f"Width {width_us:.3f}us exceeds the {coarsest_max:g}s maximum"
    )


def divider(freq_hz: float):
    """Work out the DIV1 divisor, and the rate it actually gives.

    Args:
        freq_hz: Requested repetition rate

    Returns:
        (divisor, actual frequency in Hz)

    Raises:
        ValueError: If the rate is not reachable from the clock
    """
    if not 0 < freq_hz <= CLOCK_HZ:
        raise ValueError(
            f"Frequency must be between 0 and {CLOCK_HZ / 1e6:g}MHz"
        )

    div = round(CLOCK_HZ / freq_hz)
    if div < 1:
        raise ValueError(f"{freq_hz:g}Hz is faster than the clock")

    return div, CLOCK_HZ / div


async def main(args: argparse.Namespace) -> int:
    async with ZebraDevice(args.port) as zebra:
        if args.stop:
            await zebra.write_register(args.out, int(SysBus.DISCONNECT))
            print(f"{args.out} disconnected")
            return 0

        try:
            div, actual_freq = divider(args.freq)
            prescaler, label, ticks, actual_width = pulse_width(
                actual_freq, args.duty, args.width_us
            )
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

        await zebra.configure(
            {
                # 1 MHz clock into the divider
                "DIV1_INP": int(SysBus.CLOCK_1MHZ),
                "DIV1_DIV": div,
                # Divided pulses reshaped to the width we want, no delay
                "PULSE1_INP": int(SysBus.DIV1_OUTD),
                "PULSE1_PRE": prescaler,
                "PULSE1_DLY": 0,
                "PULSE1_WID": ticks,
                # Out of the front panel
                args.out: int(SysBus.PULSE1),
            }
        )

        duty = 100.0 * actual_width / (1e6 / actual_freq)
        print(f"CLOCK_1MHZ -> DIV1 (/{div}) -> PULSE1 -> {args.out}\n")
        print(f"  frequency : {actual_freq:,.3f} Hz (asked for {args.freq:g})")
        print(f"  width     : {actual_width:.1f} us (prescaler: {label})")
        print(f"  duty      : {duty:.1f} %")
        print(f"\nScope {args.out.split('_')[0]} now. Use --stop to turn it off.")
        print("Note the output is LVTTL, about 3.3V - use a 10:1 probe, and")
        print("do not put a 50 ohm feedthrough on it.")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))
