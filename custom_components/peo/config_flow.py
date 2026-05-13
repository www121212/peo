"""PEO Config Flow — wielokrokowa konfiguracja integracji.

Implementuje Config Flow z krokami:
1. Wybór modułów (co najmniej jeden wymagany)
2. Konfiguracja taryfy (operator OSD, typ taryfy, stawki)
3. Konfiguracja EV (opcjonalna — pojazdy, ładowarki)
4. Konfiguracja odbiorników (opcjonalna — do 10 odbiorników odraczalnych)
5. Konfiguracja PV (opcjonalna — dostawca prognoz, bateria)

Wszystkie etykiety, opisy i komunikaty błędów w języku polskim.
Tryb szybkiej konfiguracji z domyślnymi wartościami (G12 + EV + bojler CWU).
Zachowanie częściowej konfiguracji przy przerwaniu (do restartu HA).

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.7, 7.8, 7.9
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant import config_entries
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_MODULES_ENABLED,
    CONF_TARIFF_TYPE,
    CONF_OSD_OPERATOR,
    CONF_SOLAR_PROVIDER,
    CONF_SOLAR_API_KEY,
    CONF_CHARGERS,
    CONF_TARIFF_RATES,
    CONF_EV_VEHICLES,
    CONF_LOADS,
    CONF_GRID_LIMIT_KW,
    CONF_PV,
    MODULE_PRICES,
    MODULE_TARIFF,
    MODULE_EV,
    MODULE_LOADS,
    MODULE_PV,
    MODULE_ANALYZER,
    MAX_LOADS,
    POWER_MIN_KW,
    POWER_MAX_KW,
    RATE_MIN_PLN_KWH,
    RATE_MAX_PLN_KWH,
    SOC_MIN,
    SOC_MAX,
)
from .enums import TariffType, OSDOperator, SolarProvider, ChargingStrategy
from .validators import InputValidator

_LOGGER = logging.getLogger(__name__)

# Maximum deferrable loads in config flow (requirement 7.5)
MAX_CONFIG_LOADS = 10

# Default rates for quick setup (G12 Tauron)
DEFAULT_RATES = {
    "energy_price": "0.4500",
    "distribution_variable": "0.2100",
    "transition_fee": "0.0009",
    "oze_fee": "0.0029",
    "capacity_fee": "0.0688",
    "cogeneration_fee": "0.0027",
}

# Default quick setup load (bojler CWU)
DEFAULT_LOAD_CWU = {
    "id": "load_cwu",
    "name": "Bojler CWU",
    "entity_id": "switch.bojler",
    "threshold_on": "0.35",
    "threshold_off": "0.55",
    "min_hours": 2.0,
    "max_hours": 6.0,
    "allowed_start": "22:00",
    "allowed_end": "06:00",
    "priority": 1,
    "power_w": 2000,
    "failsafe": True,
}


# --- Available tariffs per OSD operator ---
TARIFFS_PER_OSD: dict[str, list[str]] = {
    OSDOperator.TAURON: [t.value for t in TariffType],
    OSDOperator.PGE: [t.value for t in TariffType],
    OSDOperator.ENEA: [t.value for t in TariffType],
    OSDOperator.ENERGA: [t.value for t in TariffType],
    OSDOperator.INNOGY_STOEN: [t.value for t in TariffType],
}


def _get_available_tariffs(operator: str) -> list[str]:
    """Pobierz dostępne taryfy dla operatora OSD."""
    return TARIFFS_PER_OSD.get(operator, [t.value for t in TariffType])


def _validate_modules(modules: list[str]) -> Optional[str]:
    """Waliduj wybór modułów — co najmniej jeden wymagany.

    Returns:
        Komunikat błędu w języku polskim lub None jeśli poprawne.
    """
    if not modules:
        return "Musisz wybrać co najmniej jeden moduł"
    valid_modules = {
        MODULE_PRICES, MODULE_TARIFF, MODULE_EV,
        MODULE_LOADS, MODULE_PV, MODULE_ANALYZER,
    }
    for m in modules:
        if m not in valid_modules:
            return f"Nieznany moduł: {m}"
    return None


def _validate_tariff_config(user_input: dict[str, Any]) -> dict[str, str]:
    """Waliduj konfigurację taryfy.

    Returns:
        Słownik błędów {pole: komunikat} lub pusty słownik.
    """
    errors: dict[str, str] = {}

    osd = user_input.get("osd_operator")
    if not osd:
        errors["osd_operator"] = "Operator OSD jest wymagany"
    elif osd not in [o.value for o in OSDOperator]:
        errors["osd_operator"] = f"Nieznany operator OSD: {osd}"

    tariff = user_input.get("tariff_type")
    if not tariff:
        errors["tariff_type"] = "Typ taryfy jest wymagany"
    elif tariff not in [t.value for t in TariffType]:
        errors["tariff_type"] = f"Nieznany typ taryfy: {tariff}"

    # Validate rates
    rate_fields = [
        "energy_price", "distribution_variable", "transition_fee",
        "oze_fee", "capacity_fee", "cogeneration_fee",
    ]
    for field in rate_fields:
        value = user_input.get(field)
        if value is not None and value != "":
            try:
                InputValidator.validate_rate(value)
            except ValueError as e:
                errors[field] = str(e)

    return errors


def _validate_ev_config(user_input: dict[str, Any]) -> dict[str, str]:
    """Waliduj konfigurację EV.

    Returns:
        Słownik błędów {pole: komunikat} lub pusty słownik.
    """
    errors: dict[str, str] = {}

    # Validate vehicle name
    vehicle_name = user_input.get("vehicle_name")
    if not vehicle_name:
        errors["vehicle_name"] = "Nazwa pojazdu jest wymagana"

    # Validate battery capacity
    battery_kwh = user_input.get("battery_capacity_kwh")
    if battery_kwh is not None:
        try:
            val = float(battery_kwh)
            if val <= 0 or val > 200:
                errors["battery_capacity_kwh"] = (
                    "Pojemność baterii musi być w zakresie 0.1–200 kWh"
                )
        except (TypeError, ValueError):
            errors["battery_capacity_kwh"] = (
                "Nieprawidłowa wartość pojemności baterii"
            )

    # Validate max charging power
    max_power = user_input.get("max_charging_power_kw")
    if max_power is not None:
        try:
            InputValidator.validate_power(max_power)
        except ValueError as e:
            errors["max_charging_power_kw"] = str(e)

    # Validate target SoC
    target_soc = user_input.get("target_soc")
    if target_soc is not None:
        try:
            soc = InputValidator.validate_soc(target_soc)
            if soc < 10:
                errors["target_soc"] = (
                    "Docelowy SoC musi być w zakresie 10–100%"
                )
        except ValueError as e:
            errors["target_soc"] = str(e)

    # Validate SoC entity
    soc_entity = user_input.get("soc_entity_id")
    if not soc_entity:
        errors["soc_entity_id"] = "Encja SoC pojazdu jest wymagana"

    return errors


def _validate_load_config(user_input: dict[str, Any]) -> dict[str, str]:
    """Waliduj konfigurację odbiornika odraczalnego.

    Returns:
        Słownik błędów {pole: komunikat} lub pusty słownik.
    """
    errors: dict[str, str] = {}

    name = user_input.get("load_name")
    if not name:
        errors["load_name"] = "Nazwa odbiornika jest wymagana"

    entity_id = user_input.get("entity_id")
    if not entity_id:
        errors["entity_id"] = "Encja Home Assistant jest wymagana"

    # Validate thresholds
    threshold_on = user_input.get("threshold_on")
    if threshold_on is not None:
        try:
            InputValidator.validate_rate(threshold_on)
        except ValueError as e:
            errors["threshold_on"] = str(e)

    threshold_off = user_input.get("threshold_off")
    if threshold_off is not None:
        try:
            InputValidator.validate_rate(threshold_off)
        except ValueError as e:
            errors["threshold_off"] = str(e)

    # Validate min/max hours
    min_hours = user_input.get("min_daily_hours")
    if min_hours is not None:
        try:
            val = float(min_hours)
            if val < 0.5 or val > 24:
                errors["min_daily_hours"] = (
                    "Minimalna dzienna praca musi być w zakresie 0.5–24 godzin"
                )
        except (TypeError, ValueError):
            errors["min_daily_hours"] = "Nieprawidłowa wartość minimalnej pracy"

    max_hours = user_input.get("max_daily_hours")
    if max_hours is not None:
        try:
            val = float(max_hours)
            if val < 0.5 or val > 24:
                errors["max_daily_hours"] = (
                    "Maksymalna dzienna praca musi być w zakresie 0.5–24 godzin"
                )
        except (TypeError, ValueError):
            errors["max_daily_hours"] = "Nieprawidłowa wartość maksymalnej pracy"

    # Validate power
    power_w = user_input.get("power_w")
    if power_w is not None:
        try:
            val = int(power_w)
            if val <= 0 or val > 100000:
                errors["power_w"] = (
                    "Pobór mocy musi być w zakresie 1–100000 W"
                )
        except (TypeError, ValueError):
            errors["power_w"] = "Nieprawidłowa wartość poboru mocy"

    return errors


def _validate_pv_config(user_input: dict[str, Any]) -> dict[str, str]:
    """Waliduj konfigurację PV.

    Returns:
        Słownik błędów {pole: komunikat} lub pusty słownik.
    """
    errors: dict[str, str] = {}

    provider = user_input.get("solar_provider")
    if not provider:
        errors["solar_provider"] = "Dostawca prognoz solarnych jest wymagany"
    elif provider not in [p.value for p in SolarProvider]:
        errors["solar_provider"] = f"Nieznany dostawca: {provider}"

    api_key = user_input.get("solar_api_key")
    if not api_key:
        errors["solar_api_key"] = "Klucz API jest wymagany"

    # Validate battery capacity if provided
    battery_kwh = user_input.get("battery_capacity_kwh")
    if battery_kwh is not None and battery_kwh != "":
        try:
            val = float(battery_kwh)
            if val < 0 or val > 500:
                errors["battery_capacity_kwh"] = (
                    "Pojemność baterii musi być w zakresie 0–500 kWh"
                )
        except (TypeError, ValueError):
            errors["battery_capacity_kwh"] = (
                "Nieprawidłowa wartość pojemności baterii"
            )

    # Validate min SoC
    min_soc = user_input.get("min_soc_percent")
    if min_soc is not None and min_soc != "":
        try:
            val = int(min_soc)
            if val < 5 or val > 30:
                errors["min_soc_percent"] = (
                    "Minimalny SoC bezpieczeństwa musi być w zakresie 5–30%"
                )
        except (TypeError, ValueError):
            errors["min_soc_percent"] = "Nieprawidłowa wartość minimalnego SoC"

    return errors



class PEOConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Multi-step Config Flow dla Polish Energy Optimizer.

    Kroki:
    1. async_step_user — wybór modułów
    2. async_step_tariff — konfiguracja taryfy i OSD
    3. async_step_ev — konfiguracja EV (opcjonalna)
    4. async_step_loads — konfiguracja odbiorników (opcjonalna)
    5. async_step_pv — konfiguracja PV (opcjonalna)

    Tryb szybkiej konfiguracji: async_step_quick_setup
    """

    VERSION = 1

    def __init__(self) -> None:
        """Inicjalizacja Config Flow."""
        self._data: dict[str, Any] = {}
        self._options: dict[str, Any] = {}
        self._modules: list[str] = []

    async def async_step_user(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Krok 1: Wybór modułów do aktywacji.

        Użytkownik musi wybrać co najmniej jeden moduł.
        Oferuje również tryb szybkiej konfiguracji.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # Check if quick setup was selected
            if user_input.get("quick_setup"):
                return await self.async_step_quick_setup()

            modules = user_input.get("modules_enabled", [])
            error_msg = _validate_modules(modules)
            if error_msg:
                errors["modules_enabled"] = error_msg
            else:
                self._modules = modules
                self._data[CONF_MODULES_ENABLED] = modules
                # Proceed to tariff step (always required)
                return await self.async_step_tariff()

        schema = vol.Schema({
            vol.Required("modules_enabled", default=[MODULE_PRICES, MODULE_TARIFF]): cv.multi_select({
                MODULE_PRICES: "Ceny energii (RCE PSE)",
                MODULE_TARIFF: "Kalkulator taryf",
                MODULE_EV: "Harmonogramownik EV",
                MODULE_LOADS: "Menedżer obciążeń",
                MODULE_PV: "Optymalizator PV",
                MODULE_ANALYZER: "Analizator taryf",
            }),
            vol.Optional("quick_setup", default=False): bool,
        })

        return self._async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "title": "Polish Energy Optimizer",
                "description": (
                    "Wybierz moduły do aktywacji. "
                    "Możesz również użyć szybkiej konfiguracji z domyślnymi wartościami."
                ),
            },
        )

    async def async_step_tariff(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Krok 2: Konfiguracja taryfy i operatora OSD.

        Auto-ładowanie dostępnych taryf i domyślnych stawek po wyborze OSD.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_tariff_config(user_input)
            if not errors:
                self._data[CONF_OSD_OPERATOR] = user_input["osd_operator"]
                self._data[CONF_TARIFF_TYPE] = user_input["tariff_type"]

                # Store rates in options
                self._options[CONF_TARIFF_RATES] = {
                    "energy_price": user_input.get("energy_price", DEFAULT_RATES["energy_price"]),
                    "distribution_variable": user_input.get(
                        "distribution_variable", DEFAULT_RATES["distribution_variable"]
                    ),
                    "transition_fee": user_input.get("transition_fee", DEFAULT_RATES["transition_fee"]),
                    "oze_fee": user_input.get("oze_fee", DEFAULT_RATES["oze_fee"]),
                    "capacity_fee": user_input.get("capacity_fee", DEFAULT_RATES["capacity_fee"]),
                    "cogeneration_fee": user_input.get(
                        "cogeneration_fee", DEFAULT_RATES["cogeneration_fee"]
                    ),
                }

                # Determine next step based on selected modules
                if MODULE_EV in self._modules:
                    return await self.async_step_ev()
                elif MODULE_LOADS in self._modules:
                    return await self.async_step_loads()
                elif MODULE_PV in self._modules:
                    return await self.async_step_pv()
                else:
                    return self._create_entry()

        schema = vol.Schema({
            vol.Required("osd_operator"): vol.In(
                {o.value: o.value for o in OSDOperator}
            ),
            vol.Required("tariff_type"): vol.In(
                {t.value: t.value for t in TariffType}
            ),
            vol.Optional("energy_price", default=DEFAULT_RATES["energy_price"]): str,
            vol.Optional(
                "distribution_variable", default=DEFAULT_RATES["distribution_variable"]
            ): str,
            vol.Optional("transition_fee", default=DEFAULT_RATES["transition_fee"]): str,
            vol.Optional("oze_fee", default=DEFAULT_RATES["oze_fee"]): str,
            vol.Optional("capacity_fee", default=DEFAULT_RATES["capacity_fee"]): str,
            vol.Optional("cogeneration_fee", default=DEFAULT_RATES["cogeneration_fee"]): str,
        })

        return self._async_show_form(
            step_id="tariff",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "title": "Konfiguracja taryfy",
                "description": (
                    "Wybierz operatora OSD i typ taryfy. "
                    "Stawki zostaną automatycznie załadowane z domyślnych wartości URE. "
                    "Możesz je zmienić ręcznie."
                ),
            },
        )

    async def async_step_ev(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Krok 3: Konfiguracja EV (opcjonalna).

        Konfiguracja pojazdu elektrycznego i ładowarki.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # Allow skipping
            if user_input.get("skip", False):
                if MODULE_LOADS in self._modules:
                    return await self.async_step_loads()
                elif MODULE_PV in self._modules:
                    return await self.async_step_pv()
                else:
                    return self._create_entry()

            errors = _validate_ev_config(user_input)
            if not errors:
                vehicle_config = {
                    "id": "ev_1",
                    "name": user_input["vehicle_name"],
                    "battery_kwh": float(user_input.get("battery_capacity_kwh", 60)),
                    "max_power_kw": float(user_input.get("max_charging_power_kw", 11)),
                    "min_power_kw": float(user_input.get("min_charging_power_kw", 1.4)),
                    "soc_entity": user_input["soc_entity_id"],
                    "target_soc": int(user_input.get("target_soc", 80)),
                    "priority": 1,
                    "strategy": user_input.get("strategy", ChargingStrategy.READY_BY.value),
                }
                self._options[CONF_EV_VEHICLES] = [vehicle_config]

                # Store charger config if provided
                charger_protocol = user_input.get("charger_protocol")
                if charger_protocol:
                    charger_config = {
                        "id": "charger_1",
                        "protocol": charger_protocol,
                        "host": user_input.get("charger_host", ""),
                        "api_key": user_input.get("charger_api_key", ""),
                    }
                    self._data[CONF_CHARGERS] = [charger_config]

                # Grid limit
                grid_limit = user_input.get("grid_limit_kw")
                if grid_limit:
                    self._options[CONF_GRID_LIMIT_KW] = float(grid_limit)

                if MODULE_LOADS in self._modules:
                    return await self.async_step_loads()
                elif MODULE_PV in self._modules:
                    return await self.async_step_pv()
                else:
                    return self._create_entry()

        schema = vol.Schema({
            vol.Optional("skip", default=False): bool,
            vol.Optional("vehicle_name", default="Mój pojazd EV"): str,
            vol.Optional("battery_capacity_kwh", default="60"): str,
            vol.Optional("max_charging_power_kw", default="11"): str,
            vol.Optional("min_charging_power_kw", default="1.4"): str,
            vol.Optional("soc_entity_id", default=""): str,
            vol.Optional("target_soc", default="80"): str,
            vol.Optional("strategy", default=ChargingStrategy.READY_BY.value): vol.In(
                {s.value: s.value for s in ChargingStrategy}
            ),
            vol.Optional("charger_protocol", default=""): str,
            vol.Optional("charger_host", default=""): str,
            vol.Optional("charger_api_key", default=""): str,
            vol.Optional("grid_limit_kw", default="12"): str,
        })

        return self._async_show_form(
            step_id="ev",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "title": "Konfiguracja pojazdu elektrycznego",
                "description": (
                    "Skonfiguruj pojazd elektryczny i ładowarkę. "
                    "Możesz pominąć ten krok jeśli nie chcesz konfigurować EV."
                ),
            },
        )

    async def async_step_loads(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Krok 4: Konfiguracja odbiorników odraczalnych (opcjonalna).

        Do 10 odbiorników odraczalnych.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # Allow skipping
            if user_input.get("skip", False):
                if MODULE_PV in self._modules:
                    return await self.async_step_pv()
                else:
                    return self._create_entry()

            errors = _validate_load_config(user_input)
            if not errors:
                load_config = {
                    "id": f"load_{len(self._options.get(CONF_LOADS, []))+1}",
                    "name": user_input["load_name"],
                    "entity_id": user_input["entity_id"],
                    "threshold_on": user_input.get("threshold_on", "0.35"),
                    "threshold_off": user_input.get("threshold_off", "0.55"),
                    "min_hours": float(user_input.get("min_daily_hours", 2.0)),
                    "max_hours": float(user_input.get("max_daily_hours", 6.0)),
                    "allowed_start": user_input.get("allowed_start", "22:00"),
                    "allowed_end": user_input.get("allowed_end", "06:00"),
                    "priority": int(user_input.get("priority", 1)),
                    "power_w": int(user_input.get("power_w", 2000)),
                    "failsafe": user_input.get("failsafe_state", True),
                }

                if CONF_LOADS not in self._options:
                    self._options[CONF_LOADS] = []
                self._options[CONF_LOADS].append(load_config)

                # Check if user wants to add more loads
                if user_input.get("add_another", False):
                    current_count = len(self._options[CONF_LOADS])
                    if current_count < MAX_CONFIG_LOADS:
                        return await self.async_step_loads()
                    else:
                        errors["base"] = (
                            f"Osiągnięto maksymalną liczbę odbiorników ({MAX_CONFIG_LOADS})"
                        )

                if MODULE_PV in self._modules:
                    return await self.async_step_pv()
                else:
                    return self._create_entry()

        schema = vol.Schema({
            vol.Optional("skip", default=False): bool,
            vol.Optional("load_name", default=""): str,
            vol.Optional("entity_id", default=""): str,
            vol.Optional("threshold_on", default="0.35"): str,
            vol.Optional("threshold_off", default="0.55"): str,
            vol.Optional("min_daily_hours", default="2.0"): str,
            vol.Optional("max_daily_hours", default="6.0"): str,
            vol.Optional("allowed_start", default="22:00"): str,
            vol.Optional("allowed_end", default="06:00"): str,
            vol.Optional("priority", default="1"): str,
            vol.Optional("power_w", default="2000"): str,
            vol.Optional("failsafe_state", default=True): bool,
            vol.Optional("add_another", default=False): bool,
        })

        current_count = len(self._options.get(CONF_LOADS, []))
        return self._async_show_form(
            step_id="loads",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "title": "Konfiguracja odbiorników odraczalnych",
                "description": (
                    f"Dodaj odbiornik odraczalny ({current_count}/{MAX_CONFIG_LOADS}). "
                    "Możesz pominąć ten krok lub dodać kolejne odbiorniki."
                ),
            },
        )

    async def async_step_pv(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Krok 5: Konfiguracja PV (opcjonalna).

        Dostawca prognoz solarnych i konfiguracja baterii.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # Allow skipping
            if user_input.get("skip", False):
                return self._create_entry()

            errors = _validate_pv_config(user_input)
            if not errors:
                self._data[CONF_SOLAR_PROVIDER] = user_input["solar_provider"]
                self._data[CONF_SOLAR_API_KEY] = user_input["solar_api_key"]

                pv_config: dict[str, Any] = {
                    "capacity_kwp": float(user_input.get("capacity_kwp", 0)),
                }

                # Battery config (optional)
                battery_kwh = user_input.get("battery_capacity_kwh")
                if battery_kwh and battery_kwh != "":
                    pv_config["battery_capacity_kwh"] = float(battery_kwh)
                    pv_config["min_soc"] = int(user_input.get("min_soc_percent", 10))
                    pv_config["degradation_cost"] = user_input.get(
                        "degradation_cost", "0.15"
                    )
                    pv_config["inverter_entity"] = user_input.get("inverter_entity", "")
                    pv_config["soc_entity"] = user_input.get("battery_soc_entity", "")

                self._options[CONF_PV] = pv_config
                return self._create_entry()

        schema = vol.Schema({
            vol.Optional("skip", default=False): bool,
            vol.Optional("solar_provider", default=SolarProvider.FORECAST_SOLAR.value): vol.In(
                {p.value: p.value for p in SolarProvider}
            ),
            vol.Optional("solar_api_key", default=""): str,
            vol.Optional("capacity_kwp", default="10"): str,
            vol.Optional("battery_capacity_kwh", default=""): str,
            vol.Optional("min_soc_percent", default="10"): str,
            vol.Optional("degradation_cost", default="0.15"): str,
            vol.Optional("inverter_entity", default=""): str,
            vol.Optional("battery_soc_entity", default=""): str,
        })

        return self._async_show_form(
            step_id="pv",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "title": "Konfiguracja fotowoltaiki",
                "description": (
                    "Skonfiguruj dostawcę prognoz solarnych i opcjonalnie magazyn energii. "
                    "Możesz pominąć ten krok."
                ),
            },
        )

    async def async_step_quick_setup(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Tryb szybkiej konfiguracji z domyślnymi wartościami.

        Domyślna konfiguracja: G12 + EV + bojler CWU (Tauron).
        """
        if user_input is not None:
            # Apply quick setup defaults
            self._modules = [MODULE_PRICES, MODULE_TARIFF, MODULE_EV, MODULE_LOADS]
            self._data[CONF_MODULES_ENABLED] = self._modules
            self._data[CONF_OSD_OPERATOR] = OSDOperator.TAURON.value
            self._data[CONF_TARIFF_TYPE] = TariffType.G12.value

            self._options[CONF_TARIFF_RATES] = DEFAULT_RATES.copy()
            self._options[CONF_LOADS] = [DEFAULT_LOAD_CWU.copy()]

            # EV defaults
            soc_entity = user_input.get("soc_entity_id", "")
            vehicle_name = user_input.get("vehicle_name", "Mój pojazd EV")

            self._options[CONF_EV_VEHICLES] = [{
                "id": "ev_1",
                "name": vehicle_name,
                "battery_kwh": 60,
                "max_power_kw": 11,
                "min_power_kw": 1.4,
                "soc_entity": soc_entity,
                "target_soc": 80,
                "priority": 1,
                "strategy": ChargingStrategy.READY_BY.value,
            }]
            self._options[CONF_GRID_LIMIT_KW] = 12.0

            return self._create_entry()

        schema = vol.Schema({
            vol.Optional("vehicle_name", default="Mój pojazd EV"): str,
            vol.Optional("soc_entity_id", default=""): str,
        })

        return self._async_show_form(
            step_id="quick_setup",
            data_schema=schema,
            errors={},
            description_placeholders={
                "title": "Szybka konfiguracja",
                "description": (
                    "Szybka konfiguracja z domyślnymi wartościami: "
                    "taryfa G12 (Tauron), pojazd EV, bojler CWU. "
                    "Podaj tylko encję SoC pojazdu — resztę można zmienić później."
                ),
            },
        )

    def _create_entry(self) -> dict[str, Any]:
        """Utwórz ConfigEntry z zebranymi danymi.

        Returns:
            Wynik create_entry z danymi i opcjami.
        """
        title = "Polish Energy Optimizer"
        return self.async_create_entry(
            title=title,
            data=self._data,
            options=self._options,
        )

    def _async_show_form(
        self,
        step_id: str,
        data_schema: vol.Schema,
        errors: dict[str, str],
        description_placeholders: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Wyświetl formularz konfiguracji.

        Args:
            step_id: Identyfikator kroku.
            data_schema: Schemat danych formularza.
            errors: Słownik błędów walidacji.
            description_placeholders: Opisy i tytuły.

        Returns:
            Wynik async_show_form.
        """
        return self.async_show_form(
            step_id=step_id,
            data_schema=data_schema,
            errors=errors,
            description_placeholders=description_placeholders,
        )

    @property
    def partial_config(self) -> dict[str, Any]:
        """Zwróć częściową konfigurację (do zachowania przy przerwaniu).

        Konfiguracja jest zachowywana w pamięci instancji flow
        do momentu restartu HA (requirement 7.7).
        """
        return {
            "data": self._data,
            "options": self._options,
            "modules": self._modules,
        }
