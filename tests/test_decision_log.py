"""Unit tests for DecisionLog — optimization decision logging and notifications.

Tests cover:
- Recording decisions with correct field precision
- Circular buffer of max 10 decisions
- Diagnostic attribute output (ISO 8601 timestamps)
- Monthly savings notification (> 50 PLN, max once per month)
- Month reset behavior
- Serialization/deserialization for persistent storage

Requirements: 10.5, 10.6, 10.8
"""

from datetime import datetime
from decimal import Decimal

import pytest

from custom_components.peo.decision_log import DecisionLog, DecisionEntry


class TestDecisionLog:
    """Tests for DecisionLog class."""

    def test_record_single_decision(self):
        """Record a single decision and verify fields."""
        log = DecisionLog()

        entry = log.record_decision(
            timestamp=datetime(2024, 6, 15, 12, 30, 0),
            decision="Włączenie bojlera CWU",
            reason="Cena poniżej progu 0.35 PLN/kWh",
            savings_pln=Decimal("1.234"),
        )

        assert entry.decision == "Włączenie bojlera CWU"
        assert entry.reason == "Cena poniżej progu 0.35 PLN/kWh"
        assert entry.savings_pln == Decimal("1.23")  # rounded to 2dp
        assert entry.timestamp == datetime(2024, 6, 15, 12, 30, 0)

    def test_savings_precision_2dp(self):
        """Savings are rounded to 2 decimal places."""
        log = DecisionLog()

        entry = log.record_decision(
            timestamp=datetime(2024, 6, 15, 12, 0, 0),
            decision="test",
            reason="test",
            savings_pln=Decimal("3.456"),
        )

        assert entry.savings_pln == Decimal("3.46")

    def test_circular_buffer_max_10(self):
        """Only last 10 decisions are kept."""
        log = DecisionLog()

        for i in range(15):
            log.record_decision(
                timestamp=datetime(2024, 6, 15, i, 0, 0),
                decision=f"Decision {i}",
                reason=f"Reason {i}",
                savings_pln=Decimal("1.00"),
            )

        assert len(log.decisions) == 10
        # Oldest 5 should be removed
        assert log.decisions[0].decision == "Decision 5"
        assert log.decisions[-1].decision == "Decision 14"

    def test_get_diagnostic_attribute(self):
        """Diagnostic attribute returns last 10 decisions in reverse order."""
        log = DecisionLog()

        for i in range(3):
            log.record_decision(
                timestamp=datetime(2024, 6, 15, 10 + i, 0, 0),
                decision=f"Decision {i}",
                reason=f"Reason {i}",
                savings_pln=Decimal(f"{i + 1}.00"),
            )

        attr = log.get_diagnostic_attribute()

        assert len(attr) == 3
        # Most recent first
        assert attr[0]["decision"] == "Decision 2"
        assert attr[1]["decision"] == "Decision 1"
        assert attr[2]["decision"] == "Decision 0"

    def test_diagnostic_attribute_iso_8601_timestamps(self):
        """Timestamps in diagnostic attribute are ISO 8601 format."""
        log = DecisionLog()

        log.record_decision(
            timestamp=datetime(2024, 6, 15, 12, 30, 45),
            decision="Test",
            reason="Test reason",
            savings_pln=Decimal("1.00"),
        )

        attr = log.get_diagnostic_attribute()
        assert attr[0]["timestamp"] == "2024-06-15T12:30:45"

    def test_diagnostic_attribute_savings_as_string(self):
        """Savings in diagnostic attribute are string representation."""
        log = DecisionLog()

        log.record_decision(
            timestamp=datetime(2024, 6, 15, 12, 0, 0),
            decision="Test",
            reason="Test",
            savings_pln=Decimal("5.50"),
        )

        attr = log.get_diagnostic_attribute()
        assert attr[0]["savings_pln"] == "5.50"

    def test_monthly_savings_notification_above_50_pln(self):
        """Notification is generated when monthly savings exceed 50 PLN."""
        notifications = []

        def notify(title, message):
            notifications.append((title, message))

        log = DecisionLog(notify_callback=notify)

        # Record decisions totaling > 50 PLN
        for i in range(6):
            log.record_decision(
                timestamp=datetime(2024, 6, 15, i, 0, 0),
                decision=f"Decision {i}",
                reason="Test",
                savings_pln=Decimal("10.00"),
            )

        # After 6 * 10 = 60 PLN, notification should fire
        assert len(notifications) == 1
        assert "50 PLN" in notifications[0][0]
        assert "60.00" in notifications[0][1]

    def test_notification_max_once_per_month(self):
        """Notification is sent at most once per calendar month."""
        notifications = []

        def notify(title, message):
            notifications.append((title, message))

        log = DecisionLog(notify_callback=notify)

        # First batch: exceed 50 PLN
        for i in range(6):
            log.record_decision(
                timestamp=datetime(2024, 6, 10 + i, 10, 0, 0),
                decision=f"Decision {i}",
                reason="Test",
                savings_pln=Decimal("10.00"),
            )

        # Second batch: more savings in same month
        for i in range(5):
            log.record_decision(
                timestamp=datetime(2024, 6, 20 + i, 10, 0, 0),
                decision=f"Decision extra {i}",
                reason="Test",
                savings_pln=Decimal("10.00"),
            )

        # Only one notification for the month
        assert len(notifications) == 1

    def test_notification_resets_on_new_month(self):
        """Notification can fire again in a new month."""
        notifications = []

        def notify(title, message):
            notifications.append((title, message))

        log = DecisionLog(notify_callback=notify)

        # Month 1: exceed 50 PLN
        for i in range(6):
            log.record_decision(
                timestamp=datetime(2024, 6, 15, i, 0, 0),
                decision=f"June {i}",
                reason="Test",
                savings_pln=Decimal("10.00"),
            )

        assert len(notifications) == 1

        # Month 2: exceed 50 PLN again
        for i in range(6):
            log.record_decision(
                timestamp=datetime(2024, 7, 15, i, 0, 0),
                decision=f"July {i}",
                reason="Test",
                savings_pln=Decimal("10.00"),
            )

        assert len(notifications) == 2

    def test_monthly_savings_reset_on_new_month(self):
        """Monthly savings counter resets on new month."""
        log = DecisionLog()

        # June savings
        log.record_decision(
            timestamp=datetime(2024, 6, 28, 10, 0, 0),
            decision="June decision",
            reason="Test",
            savings_pln=Decimal("30.00"),
        )

        assert log.monthly_savings == Decimal("30.00")

        # July — should reset
        log.record_decision(
            timestamp=datetime(2024, 7, 1, 10, 0, 0),
            decision="July decision",
            reason="Test",
            savings_pln=Decimal("5.00"),
        )

        assert log.monthly_savings == Decimal("5.00")

    def test_no_notification_below_threshold(self):
        """No notification when savings are below 50 PLN."""
        notifications = []

        def notify(title, message):
            notifications.append((title, message))

        log = DecisionLog(notify_callback=notify)

        # Record 40 PLN total — below threshold
        for i in range(4):
            log.record_decision(
                timestamp=datetime(2024, 6, 15, i, 0, 0),
                decision=f"Decision {i}",
                reason="Test",
                savings_pln=Decimal("10.00"),
            )

        assert len(notifications) == 0

    def test_no_notification_without_callback(self):
        """No error when notify_callback is None."""
        log = DecisionLog(notify_callback=None)

        # Should not raise even when threshold exceeded
        for i in range(6):
            log.record_decision(
                timestamp=datetime(2024, 6, 15, i, 0, 0),
                decision=f"Decision {i}",
                reason="Test",
                savings_pln=Decimal("10.00"),
            )

    def test_serialization_to_storage(self):
        """Serialize decision log state to storage format."""
        log = DecisionLog()

        log.record_decision(
            timestamp=datetime(2024, 6, 15, 12, 0, 0),
            decision="Test decision",
            reason="Test reason",
            savings_pln=Decimal("5.00"),
        )

        data = log.to_storage_data()

        assert "decisions" in data
        assert len(data["decisions"]) == 1
        assert data["decisions"][0]["decision"] == "Test decision"
        assert data["monthly_savings"] == "5.00"
        assert data["tracking_month"] == 6

    def test_load_from_storage(self):
        """Load decision log state from storage."""
        log = DecisionLog()

        storage_data = {
            "decisions": [
                {
                    "timestamp": "2024-06-15T12:00:00",
                    "decision": "Stored decision",
                    "reason": "Stored reason",
                    "savings_pln": "5.00",
                }
            ],
            "monthly_savings": "25.00",
            "notification_sent_month": None,
            "tracking_month": 6,
        }

        log.load_from_storage(storage_data)

        assert len(log.decisions) == 1
        assert log.decisions[0].decision == "Stored decision"
        assert log.monthly_savings == Decimal("25.00")

    def test_load_from_storage_skips_invalid(self):
        """Invalid entries in storage are skipped."""
        log = DecisionLog()

        storage_data = {
            "decisions": [
                {
                    "timestamp": "2024-06-15T12:00:00",
                    "decision": "Valid",
                    "reason": "Valid",
                    "savings_pln": "5.00",
                },
                {
                    "timestamp": "invalid",
                    # Will fail to parse
                },
            ],
            "monthly_savings": "5.00",
            "notification_sent_month": None,
            "tracking_month": 6,
        }

        log.load_from_storage(storage_data)
        assert len(log.decisions) == 1

    def test_clear_log(self):
        """Clear all decisions and reset state."""
        log = DecisionLog()

        log.record_decision(
            timestamp=datetime(2024, 6, 15, 12, 0, 0),
            decision="Test",
            reason="Test",
            savings_pln=Decimal("10.00"),
        )

        log.clear()

        assert len(log.decisions) == 0
        assert log.monthly_savings == Decimal("0.00")

    def test_decision_entry_to_dict(self):
        """DecisionEntry serializes correctly."""
        entry = DecisionEntry(
            timestamp=datetime(2024, 6, 15, 12, 30, 0),
            decision="Ładowanie EV przesunięte",
            reason="Tańsza godzina o 02:00",
            savings_pln=Decimal("3.50"),
        )

        d = entry.to_dict()
        assert d["timestamp"] == "2024-06-15T12:30:00"
        assert d["decision"] == "Ładowanie EV przesunięte"
        assert d["reason"] == "Tańsza godzina o 02:00"
        assert d["savings_pln"] == "3.50"

    def test_decision_entry_from_dict(self):
        """DecisionEntry deserializes correctly."""
        data = {
            "timestamp": "2024-06-15T12:30:00",
            "decision": "Test decision",
            "reason": "Test reason",
            "savings_pln": "3.50",
        }

        entry = DecisionEntry.from_dict(data)
        assert entry.timestamp == datetime(2024, 6, 15, 12, 30, 0)
        assert entry.decision == "Test decision"
        assert entry.savings_pln == Decimal("3.50")
