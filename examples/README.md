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

## 05_square_wave.py - a pulse train on an output, over serial

Builds an arbitrary frequency, arbitrary width TTL pulse train from the
Zebra's own 1 MHz clock:

    CLOCK_1MHZ -> DIV1 (divide by N) -> PULSE1 (fixed width) -> OUT1_TTL

```bash
python examples/05_square_wave.py                       # 1 kHz square
python examples/05_square_wave.py --freq 100 --duty 10  # 100 Hz, 10%
python examples/05_square_wave.py --freq 5000 --width-us 2
python examples/05_square_wave.py --out OUT3_TTL
python examples/05_square_wave.py --monitor OUT2_TTL    # same signal, 2 BNCs
python examples/05_square_wave.py --stop
```

`--monitor` drives a second output from the same system bus signal. The bus
fans out, so the copy is free and comes from its own buffer: you can scope it
without loading the first output or reaching for a T-piece. Both are set and
cleared together, which matters because `--stop` only clears the outputs it
was given, and a forgotten second output keeps running.

The fastest way to check a cable, a scope setup or a detector trigger input
without a signal generator. It reports the rate and width it actually
achieved, which will differ from what you asked for when the rate does not
divide the clock exactly.

The configuration persists after the script exits, since the Zebra holds it
in volatile memory until it loses power. `--stop` disconnects the output.

## 06_square_wave_epics.py - the same thing over EPICS

What example 5 does over the serial port, through a running IOC instead.
This is how you would really do it: the IOC owns the port, and everything
else goes through PVs.

```bash
zebra-ioc --port /dev/ttyUSB0 --prefix BENCH:ZEBRA:     # one terminal
python examples/06_square_wave_epics.py BENCH:ZEBRA:    # another
python examples/06_square_wave_epics.py BENCH:ZEBRA: --freq 100 --duty 10
python examples/06_square_wave_epics.py BENCH:ZEBRA: --monitor OUT2_TTL
python examples/06_square_wave_epics.py BENCH:ZEBRA: --stop
```

Both examples call the same `zebra_ioc.pulse_train` code to work out the
register values, so the only difference between them is how those values
reach the hardware: `write_register` in one, `caput` in the other. Nothing
else changes, because the PV names *are* the register names.

It checks `CONNECTED` before writing anything - an IOC that is up but has no
Zebra behind it accepts every caput and reports success - and reads the
`_RBV` PVs back afterwards, since those come from the hardware rather than
from the demands that were just sent.

## 07_pulse_counting.py - counting pulses, read with one caget

The Zebra has no scaler block, but a DIV block's internal counter is a free
running pulse counter if the divisor is set high enough never to wrap.
Position compare samples it and the IOC publishes the latest value, so the
running total is a single PV.

    IN1_TTL --> DIV1 (counter) --> sampled by PC --> PC_DIV1_LAST

```bash
python examples/07_pulse_counting.py BENCH:ZEBRA: setup
python examples/07_pulse_counting.py BENCH:ZEBRA: zero
# ... time passes, pulses arrive ...
caget BENCH:ZEBRA:PC_DIV1_LAST
```

`read` and `watch` are conveniences for when there is no caget binary, and
`stop` disarms. `--input`, `--block` and `--sample-ms` change what is counted,
where, and how often the total is republished.

Pulses are never missed - the counter runs in the FPGA - but the readout is
sampled, so the PV lags by up to one sample interval (100 ms by default).

The capture runs for a single gate of 0xFFFFFFFF timestamp ticks, 119 hours
at the 100 us tick. When it ends the counter PV stops updating, so counting
that works and then stops dead after a fixed interval means the gate expired
rather than the signal going away.

`zero` uses SYS_RESET, which also resets the gate, pulse and quad blocks and
disarms position compare. That is fine on a bench; in a running system take a
baseline reading and subtract instead.

### Blocks are a shared resource

There are four of each block, and nothing stops two configurations fighting
over one. Examples 5 and 6 generate their pulse train with DIV1; counting
with `--block 1` would repurpose it, setting the divisor to 4294967295 so its
OUTD fires once every four billion edges. The pulse train stops, and it looks
exactly like a dead cable. `setup` refuses to take a DIV block that something
else is already feeding; `--force` overrides.

### Self test

Count the Zebra's own pulse train, so the answer is known. Note the counter
uses a different DIV block from the generator:

```bash
# patch OUT1 TTL to IN1 TTL with a BNC lead, then
python examples/06_square_wave_epics.py BENCH:ZEBRA: --freq 1000 --width-us 100
python examples/07_pulse_counting.py BENCH:ZEBRA: setup --block 2
python examples/07_pulse_counting.py BENCH:ZEBRA: zero --block 2
python examples/07_pulse_counting.py BENCH:ZEBRA: watch --block 2  # +1000/s
```

## 08_one_per_train.py - one short pulse per train of pulses

Given trains of N pulses, emit one short pulse timed with the first of each
train and swallow the other N-1.

    IN1_TTL --> PULSE1 (dead time) --> PULSE2 (short) --> OUT1_TTL

```bash
python examples/08_one_per_train.py BENCH:ZEBRA: --train-ms 500
python examples/08_one_per_train.py BENCH:ZEBRA: --train-ms 500 --width-us 2
python examples/08_one_per_train.py BENCH:ZEBRA: --monitor OUT2_TTL
python examples/08_one_per_train.py BENCH:ZEBRA: --stop
```

A PULSE block ignores any edge arriving while it is still producing, so
PULSE1 set to span the train is a self resetting dead time. Its output is as
wide as the train, so PULSE2 reshapes it into the short pulse you want.

A DIV block looks like the answer but is not: it emits on the Nth pulse of
each N rather than the first, its counter does not reset between trains (so
one train of N+1 permanently shifts the phase of everything after), and it
needs N in advance. None of that applies here.

Constraints: the dead time must be longer than a train and shorter than the
gap between the start of consecutive trains, and at most 6.5535 s. If both
cannot be met, use a GATE block reset by an external end of train signal.

Every swallowed edge latches a pulse generator error bit in SYS_STATERR.
That is documented retrigger behaviour, not a fault, but it means
SYS_STATERR stays lit until SYS_RESET and is no longer a useful health
indicator for those blocks.

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
