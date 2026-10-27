"""Accumulation of position compare capture data into arrays.

The Zebra streams one interrupt message per captured point. A scan wants the
whole sweep as arrays - the vector of captured encoder positions is the thing
that gets written alongside the images - so this module buffers the points
between the PR (reset) and PX (end) markers.

Storage is preallocated so that appending a point is an indexed write rather
than a list append plus a conversion, and the published arrays are views onto
the filled portion.
"""

import logging

import numpy as np

from .interrupts import PositionCompareData

logger = logging.getLogger(__name__)

#: Capture fields in PC_BIT_CAP bit order: (array name, data attribute, dtype).
#: Encoders are signed, everything else is unsigned, matching the parsing in
#: InterruptHandler. The timestamp is always present and is not in the bitmask.
CAPTURE_FIELDS: tuple[tuple[str, str, type], ...] = (
    ("enc1", "encoder1", np.int32),
    ("enc2", "encoder2", np.int32),
    ("enc3", "encoder3", np.int32),
    ("enc4", "encoder4", np.int32),
    ("sys1", "sysbus1", np.uint32),
    ("sys2", "sysbus2", np.uint32),
    ("div1", "div1", np.uint32),
    ("div2", "div2", np.uint32),
    ("div3", "div3", np.uint32),
    ("div4", "div4", np.uint32),
)

TIME_FIELD = ("time", "timestamp", np.uint32)

ALL_FIELDS = (TIME_FIELD, *CAPTURE_FIELDS)


class CaptureBuffer:
    """Accumulates position compare points into preallocated arrays.

    Only the fields actually captured (as decided by PC_BIT_CAP, and so
    reported as non-None by the interrupt handler) are tracked, so a scan
    capturing one encoder does not pay for ten arrays.

    Points beyond ``max_points`` are counted and dropped rather than growing
    the buffer without bound - a runaway capture should not take the IOC out
    with it.
    """

    def __init__(self, max_points: int = 100000):
        """Initialize the buffer.

        Args:
            max_points: Maximum number of points to retain per array

        Raises:
            ValueError: If max_points is not positive
        """
        if max_points < 1:
            raise ValueError(f"max_points must be positive, got {max_points}")

        self.max_points = max_points
        self._arrays: dict[str, np.ndarray] = {
            name: np.zeros(max_points, dtype=dtype) for name, _, dtype in ALL_FIELDS
        }
        self._active: set[str] = set()
        self._count = 0
        self._received = 0

    @property
    def count(self) -> int:
        """Number of points held in the arrays."""
        return self._count

    @property
    def received(self) -> int:
        """Number of points received, including any dropped when full."""
        return self._received

    @property
    def overflowed(self) -> bool:
        """True if points were dropped because the buffer filled."""
        return self._received > self._count

    @property
    def active_fields(self) -> set[str]:
        """Names of the arrays that carry captured data."""
        return set(self._active)

    def reset(self) -> None:
        """Discard buffered data, ready for a new capture.

        The arrays are not zeroed; ``arrays()`` only ever exposes the filled
        portion, so stale values beyond the count are not observable.
        """
        self._count = 0
        self._received = 0
        self._active.clear()

    def append(self, data: PositionCompareData) -> bool:
        """Add one captured point.

        Args:
            data: Parsed point from the interrupt handler

        Returns:
            True if the point was stored, False if it was dropped
        """
        self._received += 1

        if self._count >= self.max_points:
            if self._received == self.max_points + 1:
                # Log the transition only, not once per dropped point
                logger.warning(
                    f"Capture buffer full at {self.max_points} points, "
                    "further points will be dropped"
                )
            return False

        index = self._count
        for name, attribute, _ in ALL_FIELDS:
            value = getattr(data, attribute)
            if value is None:
                continue
            self._arrays[name][index] = value
            self._active.add(name)

        self._count += 1
        return True

    def arrays(self) -> dict[str, np.ndarray]:
        """Return the captured data.

        Returns:
            Mapping of array name to a view of the filled portion, for the
            captured fields only. Empty while nothing has been captured.
        """
        return {name: self._arrays[name][: self._count] for name in self._active}
