"""Unit tests for SessionLogger — charging session logging.

Tests cover:
- Logging individual sessions with correct field precision
- Max 1000 sessions limit (oldest removed when exceeded)
- Serialization/deserialization for persistent storage
- Querying sessions by vehicle and latest sessions
- Integration with ChargingSession model

Requirements: 10.3
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from custom_components.peo.session_logger import SessionLogger, SessionRecord
from custom_components.peo.models import ChargingSession


class TestSessionLogger:
    """Tests for SessionLogger class."""

    def test_log_session_basic(self):
        """Log a single session and verify fields."""
        logger = SessionLogger()

        record = logger.log_session(
            session_id="sess_001",
            vehicle_id="ev_1",
            start_time=datetime(2024, 6, 15, 22, 0, 0),
            end_time=datetime(2024, 6, 16, 4, 0, 0),
            duration_minutes=360,
            energy_kwh=Decimal("35.50"),
            actual_cost_pln=Decimal("12.345"),
            hypothetical_cost_pln=Decimal("18.678"),
            is_manual=False,
        )

        assert record.session_id == "sess_001"
        assert record.vehicle_id == "ev_1"
        assert record.duration_minutes == 360
        assert record.energy_kwh == Decimal("35.50")
        assert record.actual_cost_pln == Decimal("12.35")  # rounded to 2dp
        assert record.hypothetical_cost_pln == Decimal("18.68")  # rounded to 2dp
        assert record.is_manual is False
        assert logger.session_count == 1

    def test_log_session_precision_2dp(self):
        """Energy and costs are rounded to 2 decimal places."""
        logger = SessionLogger()

        record = logger.log_session(
            session_id="sess_002",
            vehicle_id="ev_1",
            start_time=datetime(2024, 6, 15, 22, 0, 0),
            end_time=datetime(2024, 6, 16, 4, 0, 0),
            duration_minutes=120,
            energy_kwh=Decimal("10.999"),
            actual_cost_pln=Decimal("5.555"),
            hypothetical_cost_pln=Decimal("7.444"),
            is_manual=False,
        )

        assert record.energy_kwh == Decimal("11.00")
        assert record.actual_cost_pln == Decimal("5.56")
        assert record.hypothetical_cost_pln == Decimal("7.44")

    def test_max_sessions_limit(self):
        """Oldest sessions are removed when max limit (1000) is exceeded."""
        logger = SessionLogger(max_sessions=5)

        for i in range(7):
            logger.log_session(
                session_id=f"sess_{i:03d}",
                vehicle_id="ev_1",
                start_time=datetime(2024, 6, 15, i, 0, 0),
                end_time=datetime(2024, 6, 15, i + 1, 0, 0),
                duration_minutes=60,
                energy_kwh=Decimal("10.00"),
                actual_cost_pln=Decimal("5.00"),
                hypothetical_cost_pln=Decimal("7.00"),
            )

        assert logger.session_count == 5
        # Oldest sessions (0, 1) should be removed
        sessions = logger.sessions
        assert sessions[0].session_id == "sess_002"
        assert sessions[-1].session_id == "sess_006"

    def test_default_max_sessions_is_1000(self):
        """Default max sessions is 1000 (from const.MAX_CHARGING_SESSIONS)."""
        logger = SessionLogger()
        assert logger._max_sessions == 1000

    def test_log_charging_session_from_model(self):
        """Log session from ChargingSession dataclass."""
        logger = SessionLogger()

        session = ChargingSession(
            session_id="sess_model_001",
            vehicle_id="ev_2",
            start_time=datetime(2024, 6, 15, 22, 0, 0),
            end_time=datetime(2024, 6, 16, 2, 0, 0),
            energy_kwh=Decimal("25.00"),
            actual_cost_pln=Decimal("10.00"),
            hypothetical_cost_pln=Decimal("15.00"),
            is_manual=True,
            duration_minutes=240,
        )

        record = logger.log_charging_session(session)

        assert record.session_id == "sess_model_001"
        assert record.vehicle_id == "ev_2"
        assert record.duration_minutes == 240
        assert record.energy_kwh == Decimal("25.00")
        assert record.actual_cost_pln == Decimal("10.00")
        assert record.hypothetical_cost_pln == Decimal("15.00")
        assert record.is_manual is True

    def test_get_sessions_for_vehicle(self):
        """Filter sessions by vehicle ID."""
        logger = SessionLogger()

        for i in range(3):
            logger.log_session(
                session_id=f"ev1_{i}",
                vehicle_id="ev_1",
                start_time=datetime(2024, 6, 15, i, 0, 0),
                end_time=datetime(2024, 6, 15, i + 1, 0, 0),
                duration_minutes=60,
                energy_kwh=Decimal("10.00"),
                actual_cost_pln=Decimal("5.00"),
                hypothetical_cost_pln=Decimal("7.00"),
            )

        for i in range(2):
            logger.log_session(
                session_id=f"ev2_{i}",
                vehicle_id="ev_2",
                start_time=datetime(2024, 6, 15, i, 0, 0),
                end_time=datetime(2024, 6, 15, i + 1, 0, 0),
                duration_minutes=60,
                energy_kwh=Decimal("8.00"),
                actual_cost_pln=Decimal("4.00"),
                hypothetical_cost_pln=Decimal("6.00"),
            )

        ev1_sessions = logger.get_sessions_for_vehicle("ev_1")
        ev2_sessions = logger.get_sessions_for_vehicle("ev_2")

        assert len(ev1_sessions) == 3
        assert len(ev2_sessions) == 2
        assert all(s.vehicle_id == "ev_1" for s in ev1_sessions)
        assert all(s.vehicle_id == "ev_2" for s in ev2_sessions)

    def test_get_latest_sessions(self):
        """Get N most recent sessions in reverse chronological order."""
        logger = SessionLogger()

        for i in range(5):
            logger.log_session(
                session_id=f"sess_{i}",
                vehicle_id="ev_1",
                start_time=datetime(2024, 6, 15, i, 0, 0),
                end_time=datetime(2024, 6, 15, i + 1, 0, 0),
                duration_minutes=60,
                energy_kwh=Decimal("10.00"),
                actual_cost_pln=Decimal("5.00"),
                hypothetical_cost_pln=Decimal("7.00"),
            )

        latest = logger.get_latest_sessions(3)
        assert len(latest) == 3
        # Most recent first
        assert latest[0].session_id == "sess_4"
        assert latest[1].session_id == "sess_3"
        assert latest[2].session_id == "sess_2"

    def test_serialization_to_storage(self):
        """Serialize sessions to storage format."""
        logger = SessionLogger()

        logger.log_session(
            session_id="sess_001",
            vehicle_id="ev_1",
            start_time=datetime(2024, 6, 15, 22, 0, 0),
            end_time=datetime(2024, 6, 16, 4, 0, 0),
            duration_minutes=360,
            energy_kwh=Decimal("35.50"),
            actual_cost_pln=Decimal("12.34"),
            hypothetical_cost_pln=Decimal("18.67"),
            is_manual=False,
        )

        data = logger.to_storage_data()
        assert len(data) == 1
        assert data[0]["session_id"] == "sess_001"
        assert data[0]["energy_kwh"] == "35.50"
        assert data[0]["actual_cost_pln"] == "12.34"
        assert data[0]["hypothetical_cost_pln"] == "18.67"
        assert data[0]["start_time"] == "2024-06-15T22:00:00"
        assert data[0]["end_time"] == "2024-06-16T04:00:00"

    def test_load_from_storage(self):
        """Load sessions from storage format."""
        logger = SessionLogger()

        storage_data = [
            {
                "session_id": "sess_001",
                "vehicle_id": "ev_1",
                "start_time": "2024-06-15T22:00:00",
                "end_time": "2024-06-16T04:00:00",
                "duration_minutes": 360,
                "energy_kwh": "35.50",
                "actual_cost_pln": "12.34",
                "hypothetical_cost_pln": "18.67",
                "is_manual": False,
            },
            {
                "session_id": "sess_002",
                "vehicle_id": "ev_2",
                "start_time": "2024-06-16T10:00:00",
                "end_time": "2024-06-16T12:00:00",
                "duration_minutes": 120,
                "energy_kwh": "15.00",
                "actual_cost_pln": "6.00",
                "hypothetical_cost_pln": "9.00",
                "is_manual": True,
            },
        ]

        logger.load_from_storage(storage_data)

        assert logger.session_count == 2
        sessions = logger.sessions
        assert sessions[0].session_id == "sess_001"
        assert sessions[1].session_id == "sess_002"
        assert sessions[0].energy_kwh == Decimal("35.50")
        assert sessions[1].is_manual is True

    def test_load_from_storage_skips_invalid_records(self):
        """Invalid records in storage are skipped with warning."""
        logger = SessionLogger()

        storage_data = [
            {
                "session_id": "sess_001",
                "vehicle_id": "ev_1",
                "start_time": "2024-06-15T22:00:00",
                "end_time": "2024-06-16T04:00:00",
                "duration_minutes": 360,
                "energy_kwh": "35.50",
                "actual_cost_pln": "12.34",
                "hypothetical_cost_pln": "18.67",
                "is_manual": False,
            },
            {
                "session_id": "invalid",
                # Missing required fields
            },
        ]

        logger.load_from_storage(storage_data)
        assert logger.session_count == 1

    def test_clear_sessions(self):
        """Clear all sessions."""
        logger = SessionLogger()

        logger.log_session(
            session_id="sess_001",
            vehicle_id="ev_1",
            start_time=datetime(2024, 6, 15, 22, 0, 0),
            end_time=datetime(2024, 6, 16, 4, 0, 0),
            duration_minutes=360,
            energy_kwh=Decimal("35.50"),
            actual_cost_pln=Decimal("12.34"),
            hypothetical_cost_pln=Decimal("18.67"),
        )

        logger.clear()
        assert logger.session_count == 0
        assert logger.sessions == []
