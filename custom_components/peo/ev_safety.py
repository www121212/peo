"""Moduł bezpieczeństwa EV dla Polish Energy Optimizer (PEO).

Implementuje:
- EVSafetyMonitor: nadzór bezpieczeństwa ładowania EV
  - Respektowanie limitów mocy ładowarki (max prąd A, max moc kW)
  - Pauza ładowania przy przekroczeniu progu temperatury baterii
  - Wznowienie ładowania po spadku temperatury poniżej progu
  - Kontynuacja ładowania bez sprawdzania temperatury gdy brak danych (req 9.9)
  - Obsługa utraty komunikacji (60s timeout): powiadomienie + oznaczenie sesji

Requirements: 9.3, 9.4, 9.6, 9.9
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Optional

from .charger_adapters import ChargerAdapter, ChargerStatus
from .const import CHARGER_COMM_TIMEOUT

_LOGGER = logging.getLogger(__name__)

# Default battery temperature safety threshold (°C)
DEFAULT_BATTERY_TEMP_THRESHOLD: float = 45.0

# Voltage assumptions for current-to-power conversion
SINGLE_PHASE_VOLTAGE: float = 230.0
THREE_PHASE_VOLTAGE: float = 400.0

# Power threshold to distinguish single-phase vs three-phase chargers (kW)
THREE_PHASE_POWER_THRESHOLD: float = 7.4


class EVSafetyMonitor:
    """Monitor bezpieczeństwa ładowania EV.

    Odpowiedzialności:
    - Ograniczanie mocy do limitów ładowarki (nigdy nie przekraczaj max_power/max_current)
    - Monitorowanie temperatury baterii i pauza/wznowienie ładowania
    - Wykrywanie utraty komunikacji z ładowarką (60s timeout)
    - Powiadamianie użytkownika o problemach bezpieczeństwa
    """

    def __init__(
        self,
        notify_user: Callable[[str, str], Any],
        mark_session_verification: Callable[[str], Any],
        temp_threshold: float = DEFAULT_BATTERY_TEMP_THRESHOLD,
    ) -> None:
        """Inicjalizacja EVSafetyMonitor.

        Args:
            notify_user: Callback do powiadomienia użytkownika (title, message).
            mark_session_verification: Callback do oznaczenia sesji jako
                "wymagająca weryfikacji" (vehicle_id).
            temp_threshold: Próg temperatury baterii (°C) powyżej którego
                ładowanie jest wstrzymywane.
        """
        self._notify_user = notify_user
        self._mark_session_verification = mark_session_verification
        self._temp_threshold = temp_threshold
        self._last_comm_times: dict[str, datetime] = {}
        self._temp_paused: dict[str, bool] = {}

    @property
    def temp_threshold(self) -> float:
        """Próg temperatury bezpieczeństwa (°C)."""
        return self._temp_threshold

    @property
    def last_comm_times(self) -> dict[str, datetime]:
        """Ostatnie czasy komunikacji per vehicle_id."""
        return self._last_comm_times

    @property
    def temp_paused_vehicles(self) -> dict[str, bool]:
        """Pojazdy wstrzymane z powodu temperatury."""
        return self._temp_paused

    def record_communication(self, vehicle_id: str, timestamp: Optional[datetime] = None) -> None:
        """Zarejestruj udaną komunikację z ładowarką.

        Args:
            vehicle_id: ID pojazdu.
            timestamp: Czas komunikacji (domyślnie datetime.now()).
        """
        self._last_comm_times[vehicle_id] = timestamp or datetime.now()

    def check_power_limits(
        self,
        max_power_kw: float,
        max_current_a: float,
        requested_power_kw: float,
    ) -> float:
        """Ogranicz żądaną moc do limitów ładowarki.

        Nigdy nie przekracza max_power_kw ani mocy wynikającej z max_current_a.
        Konwersja prądu na moc: P = I * V, gdzie V zależy od typu ładowarki
        (230V jednofazowa lub 400V trójfazowa, rozpoznawane po max_power_kw).

        Args:
            max_power_kw: Maksymalna moc ładowarki (kW).
            max_current_a: Maksymalny prąd ładowarki (A).
            requested_power_kw: Żądana moc ładowania (kW).

        Returns:
            Bezpieczna moc ładowania (kW), nie przekraczająca żadnego limitu.

        Requirements: 9.3
        """
        # Determine voltage based on charger power capacity
        if max_power_kw > THREE_PHASE_POWER_THRESHOLD:
            voltage = THREE_PHASE_VOLTAGE
        else:
            voltage = SINGLE_PHASE_VOLTAGE

        # Calculate power limit from current: P = I * V / 1000 (to kW)
        current_power_limit_kw = (max_current_a * voltage) / 1000.0

        # Clamp to the minimum of all limits
        safe_power = min(requested_power_kw, max_power_kw, current_power_limit_kw)

        # Ensure non-negative
        safe_power = max(safe_power, 0.0)

        if safe_power < requested_power_kw:
            _LOGGER.debug(
                "Moc ograniczona: żądane=%.2f kW, limit mocy=%.2f kW, "
                "limit prądu=%.2f kW (%.1f A × %.0f V), wynik=%.2f kW",
                requested_power_kw,
                max_power_kw,
                current_power_limit_kw,
                max_current_a,
                voltage,
                safe_power,
            )

        return safe_power

    def is_temperature_safe(self, status: ChargerStatus) -> bool:
        """Sprawdź czy temperatura baterii jest bezpieczna.

        Jeśli ładowarka nie udostępnia informacji o temperaturze (None),
        zwraca True — ładowanie kontynuowane bez sprawdzania temperatury (req 9.9).

        Args:
            status: Status ładowarki z opcjonalną temperaturą.

        Returns:
            True jeśli temperatura jest bezpieczna lub niedostępna.

        Requirements: 9.4, 9.9
        """
        if status.temperature is None:
            return True
        return status.temperature < self._temp_threshold

    def check_temperature(
        self,
        vehicle_id: str,
        status: ChargerStatus,
        charger_adapter: ChargerAdapter,
    ) -> bool:
        """Sprawdź temperaturę i zarządzaj pauzą/wznowieniem ładowania.

        - Jeśli temperatura przekracza próg: pauza ładowania, log WARNING
        - Jeśli temperatura spadła poniżej progu: wznowienie, log INFO
        - Jeśli brak danych temperatury (None): kontynuuj normalnie (req 9.9)

        Args:
            vehicle_id: ID pojazdu.
            status: Aktualny status ładowarki.
            charger_adapter: Adapter ładowarki (do ewentualnego sterowania).

        Returns:
            True jeśli ładowanie może kontynuować, False jeśli wstrzymane.

        Requirements: 9.4, 9.9
        """
        if status.temperature is None:
            # Brak danych temperatury — kontynuuj normalnie (req 9.9)
            return True

        is_safe = status.temperature < self._temp_threshold
        was_paused = self._temp_paused.get(vehicle_id, False)

        if not is_safe and not was_paused:
            # Temperatura przekroczyła próg — pauza
            self._temp_paused[vehicle_id] = True
            _LOGGER.warning(
                "Temperatura baterii EV przekroczyła próg bezpieczeństwa: "
                "vehicle=%s, temp=%.1f°C, próg=%.1f°C — wstrzymuję ładowanie",
                vehicle_id,
                status.temperature,
                self._temp_threshold,
            )
            return False

        if not is_safe and was_paused:
            # Nadal za gorąco — pozostaje wstrzymane
            return False

        if is_safe and was_paused:
            # Temperatura spadła poniżej progu — wznowienie
            self._temp_paused[vehicle_id] = False
            _LOGGER.info(
                "Temperatura baterii EV spadła poniżej progu: "
                "vehicle=%s, temp=%.1f°C, próg=%.1f°C — wznawiam ładowanie",
                vehicle_id,
                status.temperature,
                self._temp_threshold,
            )
            return True

        # Temperatura bezpieczna i nie było pauzy
        return True

    def handle_communication_loss(
        self,
        vehicle_id: str,
        now: Optional[datetime] = None,
    ) -> bool:
        """Wykryj utratę komunikacji z ładowarką (60s timeout).

        Jeśli od ostatniej udanej komunikacji minęło >CHARGER_COMM_TIMEOUT (60s):
        - Powiadom użytkownika via HA notification
        - Oznacz sesję jako "wymagająca weryfikacji"
        - Zwróć True (utrata wykryta)

        Args:
            vehicle_id: ID pojazdu.
            now: Bieżący czas (domyślnie datetime.now()).

        Returns:
            True jeśli wykryto utratę komunikacji, False w przeciwnym razie.

        Requirements: 9.6
        """
        now = now or datetime.now()
        last_comm = self._last_comm_times.get(vehicle_id)

        if last_comm is None:
            # Brak zarejestrowanej komunikacji — nie możemy ocenić
            return False

        elapsed = (now - last_comm).total_seconds()

        if elapsed > CHARGER_COMM_TIMEOUT:
            _LOGGER.warning(
                "Utrata komunikacji z ładowarką: vehicle=%s, "
                "ostatnia komunikacja=%.0f s temu (próg=%d s)",
                vehicle_id,
                elapsed,
                CHARGER_COMM_TIMEOUT,
            )
            self._notify_user(
                "PEO: Utrata komunikacji z ładowarką",
                f"Ładowarka pojazdu {vehicle_id} nie odpowiada od "
                f"{int(elapsed)} sekund. Sesja ładowania została oznaczona "
                f"jako wymagająca weryfikacji.",
            )
            self._mark_session_verification(vehicle_id)
            return True

        return False

    def get_safe_power(
        self,
        max_power_kw: float,
        max_current_a: float,
        requested_power_kw: float,
        grid_available_kw: Optional[float] = None,
    ) -> float:
        """Oblicz bezpieczną moc ładowania uwzględniając wszystkie limity.

        Bierze pod uwagę:
        - Limit mocy ładowarki (max_power_kw)
        - Limit prądu ładowarki (max_current_a, konwertowany na moc)
        - Dostępną moc sieci (grid_available_kw)

        Args:
            max_power_kw: Maksymalna moc ładowarki (kW).
            max_current_a: Maksymalny prąd ładowarki (A).
            requested_power_kw: Żądana moc ładowania (kW).
            grid_available_kw: Dostępna moc z sieci (kW), opcjonalnie.

        Returns:
            Bezpieczna moc ładowania (kW).

        Requirements: 9.3
        """
        safe_power = self.check_power_limits(
            max_power_kw=max_power_kw,
            max_current_a=max_current_a,
            requested_power_kw=requested_power_kw,
        )

        if grid_available_kw is not None:
            safe_power = min(safe_power, max(grid_available_kw, 0.0))

        return safe_power

    def reset_vehicle(self, vehicle_id: str) -> None:
        """Wyczyść stan monitoringu dla pojazdu.

        Args:
            vehicle_id: ID pojazdu.
        """
        self._last_comm_times.pop(vehicle_id, None)
        self._temp_paused.pop(vehicle_id, None)
