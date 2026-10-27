# zebra-ioc

An EPICS soft IOC for the Quantum Detectors Zebra, in Python, with no control
system framework between the records and the serial protocol.

```bash
pip install -e .

zebra-ioc --port /dev/ttyUSB0 --prefix NECAT:ZEBRA1:
zebra-ioc --port tcp://172.23.241.3:7012 --prefix NECAT:ZEBRA1:
zebra-ioc --port sim://zebra01 --prefix TEST:ZEBRA:
```

See [`examples/`](examples/README.md) for four runnable examples, none of
which need hardware.

## Why this exists

The alternatives are a C++ asyn/areaDetector driver that needs EPICS base,
asyn, ADCore, busy and motor built before it compiles, or a FastCS prototype
that is unmaintained and whose framework had breaking API changes twice in
one quarter.

The Zebra is a serial device with a documented register map and a four
command ASCII protocol. It does not need a framework. What it needs is the
register table, which is the part worth keeping, and that was lifted intact.

## Legacy PV names

**This is the main reason to prefer this over the FastCS driver.** PV names
are the legacy Diamond ALL_CAPS names:

```
$(P)PC_GATE_START      not  $(P)Pc:GateStart
$(P)PC_BIT_CAP              $(P)Pc:BitCap
$(P)AND1_INP1               $(P)And1:Inp1
```

Those names are the de facto Zebra interface. Every ophyd device, bluesky
plan, CS-Studio screen and commissioning script ever written against a Zebra
expects them. Keeping them means existing code works against this IOC
unmodified, and that every worked example you find elsewhere applies
directly.

## PV interface

Generated from the register tables rather than hand written, so the whole
interface follows from `registers.py`:

| Register type | Records |
|---|---|
| Read-write (16 or 32 bit) | `<NAME>` longout, `<NAME>_RBV` longin |
| Multiplexer (routing) | as above, plus `<NAME>_STR` stringin with the system bus signal name |
| Read-only | `<NAME>` longin |
| Command | `<NAME>` action |

Plus:

- **Capture arrays** - `PC_TIME`, `PC_ENC1`-`PC_ENC4`, `PC_SYS1`-`PC_SYS2`,
  `PC_DIV1`-`PC_DIV4`, with `PC_NUM_DOWN`, `PC_CAPTURE_MAX` and `PC_OVERFLOW`
- **System bus** - one bi per signal, `SYS_BUS_SOFT_IN1`, `SYS_BUS_PC_GATE`,
  `SYS_BUS_AND1` and so on, named after the signal rather than numbered
- **IOC status** - `CONNECTED`, `STATUS`, `PC_CAPTURING`

To see the whole interface without starting a server:

```bash
zebra-ioc --port sim://z --prefix TEST:ZEBRA: --list-pvs
```

440 PVs with the defaults.

## Architecture

```
  ioc.py        EPICS records, generated from the register tables
  __main__.py   CLI and softioc startup
  ------------  everything below knows nothing about EPICS
  device.py     connection, register access, capture, interrupt dispatch
  protocol.py   R / W / S / L commands and response parsing
  transport.py  serial, TCP, or the simulator
  interrupts.py the unsolicited PR / P<data> / PX stream
  capture.py    accumulation into arrays
  registers.py  the register map and the 64-way system bus
  simulator.py  a Zebra that is not there
```

The line matters. `ZebraDevice` is usable from a plain script, which is what
examples 1 to 3 do, and swapping or dropping the control system layer does
not touch anything below it.

## Reading captures

While position compare is armed the box streams one message per captured
point. These accumulate into the waveform PVs, which are republished at 5 Hz
during a capture and once more when it ends. **Read the arrays after the
capture ends**, not while it is running: `PC_NUM_DOWN` lags the hardware
slightly mid-scan, but the final values are always complete.

Which fields are populated is set by `PC_BIT_CAP`: bit 0 is encoder 1, bits
4-5 the system bus, bits 6-9 the dividers. Fields not selected stay empty
rather than being published as zeros.

Capacity is `--capture-points`, default 100000 to match `NELM` in the legacy
driver. Arrays that size exceed the default CA payload limit, so raise
`EPICS_CA_MAX_ARRAY_BYTES` on the IOC and the client, or lower it. Points
past capacity are dropped and `PC_OVERFLOW` goes true; the count is never
silently wrong.

Note that the unsigned arrays (`PC_TIME`, `PC_SYS*`, `PC_DIV*`) are `ULONG`,
which Channel Access has no native type for, so some clients promote them to
double. The values are correct; the encoders are `LONG` and come back as
signed integers.

## Configuration

The Zebra has no configuration file of its own. Configuration is the set of
register values, held in volatile memory until written to flash with
`caput $(P)STORE 1` (the `S` wire command). The IOC reads every register back at startup, so the PVs
reflect whatever the box is actually doing rather than zeros.

Snapshot a working configuration before changing anything. There is no undo,
and a Zebra with one wrong mux value looks exactly like a Zebra with a dead
output.

## Not implemented

- **Ini file configuration.** The legacy driver's `CONFIG_FILE` /
  `CONFIG_READ` / `CONFIG_WRITE` read and write the `[regs]` format used by
  the example configs in `DiamondLightSource/zebra`. Worth adding: those
  files are the easiest way to move a configuration between boxes.
- **Motor integration.** Captured positions are raw encoder counts; the
  legacy driver ties them to motor records to give engineering units.
- **Reconnection.** If the connection drops the reader task logs and exits.
  The IOC stays up but stops updating. Restart it.
- **Autosave.** No `save_restore` integration.
- **PVI.** No ophyd-async auto-introspection; write the device by hand, using
  `DiamondLightSource/dodal`, `src/dodal/devices/zebra/zebra.py` as the
  template. It is hand written there too.

## Testing

```bash
pip install -e '.[dev]'
pytest
```

127 tests, no hardware needed.

## Documentation

The vendor documentation is thin. The real manual is checked into the legacy
Diamond support module: `DiamondLightSource/zebra`,
`documentation/TDI-CTRL-TNO-042-Zebra-Manual.pdf`. The register dumps in
`zebraApp/src/configs/` are complete working configurations and are the
fastest way to see how one hangs together.

## Licence

Apache-2.0. Derived from `gilesknap/fastcs-zebra`; see `NOTICE`.
