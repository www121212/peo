"""Walidator danych cenowych dla Polish Energy Optimizer (PEO).

Moduł odpowiedzialny za walidację zestawów danych cenowych pobranych z API RCE PSE.
Walidacja obejmuje sprawdzenie kompletności (24 wartości godzinowe), zakresu cenowego
(0–5000 PLN/MWh), poprawności typów danych i obecności wymaganych pól.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from .const import HOURS_PER_DAY, PRICE_MAX_PLN_MWH, PRICE_MIN_PLN_MWH
from .models import HourlyPrice

_LOGGER = logging.getLogger(__name__)


class PriceValidator:
    """Walidator danych cenowych z RCE PSE.

    Sprawdza kompletność i poprawność zestawu 24 cen godzinowych.
    W przypadku niepowodzenia walidacji odrzuca cały zestaw danych
    i loguje ostrzeżenie z opisem błędów.
    """

    def validate(self, prices: list[HourlyPrice]) -> bool:
        """Sprawdź poprawność zestawu danych cenowych.

        Walidacja obejmuje:
        - Dokładnie 24 wartości godzinowe (po jednej na każdą godzinę 0-23)
        - Wszystkie ceny w zakresie 0–5000 PLN/MWh
        - Brak duplikatów i luk w godzinach
        - Obecność i poprawność typów wymaganych pól

        Args:
            prices: Lista obiektów HourlyPrice do walidacji.

        Returns:
            True jeśli dane są poprawne, False w przeciwnym razie.
        """
        errors = self.get_validation_errors(prices)
        if errors:
            for error in errors:
                _LOGGER.warning("Walidacja cen: %s", error)
            return False
        return True

    def get_validation_errors(self, prices: list[HourlyPrice]) -> list[str]:
        """Zwróć listę błędów walidacji dla zestawu danych cenowych.

        Args:
            prices: Lista obiektów HourlyPrice do walidacji.

        Returns:
            Lista opisów błędów w języku polskim. Pusta lista oznacza brak błędów.
        """
        errors: list[str] = []

        # Sprawdź czy lista nie jest None lub nie jest listą
        if prices is None:
            errors.append("Dane cenowe są puste (None)")
            return errors

        if not isinstance(prices, list):
            errors.append(
                f"Dane cenowe muszą być listą, otrzymano: {type(prices).__name__}"
            )
            return errors

        # Sprawdź liczbę elementów — wymagane dokładnie 24
        if len(prices) != HOURS_PER_DAY:
            errors.append(
                f"Wymagane dokładnie {HOURS_PER_DAY} wartości godzinowych, "
                f"otrzymano: {len(prices)}"
            )

        # Walidacja poszczególnych elementów
        hours_seen: set[int] = set()

        for i, item in enumerate(prices):
            # Sprawdź typ obiektu
            if not isinstance(item, HourlyPrice):
                errors.append(
                    f"Element [{i}]: oczekiwano HourlyPrice, "
                    f"otrzymano {type(item).__name__}"
                )
                continue

            # Sprawdź wymagane pole: hour
            if not isinstance(item.hour, int):
                errors.append(
                    f"Element [{i}]: pole 'hour' musi być liczbą całkowitą, "
                    f"otrzymano {type(item.hour).__name__}"
                )
            elif item.hour < 0 or item.hour > 23:
                errors.append(
                    f"Element [{i}]: godzina {item.hour} poza zakresem 0–23"
                )
            else:
                if item.hour in hours_seen:
                    errors.append(
                        f"Element [{i}]: zduplikowana godzina {item.hour}"
                    )
                hours_seen.add(item.hour)

            # Sprawdź wymagane pole: price_pln_mwh
            if not isinstance(item.price_pln_mwh, Decimal):
                errors.append(
                    f"Element [{i}] (godz. {item.hour}): pole 'price_pln_mwh' "
                    f"musi być typu Decimal, otrzymano {type(item.price_pln_mwh).__name__}"
                )
            elif (
                item.price_pln_mwh < PRICE_MIN_PLN_MWH
                or item.price_pln_mwh > PRICE_MAX_PLN_MWH
            ):
                errors.append(
                    f"Element [{i}] (godz. {item.hour}): cena {item.price_pln_mwh} PLN/MWh "
                    f"poza dozwolonym zakresem {PRICE_MIN_PLN_MWH}–{PRICE_MAX_PLN_MWH} PLN/MWh"
                )

            # Sprawdź wymagane pole: price_pln_kwh
            if not isinstance(item.price_pln_kwh, Decimal):
                errors.append(
                    f"Element [{i}] (godz. {item.hour}): pole 'price_pln_kwh' "
                    f"musi być typu Decimal, otrzymano {type(item.price_pln_kwh).__name__}"
                )

            # Sprawdź wymagane pole: date
            if not isinstance(item.date, date):
                errors.append(
                    f"Element [{i}] (godz. {item.hour}): pole 'date' "
                    f"musi być typu date, otrzymano {type(item.date).__name__}"
                )

        # Sprawdź kompletność godzin (0-23) — tylko jeśli mamy 24 elementy
        if len(prices) == HOURS_PER_DAY and len(hours_seen) == HOURS_PER_DAY:
            expected_hours = set(range(HOURS_PER_DAY))
            missing_hours = expected_hours - hours_seen
            if missing_hours:
                errors.append(
                    f"Brakujące godziny: {sorted(missing_hours)}"
                )

        return errors
