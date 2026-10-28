# Zebra inline between the MD3 and the Eiger

A configuration that sits the Zebra in the trigger path between the MD3
diffractometer and the Eiger detector, and does three things at once for the
duration of a run:

1. **Swallows pulses** - passes the first pulse of each train through to the
   detector as a short pulse, and drops the rest
2. **Records a timestamp** for every pulse the MD3 produces
3. **Counts** the total number of pulses

Everything is bounded by an explicit setup and teardown, so the three records
cover exactly the same set of pulses.

`examples/09_md3_eiger.py` implements all of this; this document explains what
it does and why, so the configuration can be rebuilt or adapted by hand.

## Physical wiring

All connections are BNC. The Zebra's TTL outputs are LVTTL at about 3.3 V -
check that against the Eiger trigger input's threshold before relying on it.

```
     MD3                          ZEBRA                        EIGER
  ___________              ___________________             ___________
 |           |            |                   |           |           |
 | trigger   |----------->| IN1 TTL           |           |           |
 | out       |            |                   |           |           |
 |___________|            |           OUT1 TTL|---------->| trigger in|
                          |                   |           |___________|
                          |           OUT2 TTL|----+
                          |___________________|    |
                                                   |       ___________
                                                   +------>|   scope   |
                                                           |___________|
```

OUT2 carries the same signal as OUT1 from its own buffer, so the scope does
not load the detector trigger line. Leave it connected in normal operation -
it costs nothing and it is the only way to see what the detector is actually
being sent.

Do **not** put a 50 ohm feedthrough on either output; see the bench notes in
the main README.

## Internal routing

```
                         SOFT_IN1  (the run gate, set over EPICS)
                             |
                             v
   IN1_TTL  ------------> [ AND1 ] ---+---> [ PULSE1 ]  dead time, spans a train
                                      |         |
                                      |         v
                                      |     [ PULSE2 ]  short output pulse
                                      |         |
                                      |         +------> OUT1_TTL  -> Eiger
                                      |         +------> OUT2_TTL  -> scope
                                      |
                                      +---> [ DIV1 ]    free running counter
                                      |
                                      +---> PC pulse input
                                              |
                                              v
                                       capture: timestamp + DIV1 counter
```

Everything downstream hangs off `AND1`, which is `IN1_TTL AND SOFT_IN1`. That
one gate is what makes the three records consistent: the detector pulse, the
count and the timestamps all see exactly the same pulses, and nothing happens
outside a run.

### Why AND1 and not the position compare gate

In external trigger mode the Zebra's gate does **not** gate the capture. The
manual is explicit: each external pulse captures regardless of the gate
signal, and the gate is only used to count gates so the box can disarm itself.
So `PC_GATE_*` cannot be used as a run gate here. Gating the pulses themselves
with `AND1` is what actually bounds the run.

`PC_GATE_NGATE` is set to 0 so the Zebra never disarms itself; teardown is
always explicit.

## Resource allocation

| Resource | Use |
|---|---|
| `IN1_TTL` | MD3 trigger in |
| `OUT1_TTL` | Eiger trigger out |
| `OUT2_TTL` | Scope monitor, same signal |
| `SOFT_IN1` | Run gate, raised at setup and dropped at teardown |
| `AND1` | Gates the input with the run gate |
| `PULSE1` | Dead time - swallows all but the first pulse of a train |
| `PULSE2` | Shapes the surviving pulse to a short output |
| `DIV1` | Free running pulse counter |
| Position compare | Timestamps, external pulse mode |

That leaves AND2-4, OR1-4, GATE1-4, PULSE3-4, DIV2-4 and the other inputs and
outputs free. Note there are only four of each block and nothing stops two
configurations fighting over one - see the collision note in
`examples/README.md`.

## Configuration

Register values, all written as PVs with the IOC's prefix. `<DEAD>` and
`<WIDTH>` are in prescaler ticks; see "Sizing" below.

| PV | Value | Why |
|---|---|---|
| `AND1_INP1` | 1 (`IN1_TTL`) | The MD3 pulses |
| `AND1_INP2` | 60 (`SOFT_IN1`) | The run gate |
| `AND1_ENA` | 3 | Inputs 1 and 2 only |
| `AND1_INV` | 0 | Neither inverted |
| `PULSE1_INP` | 32 (`AND1`) | Dead time triggered by the first pulse |
| `PULSE1_PRE` | 5000 | 100 us tick, for a dead time in the 0.1-6.5 s range |
| `PULSE1_DLY` | 0 | |
| `PULSE1_WID` | `<DEAD>` | Longer than a train, shorter than the inter-train gap |
| `PULSE2_INP` | 52 (`PULSE1`) | Fires on the rising edge of the dead time |
| `PULSE2_PRE` | 5 | 100 ns tick, for a short output |
| `PULSE2_DLY` | 0 | |
| `PULSE2_WID` | `<WIDTH>` | Output pulse width |
| `OUT1_TTL` | 53 (`PULSE2`) | To the Eiger |
| `OUT2_TTL` | 53 (`PULSE2`) | To the scope |
| `DIV1_INP` | 32 (`AND1`) | Counts the same gated pulses |
| `DIV1_DIV` | 4294967295 | Never wraps within a run |
| `PC_ARM_SEL` | 0 | Arm from software |
| `PC_GATE_SEL` | 2 | External |
| `PC_GATE_INP` | 60 (`SOFT_IN1`) | Nominal only; see above |
| `PC_GATE_NGATE` | 0 | Never self-disarm |
| `PC_PULSE_SEL` | 2 | External: capture on each pulse |
| `PC_PULSE_INP` | 32 (`AND1`) | The same gated pulses |
| `PC_TSPRE` | 5 | 100 ns timestamp resolution |
| `PC_BIT_CAP` | 64 | Bit 6: capture the DIV1 counter alongside the timestamp |

