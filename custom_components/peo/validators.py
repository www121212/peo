"""Walidatory danych wejściowych dla Polish Energy Optimizer (PEO)."""

from decimal import Decimal, InvalidOperation

from .const import (
    POWER_MAX_KW,
    POWER_MIN_KW,
    PRICE_MAX_PLN_MWH,
    PRICE_MIN_PLN_MWH,
    RATE_MAX_PLN_KWH,
    RATE_MIN_PLN_KWH,
    SOC_MAX,
    SOC_MIN,
)


class InputValidator:
    """Klasa narzędziowa do walidacji danych wejściowych.

    Wszystkie metody są statyczne i zgłaszają ValueError
    z komunikatami w języku polskim w przypadku nieprawidłowych danych.
    """

    @staticmethod
    def validate_price(value) -> Decimal:
        """Waliduj cenę energii w zakresie 0–5000 PLN/MWh.

        Args:
            value: Wartość ceny do walidacji (konwertowana na Decimal).

        Returns:
            Decimal: Zwalidowana cena jako Decimal.

        Raises:
            ValueError: Gdy wartość jest nieprawidłowa lub poza zakresem.
        """
        if value is None:
            raise ValueError(
                "Cena energii jest wymagana — wartość nie może być pusta"
            )

        try:
            price = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as err:
            raise ValueError(
                f"Nieprawidłowa wartość ceny energii: '{value}' "
                f"— wymagana wartość liczbowa"
            ) from err

        if price < PRICE_MIN_PLN_MWH or price > PRICE_MAX_PLN_MWH:
            raise ValueError(
                f"Cena energii {price} PLN/MWh jest poza dozwolonym zakresem "
                f"{PRICE_MIN_PLN_MWH}–{PRICE_MAX_PLN_MWH} PLN/MWh"
            )

        return price

    @staticmethod
    def validate_soc(value) -> int:
        """Waliduj poziom naładowania baterii (SoC) w zakresie 0–100%.

        Args:
            value: Wartość SoC do walidacji (konwertowana na int).

        Returns:
            int: Zwalidowany poziom SoC jako liczba całkowita.

        Raises:
            ValueError: Gdy wartość jest nieprawidłowa lub poza zakresem.
        """
        if value is None:
            raise ValueError(
                "Poziom naładowania (SoC) jest wymagany — wartość nie może być pusta"
            )

        try:
            soc = int(value)
        except (TypeError, ValueError) as err:
            raise ValueError(
                f"Nieprawidłowa wartość SoC: '{value}' "
                f"— wymagana liczba całkowita"
            ) from err

        if soc < SOC_MIN or soc > SOC_MAX:
            raise ValueError(
                f"Poziom naładowania (SoC) {soc}% jest poza dozwolonym zakresem "
                f"{SOC_MIN}–{SOC_MAX}%"
            )

        return soc

    @staticmethod
    def validate_power(value) -> float:
        """Waliduj moc w zakresie 0–100 kW.

        Args:
            value: Wartość mocy do walidacji (konwertowana na float).

        Returns:
            float: Zwalidowana moc jako float.

        Raises:
            ValueError: Gdy wartość jest nieprawidłowa lub poza zakresem.
        """
        if value is None:
            raise ValueError(
                "Wartość mocy jest wymagana — wartość nie może być pusta"
            )

        try:
            power = float(value)
        except (TypeError, ValueError) as err:
            raise ValueError(
                f"Nieprawidłowa wartość mocy: '{value}' "
                f"— wymagana wartość liczbowa"
            ) from err

        if power < POWER_MIN_KW or power > POWER_MAX_KW:
            raise ValueError(
                f"Moc {power} kW jest poza dozwolonym zakresem "
                f"{POWER_MIN_KW}–{POWER_MAX_KW} kW"
            )

        return power

    @staticmethod
    def validate_rate(value) -> Decimal:
        """Waliduj stawkę taryfową w zakresie 0–5 PLN/kWh.

        Args:
            value: Wartość stawki do walidacji (konwertowana na Decimal).

        Returns:
            Decimal: Zwalidowana stawka jako Decimal.

        Raises:
            ValueError: Gdy wartość jest nieprawidłowa lub poza zakresem.
        """
        if value is None:
            raise ValueError(
                "Stawka taryfowa jest wymagana — wartość nie może być pusta"
            )

        try:
            rate = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as err:
            raise ValueError(
                f"Nieprawidłowa wartość stawki taryfowej: '{value}' "
                f"— wymagana wartość liczbowa"
            ) from err

        if rate < RATE_MIN_PLN_KWH or rate > RATE_MAX_PLN_KWH:
            raise ValueError(
                f"Stawka taryfowa {rate} PLN/kWh jest poza dozwolonym zakresem "
                f"{RATE_MIN_PLN_KWH}–{RATE_MAX_PLN_KWH} PLN/kWh"
            )

        return rate
