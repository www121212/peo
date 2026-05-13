"""Koordynator prognoz PV (PVForecastCoordinator) dla Polish Energy Optimizer (PEO).

Odpowiedzialny za cykliczne pobieranie prognoz produkcji PV,
obliczanie strategii baterii i udostępnianie sensorów:
- prognozowana produkcja PV (dziś/jutro kWh)
- prognozowana autokonsumpcja (dziś kWh)
- rekomendowany tryb baterii
- szacowane dzienne oszczędności (PLN)

Obsługuje komunikację z inwerterami przez integracje HA:
SolarEdge, Huawei Solar, GoodWe, Fronius, SMA.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DEFAULT_PV_FORECAST_UPDATE_INTERVAL, DOMAIN
from .enums import BatteryMode
from .models import BatteryConfig, BatteryStrategy, HourlyCost, HourlyPVForecast
from .pv_optimizer import PVOptimizer
from .solar_forecast_client import SolarForecastClient

_LOGGER = logging.getLogger(__name__)

# Standardowy interwał aktualizacji (60 minut)
_DEFAULT_PV_FORECAST_UPDATE_INTERVAL = timedelta(
    minutes=DEFAULT_PV_FORECAST_UPDATE_INTERVAL
)


def _get_poland_now() -> datetime:
    """Pobierz aktualny czas w strefie czasowej Polski."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Europe/Warsaw"))
    except ImportError:
        return datetime.now(timezone(timedelta(hours=1)))


@dataclass
class PVData:
    """Dane PV zwracane przez koordynator."""

    today_production_kwh: float
    tomorrow_production_kwh: float
    autoconsumption_kwh: float
    battery_mode: BatteryMode
    estimated_savings_pln: Decimal
    is_forecast_stale: bool
    battery_strategy: Optional[BatteryStrategy] = None


class InverterAdapter(ABC):
    """Abstrakcyjny interfejs komunikacji z inwerterem.

    Umożliwia wysyłanie komend trybu baterii do inwerterów
    przez integracje Home Assistant (SolarEdge, Huawei Solar,
    GoodWe, Fronius, SMA).
    """

    @abstractmethod
    async def set_battery_mode(self, mode: BatteryMode) -> bool:
        """Ustaw tryb pracy baterii na inwerterze.

        Args:
            mode: Docelowy tryb baterii (CHARGE/DISCHARGE/STANDBY).

        Returns:
            True jeśli komenda została przyjęta, False w przypadku błędu.
        """

    @abstractmethod
    async def get_current_soc(self) -> Optional[float]:
        """Pobierz aktualny poziom SoC baterii.

        Returns:
            Poziom SoC (0-100%) lub None jeśli niedostępny.
        """

    @abstractmethod
    async def get_inverter_type(self) -> str:
        """Zwróć typ/nazwę inwertera.

        Returns:
            Nazwa typu inwertera (np. 'solaredge', 'huawei_solar').
        """


class SolarEdgeInverterAdapter(InverterAdapter):
    """Adapter inwertera SolarEdge przez integrację HA."""

    def __init__(self, hass: HomeAssistant, entity_id: str, soc_entity_id: str) -> None:
        self._hass = hass
        self._entity_id = entity_id
        self._soc_entity_id = soc_entity_id

    async def set_battery_mode(self, mode: BatteryMode) -> bool:
        """Ustaw tryb baterii SolarEdge przez service call."""
        try:
            mode_map = {
                BatteryMode.CHARGE: "charge_from_grid",
                BatteryMode.DISCHARGE: "discharge_to_grid",
                BatteryMode.STANDBY: "maximize_self_consumption",
            }
            service_mode = mode_map.get(mode, "maximize_self_consumption")
            await self._hass.services.async_call(
                "solaredge_modbus",
                "set_storage_command_mode",
                {"entity_id": self._entity_id, "mode": service_mode},
                blocking=True,
            )
            _LOGGER.info("SolarEdge: ustawiono tryb baterii na %s", mode.value)
            return True
        except Exception as err:
            _LOGGER.error("SolarEdge: błąd ustawiania trybu baterii: %s", err)
            return False

    async def get_current_soc(self) -> Optional[float]:
        """Pobierz SoC z encji HA."""
        return _get_entity_float(self._hass, self._soc_entity_id)

    async def get_inverter_type(self) -> str:
        return "solaredge"


