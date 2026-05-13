"""Binary sensors i sensory z atrybutami dla PEO.

Implementuje:
- Binary sensors: tanie okno, ładowanie EV aktywne, nadwyżka PV aktywna
- Sensory z atrybutami: hourly_prices (24h), schedule (JSON), last_updated
- Zdarzenia HA: peo_charging_started, peo_charging_completed, peo_load_shifted,
  peo_price_threshold_crossed, peo_schedule_updated

Requirements: 12.2, 12.5, 12.6
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from homeassistant.core import HomeAssistant, callback
from homeassistant import config_entries

from .const import (
    DOMAIN,
    CONF_MODULES_ENABLED,
    CONF_PRICE_THRESHOLD_CHEAP,
    EVENT_CHARGING_STARTED,
    EVENT_CHARGING_COMPLETED,
    EVENT_LOAD_SHIFTED,
    EVENT_PRICE_THRESHOLD_CROSSED,
    EVENT_SCHEDULE_UPDATED,
    MODULE_PRICES,
    MODULE_EV,
    MODULE_PV,
)

_LOGGER = logging.getLogger(__name__)

# Default cheap price threshold (PLN/kWh)
DEFAULT_CHEAP_THRESHOLD = Decimal("0.40")


class PEOBinarySensorBase:
    """Bazowa klasa dla binary sensorów PEO.

    Implementuje wzorzec BinarySensorEntity z unique_id i device_info.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: config_entries.ConfigEntry,
        name: str,
        unique_id_suffix: str,
    ) -> None:
        """Inicjalizacja binary sensora.

        Args:
            hass: Instancja Home Assistant.
            entry: Wpis konfiguracyjny.
            name: Nazwa sensora.
            unique_id_suffix: Sufiks unique_id.
        """
        self._hass = hass
        self._entry = entry
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{unique_id_suffix}"
        self._attr_is_on: bool = False
        self._attr_extra_state_attributes: dict[str, Any] = {}

    @property
    def name(self) -> str:
        """Nazwa sensora."""
        return self._attr_name

    @property
    def unique_id(self) -> str:
        """Unikalny identyfikator sensora."""
        return self._attr_unique_id

    @property
    def is_on(self) -> bool:
        """Stan sensora (ON/OFF)."""
        return self._attr_is_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Dodatkowe atrybuty stanu."""
        return self._attr_extra_state_attributes

    @property
    def device_info(self) -> dict[str, Any]:
        """Informacje o urządzeniu."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Polish Energy Optimizer",
            "manufacturer": "PEO",
            "model": "Energy Optimizer",
            "sw_version": "1.0.0",
        }


