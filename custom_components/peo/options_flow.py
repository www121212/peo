"""PEO Options Flow — rekonfiguracja modułów bez przeładowania integracji.

Implementuje Options Flow z krokami:
1. async_step_init — menu wyboru modułu do rekonfiguracji
2. async_step_tariff_rates — aktualizacja stawek taryfowych
3. async_step_ev_config — aktualizacja konfiguracji EV
4. async_step_loads_config — dodawanie/usuwanie odbiorników odraczalnych
5. async_step_pv_config — aktualizacja konfiguracji PV

Każdy krok aktualizuje ConfigEntry.options bez wymagania przeładowania integracji.

Requirements: 7.5, 7.6, 8.9
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import voluptuous as vol

from homeassistant import config_entries

from .const import (
    DOMAIN,
    CONF_TARIFF_RATES,
    CONF_EV_VEHICLES,
    CONF_LOADS,
    CONF_GRID_LIMIT_KW,
    CONF_PV,
    CONF_PRICE_THRESHOLD_CHEAP,
    MAX_LOADS,
    POWER_MIN_KW,
    POWER_MAX_KW,
    RATE_MIN_PLN_KWH,
    RATE_MAX_PLN_KWH,
    SOC_MIN,
    SOC_MAX,
)
from .enums import ChargingStrategy, SolarProvider
from .validators import InputValidator

_LOGGER = logging.getLogger(__name__)

# Maximum deferrable loads in options flow
MAX_OPTIONS_LOADS = 16


class PEOOptionsFlow:
    """Options Flow dla Polish Energy Optimizer.

    Umożliwia niezależną rekonfigurację każdego modułu (EV, taryfa, PV, odbiory)
    bez konieczności przeładowania integracji.

    Requirements: 7.5, 7.6, 8.9
    """

    def __init__(self, config_entry) -> None:
        """Inicjalizacja Options Flow.

        Args:
            config_entry: Bieżący ConfigEntry integracji.
        """
        self._config_entry = config_entry
        self._options: dict[str, Any] = dict(config_entry.options)

    async def async_step_init(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Krok początkowy — menu wyboru modułu do rekonfiguracji.

        Wyświetla menu z opcjami:
        - Stawki taryfowe
        - Konfiguracja EV
        - Odbiorniki odraczalne
        - Konfiguracja PV
        """
        if user_input is not None:
            next_step = user_input.get("module")
            if next_step == "tariff_rates":
                return await self.async_step_tariff_rates()
            elif next_step == "ev_config":
                return await self.async_step_ev_config()
            elif next_step == "loads_config":
                return await self.async_step_loads_config()
            elif next_step == "pv_config":
                return await self.async_step_pv_config()

        schema = vol.Schema({
            vol.Required("module"): vol.In({
                "tariff_rates": "Stawki taryfowe",
                "ev_config": "Konfiguracja EV",
                "loads_config": "Odbiorniki odraczalne",
                "pv_config": "Konfiguracja PV",
            }),
        })

        return self._async_show_form(
            step_id="init",
            data_schema=schema,
            errors={},
            description_placeholders={
                "title": "Rekonfiguracja PEO",
                "description": (
                    "Wybierz moduł do rekonfiguracji. "
                    "Zmiany zostaną zastosowane bez konieczności przeładowania integracji."
                ),
            },
        )

    async def async_step_tariff_rates(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Aktualizacja stawek taryfowych.

        Umożliwia zmianę wszystkich składników stawki taryfowej
        bez przeładowania integracji.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate all rate fields
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

            if not errors:
                self._options[CONF_TARIFF_RATES] = {
                    "energy_price": user_input.get("energy_price", "0.4500"),
                    "distribution_variable": user_input.get("distribution_variable", "0.2100"),
                    "transition_fee": user_input.get("transition_fee", "0.0009"),
                    "oze_fee": user_input.get("oze_fee", "0.0029"),
                    "capacity_fee": user_input.get("capacity_fee", "0.0688"),
                    "cogeneration_fee": user_input.get("cogeneration_fee", "0.0027"),
                }
                return self._create_entry()

        # Load current rates as defaults
        current_rates = self._options.get(CONF_TARIFF_RATES, {})

        schema = vol.Schema({
            vol.Optional(
                "energy_price",
                default=current_rates.get("energy_price", "0.4500"),
            ): str,
            vol.Optional(
                "distribution_variable",
                default=current_rates.get("distribution_variable", "0.2100"),
            ): str,
            vol.Optional(
                "transition_fee",
                default=current_rates.get("transition_fee", "0.0009"),
            ): str,
            vol.Optional(
                "oze_fee",
                default=current_rates.get("oze_fee", "0.0029"),
            ): str,
            vol.Optional(
                "capacity_fee",
                default=current_rates.get("capacity_fee", "0.0688"),
            ): str,
            vol.Optional(
                "cogeneration_fee",
                default=current_rates.get("cogeneration_fee", "0.0027"),
            ): str,
        })

        return self._async_show_form(
            step_id="tariff_rates",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "title": "Stawki taryfowe",
                "description": (
                    "Zaktualizuj składniki stawki taryfowej (PLN/kWh). "
                    "Zmiany zostaną zastosowane natychmiast."
                ),
            },
        )

    async def async_step_ev_config(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Aktualizacja konfiguracji EV.

        Umożliwia zmianę parametrów pojazdu elektrycznego
        bez przeładowania integracji.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate EV parameters
            target_soc = user_input.get("target_soc")
            if target_soc is not None and target_soc != "":
                try:
                    soc = InputValidator.validate_soc(target_soc)
                    if soc < 10:
                        errors["target_soc"] = (
                            "Docelowy SoC musi być w zakresie 10–100%"
                        )
                except ValueError as e:
                    errors["target_soc"] = str(e)

            max_power = user_input.get("max_charging_power_kw")
            if max_power is not None and max_power != "":
                try:
                    InputValidator.validate_power(max_power)
                except ValueError as e:
                    errors["max_charging_power_kw"] = str(e)

            grid_limit = user_input.get("grid_limit_kw")
            if grid_limit is not None and grid_limit != "":
                try:
                    val = float(grid_limit)
                    if val <= 0 or val > 100:
                        errors["grid_limit_kw"] = (
                            "Moc przyłączeniowa musi być w zakresie 0.1–100 kW"
                        )
                except (TypeError, ValueError):
                    errors["grid_limit_kw"] = "Nieprawidłowa wartość mocy przyłączeniowej"

            if not errors:
                # Update EV vehicles config
                current_vehicles = self._options.get(CONF_EV_VEHICLES, [])
                if current_vehicles:
                    vehicle = dict(current_vehicles[0])
                else:
                    vehicle = {"id": "ev_1", "name": "Mój pojazd EV"}

                if user_input.get("vehicle_name"):
                    vehicle["name"] = user_input["vehicle_name"]
                if target_soc:
                    vehicle["target_soc"] = int(target_soc)
                if max_power:
                    vehicle["max_power_kw"] = float(max_power)
                if user_input.get("min_charging_power_kw"):
                    vehicle["min_power_kw"] = float(user_input["min_charging_power_kw"])
                if user_input.get("soc_entity_id"):
                    vehicle["soc_entity"] = user_input["soc_entity_id"]
                if user_input.get("strategy"):
                    vehicle["strategy"] = user_input["strategy"]

                self._options[CONF_EV_VEHICLES] = [vehicle]

                if grid_limit:
                    self._options[CONF_GRID_LIMIT_KW] = float(grid_limit)

                return self._create_entry()

        # Load current EV config as defaults
        current_vehicles = self._options.get(CONF_EV_VEHICLES, [])
        current_vehicle = current_vehicles[0] if current_vehicles else {}
        current_grid_limit = self._options.get(CONF_GRID_LIMIT_KW, 12.0)

        schema = vol.Schema({
            vol.Optional(
                "vehicle_name",
                default=current_vehicle.get("name", "Mój pojazd EV"),
            ): str,
            vol.Optional(
                "max_charging_power_kw",
                default=str(current_vehicle.get("max_power_kw", 11)),
            ): str,
            vol.Optional(
                "min_charging_power_kw",
                default=str(current_vehicle.get("min_power_kw", 1.4)),
            ): str,
            vol.Optional(
                "soc_entity_id",
                default=current_vehicle.get("soc_entity", ""),
            ): str,
            vol.Optional(
                "target_soc",
                default=str(current_vehicle.get("target_soc", 80)),
            ): str,
            vol.Optional(
                "strategy",
                default=current_vehicle.get("strategy", ChargingStrategy.READY_BY.value),
            ): vol.In({s.value: s.value for s in ChargingStrategy}),
            vol.Optional(
                "grid_limit_kw",
                default=str(current_grid_limit),
            ): str,
        })

        return self._async_show_form(
            step_id="ev_config",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "title": "Konfiguracja EV",
                "description": (
                    "Zaktualizuj parametry pojazdu elektrycznego. "
                    "Zmiany zostaną zastosowane bez przeładowania integracji."
                ),
            },
        )

    async def async_step_loads_config(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Dodawanie/usuwanie odbiorników odraczalnych.

        Umożliwia zarządzanie listą odbiorników bez pełnej rekonfiguracji.
        Obsługuje dodawanie nowych i usuwanie istniejących odbiorników.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            action = user_input.get("action", "add")

            if action == "remove":
                # Remove a load by index
                remove_index = user_input.get("remove_index")
                current_loads = self._options.get(CONF_LOADS, [])
                if remove_index is not None:
                    try:
                        idx = int(remove_index)
                        if 0 <= idx < len(current_loads):
                            current_loads.pop(idx)
                            self._options[CONF_LOADS] = current_loads
                            return self._create_entry()
                        else:
                            errors["remove_index"] = (
                                "Nieprawidłowy indeks odbiornika"
                            )
                    except (TypeError, ValueError):
                        errors["remove_index"] = (
                            "Nieprawidłowy indeks odbiornika"
                        )
                else:
                    errors["remove_index"] = "Indeks odbiornika jest wymagany"

            elif action == "add":
                # Validate new load
                load_name = user_input.get("load_name")
                if not load_name:
                    errors["load_name"] = "Nazwa odbiornika jest wymagana"

                entity_id = user_input.get("entity_id")
                if not entity_id:
                    errors["entity_id"] = "Encja Home Assistant jest wymagana"

                # Validate thresholds
                threshold_on = user_input.get("threshold_on")
                if threshold_on:
                    try:
                        InputValidator.validate_rate(threshold_on)
                    except ValueError as e:
                        errors["threshold_on"] = str(e)

                threshold_off = user_input.get("threshold_off")
                if threshold_off:
                    try:
                        InputValidator.validate_rate(threshold_off)
                    except ValueError as e:
                        errors["threshold_off"] = str(e)

                # Validate power
                power_w = user_input.get("power_w")
                if power_w:
                    try:
                        val = int(power_w)
                        if val <= 0 or val > 100000:
                            errors["power_w"] = (
                                "Pobór mocy musi być w zakresie 1–100000 W"
                            )
                    except (TypeError, ValueError):
                        errors["power_w"] = "Nieprawidłowa wartość poboru mocy"

                # Check max loads limit
                current_loads = self._options.get(CONF_LOADS, [])
                if len(current_loads) >= MAX_OPTIONS_LOADS:
                    errors["base"] = (
                        f"Osiągnięto maksymalną liczbę odbiorników ({MAX_OPTIONS_LOADS})"
                    )

                if not errors:
                    load_config = {
                        "id": f"load_{len(current_loads) + 1}",
                        "name": load_name,
                        "entity_id": entity_id,
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
                    current_loads.append(load_config)
                    self._options[CONF_LOADS] = current_loads
                    return self._create_entry()

            elif action == "done":
                return self._create_entry()

        current_loads = self._options.get(CONF_LOADS, [])
        load_count = len(current_loads)

        schema = vol.Schema({
            vol.Required("action", default="add"): vol.In({
                "add": "Dodaj odbiornik",
                "remove": "Usuń odbiornik",
                "done": "Zakończ",
            }),
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
            vol.Optional("remove_index", default=""): str,
        })

        return self._async_show_form(
            step_id="loads_config",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "title": "Odbiorniki odraczalne",
                "description": (
                    f"Zarządzaj odbiornikami odraczalnymi ({load_count}/{MAX_OPTIONS_LOADS}). "
                    "Możesz dodać nowy odbiornik, usunąć istniejący lub zakończyć."
                ),
            },
        )

    async def async_step_pv_config(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Aktualizacja konfiguracji PV.

        Umożliwia zmianę parametrów fotowoltaiki i baterii
        bez przeładowania integracji.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate battery capacity
            battery_kwh = user_input.get("battery_capacity_kwh")
            if battery_kwh and battery_kwh != "":
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
            if min_soc and min_soc != "":
                try:
                    val = int(min_soc)
                    if val < 5 or val > 30:
                        errors["min_soc_percent"] = (
                            "Minimalny SoC bezpieczeństwa musi być w zakresie 5–30%"
                        )
                except (TypeError, ValueError):
                    errors["min_soc_percent"] = (
                        "Nieprawidłowa wartość minimalnego SoC"
                    )

            # Validate degradation cost
            degradation_cost = user_input.get("degradation_cost")
            if degradation_cost and degradation_cost != "":
                try:
                    InputValidator.validate_rate(degradation_cost)
                except ValueError as e:
                    errors["degradation_cost"] = str(e)

            if not errors:
                pv_config: dict[str, Any] = {
                    "capacity_kwp": float(user_input.get("capacity_kwp", 0)),
                }

                if battery_kwh and battery_kwh != "":
                    pv_config["battery_capacity_kwh"] = float(battery_kwh)
                    pv_config["min_soc"] = int(user_input.get("min_soc_percent", 10))
                    pv_config["degradation_cost"] = user_input.get(
                        "degradation_cost", "0.15"
                    )
                    pv_config["inverter_entity"] = user_input.get(
                        "inverter_entity", ""
                    )
                    pv_config["soc_entity"] = user_input.get(
                        "battery_soc_entity", ""
                    )

                self._options[CONF_PV] = pv_config
                return self._create_entry()

        # Load current PV config as defaults
        current_pv = self._options.get(CONF_PV, {})

        schema = vol.Schema({
            vol.Optional(
                "capacity_kwp",
                default=str(current_pv.get("capacity_kwp", 10)),
            ): str,
            vol.Optional(
                "battery_capacity_kwh",
                default=str(current_pv.get("battery_capacity_kwh", "")),
            ): str,
            vol.Optional(
                "min_soc_percent",
                default=str(current_pv.get("min_soc", 10)),
            ): str,
            vol.Optional(
                "degradation_cost",
                default=current_pv.get("degradation_cost", "0.15"),
            ): str,
            vol.Optional(
                "inverter_entity",
                default=current_pv.get("inverter_entity", ""),
            ): str,
            vol.Optional(
                "battery_soc_entity",
                default=current_pv.get("soc_entity", ""),
            ): str,
        })

        return self._async_show_form(
            step_id="pv_config",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "title": "Konfiguracja PV",
                "description": (
                    "Zaktualizuj parametry fotowoltaiki i magazynu energii. "
                    "Zmiany zostaną zastosowane bez przeładowania integracji."
                ),
            },
        )

    def _create_entry(self) -> dict[str, Any]:
        """Zapisz zaktualizowane opcje do ConfigEntry.

        Returns:
            Wynik create_entry z zaktualizowanymi opcjami.
        """
        return self._async_create_entry(data=self._options)

    def _async_create_entry(self, *, data: dict[str, Any]) -> dict[str, Any]:
        """Utwórz wpis opcji.

        Args:
            data: Zaktualizowane opcje.

        Returns:
            Słownik z typem i danymi.
        """
        return {
            "type": "create_entry",
            "data": data,
        }

    def _async_show_form(
        self,
        step_id: str,
        data_schema: vol.Schema,
        errors: dict[str, str],
        description_placeholders: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Wyświetl formularz opcji.

        Args:
            step_id: Identyfikator kroku.
            data_schema: Schemat danych formularza.
            errors: Słownik błędów walidacji.
            description_placeholders: Opisy i tytuły.

        Returns:
            Wynik async_show_form.
        """
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors or {},
            "description_placeholders": description_placeholders,
        }
