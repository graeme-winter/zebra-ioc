#!/usr/bin/env python3
"""Example 1: talk to a Zebra with no EPICS at all.

The device layer has no control system in it, so you can drive a box from a
plain script. Useful for commissioning, for debugging, and for convincing
yourself the box is alive before blaming the IOC.

    python examples/01_protocol.py                        # simulator
    python examples/01_protocol.py /dev/ttyUSB0           # real box
    python examples/01_protocol.py tcp://172.23.241.3:7012
"""

import asyncio
import sys

from zebra_ioc import ZebraDevice


async def main(port: str) -> None:
    async with ZebraDevice(port) as zebra:
        version = await zebra.read_register("SYS_VER")
        errors = await zebra.read_register("SYS_STATERR")
        print(f"Firmware version : {version:#06x}")
        print(f"System errors    : {errors:#06x}")

        # Registers are addressed by the names in the manual
        print("\nWriting PC_GATE_START = 1000 (a 32 bit register pair)")
        await zebra.write_register("PC_GATE_START", 1000)
        print(f"  read back: {await zebra.read_register('PC_GATE_START')}")

        print("\nWriting PC_GATE_WID = 90")
        await zebra.write_register("PC_GATE_WID", 90)
        print(f"  read back: {await zebra.read_register('PC_GATE_WID')}")

        # Several at once
        print("\nConfiguring the timestamp prescaler and capture mask")
        await zebra.configure({"PC_TSPRE": 5000, "PC_BIT_CAP": 0b0000000001})
        print(f"  PC_TSPRE   = {await zebra.read_register('PC_TSPRE')}")
        print(f"  PC_BIT_CAP = {await zebra.read_register('PC_BIT_CAP'):#06b}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "sim://zebra01"))
