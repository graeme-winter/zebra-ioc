"""Tests for the position compare capture buffer."""

import numpy as np
import pytest

from zebra_ioc.capture import CaptureBuffer
from zebra_ioc.interrupts import PositionCompareData

# PC_BIT_CAP bit 0 is encoder 1, bit 3 is encoder 4, bit 6 is divider 1
BIT_CAP_ENC1 = 0b0000000001
BIT_CAP_ENC1_ENC4 = 0b0000001001
BIT_CAP_ENC1_DIV1 = 0b0001000001


def point(timestamp: int, **fields) -> PositionCompareData:
    """Build a capture point with only the named fields present."""
    return PositionCompareData(timestamp=timestamp, **fields)


class TestCaptureBuffer:
    """The buffer decides what is kept and what is exposed."""

    def test_starts_empty(self):
        buffer = CaptureBuffer(max_points=10)
        assert buffer.count == 0
        assert buffer.arrays() == {}
        assert not buffer.overflowed

    def test_rejects_non_positive_capacity(self):
        with pytest.raises(ValueError):
            CaptureBuffer(max_points=0)

    def test_accumulates_one_encoder(self):
        buffer = CaptureBuffer(max_points=10)
        for i in range(3):
            buffer.append(point(i * 100, encoder1=i * 1000))

        arrays = buffer.arrays()
        assert buffer.count == 3
        assert set(arrays) == {"time", "enc1"}
        np.testing.assert_array_equal(arrays["time"], [0, 100, 200])
        np.testing.assert_array_equal(arrays["enc1"], [0, 1000, 2000])

    def test_only_captured_fields_are_exposed(self):
        """A scan capturing one encoder should not publish ten arrays."""
        buffer = CaptureBuffer(max_points=10)
        buffer.append(point(0, encoder1=5, div1=2))
        assert set(buffer.arrays()) == {"time", "enc1", "div1"}

    def test_encoders_are_signed(self):
        """Omega running negative must come back negative, not as 2**32."""
        buffer = CaptureBuffer(max_points=10)
        buffer.append(point(0, encoder1=-12345))
        arrays = buffer.arrays()
        assert arrays["enc1"].dtype == np.int32
        assert arrays["enc1"][0] == -12345

    def test_system_bus_is_unsigned(self):
        buffer = CaptureBuffer(max_points=10)
        buffer.append(point(0, sysbus1=0xFFFFFFFF))
        arrays = buffer.arrays()
        assert arrays["sys1"].dtype == np.uint32
        assert arrays["sys1"][0] == 0xFFFFFFFF

    def test_overflow_drops_and_counts(self):
        buffer = CaptureBuffer(max_points=3)
        for i in range(5):
            stored = buffer.append(point(i, encoder1=i))
            assert stored == (i < 3)

        assert buffer.count == 3
        assert buffer.received == 5
        assert buffer.overflowed
        np.testing.assert_array_equal(buffer.arrays()["enc1"], [0, 1, 2])

    def test_reset_hides_previous_capture(self):
        """Stale values beyond the count must not be observable."""
        buffer = CaptureBuffer(max_points=10)
        for i in range(4):
            buffer.append(point(i, encoder1=999))

        buffer.reset()
        assert buffer.count == 0
        assert buffer.arrays() == {}
        assert not buffer.overflowed

        buffer.append(point(0, encoder1=7))
        np.testing.assert_array_equal(buffer.arrays()["enc1"], [7])
