# Toy examples

Four examples, in increasing order of how much machinery is involved. All of
them run against the simulator with no hardware and no EPICS installation
beyond what `pip install -e .` pulls in.

Each takes an optional connection argument, so the same script runs against a
real box:

```bash
python examples/01_protocol.py                          # simulator
python examples/01_protocol.py /dev/ttyUSB0             # serial
python examples/01_protocol.py tcp://172.23.241.3:7012  # terminal server
```

## 01_protocol.py - registers, no EPICS

Connects, reads the firmware version, writes and reads back a few registers
including a 32-bit pair. Start here to confirm a box is alive.

## 02_routing.py - the patch panel

Routes `SOFT_IN1` through `AND1` to the TTL output 1 connector, then toggles
it while watching the system bus. This is the Zebra's whole model in twenty
lines: every signal has a bus number, and routing is writing that number into
a block's input register.

On real hardware, scope OUT1 TTL while it runs.

## 03_capture.py - position compare

Configures a 90 degree sweep with one pulse per degree, arms, captures, and
prints the encoder and timestamp arrays. This is the shape of a rotation
scan.

## 05_square_wave.py - a pulse train on an output

Builds an arbitrary frequency, arbitrary width TTL pulse train from the
Zebra's own 1 MHz clock:

    CLOCK_1MHZ -> DIV1 (divide by N) -> PULSE1 (fixed width) -> OUT1_TTL

```bash
python examples/05_square_wave.py                       # 1 kHz square
python examples/05_square_wave.py --freq 100 --duty 10  # 100 Hz, 10%
python examples/05_square_wave.py --freq 5000 --width-us 2
python examples/05_square_wave.py --out OUT3_TTL
python examples/05_square_wave.py --stop
```

The fastest way to check a cable, a scope setup or a detector trigger input
without a signal generator. It reports the rate and width it actually
achieved, which will differ from what you asked for when the rate does not
divide the clock exactly.

The configuration persists after the script exits, since the Zebra holds it
in volatile memory until it loses power. `--stop` disconnects the output.

## 04_ioc_client.py - the same thing over Channel Access

Needs the IOC running in another terminal:

```bash
zebra-ioc --port sim://zebra01 --prefix TEST:ZEBRA:
```

then

```bash
python examples/04_ioc_client.py TEST:ZEBRA:
```

Everything in it is `caget` and `caput` against legacy PV names, which is the
point: the same script would work against the Diamond areaDetector driver.

## The same by hand

These need the `caget` and `caput` binaries, which come from an EPICS base
install. The pip dependencies give you `aioca` as a Python library only, so
without EPICS base use example 04 or a one-liner:

```bash
python3 -c "from aioca import caget; import asyncio; \
    print(asyncio.run(caget('TEST:ZEBRA:SYS_VER')))"
```

```bash
caget TEST:ZEBRA:CONNECTED TEST:ZEBRA:STATUS TEST:ZEBRA:SYS_VER

caput TEST:ZEBRA:PC_BIT_CAP 1          # capture encoder 1
caput TEST:ZEBRA:PC_GATE_START 0
caput TEST:ZEBRA:PC_GATE_WID 90
caput TEST:ZEBRA:PC_PULSE_STEP 1
caput TEST:ZEBRA:OUT1_TTL 31           # drive OUT1 from PC_PULSE
caget TEST:ZEBRA:OUT1_TTL_STR          # -> PC_PULSE

caput TEST:ZEBRA:PC_ARM 1
caget TEST:ZEBRA:PC_NUM_DOWN           # climbs while capturing
caput TEST:ZEBRA:PC_DISARM 1

caget -# 20 TEST:ZEBRA:PC_ENC1         # read arrays after the capture ends
caget -# 20 TEST:ZEBRA:PC_TIME
caget TEST:ZEBRA:PC_OVERFLOW
```

## One process at a time

The serial port is opened exclusively, so the IOC and these scripts cannot
both hold it. Stop one before starting the other, or you get a
`SerialException` about the device being busy, which reads like a cabling
fault if you are not expecting it.

## What the simulator does and does not do

It answers register reads and writes, reflects the soft inputs onto the
system bus, evaluates the four AND and four OR blocks from their INP / ENA /
INV registers, and streams capture points at 10 Hz between arm and disarm.

It does **not** model GATE, PULSE or DIV timing, and the capture points it
generates are a synthetic ramp rather than a response to your gate and pulse
configuration. So example 3 proves the plumbing works end to end; it proves
nothing about whether your scan geometry is right. That needs a box.