class HuaweiSolarInverterAdapter(InverterAdapter):
    """Adapter inwertera Huawei Solar przez integrację HA."""

    def __init__(self, hass: HomeAssistant, entity_id: str, soc_entity_id: str) -> None:
        self._hass = hass
        self._entity_id = entity_id
        self._soc_entity_id = soc_entity_id

    async def set_battery_mode(self, mode: BatteryMode) -> bool:
        """Ustaw tryb baterii Huawei Solar przez service call."""
        try:
            mode_map = {
                BatteryMode.CHARGE: "forced_charge",
                BatteryMode.DISCHARGE: "forced_discharge",
                BatteryMode.STANDBY: "maximum_self_consumption",
            }
            service_mode = mode_map.get(mode, "maximum_self_consumption")
            await self._hass.services.async_call(
                "huawei_solar",
                "set_storage_mode",
                {"entity_id": self._entity_id, "mode": service_mode},
                blocking=True,
            )
            _LOGGER.info("Huawei Solar: ustawiono tryb baterii na %s", mode.value)
            return True
        except Exception as err:
            _LOGGER.error("Huawei Solar: błąd ustawiania trybu baterii: %s", err)
            return False

    async def get_current_soc(self) -> Optional[float]:
        """Pobierz SoC z encji HA."""
        return _get_entity_float(self._hass, self._soc_entity_id)

    async def get_inverter_type(self) -> str:
        return "huawei_solar"


class GoodWeInverterAdapter(InverterAdapter):
    """Adapter inwertera GoodWe przez integrację HA."""

    def __init__(self, hass: HomeAssistant, entity_id: str, soc_entity_id: str) -> None:
        self._hass = hass
        self._entity_id = entity_id
        self._soc_entity_id = soc_entity_id

    async def set_battery_mode(self, mode: BatteryMode) -> bool:
        """Ustaw tryb baterii GoodWe przez service call."""
        try:
            mode_map = {
                BatteryMode.CHARGE: "eco_charge",
                BatteryMode.DISCHARGE: "eco_discharge",
                BatteryMode.STANDBY: "general",
            }
            service_mode = mode_map.get(mode, "general")
            await self._hass.services.async_call(
                "goodwe",
                "set_operation_mode",
                {"entity_id": self._entity_id, "mode": service_mode},
                blocking=True,
            )
            _LOGGER.info("GoodWe: ustawiono tryb baterii na %s", mode.value)
            return True
        except Exception as err:
            _LOGGER.error("GoodWe: błąd ustawiania trybu baterii: %s", err)
            return False

    async def get_current_soc(self) -> Optional[float]:
        """Pobierz SoC z encji HA."""
        return _get_entity_float(self._hass, self._soc_entity_id)

    async def get_inverter_type(self) -> str:
        return "goodwe"


class FroniusInverterAdapter(InverterAdapter):
    """Adapter inwertera Fronius przez integrację HA."""

    def __init__(self, hass: HomeAssistant, entity_id: str, soc_entity_id: str) -> None:
        self._hass = hass
        self._entity_id = entity_id
        self._soc_entity_id = soc_entity_id

    async def set_battery_mode(self, mode: BatteryMode) -> bool:
        """Ustaw tryb baterii Fronius przez service call."""
        try:
            mode_map = {
                BatteryMode.CHARGE: "force_charge",
                BatteryMode.DISCHARGE: "force_discharge",
                BatteryMode.STANDBY: "automatic",
            }
            service_mode = mode_map.get(mode, "automatic")
            await self._hass.services.async_call(
                "fronius",
                "set_battery_mode",
                {"entity_id": self._entity_id, "mode": service_mode},
                blocking=True,
            )
            _LOGGER.info("Fronius: ustawiono tryb baterii na %s", mode.value)
            return True
        except Exception as err:
            _LOGGER.error("Fronius: błąd ustawiania trybu baterii: %s", err)
            return False

    async def get_current_soc(self) -> Optional[float]:
        """Pobierz SoC z encji HA."""
        return _get_entity_float(self._hass, self._soc_entity_id)

    async def get_inverter_type(self) -> str:
        return "fronius"


class SMAInverterAdapter(InverterAdapter):
    """Adapter inwertera SMA przez integrację HA."""

    def __init__(self, hass: HomeAssistant, entity_id: str, soc_entity_id: str) -> None:
        self._hass = hass
        self._entity_id = entity_id
        self._soc_entity_id = soc_entity_id

    async def set_battery_mode(self, mode: BatteryMode) -> bool:
        """Ustaw tryb baterii SMA przez service call."""
        try:
            mode_map = {
                BatteryMode.CHARGE: "charge",
                BatteryMode.DISCHARGE: "discharge",
                BatteryMode.STANDBY: "auto",
            }
            service_mode = mode_map.get(mode, "auto")
            await self._hass.services.async_call(
                "sma",
                "set_battery_mode",
                {"entity_id": self._entity_id, "mode": service_mode},
                blocking=True,
            )
            _LOGGER.info("SMA: ustawiono tryb baterii na %s", mode.value)
            return True
        except Exception as err:
            _LOGGER.error("SMA: błąd ustawiania trybu baterii: %s", err)
            return False

    async def get_current_soc(self) -> Optional[float]:
        """Pobierz SoC z encji HA."""
        return _get_entity_float(self._hass, self._soc_entity_id)

    async def get_inverter_type(self) -> str:
        return "sma"