class CheapWindowBinarySensor(PEOBinarySensorBase):
    """Binary sensor: tanie okno cenowe.

    ON gdy aktualna cena energii jest poniżej progu cenowego
    skonfigurowanego przez użytkownika.

    Requirement 12.5
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: config_entries.ConfigEntry,
    ) -> None:
        """Inicjalizacja sensora taniego okna."""
        super().__init__(
            hass, entry,
            name="PEO Tanie okno cenowe",
            unique_id_suffix="cheap_window",
        )
        threshold_str = entry.options.get(
            CONF_PRICE_THRESHOLD_CHEAP, "0.40"
        )
        self._threshold = Decimal(str(threshold_str))
        self._current_price: Optional[Decimal] = None

    def update_price(self, current_price_pln_kwh: Decimal) -> None:
        """Aktualizuj stan sensora na podstawie bieżącej ceny.

        Args:
            current_price_pln_kwh: Bieżąca cena energii w PLN/kWh.
        """
        old_state = self._attr_is_on
        self._current_price = current_price_pln_kwh
        self._attr_is_on = current_price_pln_kwh < self._threshold

        self._attr_extra_state_attributes = {
            "current_price_pln_kwh": str(current_price_pln_kwh),
            "threshold_pln_kwh": str(self._threshold),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

        # Fire event on threshold crossing
        if old_state != self._attr_is_on:
            direction = "below" if self._attr_is_on else "above"
            self._hass.bus.async_fire(
                EVENT_PRICE_THRESHOLD_CROSSED,
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "entity_id": f"binary_sensor.{self._attr_unique_id}",
                    "current_price": str(current_price_pln_kwh),
                    "threshold": str(self._threshold),
                    "direction": direction,
                },
            )

    def update_threshold(self, new_threshold: Decimal) -> None:
        """Aktualizuj próg cenowy.

        Args:
            new_threshold: Nowy próg cenowy w PLN/kWh.
        """
        self._threshold = new_threshold
        if self._current_price is not None:
            self.update_price(self._current_price)


class EVChargingActiveBinarySensor(PEOBinarySensorBase):
    """Binary sensor: ładowanie EV aktywne.

    ON gdy trwa aktywne ładowanie pojazdu elektrycznego.

    Requirement 12.5
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: config_entries.ConfigEntry,
    ) -> None:
        """Inicjalizacja sensora ładowania EV."""
        super().__init__(
            hass, entry,
            name="PEO Ładowanie EV aktywne",
            unique_id_suffix="ev_charging_active",
        )
        self._vehicle_id: Optional[str] = None

    def set_charging_active(
        self, active: bool, vehicle_id: Optional[str] = None
    ) -> None:
        """Ustaw stan ładowania.

        Args:
            active: Czy ładowanie jest aktywne.
            vehicle_id: ID pojazdu (opcjonalne).
        """
        old_state = self._attr_is_on
        self._attr_is_on = active
        self._vehicle_id = vehicle_id

        self._attr_extra_state_attributes = {
            "vehicle_id": vehicle_id,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

        # Fire events on state change
        if active and not old_state:
            self._hass.bus.async_fire(
                EVENT_CHARGING_STARTED,
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "entity_id": f"binary_sensor.{self._attr_unique_id}",
                    "vehicle_id": vehicle_id,
                },
            )
        elif not active and old_state:
            self._hass.bus.async_fire(
                EVENT_CHARGING_COMPLETED,
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "entity_id": f"binary_sensor.{self._attr_unique_id}",
                    "vehicle_id": vehicle_id,
                },
            )


class PVSurplusActiveBinarySensor(PEOBinarySensorBase):
    """Binary sensor: nadwyżka PV aktywna.

    ON gdy produkcja PV przekracza bieżące zużycie.

    Requirement 12.5
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: config_entries.ConfigEntry,
    ) -> None:
        """Inicjalizacja sensora nadwyżki PV."""
        super().__init__(
            hass, entry,
            name="PEO Nadwyżka PV aktywna",
            unique_id_suffix="pv_surplus_active",
        )
        self._production_kw: float = 0.0
        self._consumption_kw: float = 0.0

    def update_pv_status(
        self, production_kw: float, consumption_kw: float
    ) -> None:
        """Aktualizuj stan sensora na podstawie produkcji i zużycia.

        Args:
            production_kw: Bieżąca produkcja PV w kW.
            consumption_kw: Bieżące zużycie w kW.
        """
        self._production_kw = production_kw
        self._consumption_kw = consumption_kw
        self._attr_is_on = production_kw > consumption_kw

        surplus_kw = max(0.0, production_kw - consumption_kw)
        self._attr_extra_state_attributes = {
            "production_kw": round(production_kw, 2),
            "consumption_kw": round(consumption_kw, 2),
            "surplus_kw": round(surplus_kw, 2),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }


class PEOScheduleSensor:
    """Sensor z atrybutami harmonogramu.

    Udostępnia atrybuty: hourly_prices (24h), schedule (JSON), last_updated.

    Requirement 12.6
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: config_entries.ConfigEntry,
    ) -> None:
        """Inicjalizacja sensora harmonogramu."""
        self._hass = hass
        self._entry = entry
        self._attr_name = "PEO Harmonogram"
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_schedule"
        self._attr_state: str = "idle"
        self._hourly_prices: list[dict[str, Any]] = []
        self._schedule: dict[str, Any] = {}
        self._last_updated: Optional[str] = None

    @property
    def name(self) -> str:
        """Nazwa sensora."""
        return self._attr_name

    @property
    def unique_id(self) -> str:
        """Unikalny identyfikator sensora."""
        return self._attr_unique_id

    @property
    def state(self) -> str:
        """Stan sensora."""
        return self._attr_state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Atrybuty stanu z danymi harmonogramu."""
        return {
            "hourly_prices": self._hourly_prices,
            "schedule": self._schedule,
            "last_updated": self._last_updated,
        }

    @property
    def device_info(self) -> dict[str, Any]:
        """Informacje o urządzeniu."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Polish Energy Optimizer",
            "manufacturer": "PEO",
            "model": "Energy Optimizer",
            "sw_version": "1.0.0",
        }

    def update_hourly_prices(self, prices: list[dict[str, Any]]) -> None:
        """Aktualizuj listę cen godzinowych (24h).

        Args:
            prices: Lista słowników z cenami godzinowymi.
        """
        self._hourly_prices = prices[:24]
        self._last_updated = datetime.now(timezone.utc).isoformat()
        self._attr_state = "active"

    def update_schedule(self, schedule: dict[str, Any]) -> None:
        """Aktualizuj harmonogram operacji.

        Args:
            schedule: Słownik z harmonogramem w formacie JSON-serializable.
        """
        self._schedule = schedule
        self._last_updated = datetime.now(timezone.utc).isoformat()
        self._attr_state = "active"

        # Fire schedule updated event
        self._hass.bus.async_fire(
            EVENT_SCHEDULE_UPDATED,
            {
                "timestamp": self._last_updated,
                "entity_id": f"sensor.{self._attr_unique_id}",
                "schedule_type": schedule.get("type", "unknown"),
            },
        )


