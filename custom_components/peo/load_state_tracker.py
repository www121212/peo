"""LoadStateTracker — śledzenie stanu i czasu pracy odbiorników odraczalnych.

Odpowiada za:
- Rejestrowanie zdarzeń on/off z timestampami
- Obliczanie dziennego czasu pracy z rozdzielczością 0.1h
- Blokowanie odbiorników po osiągnięciu max_daily_hours (do 00:00 następnego dnia)
- Wykrywanie sterowania ręcznego (manual override)
- Ponawianie komend (retry 3x, 30s interwały) przy braku potwierdzenia w 60s
- Ekspozycja sensorów: planowane okna, zrealizowany czas, pozostały wymagany czas, status

Requirements: 4.5, 4.7, 4.8, 4.9
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Optional

from .const import LOAD_COMMAND_TIMEOUT, LOAD_RETRY_COUNT, LOAD_RETRY_INTERVAL
from .models import TimeWindow

_LOGGER = logging.getLogger(__name__)


@dataclass
class LoadState:
    """Stan pojedynczego odbiornika."""

    load_id: str
    is_on: bool = False
    daily_runtime_hours: float = 0.0
    manual_override: bool = False
    last_change: Optional[datetime] = None
    last_on_timestamp: Optional[datetime] = None
    tracking_date: Optional[date] = None
    planned_windows: list[TimeWindow] = field(default_factory=list)
    needs_verification: bool = False


class LoadStateTracker:
    """Śledzenie stanu i czasu pracy odbiorników odraczalnych.

    Zarządza:
    - Rejestracją zdarzeń on/off per odbiornik
    - Obliczaniem dziennego czasu pracy (rozdzielczość 0.1h)
    - Blokowaniem po max_daily_hours
    - Wykrywaniem sterowania ręcznego
    - Ponawianiem komend (retry logic)
    - Ekspozycją danych sensorów
    """

    def __init__(self) -> None:
        """Inicjalizacja LoadStateTracker."""
        self._states: dict[str, LoadState] = {}

    def _get_or_create_state(self, load_id: str) -> LoadState:
        """Pobierz lub utwórz stan dla odbiornika."""
        if load_id not in self._states:
            self._states[load_id] = LoadState(load_id=load_id)
        return self._states[load_id]

    def record_on(self, load_id: str, timestamp: datetime) -> None:
        """Zarejestruj włączenie odbiornika.

        Args:
            load_id: Identyfikator odbiornika.
            timestamp: Czas włączenia.
        """
        state = self._get_or_create_state(load_id)

        # Jeśli zmienił się dzień, resetuj liczniki
        self._check_day_rollover(state, timestamp)

        if not state.is_on:
            state.is_on = True
            state.last_on_timestamp = timestamp
            state.last_change = timestamp
            _LOGGER.info(
                "Odbiornik %s włączony o %s", load_id, timestamp.isoformat()
            )

    def record_off(self, load_id: str, timestamp: datetime) -> None:
        """Zarejestruj wyłączenie odbiornika.

        Oblicza czas pracy od ostatniego włączenia i dodaje do dziennego runtime.

        Args:
            load_id: Identyfikator odbiornika.
            timestamp: Czas wyłączenia.
        """
        state = self._get_or_create_state(load_id)

        # Jeśli zmienił się dzień, resetuj liczniki
        self._check_day_rollover(state, timestamp)

        if state.is_on and state.last_on_timestamp is not None:
            # Oblicz czas pracy od ostatniego włączenia
            duration = timestamp - state.last_on_timestamp
            duration_hours = duration.total_seconds() / 3600.0
            state.daily_runtime_hours += duration_hours
            # Zaokrąglij do 0.1h
            state.daily_runtime_hours = round(state.daily_runtime_hours, 1)
            _LOGGER.info(
                "Odbiornik %s wyłączony o %s (sesja: %.1fh, dzienny: %.1fh)",
                load_id,
                timestamp.isoformat(),
                duration_hours,
                state.daily_runtime_hours,
            )

        state.is_on = False
        state.last_on_timestamp = None
        state.last_change = timestamp

    def get_daily_runtime(self, load_id: str) -> float:
        """Oblicz dzienny czas pracy odbiornika.

        Uwzględnia bieżącą sesję (jeśli odbiornik jest włączony).
        Rozdzielczość: 0.1h.

        Args:
            load_id: Identyfikator odbiornika.

        Returns:
            Czas pracy w godzinach (zaokrąglony do 0.1h).
        """
        state = self._get_or_create_state(load_id)
        runtime = state.daily_runtime_hours

        # Dodaj bieżącą sesję jeśli odbiornik jest włączony
        if state.is_on and state.last_on_timestamp is not None:
            now = datetime.now()
            current_session = (now - state.last_on_timestamp).total_seconds() / 3600.0
            runtime += current_session

        return round(runtime, 1)

    def get_daily_runtime_at(self, load_id: str, at_time: datetime) -> float:
        """Oblicz dzienny czas pracy odbiornika na dany moment.

        Args:
            load_id: Identyfikator odbiornika.
            at_time: Moment, dla którego obliczamy runtime.

        Returns:
            Czas pracy w godzinach (zaokrąglony do 0.1h).
        """
        state = self._get_or_create_state(load_id)
        runtime = state.daily_runtime_hours

        # Dodaj bieżącą sesję jeśli odbiornik jest włączony
        if state.is_on and state.last_on_timestamp is not None:
            current_session = (at_time - state.last_on_timestamp).total_seconds() / 3600.0
            runtime += current_session

        return round(runtime, 1)

    def is_max_reached(self, load_id: str, max_hours: float) -> bool:
        """Sprawdź czy osiągnięto maksymalny dzienny czas pracy.

        Args:
            load_id: Identyfikator odbiornika.
            max_hours: Maksymalny dozwolony czas pracy (h).

        Returns:
            True jeśli czas pracy >= max_hours.
        """
        runtime = self.get_daily_runtime(load_id)
        return runtime >= max_hours

    def is_max_reached_at(self, load_id: str, max_hours: float, at_time: datetime) -> bool:
        """Sprawdź czy osiągnięto max czas pracy na dany moment.

        Args:
            load_id: Identyfikator odbiornika.
            max_hours: Maksymalny dozwolony czas pracy (h).
            at_time: Moment sprawdzenia.

        Returns:
            True jeśli czas pracy >= max_hours.
        """
        runtime = self.get_daily_runtime_at(load_id, at_time)
        return runtime >= max_hours

    def is_manual_override(self, load_id: str) -> bool:
        """Sprawdź czy odbiornik jest w trybie sterowania ręcznego.

        Args:
            load_id: Identyfikator odbiornika.

        Returns:
            True jeśli manual override jest aktywny.
        """
        state = self._get_or_create_state(load_id)
        return state.manual_override

    def set_manual_override(self, load_id: str, is_manual: bool) -> None:
        """Ustaw/wyczyść tryb sterowania ręcznego.

        Gdy użytkownik ręcznie włączy odbiornik, automatyka jest wstrzymana
        do momentu ręcznego wyłączenia lub końca dozwolonego okna czasowego.

        Args:
            load_id: Identyfikator odbiornika.
            is_manual: True = aktywuj override, False = wyczyść.
        """
        state = self._get_or_create_state(load_id)
        state.manual_override = is_manual
        if is_manual:
            _LOGGER.info(
                "Odbiornik %s: aktywowano sterowanie ręczne — automatyka wstrzymana",
                load_id,
            )
        else:
            _LOGGER.info(
                "Odbiornik %s: dezaktywowano sterowanie ręczne — automatyka wznowiona",
                load_id,
            )

    def reset_daily(self, load_id: str) -> None:
        """Resetuj dzienne liczniki o 00:00.

        Zeruje daily_runtime_hours i tracking_date.
        Nie zmienia stanu is_on ani manual_override.

        Args:
            load_id: Identyfikator odbiornika.
        """
        state = self._get_or_create_state(load_id)
        state.daily_runtime_hours = 0.0
        state.tracking_date = None
        state.needs_verification = False
        _LOGGER.debug("Odbiornik %s: reset dziennych liczników", load_id)

    def get_load_state(self, load_id: str) -> dict:
        """Zwróć pełny stan odbiornika.

        Args:
            load_id: Identyfikator odbiornika.

        Returns:
            Słownik z kluczami: is_on, daily_runtime, manual_override,
            last_change, planned_windows, needs_verification.
        """
        state = self._get_or_create_state(load_id)
        return {
            "is_on": state.is_on,
            "daily_runtime": state.daily_runtime_hours,
            "manual_override": state.manual_override,
            "last_change": state.last_change,
            "planned_windows": state.planned_windows,
            "needs_verification": state.needs_verification,
        }

    def set_planned_windows(self, load_id: str, windows: list[TimeWindow]) -> None:
        """Ustaw planowane okna pracy dla odbiornika.

        Args:
            load_id: Identyfikator odbiornika.
            windows: Lista zaplanowanych okien TimeWindow.
        """
        state = self._get_or_create_state(load_id)
        state.planned_windows = windows

    def get_sensor_data(self, load_id: str, min_daily_hours: float = 0.0) -> dict:
        """Zwróć dane do ekspozycji jako sensor HA.

        Args:
            load_id: Identyfikator odbiornika.
            min_daily_hours: Minimalny wymagany czas pracy (h).

        Returns:
            Słownik z danymi sensora: planned_windows, realized_runtime,
            remaining_required_runtime, status.
        """
        state = self._get_or_create_state(load_id)
        runtime = state.daily_runtime_hours

        # Oblicz pozostały wymagany czas
        remaining = max(0.0, min_daily_hours - runtime)
        remaining = round(remaining, 1)

        # Określ status
        if state.needs_verification:
            status = "wymagający_weryfikacji"
        elif state.manual_override:
            status = "ręczny"
        elif state.is_on:
            status = "włączony"
        else:
            status = "wyłączony"

        return {
            "planned_windows": [
                {"start": w.start.isoformat(), "end": w.end.isoformat(), "power_kw": w.power_kw}
                for w in state.planned_windows
            ],
            "realized_runtime": runtime,
            "remaining_required_runtime": remaining,
            "status": status,
        }

    def _check_day_rollover(self, state: LoadState, timestamp: datetime) -> None:
        """Sprawdź czy zmienił się dzień i resetuj liczniki jeśli tak.

        Args:
            state: Stan odbiornika.
            timestamp: Bieżący timestamp.
        """
        current_date = timestamp.date()
        if state.tracking_date is not None and state.tracking_date != current_date:
            # Nowy dzień — resetuj liczniki
            state.daily_runtime_hours = 0.0
            state.needs_verification = False
            _LOGGER.debug(
                "Odbiornik %s: automatyczny reset (nowy dzień %s)",
                state.load_id,
                current_date.isoformat(),
            )
        state.tracking_date = current_date


async def send_command_with_retry(
    hass,
    entity_id: str,
    service: str,
    retries: int = LOAD_RETRY_COUNT,
    interval: int = LOAD_RETRY_INTERVAL,
    confirm_timeout: int = LOAD_COMMAND_TIMEOUT,
) -> bool:
    """Wyślij komendę do odbiornika z logiką ponawiania.

    Jeśli odbiornik nie potwierdzi zmiany stanu w ciągu confirm_timeout sekund,
    ponów komendę do retries razy w odstępach interval sekund.

    Args:
        hass: Instancja Home Assistant.
        entity_id: Identyfikator encji HA (np. switch.bojler).
        service: Usługa do wywołania (np. "turn_on", "turn_off").
        retries: Maksymalna liczba ponowień (domyślnie 3).
        interval: Interwał między ponowieniami w sekundach (domyślnie 30).
        confirm_timeout: Czas oczekiwania na potwierdzenie w sekundach (domyślnie 60).

    Returns:
        True jeśli komenda została potwierdzona, False po wyczerpaniu prób.
    """
    domain = entity_id.split(".")[0] if "." in entity_id else "homeassistant"

    for attempt in range(1, retries + 1):
        _LOGGER.debug(
            "Wysyłanie komendy %s do %s (próba %d/%d)",
            service,
            entity_id,
            attempt,
            retries,
        )

        try:
            # Wywołaj usługę HA
            await hass.services.async_call(
                domain,
                service,
                {"entity_id": entity_id},
                blocking=False,
            )
        except Exception as err:
            _LOGGER.warning(
                "Błąd wysyłania komendy %s do %s (próba %d/%d): %s",
                service,
                entity_id,
                attempt,
                retries,
                err,
            )
            if attempt < retries:
                await asyncio.sleep(interval)
            continue

        # Czekaj na potwierdzenie zmiany stanu
        confirmed = await _wait_for_state_confirmation(
            hass, entity_id, service, confirm_timeout
        )

        if confirmed:
            _LOGGER.info(
                "Komenda %s do %s potwierdzona (próba %d/%d)",
                service,
                entity_id,
                attempt,
                retries,
            )
            return True

        _LOGGER.warning(
            "Brak potwierdzenia komendy %s do %s w ciągu %ds (próba %d/%d)",
            service,
            entity_id,
            confirm_timeout,
            attempt,
            retries,
        )

        if attempt < retries:
            await asyncio.sleep(interval)

    _LOGGER.error(
        "Komenda %s do %s nie potwierdzona po %d próbach — "
        "odbiornik wymaga weryfikacji",
        service,
        entity_id,
        retries,
    )
    return False


async def _wait_for_state_confirmation(
    hass,
    entity_id: str,
    service: str,
    timeout: int,
) -> bool:
    """Czekaj na potwierdzenie zmiany stanu encji.

    Args:
        hass: Instancja Home Assistant.
        entity_id: Identyfikator encji.
        service: Usługa (turn_on/turn_off) — określa oczekiwany stan.
        timeout: Maksymalny czas oczekiwania w sekundach.

    Returns:
        True jeśli stan został potwierdzony w czasie timeout.
    """
    expected_state = "on" if "on" in service else "off"
    check_interval = 5  # Sprawdzaj co 5 sekund
    elapsed = 0

    while elapsed < timeout:
        try:
            state = hass.states.get(entity_id)
            if state is not None and state.state == expected_state:
                return True
        except Exception:
            pass

        await asyncio.sleep(check_interval)
        elapsed += check_interval

    return False
