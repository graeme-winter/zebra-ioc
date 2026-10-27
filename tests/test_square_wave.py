"""Tests for the pulse train arithmetic in zebra_ioc.pulse_train.

The register values that come out of this are what actually reach the
hardware, and getting a prescaler or a divisor wrong gives a plausible
looking wave at the wrong rate, so the sums are worth pinning down.
"""

import pytest

from zebra_ioc import SysBus
from zebra_ioc.pulse_train import divider, pulse_train_registers, pulse_width


class TestDivider:
    """DIV1 divides the 1 MHz clock down to the repetition rate."""

    @pytest.mark.parametrize(
        "freq,expected_div",
        [(1_000_000, 1), (1000, 1000), (100, 10_000), (1, 1_000_000)],
    )
    def test_exact_rates(self, freq, expected_div):
        div, actual = divider(freq)
        assert div == expected_div
        assert actual == pytest.approx(freq)

    def test_inexact_rate_reports_what_it_got(self):
        """3 Hz does not divide the clock exactly, so say so rather than lie."""
        div, actual = divider(3)
        assert div == 333_333
        assert actual == pytest.approx(3.000003, rel=1e-6)

    @pytest.mark.parametrize("freq", [0, -1, 2_000_000])
    def test_unreachable_rates_raise(self, freq):
        with pytest.raises(ValueError):
            divider(freq)


class TestPulseWidth:
    """PULSE1 reshapes each divided pulse to the requested width."""

    def test_default_is_half_the_period(self):
        _, _, ticks, width_us = pulse_width(1000, None, None)
        assert width_us == pytest.approx(500.0)
        assert ticks == 5000

    def test_duty_cycle(self):
        _, _, _, width_us = pulse_width(1000, 10.0, None)
        assert width_us == pytest.approx(100.0)

    def test_explicit_width_wins(self):
        _, _, _, width_us = pulse_width(1000, None, 2.0)
        assert width_us == pytest.approx(2.0)

    def test_millisecond_prescaler_for_short_pulses(self):
        prescaler, label, _, _ = pulse_width(1000, None, 2.0)
        assert (prescaler, label) == (5, "ms")

    def test_prescaler_steps_up_for_long_pulses(self):
        """A 50% duty cycle below about 76Hz overflows the ms prescaler.

        Stepping up to the second prescaler is what stops that being a
        confusing cliff in the middle of the useful range.
        """
        prescaler, label, _, width_us = pulse_width(10, None, None)
        assert (prescaler, label) == (5000, "s")
        assert width_us == pytest.approx(50_000.0)

    def test_coarsest_prescaler_for_very_long_pulses(self):
        prescaler, label, _, _ = pulse_width(0.05, None, None)
        assert (prescaler, label) == (50000, "10s")

    def test_width_must_fit_in_the_period(self):
        """A PULSE block errors if retriggered while still producing."""
        with pytest.raises(ValueError, match="does not fit"):
            pulse_width(1000, None, 1000.0)

    def test_width_below_resolution_raises(self):
        with pytest.raises(ValueError, match="resolution"):
            pulse_width(1000, None, 0.01)

    def test_zero_width_raises(self):
        with pytest.raises(ValueError, match="positive"):
            pulse_width(1000, 0.0, None)

    def test_register_values_are_integers(self):
        """Anything else fails on the way to a 16 bit register."""
        for freq in (1, 10, 100, 1000, 10_000, 100_000):
            _, _, ticks, _ = pulse_width(freq, None, None)
            assert isinstance(ticks, int)
            assert 1 <= ticks <= 65535


class TestPulseTrainRegisters:
    """The settings dict both examples write, however they write it."""

    def test_full_chain(self):
        settings, achieved = pulse_train_registers(1000)
        assert settings == {
            "DIV1_INP": int(SysBus.CLOCK_1MHZ),
            "DIV1_DIV": 1000,
            "PULSE1_INP": int(SysBus.DIV1_OUTD),
            "PULSE1_PRE": 5,
            "PULSE1_DLY": 0,
            "PULSE1_WID": 5000,
            "OUT1_TTL": int(SysBus.PULSE1),
        }
        assert achieved["frequency_hz"] == pytest.approx(1000)
        assert achieved["duty_percent"] == pytest.approx(50.0)

    def test_alternate_output(self):
        settings, _ = pulse_train_registers(1000, out="OUT3_NIM")
        assert settings["OUT3_NIM"] == int(SysBus.PULSE1)
        assert "OUT1_TTL" not in settings

    def test_alternate_block(self):
        settings, _ = pulse_train_registers(1000, block=3)
        assert settings["PULSE3_INP"] == int(SysBus.DIV3_OUTD)
        assert settings["OUT1_TTL"] == int(SysBus.PULSE3)
        assert "DIV1_DIV" not in settings

    @pytest.mark.parametrize("block", [0, 5, -1])
    def test_invalid_block_raises(self, block):
        with pytest.raises(ValueError, match="Block must be"):
            pulse_train_registers(1000, block=block)

    def test_achieved_reports_the_real_rate(self):
        """3Hz does not divide the clock exactly; say so rather than lie."""
        _, achieved = pulse_train_registers(3)
        assert achieved["frequency_hz"] != 3
        assert achieved["frequency_hz"] == pytest.approx(3.000003, rel=1e-6)
