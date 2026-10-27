#!/usr/bin/env python3
"""Example 5: put a TTL pulse train on an output, over serial.

Builds an arbitrary frequency, arbitrary width pulse train from the Zebra's
own 1 MHz clock and sends it to a TTL output, which is the quickest way to
check a cable, a scope setup, or a detector's trigger input without needing a
signal generator.

    CLOCK_1MHZ --> DIV1 (divide by N) --> PULSE1 (fixed width) --> OUT1_TTL

The registers are worked out by zebra_ioc.pulse_train, which does arithmetic
only. Example 6 writes the same registers over Channel Access.

    python examples/05_square_wave.py                       # 1 kHz square
    python examples/05_square_wave.py --freq 100 --duty 10  # 100 Hz, 10%
    python examples/05_square_wave.py --freq 5000 --width-us 2
    python examples/05_square_wave.py --out OUT3_TTL
    python examples/05_square_wave.py --monitor OUT2_TTL  # same signal, 2 BNCs
    python examples/05_square_wave.py --stop

The configuration persists after the script exits - the Zebra holds it in
volatile memory until it loses power or you change it. Use --stop to
disconnect the output again.
"""

import argparse
import asyncio
import sys

from zebra_ioc import SysBus, ZebraDevice, pulse_train_registers


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Put a TTL pulse train on a Zebra output, over serial",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "port",
        nargs="?",
        default="sim://zebra01",
        help="Serial device, tcp://host:port, or sim://name",
    )
    parser.add_argument("--freq", type=float, default=1000.0, help="Rate in Hz")
    width = parser.add_mutually_exclusive_group()
    width.add_argument("--duty", type=float, help="Duty cycle in percent")
    width.add_argument("--width-us", type=float, help="Pulse width in microseconds")
    parser.add_argument(
        "--out", default="OUT1_TTL", help="Output register to drive"
    )
    parser.add_argument(
        "--monitor",
        help=(
            "Second output carrying the same signal, e.g. OUT2_TTL, so it "
            "can be scoped without loading the first. Set and cleared "
            "together with --out"
        ),
    )
    parser.add_argument(
        "--block", type=int, default=1, help="Which DIV/PULSE pair to use, 1-4"
    )
    parser.add_argument(
        "--stop", action="store_true", help="Disconnect the output instead"
    )
    return parser.parse_args(argv)


def report(achieved: dict, requested: float) -> None:
    """Print what the hardware will actually produce."""
    print(f"{achieved['chain']}\n")
    print(
        f"  frequency : {achieved['frequency_hz']:,.3f} Hz "
        f"(asked for {requested:g})"
    )
    print(
        f"  width     : {achieved['width_us']:.1f} us "
        f"(prescaler: {achieved['prescaler']})"
    )
    print(f"  duty      : {achieved['duty_percent']:.1f} %")


async def main(args: argparse.Namespace) -> int:
    async with ZebraDevice(args.port) as zebra:
        outputs = [args.out] + ([args.monitor] if args.monitor else [])

        if args.stop:
            for output in outputs:
                await zebra.write_register(output, int(SysBus.DISCONNECT))
            print(f"{', '.join(outputs)} disconnected")
            return 0

        try:
            settings, achieved = pulse_train_registers(
                args.freq, args.duty, args.width_us, outputs, args.block
            )
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

        await zebra.configure(settings)

        report(achieved, args.freq)
        scope = " and ".join(o.split("_")[0] for o in outputs)
        print(f"\nScope {scope} now. Use --stop to turn it off.")
        print("The output is LVTTL, about 3.3V - use a 10:1 probe, and do not")
        print("put a 50 ohm feedthrough on it.")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))
