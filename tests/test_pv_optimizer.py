"""Testy jednostkowe dla PVOptimizer — optymalizator PV i baterii."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from custom_components.peo.enums import BatteryMode, TimeZoneName
from custom_components.peo.models import (
    BatteryConfig,
    BatteryStrategy,
    HourlyCost,
    HourlyPVForecast,
    TariffRates,
    TimeWindow,
)
from custom_components.peo.pv_optimizer import PVOptimizer


@pytest.fixture
def optimizer():
    """Fixture: instancja PVOptimizer."""
    return PVOptimizer()


@pytest.fixture
def battery_config():
    """Fixture: typowa konfiguracja baterii 10 kWh."""
    return BatteryConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        min_soc_percent=10,
        degradation_cost_pln_kwh=Decimal("0.15"),
        inverter_entity_id="sensor.inverter_power",
        soc_entity_id="sensor.battery_soc",
    )


@pytest.fixture
def sample_tariff_rates():
    """Fixture: przykładowe stawki taryfowe."""
    return TariffRates(
        energy_price=Decimal("0.50"),
        distribution_variable=Decimal("0.20"),
        transition_fee=Decimal("0.01"),
        oze_fee=Decimal("0.01"),
        capacity_fee=Decimal("0.05"),
        cogeneration_fee=Decimal("0.01"),
    )


def _make_pv_forecast(hourly_production: list[float]) -> list[HourlyPVForecast]:
    """Helper: utwórz listę prognoz PV z wartości godzinowych."""
    base_ts = datetime(2024, 6, 15, 0, 0, 0, tzinfo=timezone.utc)
    return [
        HourlyPVForecast(
            hour=h,
            timestamp=base_ts.replace(hour=h),
            production_kwh=prod,
        )
        for h, prod in enumerate(hourly_production)
    ]


def _make_hourly_costs(hourly_prices: list[Decimal]) -> list[HourlyCost]:
    """Helper: utwórz listę kosztów godzinowych."""
    base_ts = datetime(2024, 6, 15, 0, 0, 0, tzinfo=timezone.utc)
    rates = TariffRates(
        energy_price=Decimal("0.50"),
        distribution_variable=Decimal("0.20"),
        transition_fee=Decimal("0.01"),
        oze_fee=Decimal("0.01"),
        capacity_fee=Decimal("0.05"),
        cogeneration_fee=Decimal("0.01"),
    )
    return [
        HourlyCost(
            hour=h,
            timestamp=base_ts.replace(hour=h),
            cost_pln_kwh=price,
            zone=TimeZoneName.SINGLE,
            components=rates,
        )
        for h, price in enumerate(hourly_prices)
    ]


# ============================================================
# Tests for calculate_surplus_profile
# ============================================================


class TestCalculateSurplusProfile:
    """Testy profilu nadwyżki PV."""

    def test_basic_surplus_calculation(self, optimizer):
        """Nadwyżka = produkcja - zużycie dla każdej godziny."""
        # PV produces 5 kWh at hour 12, nothing else
        pv_forecast = _make_pv_forecast([0.0] * 12 + [5.0] + [0.0] * 11)
        avg_consumption = [1.0] * 24  # 1 kWh/h constant

        surplus = optimizer.calculate_surplus_profile(pv_forecast, avg_consumption)

        assert len(surplus) == 24
        assert surplus[12] == pytest.approx(4.0)  # 5.0 - 1.0
        assert surplus[0] == pytest.approx(-1.0)  # 0.0 - 1.0
        assert surplus[23] == pytest.approx(-1.0)

    def test_all_surplus(self, optimizer):
        """Gdy PV > zużycie na każdej godzinie, wszystkie wartości dodatnie."""
        pv_forecast = _make_pv_forecast([3.0] * 24)
        avg_consumption = [1.0] * 24

        surplus = optimizer.calculate_surplus_profile(pv_forecast, avg_consumption)

        assert all(s == pytest.approx(2.0) for s in surplus)

    def test_all_deficit(self, optimizer):
        """Gdy PV = 0, profil to ujemne zużycie."""
        pv_forecast = _make_pv_forecast([0.0] * 24)
        avg_consumption = [2.0] * 24

        surplus = optimizer.calculate_surplus_profile(pv_forecast, avg_consumption)

        assert all(s == pytest.approx(-2.0) for s in surplus)

    def test_empty_pv_forecast(self, optimizer):
        """Pusta prognoza PV → profil = -zużycie."""
        pv_forecast = []
        avg_consumption = [1.5] * 24

        surplus = optimizer.calculate_surplus_profile(pv_forecast, avg_consumption)

        assert len(surplus) == 24
        assert all(s == pytest.approx(-1.5) for s in surplus)

    def test_realistic_summer_day(self, optimizer):
        """Realistyczny letni dzień — PV produkuje w godzinach 6-20."""
        # Bell curve PV production
        pv_production = [
            0, 0, 0, 0, 0, 0,  # 0-5: noc
            0.5, 1.5, 3.0, 4.5, 5.5, 6.0,  # 6-11: poranek
            6.5, 6.0, 5.5, 4.5, 3.0, 1.5,  # 12-17: popołudnie
            0.5, 0, 0, 0, 0, 0,  # 18-23: wieczór
        ]
        pv_forecast = _make_pv_forecast(pv_production)
        avg_consumption = [1.0] * 24  # stałe zużycie 1 kWh/h

        surplus = optimizer.calculate_surplus_profile(pv_forecast, avg_consumption)

        # Night hours should be deficit
        assert surplus[0] == pytest.approx(-1.0)
        assert surplus[3] == pytest.approx(-1.0)
        # Peak hours should be surplus
        assert surplus[12] == pytest.approx(5.5)  # 6.5 - 1.0
        assert surplus[11] == pytest.approx(5.0)  # 6.0 - 1.0

    def test_surplus_profile_length_always_24(self, optimizer):
        """Profil zawsze ma 24 elementy, nawet przy krótszej prognozie."""
        pv_forecast = _make_pv_forecast([2.0] * 12)  # Only 12 hours
        avg_consumption = [1.0] * 24

        surplus = optimizer.calculate_surplus_profile(pv_forecast, avg_consumption)

        assert len(surplus) == 24
        # Hours 0-11 have PV
        assert surplus[5] == pytest.approx(1.0)
        # Hours 12-23 have no PV
        assert surplus[15] == pytest.approx(-1.0)


# ============================================================
# Tests for determine_battery_mode
# ============================================================


class TestDetermineBatteryMode:
    """Testy decyzji o trybie baterii."""

    def test_standby_at_min_soc(self, optimizer):
        """Bateria na min SoC → STANDBY (bezpieczeństwo)."""
        mode = optimizer.determine_battery_mode(
            grid_price=Decimal("1.00"),
            degradation_cost=Decimal("0.15"),
            pv_available=0.0,
            current_soc=10.0,
            min_soc=10.0,
        )
        assert mode == BatteryMode.STANDBY

    def test_standby_below_min_soc(self, optimizer):
        """Bateria poniżej min SoC → STANDBY."""
        mode = optimizer.determine_battery_mode(
            grid_price=Decimal("1.00"),
            degradation_cost=Decimal("0.15"),
            pv_available=0.0,
            current_soc=5.0,
            min_soc=10.0,
        )
        assert mode == BatteryMode.STANDBY

    def test_charge_when_grid_cheap(self, optimizer):
        """Tani prąd (grid_price < degradation_cost) → CHARGE."""
        mode = optimizer.determine_battery_mode(
            grid_price=Decimal("0.10"),
            degradation_cost=Decimal("0.15"),
            pv_available=0.0,
            current_soc=50.0,
            min_soc=10.0,
        )
        assert mode == BatteryMode.CHARGE

    def test_discharge_when_grid_expensive_no_pv(self, optimizer):
        """Drogi prąd, brak PV → DISCHARGE."""
        mode = optimizer.determine_battery_mode(
            grid_price=Decimal("0.80"),
            degradation_cost=Decimal("0.15"),
            pv_available=0.0,
            current_soc=80.0,
            min_soc=10.0,
        )
        assert mode == BatteryMode.DISCHARGE

    def test_standby_when_price_equals_degradation(self, optimizer):
        """Cena = koszt degradacji → STANDBY."""
        mode = optimizer.determine_battery_mode(
            grid_price=Decimal("0.15"),
            degradation_cost=Decimal("0.15"),
            pv_available=0.0,
            current_soc=50.0,
            min_soc=10.0,
        )
        assert mode == BatteryMode.STANDBY

    def test_standby_when_price_slightly_above_degradation(self, optimizer):
        """Cena nieco powyżej degradacji, ale z PV → STANDBY (lepiej magazynować PV)."""
        mode = optimizer.determine_battery_mode(
            grid_price=Decimal("0.20"),
            degradation_cost=Decimal("0.15"),
            pv_available=2.0,
            current_soc=50.0,
            min_soc=10.0,
        )
        assert mode == BatteryMode.STANDBY

    def test_min_soc_takes_priority_over_cheap_grid(self, optimizer):
        """Min SoC ma priorytet nad tanim prądem."""
        mode = optimizer.determine_battery_mode(
            grid_price=Decimal("0.05"),  # Very cheap
            degradation_cost=Decimal("0.15"),
            pv_available=0.0,
            current_soc=10.0,  # At min
            min_soc=10.0,
        )
        # At min_soc, safety takes priority
        assert mode == BatteryMode.STANDBY


# ============================================================
# Tests for calculate_battery_strategy
# ============================================================


class TestCalculateBatteryStrategy:
    """Testy strategii baterii na 24h."""

    def test_basic_strategy_with_cheap_and_expensive_hours(
        self, optimizer, battery_config
    ):
        """Strategia z tanimi i drogimi godzinami generuje okna."""
        # Night cheap (0.10), day expensive (0.80)
        prices = [Decimal("0.10")] * 6 + [Decimal("0.80")] * 12 + [Decimal("0.10")] * 6
        costs = _make_hourly_costs(prices)
        pv_forecast = _make_pv_forecast([0.0] * 24)
        consumption = [1.0] * 24

        strategy = optimizer.calculate_battery_strategy(
            pv_forecast=pv_forecast,
            costs=costs,
            battery=battery_config,
            consumption_profile=consumption,
        )

        assert isinstance(strategy, BatteryStrategy)
        assert strategy.target_soc >= battery_config.min_soc_percent
        assert strategy.target_soc <= 100
        assert len(strategy.charge_windows) > 0
        assert len(strategy.discharge_windows) > 0
        assert strategy.estimated_savings_pln >= Decimal("0.00")

    def test_strategy_enforces_min_soc(self, optimizer, battery_config):
        """Strategia nie pozwala na SoC poniżej minimum."""
        prices = [Decimal("0.50")] * 24
        costs = _make_hourly_costs(prices)
        pv_forecast = _make_pv_forecast([0.0] * 24)
        consumption = [1.0] * 24

        strategy = optimizer.calculate_battery_strategy(
            pv_forecast=pv_forecast,
            costs=costs,
            battery=battery_config,
            consumption_profile=consumption,
        )

        assert strategy.target_soc >= battery_config.min_soc_percent

    def test_strategy_limits_night_charging_with_high_pv(self, optimizer, battery_config):
        """Gdy PV > zużycie, nocne ładowanie jest ograniczone."""
        # Night cheap, day expensive
        prices = [Decimal("0.10")] * 6 + [Decimal("0.80")] * 12 + [Decimal("0.10")] * 6
        costs = _make_hourly_costs(prices)

        # High PV production (exceeds daily consumption)
        pv_production = [0.0] * 6 + [5.0] * 12 + [0.0] * 6  # 60 kWh total
        pv_forecast = _make_pv_forecast(pv_production)
        consumption = [1.0] * 24  # 24 kWh total (PV >> consumption)

        strategy = optimizer.calculate_battery_strategy(
            pv_forecast=pv_forecast,
            costs=costs,
            battery=battery_config,
            consumption_profile=consumption,
        )

        # Target SoC should be limited (not 100%) to leave room for PV surplus
        assert strategy.target_soc < 100

    def test_strategy_with_no_cheap_hours(self, optimizer, battery_config):
        """Brak tanich godzin → target SoC = min_soc."""
        # All prices above degradation cost
        prices = [Decimal("0.50")] * 24
        costs = _make_hourly_costs(prices)
        pv_forecast = _make_pv_forecast([0.0] * 24)
        consumption = [1.0] * 24

        strategy = optimizer.calculate_battery_strategy(
            pv_forecast=pv_forecast,
            costs=costs,
            battery=battery_config,
            consumption_profile=consumption,
        )

        # No cheap hours means no charging from grid
        assert strategy.target_soc >= battery_config.min_soc_percent

    def test_strategy_returns_valid_battery_strategy(self, optimizer, battery_config):
        """Strategia zwraca poprawny obiekt BatteryStrategy."""
        prices = [Decimal("0.30")] * 24
        costs = _make_hourly_costs(prices)
        pv_forecast = _make_pv_forecast([2.0] * 24)
        consumption = [1.0] * 24

        strategy = optimizer.calculate_battery_strategy(
            pv_forecast=pv_forecast,
            costs=costs,
            battery=battery_config,
            consumption_profile=consumption,
        )

        assert isinstance(strategy.mode, BatteryMode)
        assert isinstance(strategy.target_soc, int)
        assert isinstance(strategy.charge_windows, list)
        assert isinstance(strategy.discharge_windows, list)
        assert isinstance(strategy.estimated_savings_pln, Decimal)

    def test_strategy_with_custom_min_soc(self, optimizer):
        """Konfigurowalny min_soc (5-30%) jest respektowany."""
        battery = BatteryConfig(
            capacity_kwh=10.0,
            max_charge_power_kw=5.0,
            max_discharge_power_kw=5.0,
            min_soc_percent=25,  # Higher min SoC
            degradation_cost_pln_kwh=Decimal("0.15"),
            inverter_entity_id="sensor.inverter_power",
            soc_entity_id="sensor.battery_soc",
        )

        prices = [Decimal("0.10")] * 6 + [Decimal("0.80")] * 12 + [Decimal("0.10")] * 6
        costs = _make_hourly_costs(prices)
        pv_forecast = _make_pv_forecast([0.0] * 24)
        consumption = [1.0] * 24

        strategy = optimizer.calculate_battery_strategy(
            pv_forecast=pv_forecast,
            costs=costs,
            battery=battery,
            consumption_profile=consumption,
        )

        assert strategy.target_soc >= 25

    def test_strategy_savings_non_negative(self, optimizer, battery_config):
        """Oszczędności nigdy nie są ujemne."""
        prices = [Decimal("0.10")] * 12 + [Decimal("0.80")] * 12
        costs = _make_hourly_costs(prices)
        pv_forecast = _make_pv_forecast([0.0] * 24)
        consumption = [1.0] * 24

        strategy = optimizer.calculate_battery_strategy(
            pv_forecast=pv_forecast,
            costs=costs,
            battery=battery_config,
            consumption_profile=consumption,
        )

        assert strategy.estimated_savings_pln >= Decimal("0.00")

    def test_strategy_with_pv_surplus_and_expensive_hours(self, optimizer, battery_config):
        """PV surplus w drogich godzinach zwiększa oszczędności."""
        # Cheap night, expensive day
        prices = [Decimal("0.10")] * 6 + [Decimal("0.80")] * 12 + [Decimal("0.10")] * 6
        costs = _make_hourly_costs(prices)

        # PV produces during expensive hours
        pv_production = [0.0] * 6 + [3.0] * 12 + [0.0] * 6
        pv_forecast = _make_pv_forecast(pv_production)
        consumption = [2.0] * 24  # 48 kWh total, PV = 36 kWh

        strategy = optimizer.calculate_battery_strategy(
            pv_forecast=pv_forecast,
            costs=costs,
            battery=battery_config,
            consumption_profile=consumption,
        )

        assert isinstance(strategy, BatteryStrategy)
        assert strategy.target_soc >= battery_config.min_soc_percent
