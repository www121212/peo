"""Ładowanie definicji taryf z plików JSON dla Polish Energy Optimizer (PEO)."""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path
from typing import Any

from .enums import OSDOperator, TariffType, TimeZoneName
from .models import TariffDefinition, TariffRates

_LOGGER = logging.getLogger(__name__)

# Path to the data directory relative to this module
_DATA_DIR = Path(__file__).parent / "data"


class TariffLoadError(Exception):
    """Błąd ładowania definicji taryfy."""


class TariffDefinitionLoader:
    """Ładowanie definicji taryf, stref OSD i domyślnych stawek z plików JSON.

    Dane są cache'owane po pierwszym załadowaniu — kolejne wywołania
    zwracają tę samą instancję bez ponownego odczytu pliku.
    """

    def __init__(self) -> None:
        """Inicjalizacja loadera z pustym cache."""
        self._tariff_cache: dict[TariffType, TariffDefinition] = {}
        self._osd_cache: dict[OSDOperator, dict[str, Any]] = {}
        self._rates_cache: dict[tuple[OSDOperator, TariffType], TariffRates] = {}
        self._rates_data: dict[str, Any] | None = None

    def load_tariff(self, tariff_type: TariffType) -> TariffDefinition:
        """Załaduj definicję taryfy z pliku JSON.

        Args:
            tariff_type: Typ taryfy do załadowania (np. TariffType.G12).

        Returns:
            TariffDefinition z typem, strefami i godzinami stref per OSD.

        Raises:
            TariffLoadError: Gdy plik nie istnieje lub dane są nieprawidłowe.
        """
        if tariff_type in self._tariff_cache:
            _LOGGER.debug("Zwracam definicję taryfy %s z cache", tariff_type)
            return self._tariff_cache[tariff_type]

        tariff_file = _DATA_DIR / "tariffs" / f"{tariff_type.value}.json"
        _LOGGER.debug("Ładuję definicję taryfy z %s", tariff_file)

        data = self._read_json(tariff_file, f"taryfa {tariff_type.value}")

        # Parse zones from tariff definition
        try:
            zones_raw = data["zones"]
            zones = [TimeZoneName(z) for z in zones_raw]
        except (KeyError, ValueError) as err:
            raise TariffLoadError(
                f"Nieprawidłowa definicja stref w taryfie {tariff_type.value}: {err}"
            ) from err

        # Build zone_hours from OSD files
        zone_hours: dict[OSDOperator, dict[TimeZoneName, list[tuple]]] = {}
        for operator in OSDOperator:
            osd_data = self.load_osd_zones(operator)
            osd_zones = osd_data.get("zones", {})
            tariff_key = tariff_type.value

            if tariff_key in osd_zones:
                tariff_zones_data = osd_zones[tariff_key]
                parsed_zones: dict[TimeZoneName, list[tuple]] = {}

                for zone_name_str, hours_data in tariff_zones_data.items():
                    # Skip special keys like "seasonal" and "weekend"
                    if zone_name_str in ("seasonal", "weekend"):
                        continue
                    try:
                        zone_name = TimeZoneName(zone_name_str)
                    except ValueError:
                        _LOGGER.debug(
                            "Pomijam nieznaną strefę '%s' dla %s/%s",
                            zone_name_str,
                            operator,
                            tariff_type,
                        )
                        continue

                    if isinstance(hours_data, list):
                        # Standard format: list of [start, end] pairs
                        parsed_zones[zone_name] = [
                            (pair[0], pair[1]) for pair in hours_data
                        ]
                    elif hours_data == "full_day":
                        parsed_zones[zone_name] = [("00:00", "24:00")]

                if parsed_zones:
                    zone_hours[operator] = parsed_zones

        tariff_def = TariffDefinition(
            tariff_type=tariff_type,
            zones=zones,
            zone_hours=zone_hours,
        )

        self._tariff_cache[tariff_type] = tariff_def
        _LOGGER.debug("Załadowano definicję taryfy %s", tariff_type)
        return tariff_def

    def load_osd_zones(self, operator: OSDOperator) -> dict[str, Any]:
        """Załaduj definicję stref OSD z pliku JSON.

        Args:
            operator: Operator OSD (np. OSDOperator.TAURON).

        Returns:
            Pełny słownik definicji stref OSD.

        Raises:
            TariffLoadError: Gdy plik nie istnieje lub dane są nieprawidłowe.
        """
        if operator in self._osd_cache:
            _LOGGER.debug("Zwracam definicję OSD %s z cache", operator)
            return self._osd_cache[operator]

        osd_file = _DATA_DIR / "osd" / f"{operator.value}.json"
        _LOGGER.debug("Ładuję definicję stref OSD z %s", osd_file)

        data = self._read_json(osd_file, f"OSD {operator.value}")

        # Validate basic structure
        if "operator" not in data or "zones" not in data:
            raise TariffLoadError(
                f"Nieprawidłowa struktura pliku OSD {operator.value}: "
                "brak pola 'operator' lub 'zones'"
            )

        self._osd_cache[operator] = data
        _LOGGER.debug("Załadowano definicję OSD %s", operator)
        return data

    def load_default_rates(
        self, operator: OSDOperator, tariff: TariffType
    ) -> TariffRates:
        """Załaduj domyślne stawki URE dla operatora i taryfy.

        Args:
            operator: Operator OSD.
            tariff: Typ taryfy.

        Returns:
            TariffRates z 6 składnikami kosztu (dla pierwszej strefy taryfy).

        Raises:
            TariffLoadError: Gdy plik nie istnieje, dane są nieprawidłowe,
                lub brak stawek dla podanej kombinacji operator/taryfa.
        """
        cache_key = (operator, tariff)
        if cache_key in self._rates_cache:
            _LOGGER.debug(
                "Zwracam domyślne stawki %s/%s z cache", operator, tariff
            )
            return self._rates_cache[cache_key]

        rates_data = self._load_rates_file()

        # Navigate to operator -> tariff
        operators = rates_data.get("operators", {})
        operator_data = operators.get(operator.value)
        if operator_data is None:
            raise TariffLoadError(
                f"Brak stawek dla operatora {operator.value} w pliku rates_2024.json"
            )

        tariff_data = operator_data.get(tariff.value)
        if tariff_data is None:
            raise TariffLoadError(
                f"Brak stawek dla taryfy {tariff.value} operatora {operator.value} "
                "w pliku rates_2024.json"
            )

        # Get the first zone's rates (primary zone for the tariff)
        # For multi-zone tariffs, use the first available zone
        first_zone_key = next(iter(tariff_data))
        zone_rates = tariff_data[first_zone_key]

        try:
            rates = TariffRates(
                energy_price=Decimal(zone_rates["energy_price"]),
                distribution_variable=Decimal(zone_rates["distribution_variable"]),
                transition_fee=Decimal(zone_rates["transition_fee"]),
                oze_fee=Decimal(zone_rates["oze_fee"]),
                capacity_fee=Decimal(zone_rates["capacity_fee"]),
                cogeneration_fee=Decimal(zone_rates["cogeneration_fee"]),
            )
        except (KeyError, ValueError) as err:
            raise TariffLoadError(
                f"Nieprawidłowe stawki dla {operator.value}/{tariff.value}: {err}"
            ) from err

        self._rates_cache[cache_key] = rates
        _LOGGER.debug(
            "Załadowano domyślne stawki dla %s/%s (strefa: %s)",
            operator,
            tariff,
            first_zone_key,
        )
        return rates

    def _load_rates_file(self) -> dict[str, Any]:
        """Załaduj plik rates_2024.json (z cache)."""
        if self._rates_data is not None:
            return self._rates_data

        rates_file = _DATA_DIR / "defaults" / "rates_2024.json"
        _LOGGER.debug("Ładuję domyślne stawki z %s", rates_file)
        self._rates_data = self._read_json(rates_file, "domyślne stawki URE")
        return self._rates_data

    @staticmethod
    def _read_json(file_path: Path, description: str) -> dict[str, Any]:
        """Odczytaj i sparsuj plik JSON.

        Args:
            file_path: Ścieżka do pliku JSON.
            description: Opis pliku (do komunikatów błędów).

        Returns:
            Sparsowany słownik JSON.

        Raises:
            TariffLoadError: Gdy plik nie istnieje lub JSON jest nieprawidłowy.
        """
        if not file_path.exists():
            raise TariffLoadError(
                f"Nie znaleziono pliku definicji ({description}): {file_path}"
            )

        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as err:
            raise TariffLoadError(
                f"Nieprawidłowy format JSON w pliku {description}: {err}"
            ) from err
        except OSError as err:
            raise TariffLoadError(
                f"Błąd odczytu pliku {description}: {err}"
            ) from err

        if not isinstance(data, dict):
            raise TariffLoadError(
                f"Plik {description} nie zawiera obiektu JSON (dict)"
            )

        return data
