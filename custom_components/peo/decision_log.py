"""DecisionLog — rejestracja decyzji optymalizacyjnych i powiadomienia o oszczędnościach.

Odpowiada za:
- Przechowywanie ostatnich 10 decyzji optymalizacyjnych jako atrybut diagnostyczny
- Każda decyzja: timestamp (ISO 8601), decision, reason, savings (PLN, 2dp)
- Generowanie powiadomienia gdy miesięczne oszczędności > 50 PLN
  (max jedno powiadomienie na miesiąc kalendarzowy)

Requirements: 10.5, 10.6, 10.8
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable, Optional

_LOGGER = logging.getLogger(__name__)

# Stałe
MAX_DECISIONS = 10
MONTHLY_SAVINGS_THRESHOLD = Decimal("50.00")


class DecisionEntry:
    """Pojedyncza decyzja optymalizacyjna."""

    def __init__(
        self,
        timestamp: datetime,
        decision: str,
        reason: str,
        savings_pln: Decimal,
    ) -> None:
        """Inicjalizacja wpisu decyzji.

        Args:
            timestamp: Czas decyzji (ISO 8601).
            decision: Opis decyzji.
            reason: Powód decyzji.
            savings_pln: Oszczędność (PLN, 2dp).
        """
        self.timestamp = timestamp
        self.decision = decision
        self.reason = reason
        self.savings_pln = savings_pln.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializuj do słownika.

        Returns:
            Słownik z polami: timestamp, decision, reason, savings_pln.
        """
        return {
            "timestamp": self.timestamp.isoformat(),
            "decision": self.decision,
            "reason": self.reason,
            "savings_pln": str(self.savings_pln),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DecisionEntry":
        """Deserializuj ze słownika.

        Args:
            data: Słownik z danymi decyzji.

        Returns:
            Instancja DecisionEntry.
        """
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            decision=data["decision"],
            reason=data["reason"],
            savings_pln=Decimal(data["savings_pln"]),
        )