def _get_entity_float(hass: HomeAssistant, entity_id: str) -> Optional[float]:
    """Pobierz wartość float z encji HA.

    Args:
        hass: Instancja Home Assistant.
        entity_id: ID encji sensora.

    Returns:
        Wartość float lub None jeśli encja niedostępna.
    """
    try:
        state = hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        return float(state.state)
    except (ValueError, TypeError, AttributeError):
        return None


def create_inverter_adapter(
    hass: HomeAssistant,
    inverter_type: str,
    entity_id: str,
    soc_entity_id: str,
) -> InverterAdapter:
    """Fabryka adapterów inwerterów.

    Args:
        hass: Instancja Home Assistant.
        inverter_type: Typ inwertera ('solaredge', 'huawei_solar', 'goodwe', 'fronius', 'sma').
        entity_id: ID encji inwertera.
        soc_entity_id: ID encji SoC baterii.

    Returns:
        Odpowiedni adapter inwertera.

    Raises:
        ValueError: Gdy typ inwertera nie jest obsługiwany.
    """
    adapters = {
        "solaredge": SolarEdgeInverterAdapter,
        "huawei_solar": HuaweiSolarInverterAdapter,
        "goodwe": GoodWeInverterAdapter,
        "fronius": FroniusInverterAdapter,
        "sma": SMAInverterAdapter,
    }

    adapter_class = adapters.get(inverter_type)
    if adapter_class is None:
        raise ValueError(
            f"Nieobsługiwany typ inwertera: {inverter_type}. "
            f"Obsługiwane: {', '.join(adapters.keys())}"
        )

    return adapter_class(hass, entity_id, soc_entity_id)


