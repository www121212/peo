"""Modele danych (dataclasses) dla Polish Energy Optimizer (PEO)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Optional

from .enums import (
    BatteryMode,
    ChargingStrategy,
    PriceDataStatus,
    TariffType,
    TimeZoneName,
    OSDOperator,
)


@dataclass(frozen=True)
class HourlyPrice:
    """Cena energii na daną godzinę z RCE PSE."""

    hour: int  # 0-23
    price_pln_mwh: Decimal  # PLN/MWh z RCE
    price_pln_kwh: Decimal  # PLN/kWh (przeliczone)
    date: date


@dataclass(frozen=True)
class PriceStats:
    """Statystyki cenowe dla zestawu danych godzinowych."""

    min_price: Decimal
    max_price: Decimal
    avg_price: Decimal
    min_hour: int
    max_hour: int


@dataclass(frozen=True)
class PriceData:
    """Pełne dane cenowe — dziś, jutro, status i statystyki."""

    today: list[HourlyPrice]  # 24 elementów
    tomorrow: Optional[list[HourlyPrice]]  # None jeśli niedostępne
    status: PriceDataStatus
    last_successful_fetch: datetime
    stats: PriceStats


@dataclass(frozen=True)
class TariffRates:
    """Stawki taryfowe — wszystkie składniki kosztu kWh."""

    energy_price: Decimal  # PLN/kWh — cena energii
    distribution_variable: Decimal  # opłata dystrybucyjna zmienna
    transition_fee: Decimal  # opłata przejściowa
    oze_fee: Decimal  # opłata OZE
    capacity_fee: Decimal  # opłata mocowa
    cogeneration_fee: Decimal  # opłata kogeneracyjna


@dataclass(frozen=True)
class TariffDefinition:
    """Definicja taryfy — typ, strefy i godziny obowiązywania per OSD."""

    tariff_type: TariffType
    zones: list[TimeZoneName]
    zone_hours: dict[OSDOperator, dict[TimeZoneName, list[tuple[time, time]]]]


@dataclass(frozen=True)
class HourlyCost:
    """Pełny koszt energii na daną godzinę z rozbiciem na składniki."""

    hour: int
    timestamp: datetime
    cost_pln_kwh: Decimal  # pełny koszt z 4 miejscami po przecinku
    zone: TimeZoneName
    components: TariffRates


@dataclass(frozen=True)
class VehicleConfig:
    """Konfiguracja pojazdu elektrycznego."""

    vehicle_id: str
    name: str
    battery_capacity_kwh: float
    max_charging_power_kw: float
    min_charging_power_kw: float  # domyślnie 1.4
    soc_entity_id: str
    target_soc: int  # 10-100%
    deadline: Optional[datetime]
    priority: int  # 1-4
    strategy: ChargingStrategy


@dataclass(frozen=True)
class ChargerConfig:
    """Konfiguracja ładowarki EV."""

    charger_id: str
    name: str
    protocol: str  # ocpp16, ocpp20, tesla, wallbox, openevse
    host: Optional[str]
    api_key: Optional[str]
    entity_id: Optional[str]
    max_power_kw: float
    max_current_a: float


@dataclass(frozen=True)
class VehicleChargerPair:
    """Para pojazd-ładowarka."""

    vehicle: VehicleConfig
    charger: ChargerConfig


@dataclass(frozen=True)
class TimeWindow:
    """Okno czasowe z przypisaną mocą."""

    start: datetime
    end: datetime
    power_kw: float


@dataclass(frozen=True)
class ChargingSchedule:
    """Harmonogram ładowania pojazdu elektrycznego."""

    vehicle_id: str
    windows: list[TimeWindow]
    estimated_cost_pln: Decimal
    estimated_energy_kwh: float
    estimated_completion: datetime
    is_feasible: bool
    best_achievable_soc: Optional[int]  # jeśli nie feasible


@dataclass(frozen=True)
class ChargingSession:
    """Zarejestrowana sesja ładowania EV."""

    session_id: str
    vehicle_id: str
    start_time: datetime
    end_time: Optional[datetime]
    energy_kwh: Decimal
    actual_cost_pln: Decimal
    hypothetical_cost_pln: Decimal
    is_manual: bool
    duration_minutes: int


@dataclass(frozen=True)
class LoadConfig:
    """Konfiguracja odbiornika odraczalnego."""

    load_id: str
    name: str
    entity_id: str
    threshold_on: Decimal  # PLN/kWh — próg włączenia
    threshold_off: Decimal  # PLN/kWh — próg wyłączenia
    min_daily_hours: float  # 0.5-24
    max_daily_hours: float  # 0.5-24
    allowed_start: time  # HH:MM
    allowed_end: time  # HH:MM
    priority: int  # 1-16
    power_w: int  # pobór mocy w watach
    failsafe_state: bool  # True=ON, False=OFF w trybie awaryjnym


@dataclass(frozen=True)
class LoadDecision:
    """Decyzja dotycząca odbiornika odraczalnego."""

    load_id: str
    action: str  # "on", "off", "blocked", "manual_override"
    reason: str
    timestamp: datetime
    savings_pln: Decimal


@dataclass(frozen=True)
class BatteryConfig:
    """Konfiguracja magazynu energii (baterii)."""

    capacity_kwh: float
    max_charge_power_kw: float
    max_discharge_power_kw: float
    min_soc_percent: int  # 5-30, domyślnie 10
    degradation_cost_pln_kwh: Decimal
    inverter_entity_id: str
    soc_entity_id: str


@dataclass(frozen=True)
class BatteryStrategy:
    """Strategia pracy baterii na 24h."""

    mode: BatteryMode
    target_soc: int
    charge_windows: list[TimeWindow]
    discharge_windows: list[TimeWindow]
    estimated_savings_pln: Decimal


@dataclass(frozen=True)
class HourlyPVForecast:
    """Prognoza produkcji PV na daną godzinę."""

    hour: int
    timestamp: datetime
    production_kwh: float


@dataclass(frozen=True)
class TariffRanking:
    """Pozycja taryfy w rankingu porównawczym."""

    tariff: TariffType
    monthly_cost_pln: Decimal
    difference_pln: Decimal  # vs aktualna taryfa
    difference_percent: float


@dataclass(frozen=True)
class TariffComparison:
    """Wynik porównania taryf na podstawie historycznego zużycia."""

    current_tariff: TariffType
    rankings: list[TariffRanking]
    recommended: TariffType
    monthly_savings_pln: Decimal
    data_days: int
    is_sufficient_data: bool


@dataclass(frozen=True)
class OptimizationDecision:
    """Zarejestrowana decyzja optymalizacyjna."""

    timestamp: datetime
    decision: str
    reason: str
    savings_pln: Decimal
    module: str


@dataclass
class ChargingConstraints:
    """Ograniczenia ładowania EV (mutable — aktualizowane w runtime)."""

    grid_limit_kw: float
    current_building_load_kw: float
    charger_max_power_kw: float
    charger_max_current_a: float
    min_charging_power_kw: float
    deadline: Optional[datetime]
    allow_discontinuous: bool