## Procedure

### Setup

1. Write every register in the table above.
2. `caput <P>SYS_RESET 1` - zeroes the DIV counters and the block state
   machines. Do this **before** arming, since it disarms position compare.
3. `caput <P>PC_ARM 1`.
4. `caput <P>SOFT_IN 1` - raises `SOFT_IN1` and opens the run gate. Pulses now
   flow.

### During the run

| PV | Shows |
|---|---|
| `<P>PC_DIV1_LAST` | Running total of MD3 pulses |
| `<P>PC_NUM_DOWN` | Number of captured points, which is the same thing until the buffer fills |
| `<P>PC_CAPTURING` | 1 while a capture is in progress |
| `<P>PC_OVERFLOW` | 1 if the capture buffer filled and points were dropped |

Use `PC_DIV1_LAST` as the authoritative count. It comes from a hardware
counter and keeps incrementing after the capture buffer fills, whereas
`PC_NUM_DOWN` stops at the buffer capacity.

### Teardown

1. `caput <P>SOFT_IN 0` - closes the run gate. No further pulses reach the
   detector, the counter or the capture.
2. `caput <P>PC_DISARM 1` - ends the capture. The arrays are published in full
   at this point.

Do them in that order. Disarming first would leave pulses still reaching the
detector while no longer being recorded.

### Reading the results

```bash
caget <P>PC_DIV1_LAST          # total pulses
caget <P>PC_NUM_DOWN           # points captured
caget -# <n> <P>PC_TIME        # timestamps, <n> = PC_NUM_DOWN
caget -# <n> <P>PC_DIV1        # counter value at each pulse
caget <P>PC_OVERFLOW           # 0 if nothing was dropped
```

`PC_TIME` is in units of `PC_TSPRE / 50 MHz`, so 100 ns with the settings
above, counted from the moment of arming. `numpy.diff` on it gives the
inter-arrival intervals.

Always check `PC_OVERFLOW` before trusting the arrays. The count in
`PC_DIV1_LAST` stays correct regardless.

## Sizing

**Timestamp resolution and wrap.** The timestamp is a 32-bit counter of
`PC_TSPRE / 50 MHz` ticks since arming:

| `PC_TSPRE` | Tick | Wraps after |
|---|---|---|
| 5 | 100 ns | 7.2 minutes |
| 5000 | 100 us | 119 hours |

Use 5 for sub-microsecond timing of a short sweep. For a run longer than about
seven minutes, either use 5000 and accept 100 us resolution, or handle the
wrap when unpacking the array.

**Capture depth.** The hardware holds `2e6 / (4 x fields)` points. Timestamp
plus the DIV1 counter is 2 fields, so 250,000. Start the IOC with a matching
capacity:

```bash
zebra-ioc --port <port> --prefix <P> --capture-points 250000
```

**Array transport.** 250,000 points across two arrays is about 2 MB, which
exceeds the default Channel Access payload limit. Raise
`EPICS_CA_MAX_ARRAY_BYTES` on both the IOC and the client, or reduce
`--capture-points`.

**Dead time.** `PULSE1_WID` must be longer than one train and shorter than the
gap between the start of consecutive trains, and at most 6.5535 s at the
100 us prescaler. If a train is longer than that, or the two constraints
cannot both be met, this arrangement cannot do the job and you need a GATE
block reset by an external end-of-train signal instead.

## Things that will catch you out

**`SYS_STATERR` will be permanently lit.** Every swallowed pulse latches a
pulse-generator error bit. That is documented retrigger behaviour, not a
fault, but it means `SYS_STATERR` is no longer usable as a health indicator
for `PULSE1` while this configuration is running. It clears only on
`SYS_RESET`.

**The DIV counter is not reset by disarming.** Only `SYS_RESET` zeroes it, and
`SYS_RESET` also disarms position compare and resets every block state
machine. That is why setup resets before arming rather than after. If you need
to re-zero without disturbing a running configuration, read the counter at the
start of the run and subtract.

**Configuration is volatile.** It survives until the Zebra loses power or
something overwrites it, and nothing else. `caput <P>STORE 1` writes the
current register set to flash if you want it to come back after a power cycle.

**Nothing here verifies the Eiger is armed.** The Zebra will happily send
triggers into a detector that is not listening. Sequencing that is the
acquisition system's job.

## Checking it before trusting it

Before putting this in the beam, verify it against a known source. Patch
`OUT3_TTL` to `IN1_TTL` and drive it from the Zebra's own pulse generator:

```bash
# a 1 kHz train out of OUT3, looped back into IN1
python examples/06_square_wave_epics.py <P> --freq 1000 --width-us 100 \
    --out OUT3_TTL --block 2
```

With a 1 kHz continuous input and a dead time of 500 ms you should see one
output pulse every 500 ms on the scope, `PC_DIV1_LAST` climbing by 1000 per
second, and `PC_NUM_DOWN` tracking it. Note `--block 2`, since `DIV1` is the
counter in this configuration.

A continuous train is not the same as discrete trains, so this checks the
counting, the timestamping and the output path but not the swallow logic's
behaviour at a train boundary. For that you need the MD3 itself, or a gated
source.
