"""Tests for the framework independent device layer.

These run against the simulator, so they need no hardware and no EPICS.
"""

import asyncio

import pytest

from zebra_ioc import SysBus, ZebraDevice

CAPTURE_ENC1 = 0b0000000001
CAPTURE_ENC1_DIV1 = 0b0001000001


@pytest.fixture
async def zebra():
    device = ZebraDevice("sim://test", capture_points=1000, poll_period=0.05)
    await device.connect()
    yield device
    await device.disconnect()


class TestRegisterAccess:
    """Registers are addressed by their legacy names."""

    async def test_read_known_register(self, zebra):
        assert await zebra.read_register("SYS_VER") == 0x0020

    async def test_write_read_round_trip(self, zebra):
        await zebra.write_register("PC_BIT_CAP", CAPTURE_ENC1)
        assert await zebra.read_register("PC_BIT_CAP") == CAPTURE_ENC1

    async def test_32bit_register_pair(self, zebra):
        """A value too wide for one register must survive the LO/HI split."""
        await zebra.write_register("PC_GATE_START", 123456)
        assert await zebra.read_register("PC_GATE_START") == 123456

    async def test_unknown_register_raises(self, zebra):
        with pytest.raises(KeyError):
            await zebra.read_register("NOT_A_REGISTER")

    async def test_configure_writes_several(self, zebra):
        await zebra.configure({"PC_GATE_WID": 90, "PC_TSPRE": 5000})
        assert await zebra.read_register("PC_GATE_WID") == 90
        assert await zebra.read_register("PC_TSPRE") == 5000

    async def test_access_before_connect_raises(self):
        device = ZebraDevice("sim://test")
        with pytest.raises(RuntimeError):
            await device.read_register("SYS_VER")


class TestSystemBus:
    """Routing is reflected in the system bus status registers."""

    async def test_soft_input_appears_on_the_bus(self, zebra):
        await zebra.write_register("SOFT_IN", 0b0001)
        await asyncio.sleep(0.15)
        assert zebra.sys_bus_bit(SysBus.SOFT_IN1)

        await zebra.write_register("SOFT_IN", 0b0000)
        await asyncio.sleep(0.15)
        assert not zebra.sys_bus_bit(SysBus.SOFT_IN1)

    async def test_routing_through_a_logic_block(self, zebra):
        await zebra.configure(
            {
                "AND1_INP1": int(SysBus.SOFT_IN1),
                "AND1_ENA": 0b0001,
                "AND1_INV": 0b0000,
            }
        )
        await zebra.write_register("SOFT_IN", 0b0001)
        await asyncio.sleep(0.15)
        assert zebra.sys_bus_bit(SysBus.AND1)


class TestCapture:
    """The PR / data / PX sequence through to the buffer."""

    async def test_capture_populates_the_buffer(self, zebra):
        await zebra.write_register("PC_BIT_CAP", CAPTURE_ENC1)
        await zebra.arm()
        await asyncio.sleep(0.5)
        await zebra.disarm()
        await asyncio.sleep(0.1)

        assert zebra.capture.count > 0
        assert set(zebra.capture.arrays()) == {"time", "enc1"}
        assert not zebra.capture.overflowed

    async def test_bit_cap_change_reaches_the_parser(self, zebra):
        """Writing PC_BIT_CAP must retune the interrupt parser.

        If it does not, every captured point fails to parse and the capture
        silently comes back empty.
        """
        await zebra.write_register("PC_BIT_CAP", CAPTURE_ENC1_DIV1)
        await zebra.arm()
        await asyncio.sleep(0.5)
        await zebra.disarm()
        await asyncio.sleep(0.1)

        assert zebra.capture.count > 0
        assert set(zebra.capture.arrays()) == {"time", "enc1", "div1"}

    async def test_callbacks_fire(self, zebra):
        started, points, ended = [], [], []

        async def on_start():
            started.append(True)

        async def on_point(point):
            points.append(point)

        async def on_end():
            ended.append(True)

        zebra.on_capture_start(on_start)
        zebra.on_capture_point(on_point)
        zebra.on_capture_end(on_end)

        await zebra.write_register("PC_BIT_CAP", CAPTURE_ENC1)
        await zebra.arm()
        await asyncio.sleep(0.4)
        await zebra.disarm()
        await asyncio.sleep(0.1)

        assert started == [True]
        assert ended == [True]
        assert len(points) == zebra.capture.count

    async def test_rearming_discards_the_previous_capture(self, zebra):
        await zebra.write_register("PC_BIT_CAP", CAPTURE_ENC1)
        await zebra.arm()
        await asyncio.sleep(0.4)
        await zebra.disarm()
        await asyncio.sleep(0.1)
        first = zebra.capture.count
        assert first > 0

        await zebra.arm()
        await asyncio.sleep(0.15)
        # The buffer was reset on PR, so the second capture is shorter
        assert zebra.capture.count < first
        await zebra.disarm()
