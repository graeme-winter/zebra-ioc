#!/usr/bin/env python3
"""Example 6: the same pulse train, over EPICS instead of serial.

Example 5 opens the serial port itself. This one talks to a running IOC over
Channel Access, which is how you would really do it: the IOC owns the serial
port, and anything that wants the Zebra goes through PVs.

Start the IOC first:

    zebra-ioc --port /dev/ttyUSB0 --prefix BENCH:ZEBRA:

then

    python examples/06_square_wave_epics.py BENCH:ZEBRA:
    python examples/06_square_wave_epics.py BENCH:ZEBRA: --freq 100 --duty 10
    python examples/06_square_wave_epics.py BENCH:ZEBRA: --out OUT3_TTL
    python examples/06_square_wave_epics.py BENCH:ZEBRA: --monitor OUT2_TTL
    python examples/06_square_wave_epics.py BENCH:ZEBRA: --stop

The register values are worked out by the same zebra_ioc.pulse_train code
example 5 uses, so the only difference between the two is how they reach the
hardware: write_register there, caput here. Nothing else changes, because the
PV names are the register names.
"""

import argparse
import asyncio
import sys

from aioca import caget, caput

from zebra_ioc import SysBus, pulse_train_registers


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Put a TTL pulse train on a Zebra output, over EPICS",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "prefix",
        nargs="?",
        default="TEST:ZEBRA:",
        help="PV prefix the IOC was started with, separator included",
    )
    parser.add_argument("--freq", type=float, default=1000.0, help="Rate in Hz")
    width = parser.add_mutually_exclusive_group()
    width.add_argument("--duty", type=float, help="Duty cycle in percent")
    width.add_argument("--width-us", type=float, help="Pulse width in microseconds")
    parser.add_argument("--out", default="OUT1_TTL", help="Output PV to drive")
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
    parser.add_argument(
        "--timeout", type=float, default=5.0, help="CA timeout in seconds"
    )
    return parser.parse_args(argv)


async def check_ioc(prefix: str, timeout: float) -> bool:
    """Confirm the IOC is up and actually talking to a Zebra.

    Without this, a disconnected IOC accepts every caput and reports success
    while nothing reaches the hardware.
    """
    try:
        connected = await caget(f"{prefix}CONNECTED", timeout=timeout)
    except Exception:
        print(
            f"error: no response from {prefix}CONNECTED - is the IOC running, "
            "and is the prefix right?",
            file=sys.stderr,
        )
        return False

    if not connected:
        status = await caget(f"{prefix}STATUS", timeout=timeout)
        print(
            f"error: the IOC is up but not connected to a Zebra ({status})",
            file=sys.stderr,
        )
        return False

    return True


async def main(args: argparse.Namespace) -> int:
    prefix = args.prefix

    if not await check_ioc(prefix, args.timeout):
        return 1

    outputs = [args.out] + ([args.monitor] if args.monitor else [])

    if args.stop:
        for output in outputs:
            await caput(
                f"{prefix}{output}",
                int(SysBus.DISCONNECT),
                wait=True,
                timeout=args.timeout,
            )
        print(f"{', '.join(prefix + o for o in outputs)} disconnected")
        return 0

    try:
        settings, achieved = pulse_train_registers(
            args.freq, args.duty, args.width_us, outputs, args.block
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    # One caput per register. The PV names are the register names, so this is
    # the same dict example 5 hands to ZebraDevice.configure
    for name, value in settings.items():
        await caput(f"{prefix}{name}", value, wait=True, timeout=args.timeout)

    print(f"{achieved['chain']}\n")
    print(
        f"  frequency : {achieved['frequency_hz']:,.3f} Hz "
        f"(asked for {args.freq:g})"
    )
    print(
        f"  width     : {achieved['width_us']:.1f} us "
        f"(prescaler: {achieved['prescaler']})"
    )
    print(f"  duty      : {achieved['duty_percent']:.1f} %")

    # Read back from the hardware rather than trusting the demands we sent.
    # The _RBV PVs are filled from the Zebra, so a mismatch here means the
    # write did not take, which a caput alone would never reveal.
    print("\nReadbacks from the hardware:")
    mismatches = 0
    for name, value in settings.items():
        readback = await caget(f"{prefix}{name}_RBV", timeout=args.timeout)
        flag = "" if int(readback) == value else "   <-- MISMATCH"
        if flag:
            mismatches += 1
        print(f"  {name:14s} = {int(readback):<10d}{flag}")

    print()
    for output in outputs:
        signal = await caget(f"{prefix}{output}_STR", timeout=args.timeout)
        print(f"  {output} is driven by {signal}")

    if mismatches:
        print(f"\n{mismatches} register(s) did not take", file=sys.stderr)
        return 1

    scope = " and ".join(o.split("_")[0] for o in outputs)
    print(f"\nScope {scope} now. Use --stop to turn it off.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))