class DecisionLog:
    """Log decyzji optymalizacyjnych z powiadomieniami o oszczędnościach.

    Przechowuje ostatnie 10 decyzji jako atrybut diagnostyczny.
    Generuje powiadomienie gdy miesięczne oszczędności > 50 PLN
    (max raz na miesiąc kalendarzowy).
    """

    def __init__(
        self,
        notify_callback: Optional[Callable[[str, str], Any]] = None,
        max_decisions: int = MAX_DECISIONS,
    ) -> None:
        """Inicjalizacja DecisionLog.

        Args:
            notify_callback: Callback do wysyłania powiadomień (title, message).
            max_decisions: Maksymalna liczba przechowywanych decyzji (domyślnie 10).
        """
        self._max_decisions = max_decisions
        self._decisions: deque[DecisionEntry] = deque(maxlen=max_decisions)
        self._notify_callback = notify_callback
        self._monthly_savings: Decimal = Decimal("0.00")
        self._notification_sent_month: Optional[int] = None
        self._tracking_month: Optional[int] = None

    @property
    def decisions(self) -> list[DecisionEntry]:
        """Lista ostatnich decyzji (od najstarszej do najnowszej)."""
        return list(self._decisions)

    @property
    def monthly_savings(self) -> Decimal:
        """Bieżące miesięczne oszczędności."""
        return self._monthly_savings

    def record_decision(
        self,
        timestamp: datetime,
        decision: str,
        reason: str,
        savings_pln: Decimal,
    ) -> DecisionEntry:
        """Zarejestruj decyzję optymalizacyjną.

        Dodaje decyzję do bufora (max 10). Sprawdza czy miesięczne
        oszczędności przekroczyły 50 PLN i generuje powiadomienie.

        Args:
            timestamp: Czas decyzji.
            decision: Opis decyzji.
            reason: Powód decyzji.
            savings_pln: Oszczędność z tej decyzji (PLN).

        Returns:
            Utworzony DecisionEntry.
        """
        # Sprawdź reset miesięczny
        self._check_month_reset(timestamp)

        entry = DecisionEntry(
            timestamp=timestamp,
            decision=decision,
            reason=reason,
            savings_pln=savings_pln,
        )

        self._decisions.append(entry)

        # Akumuluj oszczędności miesięczne
        self._monthly_savings += entry.savings_pln

        _LOGGER.debug(
            "Decyzja zarejestrowana: %s (oszczędność: %.2f PLN, "
            "miesięczna suma: %.2f PLN)",
            decision,
            float(entry.savings_pln),
            float(self._monthly_savings),
        )

        # Sprawdź próg powiadomienia
        self._check_savings_notification(timestamp)

        return entry

    def get_diagnostic_attribute(self) -> list[dict[str, Any]]:
        """Zwróć atrybut diagnostyczny z ostatnimi 10 decyzjami.

        Returns:
            Lista słowników z decyzjami (od najnowszej do najstarszej).
        """
        return [d.to_dict() for d in reversed(self._decisions)]

    def _check_month_reset(self, timestamp: datetime) -> None:
        """Sprawdź czy zmienił się miesiąc i resetuj liczniki.

        Args:
            timestamp: Bieżący czas.
        """
        current_month = timestamp.month

        if self._tracking_month is None:
            self._tracking_month = current_month
            return

        if self._tracking_month != current_month:
            # Nowy miesiąc — reset oszczędności i flagi powiadomienia
            self._monthly_savings = Decimal("0.00")
            self._notification_sent_month = None
            self._tracking_month = current_month
            _LOGGER.debug(
                "Reset miesięcznych oszczędności (nowy miesiąc: %d)", current_month
            )

    def _check_savings_notification(self, timestamp: datetime) -> None:
        """Sprawdź czy wysłać powiadomienie o oszczędnościach > 50 PLN.

        Powiadomienie jest wysyłane max raz na miesiąc kalendarzowy.

        Args:
            timestamp: Bieżący czas.
        """
        current_month = timestamp.month

        # Sprawdź czy już wysłano w tym miesiącu
        if self._notification_sent_month == current_month:
            return

        # Sprawdź próg
        if self._monthly_savings > MONTHLY_SAVINGS_THRESHOLD:
            if self._notify_callback is not None:
                self._notify_callback(
                    "PEO: Oszczędności przekroczyły 50 PLN",
                    f"Miesięczne oszczędności z optymalizacji energii wynoszą "
                    f"{self._monthly_savings:.2f} PLN. Gratulacje!",
                )
            self._notification_sent_month = current_month
            _LOGGER.info(
                "Powiadomienie o oszczędnościach: %.2f PLN (miesiąc %d)",
                float(self._monthly_savings),
                current_month,
            )

    def to_storage_data(self) -> dict[str, Any]:
        """Serializuj stan do formatu storage.

        Returns:
            Słownik z danymi do zapisu.
        """
        return {
            "decisions": [d.to_dict() for d in self._decisions],
            "monthly_savings": str(self._monthly_savings),
            "notification_sent_month": self._notification_sent_month,
            "tracking_month": self._tracking_month,
        }

    def load_from_storage(self, data: dict[str, Any]) -> None:
        """Załaduj stan z persistent storage.

        Args:
            data: Słownik z danymi.
        """
        self._decisions.clear()

        decisions_data = data.get("decisions", [])
        for item in decisions_data[-self._max_decisions:]:
            try:
                entry = DecisionEntry.from_dict(item)
                self._decisions.append(entry)
            except (KeyError, ValueError, TypeError) as err:
                _LOGGER.warning(
                    "Pominięto nieprawidłowy wpis decyzji: %s", err
                )

        self._monthly_savings = Decimal(data.get("monthly_savings", "0.00"))
        self._notification_sent_month = data.get("notification_sent_month")
        self._tracking_month = data.get("tracking_month")

    def clear(self) -> None:
        """Wyczyść log decyzji."""
        self._decisions.clear()
        self._monthly_savings = Decimal("0.00")
        self._notification_sent_month = None
        self._tracking_month = None