class PVForecastCoordinator(DataUpdateCoordinator[PVData]):
    """Koordynator prognoz PV i strategii baterii.

    Rozszerza DataUpdateCoordinator z 60-minutowym interwałem aktualizacji.
    Pobiera prognozy PV, oblicza strategię baterii i udostępnia sensory.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        solar_forecast_client: SolarForecastClient,
        pv_optimizer: PVOptimizer,
        battery_config: BatteryConfig,
        tariff_coordinator: Any,
        inverter_adapter: Optional[InverterAdapter] = None,
        energy_sensor_entity_id: Optional[str] = None,
    ) -> None:
        """Inicjalizacja koordynatora prognoz PV.

        Args:
            hass: Instancja Home Assistant.
            solar_forecast_client: Klient prognoz solarnych.
            pv_optimizer: Optymalizator PV i baterii.
            battery_config: Konfiguracja baterii.
            tariff_coordinator: TariffDataCoordinator (dla kosztów godzinowych).
            inverter_adapter: Opcjonalny adapter inwertera do wysyłania komend.
            energy_sensor_entity_id: ID encji sensora energii (do profilu zużycia).
        """
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_pv_forecast_coordinator",
            update_interval=_DEFAULT_PV_FORECAST_UPDATE_INTERVAL,
        )
        self._solar_client = solar_forecast_client
        self._pv_optimizer = pv_optimizer
        self._battery_config = battery_config
        self._tariff_coordinator = tariff_coordinator
        self._inverter_adapter = inverter_adapter
        self._energy_sensor_entity_id = energy_sensor_entity_id

        # Cache for consumption profile
        self._consumption_profile: list[float] = [0.0] * 24

    async def _async_update_data(self) -> PVData:
        """Pobierz prognozę PV i oblicz strategię baterii.

        Kroki:
        1. Pobierz prognozę PV (z fallbackiem do ostatniej prognozy)
        2. Pobierz koszty godzinowe z TariffDataCoordinator
        3. Pobierz profil zużycia (7-dniowa średnia)
        4. Oblicz strategię baterii
        5. Zwróć PVData z wynikami

        Returns:
            Obiekt PVData z prognozami i strategią.
        """
        # Step 1: Fetch PV forecast with fallback
        forecast, is_stale = await self._solar_client.fetch_forecast_with_fallback()

        # Step 2: Get hourly costs from TariffDataCoordinator
        hourly_costs = self._get_hourly_costs()

        # Step 3: Get 7-day average consumption profile
        consumption_profile = await self._get_consumption_profile()

        # Step 4: Calculate battery strategy
        strategy = self._pv_optimizer.calculate_battery_strategy(
            pv_forecast=forecast,
            costs=hourly_costs,
            battery=self._battery_config,
            consumption_profile=consumption_profile,
        )

        # Step 5: Calculate production totals
        now = _get_poland_now()
        today_production = self._calculate_daily_production(forecast, now.date())
        tomorrow_production = self._calculate_daily_production(
            forecast, now.date() + timedelta(days=1)
        )

        # Calculate autoconsumption (min of production and consumption per hour)
        autoconsumption = self._calculate_autoconsumption(
            forecast, consumption_profile
        )

        # Optionally send battery mode command to inverter
        if self._inverter_adapter is not None:
            await self._send_battery_mode(strategy.mode)

        pv_data = PVData(
            today_production_kwh=today_production,
            tomorrow_production_kwh=tomorrow_production,
            autoconsumption_kwh=autoconsumption,
            battery_mode=strategy.mode,
            estimated_savings_pln=strategy.estimated_savings_pln,
            is_forecast_stale=is_stale,
            battery_strategy=strategy,
        )

        _LOGGER.debug(
            "PV forecast update: today=%.2f kWh, tomorrow=%.2f kWh, "
            "autocons=%.2f kWh, mode=%s, savings=%s PLN, stale=%s",
            pv_data.today_production_kwh,
            pv_data.tomorrow_production_kwh,
            pv_data.autoconsumption_kwh,
            pv_data.battery_mode.value,
            pv_data.estimated_savings_pln,
            pv_data.is_forecast_stale,
        )

        return pv_data

    def _get_hourly_costs(self) -> list[HourlyCost]:
        """Pobierz koszty godzinowe z TariffDataCoordinator.

        Returns:
            Lista HourlyCost (24 elementy) lub pusta lista.
        """
        if self._tariff_coordinator is None:
            return []
        return self._tariff_coordinator.get_hourly_costs()

    async def _get_consumption_profile(self) -> list[float]:
        """Pobierz 7-dniowy średni profil zużycia godzinowego.

        Próbuje pobrać dane z historii encji sensora energii HA.
        Jeśli niedostępne, zwraca ostatni znany profil lub zerowy.

        Returns:
            Lista 24 wartości średniego zużycia godzinowego (kWh).
        """
        if self._energy_sensor_entity_id is None:
            return self._consumption_profile

        try:
            # Try to get consumption history from HA recorder
            profile = await self._fetch_energy_history()
            if profile and len(profile) == 24:
                self._consumption_profile = profile
        except Exception as err:
            _LOGGER.debug(
                "Nie udało się pobrać profilu zużycia z historii: %s", err
            )

        return self._consumption_profile

    async def _fetch_energy_history(self) -> Optional[list[float]]:
        """Pobierz historię zużycia energii z HA recorder.

        Oblicza średnie godzinowe zużycie z ostatnich 7 dni.

        Returns:
            Lista 24 wartości lub None jeśli dane niedostępne.
        """
        # In production, this would use hass.components.recorder
        # to fetch 7-day energy history and calculate hourly averages.
        # For now, return None to use cached/default profile.
        try:
            recorder = self.hass.components.recorder
            if recorder is None:
                return None

            now = _get_poland_now()
            start_time = now - timedelta(days=7)

            # Get statistics for the energy sensor
            stats = await recorder.async_get_statistics(
                start_time=start_time,
                end_time=now,
                statistic_ids=[self._energy_sensor_entity_id],
                period="hour",
            )

            if not stats or self._energy_sensor_entity_id not in stats:
                return None

            # Calculate hourly averages
            hourly_sums: dict[int, list[float]] = {h: [] for h in range(24)}
            for stat in stats[self._energy_sensor_entity_id]:
                hour = stat.get("start", now).hour
                change = stat.get("change", 0.0)
                if change is not None and change >= 0:
                    hourly_sums[hour].append(float(change))

            profile = []
            for hour in range(24):
                values = hourly_sums[hour]
                if values:
                    profile.append(sum(values) / len(values))
                else:
                    profile.append(0.0)

            return profile
        except Exception as err:
            _LOGGER.debug("Błąd pobierania historii energii: %s", err)
            return None

    def _calculate_daily_production(
        self, forecast: list[HourlyPVForecast], target_date
    ) -> float:
        """Oblicz łączną produkcję PV na dany dzień.

        Args:
            forecast: Lista prognoz godzinowych.
            target_date: Data docelowa.

        Returns:
            Łączna produkcja w kWh.
        """
        total = 0.0
        for f in forecast:
            if f.timestamp.date() == target_date:
                total += f.production_kwh
        # If no date-specific data, sum all for today
        if total == 0.0 and forecast:
            total = sum(f.production_kwh for f in forecast)
        return round(total, 2)

    def _calculate_autoconsumption(
        self,
        forecast: list[HourlyPVForecast],
        consumption_profile: list[float],
    ) -> float:
        """Oblicz prognozowaną autokonsumpcję na dziś.

        Autokonsumpcja = min(produkcja PV, zużycie) per godzina.

        Args:
            forecast: Prognoza produkcji PV.
            consumption_profile: Profil zużycia (24h).

        Returns:
            Łączna autokonsumpcja w kWh.
        """
        pv_by_hour: dict[int, float] = {}
        for f in forecast:
            if f.hour in pv_by_hour:
                pv_by_hour[f.hour] += f.production_kwh
            else:
                pv_by_hour[f.hour] = f.production_kwh

        autoconsumption = 0.0
        for hour in range(24):
            production = pv_by_hour.get(hour, 0.0)
            consumption = consumption_profile[hour] if hour < len(consumption_profile) else 0.0
            autoconsumption += min(production, consumption)

        return round(autoconsumption, 2)

    async def _send_battery_mode(self, mode: BatteryMode) -> None:
        """Wyślij komendę trybu baterii do inwertera.

        Args:
            mode: Docelowy tryb baterii.
        """
        if self._inverter_adapter is None:
            return

        try:
            success = await self._inverter_adapter.set_battery_mode(mode)
            if success:
                _LOGGER.info(
                    "Wysłano komendę trybu baterii: %s", mode.value
                )
            else:
                _LOGGER.warning(
                    "Nie udało się ustawić trybu baterii: %s", mode.value
                )
        except Exception as err:
            _LOGGER.error(
                "Błąd komunikacji z inwerterem przy ustawianiu trybu %s: %s",
                mode.value,
                err,
            )

    # --- Public API ---

    def get_forecast_production_today(self) -> float:
        """Pobierz prognozowaną produkcję PV na dziś (kWh).

        Returns:
            Produkcja w kWh lub 0.0 jeśli dane niedostępne.
        """
        if self.data is None:
            return 0.0
        return self.data.today_production_kwh

    def get_forecast_production_tomorrow(self) -> float:
        """Pobierz prognozowaną produkcję PV na jutro (kWh).

        Returns:
            Produkcja w kWh lub 0.0 jeśli dane niedostępne.
        """
        if self.data is None:
            return 0.0
        return self.data.tomorrow_production_kwh

    def get_recommended_battery_mode(self) -> BatteryMode:
        """Pobierz rekomendowany tryb baterii.

        Returns:
            BatteryMode (CHARGE/DISCHARGE/STANDBY).
            STANDBY jeśli dane niedostępne.
        """
        if self.data is None:
            return BatteryMode.STANDBY
        return self.data.battery_mode

    def get_estimated_savings(self) -> Decimal:
        """Pobierz szacowane dzienne oszczędności (PLN).

        Returns:
            Oszczędności w PLN (2 miejsca po przecinku).
            Decimal("0.00") jeśli dane niedostępne.
        """
        if self.data is None:
            return Decimal("0.00")
        return self.data.estimated_savings_pln

    def is_forecast_stale(self) -> bool:
        """Sprawdź czy prognoza PV jest nieaktualna.

        Returns:
            True jeśli prognoza jest nieaktualna (>180 min bez aktualizacji).
        """
        if self.data is None:
            return True
        return self.data.is_forecast_stale

    def get_autoconsumption_today(self) -> float:
        """Pobierz prognozowaną autokonsumpcję na dziś (kWh).

        Returns:
            Autokonsumpcja w kWh lub 0.0 jeśli dane niedostępne.
        """
        if self.data is None:
            return 0.0
        return self.data.autoconsumption_kwh

    def set_consumption_profile(self, profile: list[float]) -> None:
        """Ustaw profil zużycia ręcznie (do testów lub konfiguracji).

        Args:
            profile: Lista 24 wartości średniego zużycia godzinowego (kWh).
        """
        if len(profile) >= 24:
            self._consumption_profile = profile[:24]
        else:
            self._consumption_profile = profile + [0.0] * (24 - len(profile))
        _LOGGER.info("Zaktualizowano profil zużycia energii (24h)")
