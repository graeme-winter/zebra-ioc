#!/usr/bin/env python3
"""Example 3: run a position compare capture and read the arrays back.

Position compare is the reason to own a Zebra: it gates and pulses on actual
encoder position, and records where the axis really was at every pulse.

This is the shape of a rotation scan, though against the simulator the
geometry is synthetic - the simulator streams points at 10 Hz rather than
honouring the gate and pulse configuration. On real hardware you would set
these registers, arm, then start the motion.

    python examples/03_capture.py [port]
"""

import asyncio
import sys

from zebra_ioc import SysBus, ZebraDevice

# PC_BIT_CAP is a bitmask: bit 0 is encoder 1, bits 4-5 the system bus,
# bits 6-9 the dividers
CAPTURE_ENC1 = 0b0000000001


async def main(port: str) -> None:
    async with ZebraDevice(port, capture_points=10000) as zebra:
        print("Configuring position compare for a 90 degree sweep\n")

        await zebra.configure(
            {
                "PC_ENC": 0,  # compare against encoder 1 (omega)
                "PC_DIR": 0,  # positive direction
                "PC_TSPRE": 5000,  # timestamps in units of 0.01 s
                "PC_ARM_SEL": 0,  # arm from software
                "PC_GATE_SEL": 0,  # gate on position
                "PC_GATE_START": 0,  # open the gate at 0 degrees
                "PC_GATE_WID": 90,  # 90 degree sweep
                "PC_GATE_NGATE": 1,  # one gate
                "PC_PULSE_SEL": 0,  # pulse on position
                "PC_PULSE_START": 0,
                "PC_PULSE_STEP": 1,  # one pulse per degree
                "PC_PULSE_WID": 1,
                "PC_BIT_CAP": CAPTURE_ENC1,
                # Send the pulse train out of the TTL output the detector is on
                "OUT1_TTL": int(SysBus.PC_PULSE),
            }
        )

        points = []

        async def note_point(point):
            points.append(point)

        zebra.on_capture_point(note_point)

        print("Arming...")
        await zebra.arm()
        await asyncio.sleep(2.0)
        print("Disarming\n")
        await zebra.disarm()
        await asyncio.sleep(0.2)

        arrays = zebra.capture.arrays()
        print(f"Captured {zebra.capture.count} points "
              f"({len(points)} seen by the callback)")
        print(f"Fields   : {sorted(arrays)}")
        print(f"Overflow : {zebra.capture.overflowed}")

        if "enc1" in arrays:
            enc1 = arrays["enc1"]
            time = arrays["time"]
            print(f"\nFirst 5 timestamps : {time[:5].tolist()}")
            print(f"First 5 enc1       : {enc1[:5].tolist()}")
            print(f"enc1 range         : {enc1.min()} .. {enc1.max()}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "sim://zebra01"))
