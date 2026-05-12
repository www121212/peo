"""Testy jednostkowe dla modułu bezpieczeństwa EV (ev_safety.py).

Testuje:
- Ograniczanie mocy do limitów ładowarki (max prąd, max moc)
- Sprawdzanie temperatury baterii i pauza/wznowienie
- Kontynuacja ładowania bez danych temperatury (req 9.9)
- Wykrywanie utraty komunikacji (60s timeout)
- Obliczanie bezpiecznej mocy z uwzględnieniem wszystkich limitów
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.peo.charger_adapters import ChargerAdapter, ChargerStatus
from custom_components.peo.const import CHARGER_COMM_TIMEOUT
from custom_components.peo.ev_safety import (
    DEFAULT_BATTERY_TEMP_THRESHOLD,
    EVSafetyMonitor,
    SINGLE_PHASE_VOLTAGE,
    THREE_PHASE_POWER_THRESHOLD,
    THREE_PHASE_VOLTAGE,
)


@pytest.fixture
def notify_user():
    """Fixture: mock notify_user callback."""
    return MagicMock()


@pytest.fixture
def mark_session():
    """Fixture: mock mark_session_verification callback."""
    return MagicMock()


@pytest.fixture
def monitor(notify_user, mark_session):
    """Fixture: instancja EVSafetyMonitor z domyślnym progiem temperatury."""
    return EVSafetyMonitor(
        notify_user=notify_user,
        mark_session_verification=mark_session,
    )


@pytest.fixture
def mock_charger_adapter():
    """Fixture: mock ChargerAdapter."""
    adapter = MagicMock(spec=ChargerAdapter)
    return adapter


# --- Tests: check_power_limits ---


class TestCheckPowerLimits:
    """Testy ograniczania mocy do limitów ładowarki."""

    def test_requested_below_all_limits(self, monitor):
        """Żądana moc poniżej wszystkich limitów — zwraca żądaną."""
        result = monitor.check_power_limits(
            max_power_kw=11.0,
            max_current_a=16.0,
            requested_power_kw=5.0,
        )
        assert result == 5.0

    def test_clamp_to_max_power(self, monitor):
        """Żądana moc powyżej max_power_kw — ogranicza do max_power."""
        result = monitor.check_power_limits(
            max_power_kw=7.0,
            max_current_a=32.0,
            requested_power_kw=11.0,
        )
        assert result == 7.0

    def test_clamp_to_current_limit_single_phase(self, monitor):
        """Żądana moc powyżej limitu prądu (jednofazowa) — ogranicza."""
        # 16A * 230V = 3680W = 3.68 kW
        # max_power_kw=7.0 (below threshold, so single-phase)
        result = monitor.check_power_limits(
            max_power_kw=7.0,
            max_current_a=16.0,
            requested_power_kw=5.0,
        )
        expected = (16.0 * SINGLE_PHASE_VOLTAGE) / 1000.0  # 3.68 kW
        assert result == pytest.approx(expected)

    def test_clamp_to_current_limit_three_phase(self, monitor):
        """Żądana moc powyżej limitu prądu (trójfazowa) — ogranicza."""
        # 16A * 400V = 6400W = 6.4 kW
        # max_power_kw=11.0 (above threshold, so three-phase)
        result = monitor.check_power_limits(
            max_power_kw=11.0,
            max_current_a=16.0,
            requested_power_kw=8.0,
        )
        expected = (16.0 * THREE_PHASE_VOLTAGE) / 1000.0  # 6.4 kW
        assert result == pytest.approx(expected)

    def test_never_exceeds_max_power(self, monitor):
        """Wynik nigdy nie przekracza max_power_kw."""
        result = monitor.check_power_limits(
            max_power_kw=3.5,
            max_current_a=32.0,
            requested_power_kw=22.0,
        )
        assert result <= 3.5

    def test_never_exceeds_current_limit(self, monitor):
        """Wynik nigdy nie przekracza mocy wynikającej z max_current_a."""
        # Single-phase: 10A * 230V = 2.3 kW
        result = monitor.check_power_limits(
            max_power_kw=7.0,
            max_current_a=10.0,
            requested_power_kw=5.0,
        )
        current_limit = (10.0 * SINGLE_PHASE_VOLTAGE) / 1000.0
        assert result <= current_limit

    def test_zero_requested_power(self, monitor):
        """Żądana moc 0 — zwraca 0."""
        result = monitor.check_power_limits(
            max_power_kw=11.0,
            max_current_a=32.0,
            requested_power_kw=0.0,
        )
        assert result == 0.0

    def test_negative_requested_power_clamped_to_zero(self, monitor):
        """Ujemna żądana moc — ogranicza do 0."""
        result = monitor.check_power_limits(
            max_power_kw=11.0,
            max_current_a=32.0,
            requested_power_kw=-5.0,
        )
        assert result == 0.0

    def test_three_phase_threshold_boundary(self, monitor):
        """Ładowarka na granicy progu trójfazowego."""
        # Exactly at threshold — still single-phase
        result = monitor.check_power_limits(
            max_power_kw=THREE_PHASE_POWER_THRESHOLD,
            max_current_a=32.0,
            requested_power_kw=7.0,
        )
        # At threshold, uses single-phase voltage
        current_limit = (32.0 * SINGLE_PHASE_VOLTAGE) / 1000.0  # 7.36 kW
        expected = min(7.0, THREE_PHASE_POWER_THRESHOLD, current_limit)
        assert result == pytest.approx(expected)


# --- Tests: is_temperature_safe ---


class TestIsTemperatureSafe:
    """Testy sprawdzania bezpieczeństwa temperatury."""

    def test_temperature_none_is_safe(self, monitor):
        """Brak danych temperatury (None) — bezpieczne (req 9.9)."""
        status = ChargerStatus(is_charging=True, current_power_kw=7.0, temperature=None)
        assert monitor.is_temperature_safe(status) is True

    def test_temperature_below_threshold_is_safe(self, monitor):
        """Temperatura poniżej progu — bezpieczne."""
        status = ChargerStatus(
            is_charging=True, current_power_kw=7.0, temperature=30.0
        )
        assert monitor.is_temperature_safe(status) is True

    def test_temperature_at_threshold_is_unsafe(self, monitor):
        """Temperatura równa progowi — niebezpieczne (>= próg)."""
        status = ChargerStatus(
            is_charging=True,
            current_power_kw=7.0,
            temperature=DEFAULT_BATTERY_TEMP_THRESHOLD,
        )
        assert monitor.is_temperature_safe(status) is False

    def test_temperature_above_threshold_is_unsafe(self, monitor):
        """Temperatura powyżej progu — niebezpieczne."""
        status = ChargerStatus(
            is_charging=True, current_power_kw=7.0, temperature=50.0
        )
        assert monitor.is_temperature_safe(status) is False

    def test_custom_threshold(self, notify_user, mark_session):
        """Niestandardowy próg temperatury."""
        custom_monitor = EVSafetyMonitor(
            notify_user=notify_user,
            mark_session_verification=mark_session,
            temp_threshold=60.0,
        )
        status = ChargerStatus(
            is_charging=True, current_power_kw=7.0, temperature=55.0
        )
        assert custom_monitor.is_temperature_safe(status) is True


# --- Tests: check_temperature ---


class TestCheckTemperature:
    """Testy zarządzania pauzą/wznowieniem na podstawie temperatury."""

    def test_no_temperature_data_continues(self, monitor, mock_charger_adapter):
        """Brak danych temperatury — kontynuuj normalnie (req 9.9)."""
        status = ChargerStatus(is_charging=True, current_power_kw=7.0, temperature=None)
        result = monitor.check_temperature("ev_1", status, mock_charger_adapter)
        assert result is True

    def test_safe_temperature_continues(self, monitor, mock_charger_adapter):
        """Bezpieczna temperatura — kontynuuj."""
        status = ChargerStatus(is_charging=True, current_power_kw=7.0, temperature=30.0)
        result = monitor.check_temperature("ev_1", status, mock_charger_adapter)
        assert result is True

    def test_high_temperature_pauses(self, monitor, mock_charger_adapter):
        """Wysoka temperatura — pauza ładowania."""
        status = ChargerStatus(is_charging=True, current_power_kw=7.0, temperature=50.0)
        result = monitor.check_temperature("ev_1", status, mock_charger_adapter)
        assert result is False
        assert monitor.temp_paused_vehicles.get("ev_1") is True

    def test_temperature_drops_resumes(self, monitor, mock_charger_adapter):
        """Temperatura spada poniżej progu — wznowienie."""
        # First: pause due to high temp
        hot_status = ChargerStatus(is_charging=True, current_power_kw=7.0, temperature=50.0)
        monitor.check_temperature("ev_1", hot_status, mock_charger_adapter)
        assert monitor.temp_paused_vehicles.get("ev_1") is True

        # Then: temperature drops
        cool_status = ChargerStatus(is_charging=True, current_power_kw=7.0, temperature=35.0)
        result = monitor.check_temperature("ev_1", cool_status, mock_charger_adapter)
        assert result is True
        assert monitor.temp_paused_vehicles.get("ev_1") is False

    def test_still_hot_remains_paused(self, monitor, mock_charger_adapter):
        """Temperatura nadal wysoka — pozostaje wstrzymane."""
        hot_status = ChargerStatus(is_charging=True, current_power_kw=7.0, temperature=50.0)
        monitor.check_temperature("ev_1", hot_status, mock_charger_adapter)

        # Still hot
        result = monitor.check_temperature("ev_1", hot_status, mock_charger_adapter)
        assert result is False

    def test_multiple_vehicles_independent(self, monitor, mock_charger_adapter):
        """Pauza temperatury jest niezależna per pojazd."""
        hot_status = ChargerStatus(is_charging=True, current_power_kw=7.0, temperature=50.0)
        cool_status = ChargerStatus(is_charging=True, current_power_kw=7.0, temperature=30.0)

        monitor.check_temperature("ev_1", hot_status, mock_charger_adapter)
        monitor.check_temperature("ev_2", cool_status, mock_charger_adapter)

        assert monitor.temp_paused_vehicles.get("ev_1") is True
        assert monitor.temp_paused_vehicles.get("ev_2", False) is False


# --- Tests: handle_communication_loss ---


class TestHandleCommunicationLoss:
    """Testy wykrywania utraty komunikacji."""

    def test_no_previous_communication(self, monitor):
        """Brak zarejestrowanej komunikacji — nie wykrywa utraty."""
        result = monitor.handle_communication_loss("ev_1")
        assert result is False

    def test_recent_communication_no_loss(self, monitor):
        """Komunikacja w ciągu 60s — brak utraty."""
        now = datetime(2024, 1, 15, 12, 0, 0)
        monitor.record_communication("ev_1", now - timedelta(seconds=30))
        result = monitor.handle_communication_loss("ev_1", now=now)
        assert result is False

    def test_communication_timeout_detected(self, monitor, notify_user, mark_session):
        """Brak komunikacji >60s — utrata wykryta."""
        now = datetime(2024, 1, 15, 12, 0, 0)
        monitor.record_communication("ev_1", now - timedelta(seconds=61))
        result = monitor.handle_communication_loss("ev_1", now=now)
        assert result is True
        notify_user.assert_called_once()
        mark_session.assert_called_once_with("ev_1")

    def test_exactly_at_timeout_no_loss(self, monitor):
        """Komunikacja dokładnie 60s temu — brak utraty (>60s wymagane)."""
        now = datetime(2024, 1, 15, 12, 0, 0)
        monitor.record_communication("ev_1", now - timedelta(seconds=CHARGER_COMM_TIMEOUT))
        result = monitor.handle_communication_loss("ev_1", now=now)
        assert result is False

    def test_notification_content(self, monitor, notify_user, mark_session):
        """Powiadomienie zawiera informacje o pojeździe."""
        now = datetime(2024, 1, 15, 12, 0, 0)
        monitor.record_communication("ev_1", now - timedelta(seconds=120))
        monitor.handle_communication_loss("ev_1", now=now)

        call_args = notify_user.call_args
        title = call_args[0][0]
        message = call_args[0][1]
        assert "ev_1" in message
        assert "weryfikacji" in message

    def test_multiple_vehicles_independent(self, monitor):
        """Utrata komunikacji jest niezależna per pojazd."""
        now = datetime(2024, 1, 15, 12, 0, 0)
        monitor.record_communication("ev_1", now - timedelta(seconds=120))
        monitor.record_communication("ev_2", now - timedelta(seconds=30))

        assert monitor.handle_communication_loss("ev_1", now=now) is True
        assert monitor.handle_communication_loss("ev_2", now=now) is False


# --- Tests: get_safe_power ---


class TestGetSafePower:
    """Testy obliczania bezpiecznej mocy z uwzględnieniem wszystkich limitów."""

    def test_all_limits_respected(self, monitor):
        """Bezpieczna moc nie przekracza żadnego limitu."""
        result = monitor.get_safe_power(
            max_power_kw=11.0,
            max_current_a=32.0,
            requested_power_kw=15.0,
            grid_available_kw=8.0,
        )
        assert result <= 11.0
        assert result <= 8.0

    def test_grid_limit_is_binding(self, monitor):
        """Limit sieci jest wiążący."""
        result = monitor.get_safe_power(
            max_power_kw=22.0,
            max_current_a=32.0,
            requested_power_kw=15.0,
            grid_available_kw=5.0,
        )
        assert result == 5.0

    def test_no_grid_limit(self, monitor):
        """Brak limitu sieci — tylko limity ładowarki."""
        result = monitor.get_safe_power(
            max_power_kw=11.0,
            max_current_a=32.0,
            requested_power_kw=8.0,
            grid_available_kw=None,
        )
        assert result == 8.0

    def test_negative_grid_available_clamped_to_zero(self, monitor):
        """Ujemna dostępna moc sieci — ogranicza do 0."""
        result = monitor.get_safe_power(
            max_power_kw=11.0,
            max_current_a=32.0,
            requested_power_kw=8.0,
            grid_available_kw=-2.0,
        )
        assert result == 0.0

    def test_charger_power_limit_binding(self, monitor):
        """Limit mocy ładowarki jest wiążący."""
        result = monitor.get_safe_power(
            max_power_kw=3.7,
            max_current_a=32.0,
            requested_power_kw=7.0,
            grid_available_kw=10.0,
        )
        assert result == pytest.approx(3.7)


# --- Tests: record_communication and reset_vehicle ---


class TestRecordAndReset:
    """Testy rejestracji komunikacji i resetowania stanu."""

    def test_record_communication(self, monitor):
        """Rejestracja komunikacji aktualizuje czas."""
        now = datetime(2024, 1, 15, 12, 0, 0)
        monitor.record_communication("ev_1", now)
        assert monitor.last_comm_times["ev_1"] == now

    def test_record_communication_default_time(self, monitor):
        """Rejestracja bez podania czasu używa datetime.now()."""
        monitor.record_communication("ev_1")
        assert "ev_1" in monitor.last_comm_times

    def test_reset_vehicle_clears_state(self, monitor, mock_charger_adapter):
        """Reset pojazdu czyści cały stan monitoringu."""
        now = datetime(2024, 1, 15, 12, 0, 0)
        monitor.record_communication("ev_1", now)
        hot_status = ChargerStatus(is_charging=True, current_power_kw=7.0, temperature=50.0)
        monitor.check_temperature("ev_1", hot_status, mock_charger_adapter)

        monitor.reset_vehicle("ev_1")

        assert "ev_1" not in monitor.last_comm_times
        assert "ev_1" not in monitor.temp_paused_vehicles
