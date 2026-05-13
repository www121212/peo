"""Property-based tests for session logging.

**Validates: Requirements 10.3**

Property 25: Rejestracja sesji ładowania EV
Dla dowolnej zakończonej sesji ładowania, zarejestrowany rekord powinien zawierać:
czas trwania (minuty), energię pobraną (kWh, 2 miejsca), koszt rzeczywisty (PLN, 2 miejsca),
koszt hipotetyczny (PLN, 2 miejsca), a magazyn powinien przechowywać maksymalnie
1000 ostatnich sesji.
"""

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

import pytest
from hypothesis import given, settings, assume
from hypothesis.strategies import (
    composite,
    decimals,
    integers,
    lists,
    text,
    datetimes,
)

from custom_components.peo.session_logger import SessionLogger, SessionRecord

# Minimum 200 iterations per property test as per design doc
PROPERTY_TEST_SETTINGS = settings(max_examples=200, deadline=None)


# --- Strategies ---


@composite
def valid_energy_kwh(draw):
    """Generate a valid energy value in kWh (0.01 to 500.00)."""
    return draw(
        decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("500.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )


@composite
def valid_cost_pln(draw):
    """Generate a valid cost in PLN (0.00 to 5000.00)."""
    return draw(
        decimals(
            min_value=Decimal("0.00"),
            max_value=Decimal("5000.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )


@composite
def valid_duration_minutes(draw):
    """Generate a valid charging duration in minutes (1 to 1440)."""
    return draw(integers(min_value=1, max_value=1440))


@composite
def valid_session_data(draw):
    """Generate valid session data for logging."""
    session_id = f"session_{draw(integers(min_value=1, max_value=999999))}"
    vehicle_id = f"vehicle_{draw(integers(min_value=1, max_value=10))}"
    start_time = draw(
        datetimes(
            min_value=datetime(2024, 1, 1),
            max_value=datetime(2025, 12, 31),
        )
    )
    duration_minutes = draw(valid_duration_minutes())
    end_time = start_time + timedelta(minutes=duration_minutes)
    energy_kwh = draw(valid_energy_kwh())
    actual_cost_pln = draw(valid_cost_pln())
    hypothetical_cost_pln = draw(valid_cost_pln())

    return {
        "session_id": session_id,
        "vehicle_id": vehicle_id,
        "start_time": start_time,
        "end_time": end_time,
        "duration_minutes": duration_minutes,
        "energy_kwh": energy_kwh,
        "actual_cost_pln": actual_cost_pln,
        "hypothetical_cost_pln": hypothetical_cost_pln,
        "is_manual": False,
    }


@composite
def multiple_sessions(draw, min_count=1, max_count=50):
    """Generate multiple valid session data entries."""
    count = draw(integers(min_value=min_count, max_value=max_count))
    sessions = []
    base_time = datetime(2024, 6, 1, 8, 0, 0)
    for i in range(count):
        session_id = f"session_{i}"
        vehicle_id = f"vehicle_{draw(integers(min_value=1, max_value=4))}"
        duration_minutes = draw(valid_duration_minutes())
        start_time = base_time + timedelta(hours=i * 2)
        end_time = start_time + timedelta(minutes=duration_minutes)
        energy_kwh = draw(valid_energy_kwh())
        actual_cost_pln = draw(valid_cost_pln())
        hypothetical_cost_pln = draw(valid_cost_pln())

        sessions.append({
            "session_id": session_id,
            "vehicle_id": vehicle_id,
            "start_time": start_time,
            "end_time": end_time,
            "duration_minutes": duration_minutes,
            "energy_kwh": energy_kwh,
            "actual_cost_pln": actual_cost_pln,
            "hypothetical_cost_pln": hypothetical_cost_pln,
            "is_manual": False,
        })
    return sessions


# --- Property 25 Tests ---


class TestProperty25SessionLogging:
    """Property 25: Rejestracja sesji ładowania EV.

    **Validates: Requirements 10.3**
    """

    @PROPERTY_TEST_SETTINGS
    @given(data=valid_session_data())
    def test_session_records_energy_with_2dp(self, data):
        """Recorded energy_kwh always has exactly 2 decimal places.

        **Validates: Requirements 10.3**
        """
        logger = SessionLogger()
        record = logger.log_session(**data)

        # Verify 2 decimal places
        assert record.energy_kwh == record.energy_kwh.quantize(Decimal("0.01")), (
            f"energy_kwh should have 2dp: {record.energy_kwh}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(data=valid_session_data())
    def test_session_records_actual_cost_with_2dp(self, data):
        """Recorded actual_cost_pln always has exactly 2 decimal places.

        **Validates: Requirements 10.3**
        """
        logger = SessionLogger()
        record = logger.log_session(**data)

        assert record.actual_cost_pln == record.actual_cost_pln.quantize(
            Decimal("0.01")
        ), f"actual_cost_pln should have 2dp: {record.actual_cost_pln}"

    @PROPERTY_TEST_SETTINGS
    @given(data=valid_session_data())
    def test_session_records_hypothetical_cost_with_2dp(self, data):
        """Recorded hypothetical_cost_pln always has exactly 2 decimal places.

        **Validates: Requirements 10.3**
        """
        logger = SessionLogger()
        record = logger.log_session(**data)

        assert record.hypothetical_cost_pln == record.hypothetical_cost_pln.quantize(
            Decimal("0.01")
        ), f"hypothetical_cost_pln should have 2dp: {record.hypothetical_cost_pln}"

    @PROPERTY_TEST_SETTINGS
    @given(data=valid_session_data())
    def test_session_records_duration_in_minutes(self, data):
        """Recorded duration_minutes matches the input duration.

        **Validates: Requirements 10.3**
        """
        logger = SessionLogger()
        record = logger.log_session(**data)

        assert record.duration_minutes == data["duration_minutes"], (
            f"duration_minutes should be {data['duration_minutes']}, "
            f"got {record.duration_minutes}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(data=valid_session_data())
    def test_session_contains_all_required_fields(self, data):
        """Every recorded session contains all required fields.

        **Validates: Requirements 10.3**
        """
        logger = SessionLogger()
        record = logger.log_session(**data)

        # Verify all required fields are present
        assert record.session_id == data["session_id"]
        assert record.vehicle_id == data["vehicle_id"]
        assert record.start_time == data["start_time"]
        assert record.end_time == data["end_time"]
        assert record.duration_minutes == data["duration_minutes"]
        assert record.energy_kwh is not None
        assert record.actual_cost_pln is not None
        assert record.hypothetical_cost_pln is not None

    @PROPERTY_TEST_SETTINGS
    @given(data=multiple_sessions(min_count=1, max_count=30))
    def test_session_count_matches_logged_sessions(self, data):
        """Session count always matches the number of logged sessions.

        **Validates: Requirements 10.3**
        """
        logger = SessionLogger()

        for session_data in data:
            logger.log_session(**session_data)

        assert logger.session_count == len(data), (
            f"Session count should be {len(data)}, got {logger.session_count}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(num_sessions=integers(min_value=1001, max_value=1100))
    def test_max_1000_sessions_enforced(self, num_sessions):
        """Storage never exceeds 1000 sessions — oldest removed when exceeded.

        **Validates: Requirements 10.3**
        """
        logger = SessionLogger()
        base_time = datetime(2024, 1, 1, 0, 0, 0)

        for i in range(num_sessions):
            logger.log_session(
                session_id=f"session_{i}",
                vehicle_id="vehicle_1",
                start_time=base_time + timedelta(hours=i),
                end_time=base_time + timedelta(hours=i, minutes=30),
                duration_minutes=30,
                energy_kwh=Decimal("10.00"),
                actual_cost_pln=Decimal("5.00"),
                hypothetical_cost_pln=Decimal("7.00"),
                is_manual=False,
            )

        assert logger.session_count <= 1000, (
            f"Session count should never exceed 1000, got {logger.session_count}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(num_extra=integers(min_value=1, max_value=100))
    def test_oldest_sessions_removed_when_limit_exceeded(self, num_extra):
        """When limit is exceeded, the oldest sessions are removed.

        **Validates: Requirements 10.3**
        """
        logger = SessionLogger()
        total_sessions = 1000 + num_extra
        base_time = datetime(2024, 1, 1, 0, 0, 0)

        for i in range(total_sessions):
            logger.log_session(
                session_id=f"session_{i}",
                vehicle_id="vehicle_1",
                start_time=base_time + timedelta(hours=i),
                end_time=base_time + timedelta(hours=i, minutes=30),
                duration_minutes=30,
                energy_kwh=Decimal("10.00"),
                actual_cost_pln=Decimal("5.00"),
                hypothetical_cost_pln=Decimal("7.00"),
                is_manual=False,
            )

        # Verify oldest sessions were removed
        sessions = logger.sessions
        assert len(sessions) == 1000

        # The first session should be session_{num_extra} (oldest remaining)
        assert sessions[0].session_id == f"session_{num_extra}", (
            f"Oldest remaining session should be session_{num_extra}, "
            f"got {sessions[0].session_id}"
        )

        # The last session should be the most recently added
        assert sessions[-1].session_id == f"session_{total_sessions - 1}", (
            f"Newest session should be session_{total_sessions - 1}, "
            f"got {sessions[-1].session_id}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(data=valid_session_data())
    def test_session_serialization_preserves_precision(self, data):
        """Serialization to dict preserves 2dp precision for all monetary fields.

        **Validates: Requirements 10.3**
        """
        logger = SessionLogger()
        record = logger.log_session(**data)
        serialized = record.to_dict()

        # Verify serialized values maintain 2dp precision
        energy = Decimal(serialized["energy_kwh"])
        actual_cost = Decimal(serialized["actual_cost_pln"])
        hypothetical_cost = Decimal(serialized["hypothetical_cost_pln"])

        assert energy == energy.quantize(Decimal("0.01")), (
            f"Serialized energy should have 2dp: {energy}"
        )
        assert actual_cost == actual_cost.quantize(Decimal("0.01")), (
            f"Serialized actual_cost should have 2dp: {actual_cost}"
        )
        assert hypothetical_cost == hypothetical_cost.quantize(Decimal("0.01")), (
            f"Serialized hypothetical_cost should have 2dp: {hypothetical_cost}"
        )
