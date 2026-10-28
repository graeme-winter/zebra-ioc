#!/usr/bin/env python3
"""Example 7: count pulses, and read the total with one caget.

The Zebra has no scaler block, but a DIV block's internal counter is a free
running pulse counter if you set the divisor high enough that it never wraps.
Position compare samples that counter and the IOC publishes the most recent
value, so the running total is a single PV:

    IN1_TTL --> DIV1 (counter) --> sampled by PC --> PC_DIV1_LAST

Sized for detector trigger pulses: up to a few kHz, totals in the thousands.

Start the IOC, then:

    python examples/07_pulse_counting.py BENCH:ZEBRA: setup
    python examples/07_pulse_counting.py BENCH:ZEBRA: zero
    ... time passes, pulses arrive ...
    caget BENCH:ZEBRA:PC_DIV1_LAST

`setup` wires up the counter and arms it. `zero` resets the count to zero and
re-arms. After that the total is just a caget, from anywhere, as often as you
like. `read` and `watch` are conveniences for when you have no caget binary.

    python examples/07_pulse_counting.py BENCH:ZEBRA: read
    python examples/07_pulse_counting.py BENCH:ZEBRA: watch
    python examples/07_pulse_counting.py BENCH:ZEBRA: stop

Two things to know:

- The counter PV updates when position compare emits a sample, so at the
  default 10 Hz the total lags reality by up to 100ms. Pulses are never
  missed - the DIV counter runs in the FPGA - only the readout is sampled.
- `zero` works by resetting the Zebra's state machines, which also resets the
  gate, pulse and quad blocks. On a bench that is what you want. In a running
  system, take a baseline reading and subtract instead.
"""

import argparse
import asyncio
import sys

from aioca import caget, caput

from zebra_ioc import SysBus

NEVER_WRAP = 0xFFFFFFFF
"""DIV counter runs 0 to DIV-1, so this makes it a plain counter.

At 1 kHz that is 49 days before it wraps; at 1 MHz, about 70 minutes.
"""

CAPTURE_DIV1 = 1 << 6
"""PC_BIT_CAP bit 6 selects the DIV1 counter. Bits 0-3 are the encoders."""

TIME_TRIGGERED = 1
"""PC_GATE_SEL / PC_PULSE_SEL value selecting time rather than position."""

TSPRE = 5000
"""PC_TSPRE value. The tick is TSPRE/50MHz, so 5000 gives 100us."""

TICK_US = 100.0
"""Timestamp tick in microseconds, for the TSPRE above."""


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Count pulses with a Zebra, over EPICS",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "prefix", help="PV prefix the IOC was started with, separator included"
    )
    parser.add_argument(
        "command",
        choices=["setup", "zero", "read", "watch", "stop"],
        help="What to do",
    )
    parser.add_argument(
        "--input",
        default="IN1_TTL",
        help="System bus signal to count, e.g. IN1_TTL, PULSE1",
    )
    parser.add_argument(
        "--block", type=int, default=1, help="Which DIV block to count in, 1-4"
    )
    parser.add_argument(
        "--sample-ms",
        type=float,
        default=100.0,
        help="How often the counter is sampled, in milliseconds",
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


def counter_pv(prefix: str, block: int) -> str:
    """The PV holding the running total."""
    return f"{prefix}PC_DIV{block}_LAST"


async def setup(args) -> int:
    """Wire the input into a DIV counter and start sampling it."""
    prefix, block = args.prefix, args.block

    try:
        source = int(SysBus[args.input])
    except KeyError:
        print(f"error: {args.input} is not a system bus signal", file=sys.stderr)
        return 1

    settings = {
        # The counter itself
        f"DIV{block}_INP": source,
        f"DIV{block}_DIV": NEVER_WRAP,
        # Sample it on a timer rather than on position
        "PC_ARM_SEL": 0,
        "PC_GATE_SEL": TIME_TRIGGERED,
        "PC_PULSE_SEL": TIME_TRIGGERED,
        "PC_TSPRE": TSPRE,
        "PC_GATE_START": 0,
        "PC_GATE_NGATE": 1,
        "PC_PULSE_START": 0,
        "PC_PULSE_WID": 1,
        "PC_BIT_CAP": 1 << (5 + block),
    }

    # PC_PULSE_STEP counts timestamp ticks, not milliseconds
    settings["PC_PULSE_STEP"] = max(1, round(args.sample_ms * 1000 / TICK_US))
    # One long gate; the capture runs until disarmed
    settings["PC_GATE_WID"] = 0xFFFF

    for name, value in settings.items():
        await caput(f"{prefix}{name}", value, wait=True, timeout=args.timeout)

    await caput(f"{prefix}PC_ARM", 1, wait=True, timeout=args.timeout)

    print(f"Counting {args.input} in DIV{block}, sampled every "
          f"{args.sample_ms:g} ms\n")
    print(f"  read the total with: caget {counter_pv(prefix, block)}")
    print(f"  zero it with:        {sys.argv[0]} {prefix} zero")
    return 0


async def zero(args) -> int:
    """Reset the counter to zero and re-arm.

    SYS_RESET returns the DIV counters to zero, and also resets the gate,
    pulse and quad blocks and disarms position compare - so the capture has
    to be armed again afterwards.
    """
    prefix = args.prefix

    await caput(f"{prefix}PC_DISARM", 1, wait=True, timeout=args.timeout)
    await caput(f"{prefix}SYS_RESET", 1, wait=True, timeout=args.timeout)
    await asyncio.sleep(0.2)
    await caput(f"{prefix}PC_ARM", 1, wait=True, timeout=args.timeout)

    # Give position compare a sample or two to publish the new zero
    await asyncio.sleep(2 * args.sample_ms / 1000 + 0.2)

    count = await caget(counter_pv(prefix, args.block), timeout=args.timeout)
    print(f"Counter zeroed, now reads {int(count)}")
    return 0


async def read(args) -> int:
    """Print the running total once."""
    count = await caget(counter_pv(args.prefix, args.block), timeout=args.timeout)
    print(int(count))
    return 0


async def watch(args) -> int:
    """Print the running total until interrupted."""
    pv = counter_pv(args.prefix, args.block)
    print(f"{pv} (ctrl-c to stop)")
    previous = None
    try:
        while True:
            count = int(await caget(pv, timeout=args.timeout))
            rate = "" if previous is None else f"   (+{count - previous})"
            print(f"  {count:>8d}{rate}")
            previous = count
            await asyncio.sleep(1.0)
    except KeyboardInterrupt:
        pass
    return 0


async def stop(args) -> int:
    """Disarm the capture. The DIV counter keeps counting regardless."""
    await caput(f"{args.prefix}PC_DISARM", 1, wait=True, timeout=args.timeout)
    print("Capture disarmed - the counter PV will stop updating")
    return 0


async def main(args: argparse.Namespace) -> int:
    if not 1 <= args.block <= 4:
        print(f"error: block must be 1-4, got {args.block}", file=sys.stderr)
        return 1

    if not await check_ioc(args.prefix, args.timeout):
        return 1

    return await {
        "setup": setup,
        "zero": zero,
        "read": read,
        "watch": watch,
        "stop": stop,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))
