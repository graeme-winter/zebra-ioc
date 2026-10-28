#!/usr/bin/env python3
"""Example 9: Zebra inline between the MD3 and the Eiger.

Swallows all but the first pulse of each train on the way to the detector,
timestamps every pulse the MD3 produces, and counts them - all bounded by an
explicit setup and teardown, so the three records cover the same pulses.

    IN1_TTL --AND SOFT_IN1--> PULSE1 (dead) -> PULSE2 (short) -> OUT1/OUT2
                           |
                           +-> DIV1 (counter)
                           +-> PC pulse input (timestamp + counter capture)

See docs/md3-eiger-inline.md for the wiring and the reasoning.

    zebra-ioc --port /dev/ttyUSB0 --prefix BENCH:ZEBRA: --capture-points 250000

    python examples/09_md3_eiger.py BENCH:ZEBRA: setup --train-ms 500
    python examples/09_md3_eiger.py BENCH:ZEBRA: start
    ... the run happens ...
    python examples/09_md3_eiger.py BENCH:ZEBRA: status
    python examples/09_md3_eiger.py BENCH:ZEBRA: stop
    python examples/09_md3_eiger.py BENCH:ZEBRA: results

`setup` writes the configuration, resets the counters and arms. `start`
raises the run gate. `stop` drops the gate and then disarms, in that order -
the other way round would leave pulses reaching the detector while no longer
being recorded. `results` reads the totals and the arrays back.
"""

import argparse
import asyncio
import sys

from aioca import caget, caput

from zebra_ioc.pulse_train import md3_eiger_registers

