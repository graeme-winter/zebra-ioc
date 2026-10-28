#!/usr/bin/env python3
"""Example 8: pass the first pulse of each train, as a short pulse.

Given trains of N pulses - say 100 pulses over 0.5s, repeating - emit one
short pulse per train, timed with the first pulse of the train, and swallow
the other N-1.

    IN1_TTL --> PULSE1 (dead time) --> PULSE2 (short) --> OUT1_TTL

A PULSE block ignores any edge arriving while it is still producing, so
PULSE1 set to span the train is a self resetting dead time: the first pulse
triggers it, the rest land inside it and are dropped. Its output is as wide
as the train, so PULSE2 reshapes that into the short pulse you actually want.

A DIV block is the obvious answer and the wrong one. It emits on the Nth
pulse of each N, not the first, its counter does not reset between trains, so
one train with N+1 pulses permanently shifts the phase of everything after
it, and it needs to know N in advance. This arrangement needs none of that.

    zebra-ioc --port /dev/ttyUSB0 --prefix BENCH:ZEBRA:

    python examples/08_one_per_train.py BENCH:ZEBRA: --train-ms 500
    python examples/08_one_per_train.py BENCH:ZEBRA: --train-ms 500 --width-us 2
    python examples/08_one_per_train.py BENCH:ZEBRA: --monitor OUT2_TTL
    python examples/08_one_per_train.py BENCH:ZEBRA: --stop

The dead time has to be longer than a train and shorter than the gap between
the start of consecutive trains. If those two constraints cannot both be met,
or a train is longer than 6.5535s, this arrangement will not do it and you
need a GATE block reset by an external end of train signal instead.

Note that every swallowed edge sets a pulse generator error bit in
SYS_STATERR. That is documented retrigger behaviour rather than a fault, but
it means SYS_STATERR stays lit and only clears on SYS_RESET, so it is no
longer useful as a health indicator for those blocks.
"""

import argparse
import asyncio
import sys

from aioca import caget, caput

from zebra_ioc import SysBus
from zebra_ioc.pulse_train import one_pulse_per_train_registers


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Emit one short pulse per train of input pulses",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "prefix", help="PV prefix the IOC was started with, separator included"
    )
    parser.add_argument(
        "--input",
        default="IN1_TTL",
        help="System bus signal carrying the trains",
    )
    parser.add_argument(
        "--train-ms",
        type=float,
        default=500.0,
        help=(
            "Dead time in milliseconds. Longer than a train, shorter than "
            "the gap between the start of consecutive trains"
        ),
    )
    parser.add_argument(
        "--width-us", type=float, default=10.0, help="Output pulse width"
    )
    parser.add_argument("--out", default="OUT1_TTL", help="Output PV to drive")
    parser.add_argument(
        "--monitor",
        help="Second output carrying the same signal, for scoping",
    )
    parser.add_argument(
        "--gate-block",
        type=int,
        default=1,
        help="PULSE block used as the dead time, 1-4",
    )
    parser.add_argument(
        "--shape-block",
        type=int,
        default=2,
        help="PULSE block used to shape the output, 1-4",
    )
    parser.add_argument(
        "--stop", action="store_true", help="Disconnect the outputs instead"
    )
    parser.add_argument(
        "--timeout", type=float, default=5.0, help="CA timeout in seconds"
    )
    return parser.parse_args(argv)


async def check_ioc(prefix: str, timeout: float) -> bool:
    """Confirm the IOC is up and talking to a Zebra."""
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
        print(f"error: IOC is up but has no Zebra ({status})", file=sys.stderr)
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
        print(f"{', '.join(outputs)} disconnected")
        return 0

    try:
        settings, achieved = one_pulse_per_train_registers(
            source=args.input,
            train_us=args.train_ms * 1000.0,
            width_us=args.width_us,
            out=outputs,
            gate_block=args.gate_block,
            shape_block=args.shape_block,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    for name, value in settings.items():
        await caput(f"{prefix}{name}", value, wait=True, timeout=args.timeout)

    print(f"{achieved['chain']}\n")
    print(
        f"  dead time : {achieved['dead_time_us'] / 1000:,.3f} ms "
        f"(prescaler: {achieved['dead_prescaler']})"
    )
    print(
        f"  out width : {achieved['width_us']:.1f} us "
        f"(prescaler: {achieved['width_prescaler']})"
    )

    # The error bits latch on every swallowed edge, so clear them here and
    # the next reading tells you whether anything unexpected happened
    errors = await caget(f"{prefix}SYS_STATERR", timeout=args.timeout)
    print(f"\n  SYS_STATERR currently {int(errors):#06x}")
    print("  (bits 3-0 latch once pulses start being swallowed - expected)")

    scope = " and ".join(o.split("_")[0] for o in outputs)
    print(f"\nScope {scope} now. Use --stop to turn it off.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))
