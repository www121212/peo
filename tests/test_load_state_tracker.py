"""Testy jednostkowe dla LoadStateTracker."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.peo.load_state_tracker import (
    LoadStateTracker,
    send_command_with_retry,
)
from custom_components.peo.models import TimeWindow


# --- Fixtures ---


@pytest.fixture
def tracker():
    """Fixture: Nowy LoadStateTracker."""
    return LoadStateTracker()


@pytest.fixture
def base_time():
    """Fixture: Bazowy czas testowy (2024-01-15 10:00:00)."""
    return datetime(2024, 1, 15, 10, 0, 0)


# --- Tests for record_on / record_off ---


class TestRecordOnOff:
    """Testy rejestrowania zdarzeń on/off."""

    def test_record_on_sets_state(self, tracker, base_time):
        """record_on ustawia is_on=True."""
        tracker.record_on("load_1", base_time)
        state = tracker.get_load_state("load_1")
        assert state["is_on"] is True
        assert state["last_change"] == base_time

    def test_record_off_sets_state(self, tracker, base_time):
        """record_off ustawia is_on=False."""
        tracker.record_on("load_1", base_time)
        off_time = base_time + timedelta(hours=1)
        tracker.record_off("load_1", off_time)
        state = tracker.get_load_state("load_1")
        assert state["is_on"] is False
        assert state["last_change"] == off_time

    def test_record_off_without_on_does_nothing(self, tracker, base_time):
        """record_off bez wcześniejszego on nie zmienia runtime."""
        tracker.record_off("load_1", base_time)
        state = tracker.get_load_state("load_1")
        assert state["is_on"] is False
        assert state["daily_runtime"] == 0.0

    def test_double_record_on_no_duplicate(self, tracker, base_time):
        """Podwójne record_on nie zmienia stanu."""
        tracker.record_on("load_1", base_time)
        tracker.record_on("load_1", base_time + timedelta(minutes=5))
        state = tracker.get_load_state("load_1")
        assert state["is_on"] is True
        # last_change powinno być z pierwszego on (bo drugie nie zmienia stanu)
        assert state["last_change"] == base_time


# --- Tests for get_daily_runtime ---


class TestGetDailyRuntime:
    """Testy obliczania dziennego czasu pracy."""

    def test_zero_runtime_initially(self, tracker):
        """Początkowy runtime = 0."""
        assert tracker.get_daily_runtime("load_1") == 0.0

    def test_runtime_after_one_session(self, tracker, base_time):
        """Runtime po jednej sesji 1h = 1.0h."""
        tracker.record_on("load_1", base_time)
        tracker.record_off("load_1", base_time + timedelta(hours=1))
        assert tracker.get_daily_runtime("load_1") == 1.0

    def test_runtime_after_multiple_sessions(self, tracker, base_time):
        """Runtime po wielu sesjach sumuje się."""
        # Sesja 1: 30 minut
        tracker.record_on("load_1", base_time)
        tracker.record_off("load_1", base_time + timedelta(minutes=30))
        # Sesja 2: 1 godzina
        tracker.record_on("load_1", base_time + timedelta(hours=1))
        tracker.record_off("load_1", base_time + timedelta(hours=2))
        assert tracker.get_daily_runtime("load_1") == 1.5

    def test_runtime_resolution_0_1h(self, tracker, base_time):
        """Runtime zaokrąglony do 0.1h."""
        # 7 minut = 0.1167h → zaokrąglone do 0.1h
        tracker.record_on("load_1", base_time)
        tracker.record_off("load_1", base_time + timedelta(minutes=7))
        assert tracker.get_daily_runtime("load_1") == 0.1

    def test_runtime_6_minutes_rounds_to_0_1(self, tracker, base_time):
        """6 minut = 0.1h (zaokrąglenie)."""
        tracker.record_on("load_1", base_time)
        tracker.record_off("load_1", base_time + timedelta(minutes=6))
        assert tracker.get_daily_runtime("load_1") == 0.1

    def test_runtime_at_specific_time(self, tracker, base_time):
        """get_daily_runtime_at oblicza runtime na dany moment."""
        tracker.record_on("load_1", base_time)
        # Nie wyłączamy — sprawdzamy runtime w trakcie sesji
        check_time = base_time + timedelta(hours=2)
        runtime = tracker.get_daily_runtime_at("load_1", check_time)
        assert runtime == 2.0

    def test_runtime_accumulates_across_sessions(self, tracker, base_time):
        """Runtime kumuluje się z wielu sesji."""
        # 3 sesje po 30 minut = 1.5h
        for i in range(3):
            start = base_time + timedelta(hours=i)
            tracker.record_on("load_1", start)
            tracker.record_off("load_1", start + timedelta(minutes=30))
        assert tracker.get_daily_runtime("load_1") == 1.5


# --- Tests for is_max_reached ---


class TestIsMaxReached:
    """Testy blokowania po max_daily_hours."""

    def test_not_reached_initially(self, tracker):
        """Max nie osiągnięty na starcie."""
        assert tracker.is_max_reached("load_1", max_hours=6.0) is False

    def test_reached_after_max_hours(self, tracker, base_time):
        """Max osiągnięty po pełnym czasie pracy."""
        tracker.record_on("load_1", base_time)
        tracker.record_off("load_1", base_time + timedelta(hours=6))
        assert tracker.is_max_reached("load_1", max_hours=6.0) is True

    def test_not_reached_below_max(self, tracker, base_time):
        """Max nie osiągnięty poniżej limitu."""
        tracker.record_on("load_1", base_time)
        tracker.record_off("load_1", base_time + timedelta(hours=5))
        assert tracker.is_max_reached("load_1", max_hours=6.0) is False

    def test_reached_exactly_at_max(self, tracker, base_time):
        """Max osiągnięty dokładnie na granicy."""
        tracker.record_on("load_1", base_time)
        tracker.record_off("load_1", base_time + timedelta(hours=6))
        assert tracker.is_max_reached("load_1", max_hours=6.0) is True

    def test_is_max_reached_at_specific_time(self, tracker, base_time):
        """is_max_reached_at sprawdza na dany moment."""
        tracker.record_on("load_1", base_time)
        # Nie wyłączamy — sprawdzamy w trakcie sesji
        check_time = base_time + timedelta(hours=6)
        assert tracker.is_max_reached_at("load_1", max_hours=6.0, at_time=check_time) is True
        check_time_early = base_time + timedelta(hours=3)
        assert tracker.is_max_reached_at("load_1", max_hours=6.0, at_time=check_time_early) is False


# --- Tests for manual override ---


class TestManualOverride:
    """Testy sterowania ręcznego."""

    def test_no_override_initially(self, tracker):
        """Brak override na starcie."""
        assert tracker.is_manual_override("load_1") is False

    def test_set_manual_override(self, tracker):
        """Ustawienie manual override."""
        tracker.set_manual_override("load_1", True)
        assert tracker.is_manual_override("load_1") is True

    def test_clear_manual_override(self, tracker):
        """Wyczyszczenie manual override."""
        tracker.set_manual_override("load_1", True)
        tracker.set_manual_override("load_1", False)
        assert tracker.is_manual_override("load_1") is False

    def test_override_in_load_state(self, tracker):
        """Manual override widoczny w get_load_state."""
        tracker.set_manual_override("load_1", True)
        state = tracker.get_load_state("load_1")
        assert state["manual_override"] is True


# --- Tests for reset_daily ---


class TestResetDaily:
    """Testy resetu dziennych liczników."""

    def test_reset_clears_runtime(self, tracker, base_time):
        """Reset zeruje daily_runtime."""
        tracker.record_on("load_1", base_time)
        tracker.record_off("load_1", base_time + timedelta(hours=3))
        assert tracker.get_daily_runtime("load_1") == 3.0

        tracker.reset_daily("load_1")
        assert tracker.get_daily_runtime("load_1") == 0.0

    def test_reset_does_not_change_is_on(self, tracker, base_time):
        """Reset nie zmienia stanu is_on."""
        tracker.record_on("load_1", base_time)
        tracker.reset_daily("load_1")
        state = tracker.get_load_state("load_1")
        assert state["is_on"] is True

    def test_reset_does_not_change_manual_override(self, tracker):
        """Reset nie zmienia manual_override."""
        tracker.set_manual_override("load_1", True)
        tracker.reset_daily("load_1")
        assert tracker.is_manual_override("load_1") is True

    def test_reset_clears_needs_verification(self, tracker, base_time):
        """Reset czyści flagę needs_verification."""
        tracker.record_on("load_1", base_time)
        state_obj = tracker._states["load_1"]
        state_obj.needs_verification = True
        tracker.reset_daily("load_1")
        state = tracker.get_load_state("load_1")
        assert state["needs_verification"] is False


# --- Tests for day rollover ---


class TestDayRollover:
    """Testy automatycznego resetu przy zmianie dnia."""

    def test_day_change_resets_runtime(self, tracker):
        """Zmiana dnia resetuje runtime."""
        day1 = datetime(2024, 1, 15, 10, 0)
        tracker.record_on("load_1", day1)
        tracker.record_off("load_1", day1 + timedelta(hours=3))
        assert tracker.get_daily_runtime("load_1") == 3.0

        # Następny dzień
        day2 = datetime(2024, 1, 16, 8, 0)
        tracker.record_on("load_1", day2)
        tracker.record_off("load_1", day2 + timedelta(hours=1))
        assert tracker.get_daily_runtime("load_1") == 1.0

    def test_day_change_unblocks_load(self, tracker):
        """Zmiana dnia odblokowuje odbiornik (max_hours reset)."""
        day1 = datetime(2024, 1, 15, 10, 0)
        tracker.record_on("load_1", day1)
        tracker.record_off("load_1", day1 + timedelta(hours=6))
        assert tracker.is_max_reached("load_1", max_hours=6.0) is True

        # Następny dzień — nowa rejestracja resetuje
        day2 = datetime(2024, 1, 16, 8, 0)
        tracker.record_on("load_1", day2)
        # Po resecie runtime = 0, więc max nie osiągnięty
        # (is_max_reached_at sprawdza bieżącą sesję)
        assert tracker.is_max_reached_at("load_1", max_hours=6.0, at_time=day2) is False


# --- Tests for get_load_state ---


class TestGetLoadState:
    """Testy get_load_state."""

    def test_initial_state(self, tracker):
        """Początkowy stan odbiornika."""
        state = tracker.get_load_state("load_1")
        assert state["is_on"] is False
        assert state["daily_runtime"] == 0.0
        assert state["manual_override"] is False
        assert state["last_change"] is None
        assert state["planned_windows"] == []
        assert state["needs_verification"] is False

    def test_state_after_operations(self, tracker, base_time):
        """Stan po operacjach on/off."""
        tracker.record_on("load_1", base_time)
        tracker.record_off("load_1", base_time + timedelta(hours=2))
        state = tracker.get_load_state("load_1")
        assert state["is_on"] is False
        assert state["daily_runtime"] == 2.0
        assert state["last_change"] == base_time + timedelta(hours=2)


# --- Tests for planned windows ---


class TestPlannedWindows:
    """Testy planowanych okien pracy."""

    def test_set_planned_windows(self, tracker, base_time):
        """Ustawienie planowanych okien."""
        windows = [
            TimeWindow(start=base_time, end=base_time + timedelta(hours=1), power_kw=2.0),
            TimeWindow(
                start=base_time + timedelta(hours=3),
                end=base_time + timedelta(hours=4),
                power_kw=2.0,
            ),
        ]
        tracker.set_planned_windows("load_1", windows)
        state = tracker.get_load_state("load_1")
        assert len(state["planned_windows"]) == 2

    def test_planned_windows_in_sensor_data(self, tracker, base_time):
        """Planowane okna widoczne w danych sensora."""
        windows = [
            TimeWindow(start=base_time, end=base_time + timedelta(hours=1), power_kw=2.0),
        ]
        tracker.set_planned_windows("load_1", windows)
        sensor = tracker.get_sensor_data("load_1", min_daily_hours=4.0)
        assert len(sensor["planned_windows"]) == 1
        assert sensor["planned_windows"][0]["power_kw"] == 2.0


# --- Tests for get_sensor_data ---


class TestGetSensorData:
    """Testy danych sensora."""

    def test_sensor_data_initial(self, tracker):
        """Początkowe dane sensora."""
        sensor = tracker.get_sensor_data("load_1", min_daily_hours=4.0)
        assert sensor["realized_runtime"] == 0.0
        assert sensor["remaining_required_runtime"] == 4.0
        assert sensor["status"] == "wyłączony"
        assert sensor["planned_windows"] == []

    def test_sensor_data_after_runtime(self, tracker, base_time):
        """Dane sensora po czasie pracy."""
        tracker.record_on("load_1", base_time)
        tracker.record_off("load_1", base_time + timedelta(hours=2))
        sensor = tracker.get_sensor_data("load_1", min_daily_hours=4.0)
        assert sensor["realized_runtime"] == 2.0
        assert sensor["remaining_required_runtime"] == 2.0

    def test_sensor_data_runtime_exceeds_min(self, tracker, base_time):
        """Remaining = 0 gdy runtime > min."""
        tracker.record_on("load_1", base_time)
        tracker.record_off("load_1", base_time + timedelta(hours=5))
        sensor = tracker.get_sensor_data("load_1", min_daily_hours=4.0)
        assert sensor["remaining_required_runtime"] == 0.0

    def test_sensor_status_on(self, tracker, base_time):
        """Status 'włączony' gdy is_on."""
        tracker.record_on("load_1", base_time)
        sensor = tracker.get_sensor_data("load_1")
        assert sensor["status"] == "włączony"

    def test_sensor_status_manual(self, tracker):
        """Status 'ręczny' gdy manual override."""
        tracker.set_manual_override("load_1", True)
        sensor = tracker.get_sensor_data("load_1")
        assert sensor["status"] == "ręczny"

    def test_sensor_status_needs_verification(self, tracker, base_time):
        """Status 'wymagający_weryfikacji' gdy needs_verification."""
        tracker.record_on("load_1", base_time)
        tracker._states["load_1"].needs_verification = True
        sensor = tracker.get_sensor_data("load_1")
        assert sensor["status"] == "wymagający_weryfikacji"


# --- Tests for send_command_with_retry ---


class TestSendCommandWithRetry:
    """Testy logiki ponawiania komend."""

    @pytest.fixture
    def mock_hass(self):
        """Fixture: Mock Home Assistant."""
        hass = MagicMock()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()
        hass.states = MagicMock()
        return hass

    @pytest.mark.asyncio
    async def test_success_on_first_try(self, mock_hass):
        """Sukces przy pierwszej próbie."""
        # Stan potwierdza zmianę natychmiast
        state_mock = MagicMock()
        state_mock.state = "on"
        mock_hass.states.get.return_value = state_mock

        result = await send_command_with_retry(
            mock_hass,
            "switch.bojler",
            "turn_on",
            retries=3,
            interval=0,  # Bez czekania w testach
            confirm_timeout=1,
        )

        assert result is True
        mock_hass.services.async_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_failure_after_all_retries(self, mock_hass):
        """Niepowodzenie po wyczerpaniu prób."""
        # Stan nigdy nie potwierdza zmiany
        state_mock = MagicMock()
        state_mock.state = "off"
        mock_hass.states.get.return_value = state_mock

        result = await send_command_with_retry(
            mock_hass,
            "switch.bojler",
            "turn_on",
            retries=3,
            interval=0,
            confirm_timeout=1,
        )

        assert result is False
        assert mock_hass.services.async_call.call_count == 3

    @pytest.mark.asyncio
    async def test_success_on_second_try(self, mock_hass):
        """Sukces przy drugiej próbie."""
        state_mock = MagicMock()
        # Pierwsza próba: stan nie zmieniony, druga: zmieniony
        call_count = [0]

        def get_state(entity_id):
            call_count[0] += 1
            if call_count[0] <= 1:
                state_mock.state = "off"
            else:
                state_mock.state = "on"
            return state_mock

        mock_hass.states.get.side_effect = get_state

        result = await send_command_with_retry(
            mock_hass,
            "switch.bojler",
            "turn_on",
            retries=3,
            interval=0,
            confirm_timeout=1,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_turn_off_checks_off_state(self, mock_hass):
        """turn_off sprawdza stan 'off'."""
        state_mock = MagicMock()
        state_mock.state = "off"
        mock_hass.states.get.return_value = state_mock

        result = await send_command_with_retry(
            mock_hass,
            "switch.bojler",
            "turn_off",
            retries=3,
            interval=0,
            confirm_timeout=1,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_service_call_exception_retries(self, mock_hass):
        """Wyjątek przy wywołaniu usługi — ponów."""
        call_count = [0]

        async def failing_call(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                raise ConnectionError("Connection lost")

        mock_hass.services.async_call = failing_call

        state_mock = MagicMock()
        state_mock.state = "on"
        mock_hass.states.get.return_value = state_mock

        result = await send_command_with_retry(
            mock_hass,
            "switch.bojler",
            "turn_on",
            retries=3,
            interval=0,
            confirm_timeout=1,
        )

        # Trzecia próba powinna się udać (nie rzuca wyjątku)
        assert result is True

    @pytest.mark.asyncio
    async def test_uses_entity_domain(self, mock_hass):
        """Używa domeny z entity_id."""
        state_mock = MagicMock()
        state_mock.state = "on"
        mock_hass.states.get.return_value = state_mock

        await send_command_with_retry(
            mock_hass,
            "switch.bojler",
            "turn_on",
            retries=1,
            interval=0,
            confirm_timeout=1,
        )

        mock_hass.services.async_call.assert_called_with(
            "switch",
            "turn_on",
            {"entity_id": "switch.bojler"},
            blocking=False,
        )


# --- Tests for multiple loads ---


class TestMultipleLoads:
    """Testy śledzenia wielu odbiorników jednocześnie."""

    def test_independent_tracking(self, tracker, base_time):
        """Odbiorniki śledzone niezależnie."""
        tracker.record_on("load_1", base_time)
        tracker.record_on("load_2", base_time + timedelta(minutes=30))
        tracker.record_off("load_1", base_time + timedelta(hours=1))

        assert tracker.get_daily_runtime("load_1") == 1.0
        state_2 = tracker.get_load_state("load_2")
        assert state_2["is_on"] is True

    def test_independent_manual_override(self, tracker):
        """Manual override niezależny per odbiornik."""
        tracker.set_manual_override("load_1", True)
        assert tracker.is_manual_override("load_1") is True
        assert tracker.is_manual_override("load_2") is False

    def test_independent_reset(self, tracker, base_time):
        """Reset niezależny per odbiornik."""
        tracker.record_on("load_1", base_time)
        tracker.record_off("load_1", base_time + timedelta(hours=2))
        tracker.record_on("load_2", base_time)
        tracker.record_off("load_2", base_time + timedelta(hours=3))

        tracker.reset_daily("load_1")
        assert tracker.get_daily_runtime("load_1") == 0.0
        assert tracker.get_daily_runtime("load_2") == 3.0