def fire_load_shifted_event(
    hass: HomeAssistant,
    load_id: str,
    entity_id: str,
    action: str,
    reason: str,
    cost_pln_kwh: Optional[str] = None,
) -> None:
    """Wyzwól zdarzenie peo_load_shifted.

    Args:
        hass: Instancja Home Assistant.
        load_id: Identyfikator odbiornika.
        entity_id: Encja HA odbiornika.
        action: Akcja (on/off).
        reason: Powód przesunięcia.
        cost_pln_kwh: Bieżący koszt energii.
    """
    hass.bus.async_fire(
        EVENT_LOAD_SHIFTED,
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "entity_id": entity_id,
            "load_id": load_id,
            "action": action,
            "reason": reason,
            "cost_pln_kwh": cost_pln_kwh,
        },
    )


async def async_setup_binary_sensors(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
) -> list[Any]:
    """Konfiguracja binary sensorów PEO.

    Args:
        hass: Instancja Home Assistant.
        entry: Wpis konfiguracyjny.

    Returns:
        Lista zainicjalizowanych sensorów.
    """
    sensors: list[Any] = []
    modules_enabled = entry.data.get(CONF_MODULES_ENABLED, [])

    # Always create cheap window sensor (requires prices module)
    if MODULE_PRICES in modules_enabled:
        cheap_sensor = CheapWindowBinarySensor(hass, entry)
        sensors.append(cheap_sensor)

    # EV charging active sensor
    if MODULE_EV in modules_enabled:
        ev_sensor = EVChargingActiveBinarySensor(hass, entry)
        sensors.append(ev_sensor)

    # PV surplus sensor
    if MODULE_PV in modules_enabled:
        pv_sensor = PVSurplusActiveBinarySensor(hass, entry)
        sensors.append(pv_sensor)

    # Schedule sensor (always available)
    schedule_sensor = PEOScheduleSensor(hass, entry)
    sensors.append(schedule_sensor)

    # Store sensor references in runtime data
    runtime_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    if runtime_data is not None:
        runtime_data["binary_sensors"] = sensors

    _LOGGER.info("Zainicjalizowano %d sensorów PEO", len(sensors))
    return sensors
