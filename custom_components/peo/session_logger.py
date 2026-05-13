"""SessionLogger — rejestracja zakończonych sesji ładowania EV.

Odpowiada za:
- Rejestrowanie zakończonych sesji: czas trwania (min), energia (kWh, 2dp),
  koszt rzeczywisty (PLN, 2dp), koszt hipotetyczny (PLN, 2dp)
- Przechowywanie max 1000 sesji w pamięci trwałej (persistent storage)
- Udostępnianie historii sesji

Requirements: 10.3
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from .const import MAX_CHARGING_SESSIONS
from .models import ChargingSession

_LOGGER = logging.getLogger(__name__)


class SessionRecord:
    """Rekord zakończonej sesji ładowania — serializowalny."""

    def __init__(
        self,
        session_id: str,
        vehicle_id: str,
        start_time: datetime,
        end_time: datetime,
        duration_minutes: int,
        energy_kwh: Decimal,
        actual_cost_pln: Decimal,
        hypothetical_cost_pln: Decimal,
        is_manual: bool,
    ) -> None:
        """Inicjalizacja rekordu sesji.

        Args:
            session_id: Unikalny identyfikator sesji.
            vehicle_id: Identyfikator pojazdu.
            start_time: Czas rozpoczęcia.
            end_time: Czas zakończenia.
            duration_minutes: Czas trwania w minutach.
            energy_kwh: Energia pobrana (kWh, 2dp).
            actual_cost_pln: Koszt rzeczywisty (PLN, 2dp).
            hypothetical_cost_pln: Koszt hipotetyczny bez optymalizacji (PLN, 2dp).
            is_manual: Czy sesja manualna.
        """
        self.session_id = session_id
        self.vehicle_id = vehicle_id
        self.start_time = start_time
        self.end_time = end_time
        self.duration_minutes = duration_minutes
        self.energy_kwh = energy_kwh.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.actual_cost_pln = actual_cost_pln.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        self.hypothetical_cost_pln = hypothetical_cost_pln.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        self.is_manual = is_manual

    def to_dict(self) -> dict[str, Any]:
        """Serializuj rekord do słownika (do zapisu w Store).

        Returns:
            Słownik z danymi sesji.
        """
        return {
            "session_id": self.session_id,
            "vehicle_id": self.vehicle_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_minutes": self.duration_minutes,
            "energy_kwh": str(self.energy_kwh),
            "actual_cost_pln": str(self.actual_cost_pln),
            "hypothetical_cost_pln": str(self.hypothetical_cost_pln),
            "is_manual": self.is_manual,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionRecord":
        """Deserializuj rekord ze słownika.

        Args:
            data: Słownik z danymi sesji.

        Returns:
            Instancja SessionRecord.
        """
        return cls(
            session_id=data["session_id"],
            vehicle_id=data["vehicle_id"],
            start_time=datetime.fromisoformat(data["start_time"]),
            end_time=datetime.fromisoformat(data["end_time"]),
            duration_minutes=data["duration_minutes"],
            energy_kwh=Decimal(data["energy_kwh"]),
            actual_cost_pln=Decimal(data["actual_cost_pln"]),
            hypothetical_cost_pln=Decimal(data["hypothetical_cost_pln"]),
            is_manual=data["is_manual"],
        )


class SessionLogger:
    """Logger sesji ładowania EV z persistent storage.

    Przechowuje max MAX_CHARGING_SESSIONS (1000) ostatnich sesji.
    Najstarsze sesje są usuwane gdy limit zostanie przekroczony.
    """

    def __init__(self, max_sessions: int = MAX_CHARGING_SESSIONS) -> None:
        """Inicjalizacja SessionLogger.

        Args:
            max_sessions: Maksymalna liczba przechowywanych sesji (domyślnie 1000).
        """
        self._max_sessions = max_sessions
        self._sessions: deque[SessionRecord] = deque(maxlen=max_sessions)

    @property
    def session_count(self) -> int:
        """Liczba przechowywanych sesji."""
        return len(self._sessions)

    @property
    def sessions(self) -> list[SessionRecord]:
        """Lista wszystkich przechowywanych sesji (od najstarszej do najnowszej)."""
        return list(self._sessions)

    def log_session(
        self,
        session_id: str,
        vehicle_id: str,
        start_time: datetime,
        end_time: datetime,
        duration_minutes: int,
        energy_kwh: Decimal,
        actual_cost_pln: Decimal,
        hypothetical_cost_pln: Decimal,
        is_manual: bool = False,
    ) -> SessionRecord:
        """Zarejestruj zakończoną sesję ładowania.

        Jeśli liczba sesji osiągnie max_sessions, najstarsza sesja zostanie usunięta.

        Args:
            session_id: Unikalny identyfikator sesji.
            vehicle_id: Identyfikator pojazdu.
            start_time: Czas rozpoczęcia.
            end_time: Czas zakończenia.
            duration_minutes: Czas trwania w minutach.
            energy_kwh: Energia pobrana (kWh).
            actual_cost_pln: Koszt rzeczywisty (PLN).
            hypothetical_cost_pln: Koszt hipotetyczny bez optymalizacji (PLN).
            is_manual: Czy sesja manualna.

        Returns:
            Utworzony SessionRecord.
        """
        record = SessionRecord(
            session_id=session_id,
            vehicle_id=vehicle_id,
            start_time=start_time,
            end_time=end_time,
            duration_minutes=duration_minutes,
            energy_kwh=energy_kwh,
            actual_cost_pln=actual_cost_pln,
            hypothetical_cost_pln=hypothetical_cost_pln,
            is_manual=is_manual,
        )

        self._sessions.append(record)

        _LOGGER.info(
            "Sesja ładowania zarejestrowana: vehicle=%s, duration=%d min, "
            "energy=%.2f kWh, cost=%.2f PLN, hypothetical=%.2f PLN",
            vehicle_id,
            duration_minutes,
            float(record.energy_kwh),
            float(record.actual_cost_pln),
            float(record.hypothetical_cost_pln),
        )

        return record

    def log_charging_session(self, session: ChargingSession) -> SessionRecord:
        """Zarejestruj sesję z obiektu ChargingSession.

        Args:
            session: Obiekt ChargingSession z modelu.

        Returns:
            Utworzony SessionRecord.
        """
        return self.log_session(
            session_id=session.session_id,
            vehicle_id=session.vehicle_id,
            start_time=session.start_time,
            end_time=session.end_time if session.end_time else datetime.now(),
            duration_minutes=session.duration_minutes,
            energy_kwh=session.energy_kwh,
            actual_cost_pln=session.actual_cost_pln,
            hypothetical_cost_pln=session.hypothetical_cost_pln,
            is_manual=session.is_manual,
        )

    def get_sessions_for_vehicle(self, vehicle_id: str) -> list[SessionRecord]:
        """Pobierz sesje dla konkretnego pojazdu.

        Args:
            vehicle_id: Identyfikator pojazdu.

        Returns:
            Lista sesji dla danego pojazdu.
        """
        return [s for s in self._sessions if s.vehicle_id == vehicle_id]

    def get_latest_sessions(self, count: int = 10) -> list[SessionRecord]:
        """Pobierz N ostatnich sesji.

        Args:
            count: Liczba sesji do pobrania.

        Returns:
            Lista ostatnich sesji (od najnowszej).
        """
        sessions = list(self._sessions)
        return sessions[-count:][::-1] if sessions else []

    def to_storage_data(self) -> list[dict[str, Any]]:
        """Serializuj wszystkie sesje do formatu storage.

        Returns:
            Lista słowników z danymi sesji.
        """
        return [s.to_dict() for s in self._sessions]

    def load_from_storage(self, data: list[dict[str, Any]]) -> None:
        """Załaduj sesje z persistent storage.

        Args:
            data: Lista słowników z danymi sesji.
        """
        self._sessions.clear()
        for item in data[-self._max_sessions:]:
            try:
                record = SessionRecord.from_dict(item)
                self._sessions.append(record)
            except (KeyError, ValueError, TypeError) as err:
                _LOGGER.warning(
                    "Pominięto nieprawidłowy rekord sesji: %s", err
                )

    def clear(self) -> None:
        """Wyczyść wszystkie sesje."""
        self._sessions.clear()
