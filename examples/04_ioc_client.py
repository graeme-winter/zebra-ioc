#!/usr/bin/env python3
"""Example 4: the same capture, driven entirely over Channel Access.

Start the IOC in one terminal:

    zebra-ioc --port sim://zebra01 --prefix TEST:ZEBRA:

Then run this in another:

    python examples/04_ioc_client.py [prefix]

Everything here is caget and caput against legacy PV names, so the same
script works against the Diamond areaDetector driver, and existing Zebra
client code works against this IOC.
"""

import asyncio
import sys

from aioca import caget, caput

CAPTURE_ENC1 = 0b0000000001

CONFIG = {
    "PC_ENC": 0,
    "PC_DIR": 0,
    "PC_TSPRE": 5000,
    "PC_ARM_SEL": 0,
    "PC_GATE_SEL": 0,
    "PC_GATE_START": 0,
    "PC_GATE_WID": 90,
    "PC_GATE_NGATE": 1,
    "PC_PULSE_SEL": 0,
    "PC_PULSE_START": 0,
    "PC_PULSE_STEP": 1,
    "PC_PULSE_WID": 1,
    "PC_BIT_CAP": CAPTURE_ENC1,
}


async def main(prefix: str) -> None:
    connected = await caget(f"{prefix}CONNECTED", timeout=5)
    print(f"IOC says: {await caget(f'{prefix}STATUS', timeout=5)}")
    if not connected:
        print("The IOC is not connected to a Zebra - stopping here")
        return

    print(f"Firmware: {await caget(f'{prefix}SYS_VER'):#06x}\n")

    print("Configuring over CA")
    for name, value in CONFIG.items():
        await caput(f"{prefix}{name}", value, wait=True, timeout=5)

    # Readbacks come from the hardware, not from the demand we just sent
    gate_wid = await caget(f"{prefix}PC_GATE_WID_RBV")
    print(f"  PC_GATE_WID_RBV = {gate_wid}")

    # Mux registers also publish the system bus signal name
    await caput(f"{prefix}OUT1_TTL", 31, wait=True, timeout=5)  # PC_PULSE
    print(f"  OUT1_TTL_STR    = {await caget(f'{prefix}OUT1_TTL_STR')}")

    print("\nArming")
    await caput(f"{prefix}PC_ARM", 1, wait=True, timeout=5)
    await asyncio.sleep(2.0)
    await caput(f"{prefix}PC_DISARM", 1, wait=True, timeout=5)
    await asyncio.sleep(0.5)

    # Read the arrays after the capture ends, not during - they are
    # republished at 5Hz while running
    num_down = await caget(f"{prefix}PC_NUM_DOWN")
    overflow = await caget(f"{prefix}PC_OVERFLOW")
    print(f"\nPC_NUM_DOWN = {num_down}, PC_OVERFLOW = {bool(overflow)}")

    enc1 = await caget(f"{prefix}PC_ENC1", count=int(num_down))
    time = await caget(f"{prefix}PC_TIME", count=int(num_down))
    print(f"PC_TIME[:5] = {time[:5].tolist()}")
    print(f"PC_ENC1[:5] = {enc1[:5].tolist()}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "TEST:ZEBRA:"))
