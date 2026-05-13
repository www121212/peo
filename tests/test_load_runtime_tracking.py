"""Unit tests for load runtime tracking sensor functionality.

Tests verify that LoadStateTracker correctly:
- Tracks daily hours worked per load with 0.1h resolution
- Resets at 00:00 (day rollover)
- Exposes sensor data with realized_runtime field

Requirements: 10.4
"""

from datetime import datetime, timedelta

import pytest

from custom_components.peo.load_state_tracker import LoadStateTracker


class TestLoadRuntimeTracking:
    """Tests for load runtime tracking sensor (Requirement 10.4)."""

    def test_initial_runtime_is_zero(self):
        """New load starts with 0.0 hours runtime."""
        tracker = LoadStateTracker()
        assert tracker.get_daily_runtime("load_1") == 0.0

    def test_runtime_after_on_off_cycle(self):
        """Runtime is calculated correctly after on/off cycle."""
        tracker = LoadStateTracker()

        # Turn on at 10:00, off at 12:00 = 2.0 hours
        tracker.record_on("load_1", datetime(2024, 6, 15, 10, 0, 0))
        tracker.record_off("load_1", datetime(2024, 6, 15, 12, 0, 0))

        assert tracker.get_daily_runtime("load_1") == 2.0

    def test_runtime_resolution_0_1h(self):
        """Runtime is reported with 0.1h resolution."""
        tracker = LoadStateTracker()

        # Turn on at 10:00, off at 10:06 = 0.1 hours (6 minutes)
        tracker.record_on("load_1", datetime(2024, 6, 15, 10, 0, 0))
        tracker.record_off("load_1", datetime(2024, 6, 15, 10, 6, 0))

        assert tracker.get_daily_runtime("load_1") == 0.1

    def test_runtime_rounds_to_0_1h(self):
        """Runtime rounds to nearest 0.1h."""
        tracker = LoadStateTracker()

        # Turn on at 10:00, off at 10:08 = 0.133h → rounds to 0.1
        tracker.record_on("load_1", datetime(2024, 6, 15, 10, 0, 0))
        tracker.record_off("load_1", datetime(2024, 6, 15, 10, 8, 0))

        runtime = tracker.get_daily_runtime("load_1")
        assert runtime == round(8 / 60, 1)  # 0.1

    def test_multiple_on_off_cycles_accumulate(self):
        """Multiple on/off cycles accumulate runtime."""
        tracker = LoadStateTracker()

        # Cycle 1: 1 hour
        tracker.record_on("load_1", datetime(2024, 6, 15, 8, 0, 0))
        tracker.record_off("load_1", datetime(2024, 6, 15, 9, 0, 0))

        # Cycle 2: 2 hours
        tracker.record_on("load_1", datetime(2024, 6, 15, 14, 0, 0))
        tracker.record_off("load_1", datetime(2024, 6, 15, 16, 0, 0))

        assert tracker.get_daily_runtime("load_1") == 3.0

    def test_runtime_resets_on_new_day(self):
        """Runtime resets to 0 when a new day starts."""
        tracker = LoadStateTracker()

        # Day 1: 3 hours
        tracker.record_on("load_1", datetime(2024, 6, 15, 10, 0, 0))
        tracker.record_off("load_1", datetime(2024, 6, 15, 13, 0, 0))

        assert tracker.get_daily_runtime("load_1") == 3.0

        # Day 2: new on event triggers day rollover
        tracker.record_on("load_1", datetime(2024, 6, 16, 8, 0, 0))
        tracker.record_off("load_1", datetime(2024, 6, 16, 9, 0, 0))

        assert tracker.get_daily_runtime("load_1") == 1.0

    def test_runtime_at_specific_time(self):
        """get_daily_runtime_at returns runtime at a specific moment."""
        tracker = LoadStateTracker()

        tracker.record_on("load_1", datetime(2024, 6, 15, 10, 0, 0))

        # Check at 12:00 — should be 2.0h
        runtime = tracker.get_daily_runtime_at("load_1", datetime(2024, 6, 15, 12, 0, 0))
        assert runtime == 2.0

    def test_sensor_data_exposes_realized_runtime(self):
        """get_sensor_data exposes realized_runtime field."""
        tracker = LoadStateTracker()

        tracker.record_on("load_1", datetime(2024, 6, 15, 10, 0, 0))
        tracker.record_off("load_1", datetime(2024, 6, 15, 12, 30, 0))

        sensor_data = tracker.get_sensor_data("load_1", min_daily_hours=4.0)

        assert sensor_data["realized_runtime"] == 2.5
        assert sensor_data["remaining_required_runtime"] == 1.5
        assert sensor_data["status"] == "wyłączony"

    def test_sensor_data_status_when_on(self):
        """Sensor data shows 'włączony' when load is on."""
        tracker = LoadStateTracker()

        tracker.record_on("load_1", datetime(2024, 6, 15, 10, 0, 0))

        sensor_data = tracker.get_sensor_data("load_1")
        assert sensor_data["status"] == "włączony"

    def test_sensor_data_status_manual_override(self):
        """Sensor data shows 'ręczny' when manual override is active."""
        tracker = LoadStateTracker()

        tracker.set_manual_override("load_1", True)

        sensor_data = tracker.get_sensor_data("load_1")
        assert sensor_data["status"] == "ręczny"

    def test_independent_tracking_per_load(self):
        """Each load is tracked independently."""
        tracker = LoadStateTracker()

        tracker.record_on("load_1", datetime(2024, 6, 15, 10, 0, 0))
        tracker.record_off("load_1", datetime(2024, 6, 15, 12, 0, 0))

        tracker.record_on("load_2", datetime(2024, 6, 15, 14, 0, 0))
        tracker.record_off("load_2", datetime(2024, 6, 15, 15, 0, 0))

        assert tracker.get_daily_runtime("load_1") == 2.0
        assert tracker.get_daily_runtime("load_2") == 1.0

    def test_reset_daily_clears_runtime(self):
        """reset_daily explicitly clears runtime for a load."""
        tracker = LoadStateTracker()

        tracker.record_on("load_1", datetime(2024, 6, 15, 10, 0, 0))
        tracker.record_off("load_1", datetime(2024, 6, 15, 12, 0, 0))

        tracker.reset_daily("load_1")

        assert tracker.get_daily_runtime("load_1") == 0.0

    def test_remaining_required_runtime_calculation(self):
        """Remaining required runtime = max(0, min_hours - realized)."""
        tracker = LoadStateTracker()

        tracker.record_on("load_1", datetime(2024, 6, 15, 10, 0, 0))
        tracker.record_off("load_1", datetime(2024, 6, 15, 11, 0, 0))

        # min_daily_hours = 3.0, realized = 1.0 → remaining = 2.0
        sensor_data = tracker.get_sensor_data("load_1", min_daily_hours=3.0)
        assert sensor_data["remaining_required_runtime"] == 2.0

    def test_remaining_runtime_never_negative(self):
        """Remaining required runtime is never negative."""
        tracker = LoadStateTracker()

        tracker.record_on("load_1", datetime(2024, 6, 15, 10, 0, 0))
        tracker.record_off("load_1", datetime(2024, 6, 15, 15, 0, 0))

        # min_daily_hours = 3.0, realized = 5.0 → remaining = 0.0
        sensor_data = tracker.get_sensor_data("load_1", min_daily_hours=3.0)
        assert sensor_data["remaining_required_runtime"] == 0.0