SOFT_IN = "SOFT_IN"
"""Register holding the four soft input bits."""


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Zebra inline between the MD3 and the Eiger",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("prefix", help="PV prefix, separator included")
    parser.add_argument(
        "command",
        choices=["setup", "start", "status", "stop", "results"],
        help="What to do",
    )
    parser.add_argument(
        "--input", default="IN1_TTL", help="Bus signal carrying MD3 pulses"
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
        "--width-us", type=float, default=10.0, help="Detector pulse width"
    )
    parser.add_argument(
        "--out", default="OUT1_TTL", help="Output PV driving the detector"
    )
    parser.add_argument(
        "--monitor", default="OUT2_TTL", help="Second output, for a scope"
    )
    parser.add_argument(
        "--tspre",
        type=int,
        default=5,
        choices=[5, 5000, 50000],
        help="Timestamp prescaler: 5 is 100ns and wraps in 7.2 minutes",
    )
    parser.add_argument(
        "--max-points",
        type=int,
        default=20,
        help="How many array values 'results' prints",
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


async def setup(args) -> int:
    """Write the configuration, zero the counters and arm."""
    prefix = args.prefix

    outputs = [args.out] + ([args.monitor] if args.monitor else [])

    try:
        settings, achieved = md3_eiger_registers(
            source=args.input,
            train_us=args.train_ms * 1000.0,
            width_us=args.width_us,
            out=outputs,
            tspre=args.tspre,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    # Make sure the gate is shut before anything is wired up, so no pulses
    # reach the detector while the configuration is half written
    await caput(f"{prefix}{SOFT_IN}", 0, wait=True, timeout=args.timeout)

    for name, value in settings.items():
        await caput(f"{prefix}{name}", value, wait=True, timeout=args.timeout)

    # SYS_RESET zeroes the DIV counters, and disarms, so it has to come
    # before the arm rather than after
    await caput(f"{prefix}SYS_RESET", 1, wait=True, timeout=args.timeout)
    await asyncio.sleep(0.2)
    await caput(f"{prefix}PC_ARM", 1, wait=True, timeout=args.timeout)

    print(f"{achieved['chain']}\n")
    print(f"  dead time    : {achieved['dead_time_us'] / 1000:,.3f} ms")
    print(f"  pulse out    : {achieved['width_us']:.1f} us")
    print(
        f"  timestamps   : {achieved['timestamp_tick_us']:g} us tick, "
        f"wraps after {achieved['timestamp_wrap_s'] / 60:,.1f} min"
    )
    print(f"  counter      : {prefix}{achieved['counter_pv']}")

    capacity = await caget(f"{prefix}PC_CAPTURE_MAX", timeout=args.timeout)
    print(f"  buffer       : {int(capacity):,} points")
    if int(capacity) < 250000:
        print(
            "\n  note: the hardware holds 250,000 points with these two "
            "capture\n        fields. Restart the IOC with "
            "--capture-points 250000 to use it all."
        )

    print("\nArmed, gate shut. 'start' to open it.")
    return 0


async def start(args) -> int:
    """Open the run gate."""
    await caput(f"{args.prefix}{SOFT_IN}", 1, wait=True, timeout=args.timeout)
    print("Run gate open - pulses now reach the detector and are recorded")
    return 0


async def status(args) -> int:
    """Report the live counters."""
    prefix = args.prefix
    count = await caget(f"{prefix}PC_DIV1_LAST", timeout=args.timeout)
    points = await caget(f"{prefix}PC_NUM_DOWN", timeout=args.timeout)
    capturing = await caget(f"{prefix}PC_CAPTURING", timeout=args.timeout)
    overflow = await caget(f"{prefix}PC_OVERFLOW", timeout=args.timeout)
    gate = await caget(f"{prefix}{SOFT_IN}_RBV", timeout=args.timeout)

    print(f"  run gate   : {'open' if int(gate) & 1 else 'shut'}")
    print(f"  capturing  : {'yes' if capturing else 'no'}")
    print(f"  pulses in  : {int(count):,}")
    print(f"  points held: {int(points):,}")
    if overflow:
        print("  OVERFLOW   : capture buffer full, timestamps incomplete")
        print("               (the pulse count is still correct)")
    return 0


async def stop(args) -> int:
    """Close the run gate, then end the capture.

    Order matters. Disarming first would leave pulses still reaching the
    detector while no longer being recorded.
    """
    prefix = args.prefix

    await caput(f"{prefix}{SOFT_IN}", 0, wait=True, timeout=args.timeout)
    await asyncio.sleep(0.1)
    await caput(f"{prefix}PC_DISARM", 1, wait=True, timeout=args.timeout)
    await asyncio.sleep(0.3)

    count = await caget(f"{prefix}PC_DIV1_LAST", timeout=args.timeout)
    points = await caget(f"{prefix}PC_NUM_DOWN", timeout=args.timeout)
    print(f"Stopped. {int(count):,} pulses, {int(points):,} timestamps held.")
    return 0


async def results(args) -> int:
    """Read the totals and a slice of the arrays."""
    prefix = args.prefix

    count = await caget(f"{prefix}PC_DIV1_LAST", timeout=args.timeout)
    points = int(await caget(f"{prefix}PC_NUM_DOWN", timeout=args.timeout))
    overflow = await caget(f"{prefix}PC_OVERFLOW", timeout=args.timeout)

    print(f"  pulses counted : {int(count):,}")
    print(f"  timestamps     : {points:,}")
    if overflow:
        print("  OVERFLOW: the capture buffer filled and points were dropped")
        print("            the pulse count above is still correct")

    if not points:
        print("\nNo points captured.")
        return 0

    times = await caget(f"{prefix}PC_TIME", count=points, timeout=args.timeout)
    counters = await caget(
        f"{prefix}PC_DIV1", count=points, timeout=args.timeout
    )

    tick_us = {5: 0.1, 5000: 100.0, 50000: 1000.0}[args.tspre]
    show = min(args.max_points, points)
    print(f"\n  first {show} arrivals (tick = {tick_us:g} us):\n")
    print(f"    {'ts (ticks)':>12} {'t (ms)':>12} {'counter':>10}")
    for i in range(show):
        print(
            f"    {int(times[i]):>12} "
            f"{times[i] * tick_us / 1000:>12.3f} "
            f"{int(counters[i]):>10}"
        )

    if points > 1:
        intervals = [
            (times[i + 1] - times[i]) * tick_us / 1000 for i in range(points - 1)
        ]
        shortest, longest = min(intervals), max(intervals)
        mean = sum(intervals) / len(intervals)
        print(
            f"\n  intervals: mean {mean:.3f} ms, "
            f"min {shortest:.3f} ms, max {longest:.3f} ms"
        )

    return 0


async def main(args: argparse.Namespace) -> int:
    if not await check_ioc(args.prefix, args.timeout):
        return 1

    return await {
        "setup": setup,
        "start": start,
        "status": status,
        "stop": stop,
        "results": results,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))
