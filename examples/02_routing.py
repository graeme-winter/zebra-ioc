#!/usr/bin/env python3
"""Example 2: route a signal through the logic to a physical output.

The Zebra is a patch panel. Every input, block output and position compare
output has a number on the 64-way system bus, and routing means writing that
number into a block's input register.

This wires SOFT_IN1 (a software controlled bit, bus signal 60) through AND1
(bus signal 32) to the TTL output 1 connector, then toggles it.

    python examples/02_routing.py [port]
"""

import asyncio
import sys

from zebra_ioc import SysBus, ZebraDevice

SOFT_IN1_MASK = 0b0001  # bit 0 of the SOFT_IN register


async def main(port: str) -> None:
    async with ZebraDevice(port, poll_period=0.1) as zebra:
        print("Routing SOFT_IN1 -> AND1 -> OUT1_TTL\n")

        await zebra.configure(
            {
                # AND1 takes input 1 from SOFT_IN1, and ignores inputs 2-4
                "AND1_INP1": int(SysBus.SOFT_IN1),
                "AND1_ENA": 0b0001,
                "AND1_INV": 0b0000,
                # Drive the TTL output 1 connector from AND1's output
                "OUT1_TTL": int(SysBus.AND1),
            }
        )

        for state in (1, 0, 1, 0):
            await zebra.write_register("SOFT_IN", SOFT_IN1_MASK if state else 0)

            # The system bus is polled, so wait for the next sample
            await asyncio.sleep(0.25)

            print(
                f"SOFT_IN1 set to {state}: "
                f"bus SOFT_IN1={int(zebra.sys_bus_bit(SysBus.SOFT_IN1))} "
                f"AND1={int(zebra.sys_bus_bit(SysBus.AND1))}"
            )

        await zebra.write_register("SOFT_IN", 0)
        print("\nOn a real box, scope OUT1 TTL while this runs.")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "sim://zebra01"))
