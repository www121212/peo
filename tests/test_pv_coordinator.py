"""Testy jednostkowe dla PVForecastCoordinator i adapterow inwerterow."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

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
from custom_components.peo.pv_coordinator import (
    PVForecastCoordinator,
    PVData,
    InverterAdapter,
    SolarEdgeInverterAdapter,
    HuaweiSolarInverterAdapter,
    GoodWeInverterAdapter,
    FroniusInverterAdapter,
    SMAInverterAdapter,
    create_inverter_adapter,
    _DEFAULT_PV_FORECAST_UPDATE_INTERVAL,
    _get_entity_float,
)
from custom_components.peo.pv_optimizer import PVOptimizer
from custom_components.peo.solar_forecast_client import SolarForecastClient


@pytest.fixture
def mock_hass():
    """Fixture: mock Home Assistant."""
    hass = MagicMock()
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states = MagicMock()
    hass.components = MagicMock()
    hass.components.recorder = None
    return hass


@pytest.fixture
def battery_config():
    """Fixture: konfiguracja baterii."""
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
def sample_forecast():
    """Fixture: przykladowa prognoza PV na 24h."""
    now = datetime(2024, 6, 15, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    forecasts = []
    production_profile = [
        0, 0, 0, 0, 0, 0,
        0.2, 0.8, 1.5, 2.5, 3.5, 4.0,
        4.5, 4.2, 3.8, 3.0, 2.2, 1.5,
        0.8, 0.3, 0.0, 0, 0, 0,
    ]
    for hour, prod in enumerate(production_profile):
        forecasts.append(
            HourlyPVForecast(
                hour=hour,
                timestamp=now + timedelta(hours=hour),
                production_kwh=prod,
            )
        )
    return forecasts


@pytest.fixture
def sample_hourly_costs():
    """Fixture: przykladowe koszty godzinowe na 24h."""
    now = datetime(2024, 6, 15, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    costs = []
    cost_values = [
        "0.35", "0.32", "0.30", "0.28", "0.30", "0.35",
        "0.45", "0.55", "0.65", "0.70", "0.72", "0.75",
        "0.73", "0.70", "0.68", "0.72", "0.78", "0.80",
        "0.75", "0.65", "0.55", "0.45", "0.40", "0.37",
    ]
    rates = TariffRates(
        energy_price=Decimal("0.50"),
        distribution_variable=Decimal("0.15"),
        transition_fee=Decimal("0.0009"),
        oze_fee=Decimal("0.0027"),
        capacity_fee=Decimal("0.0762"),
        cogeneration_fee=Decimal("0.0058"),
    )
    for hour, cost_str in enumerate(cost_values):
        costs.append(
            HourlyCost(
                hour=hour,
                timestamp=now + timedelta(hours=hour),
                cost_pln_kwh=Decimal(cost_str),
                zone=TimeZoneName.SZCZYT if 6 <= hour <= 21 else TimeZoneName.POZASZCZYT,
                components=rates,
            )
        )
    return costs


@pytest.fixture
def consumption_profile():
    """Fixture: profil zuzycia 24h."""
    return [
        0.3, 0.2, 0.2, 0.2, 0.2, 0.3,
        0.5, 0.8, 1.0, 0.8, 0.7, 0.6,
        0.5, 0.5, 0.6, 0.7, 0.8, 1.0,
        1.2, 1.0, 0.8, 0.6, 0.4, 0.3,
    ]


@pytest.fixture
def mock_solar_client(sample_forecast):
    """Fixture: mock SolarForecastClient."""
    client = MagicMock(spec=SolarForecastClient)
    client.fetch_forecast_with_fallback = AsyncMock(
        return_value=(sample_forecast, False)
    )
    client.is_forecast_stale = MagicMock(return_value=False)
    return client


@pytest.fixture
def mock_tariff_coordinator(sample_hourly_costs):
    """Fixture: mock TariffDataCoordinator."""
    coord = MagicMock()
    coord.get_hourly_costs = MagicMock(return_value=sample_hourly_costs)
    return coord


@pytest.fixture
def pv_optimizer():
    """Fixture: PVOptimizer (real instance)."""
    return PVOptimizer()


@pytest.fixture
def coordinator(
    mock_hass,
    mock_solar_client,
    pv_optimizer,
    battery_config,
    mock_tariff_coordinator,
    consumption_profile,
):
    """Fixture: PVForecastCoordinator z mockami."""
    coord = PVForecastCoordinator(
        hass=mock_hass,
        solar_forecast_client=mock_solar_client,
        pv_optimizer=pv_optimizer,
        battery_config=battery_config,
        tariff_coordinator=mock_tariff_coordinator,
        energy_sensor_entity_id=None,
    )
    coord.set_consumption_profile(consumption_profile)
    return coord



class TestPVForecastCoordinatorInit:
    """Testy inicjalizacji koordynatora PV."""

    def test_update_interval_is_60_minutes(self, coordinator):
        """Interwal aktualizacji wynosi 60 minut."""
        assert coordinator.update_interval == _DEFAULT_PV_FORECAST_UPDATE_INTERVAL
        assert coordinator.update_interval == timedelta(minutes=60)

    def test_initial_data_is_none(self, coordinator):
        """Poczatkowe dane to None."""
        assert coordinator.data is None

    def test_coordinator_name_contains_domain(self, coordinator):
        """Nazwa koordynatora zawiera domene."""
        assert "peo" in coordinator.name

    def test_consumption_profile_default_zeros(
        self, mock_hass, mock_solar_client, pv_optimizer, battery_config, mock_tariff_coordinator
    ):
        """Domyslny profil zuzycia to 24 zera."""
        coord = PVForecastCoordinator(
            hass=mock_hass,
            solar_forecast_client=mock_solar_client,
            pv_optimizer=pv_optimizer,
            battery_config=battery_config,
            tariff_coordinator=mock_tariff_coordinator,
        )
        assert coord._consumption_profile == [0.0] * 24


class TestAsyncUpdateData:
    """Testy _async_update_data()."""

    @pytest.mark.asyncio
    async def test_returns_pv_data(self, coordinator):
        """Aktualizacja zwraca obiekt PVData."""
        result = await coordinator._async_update_data()
        assert isinstance(result, PVData)

    @pytest.mark.asyncio
    async def test_today_production_positive(self, coordinator):
        """Prognozowana produkcja na dzis jest dodatnia."""
        result = await coordinator._async_update_data()
        assert result.today_production_kwh > 0

    @pytest.mark.asyncio
    async def test_battery_mode_is_valid(self, coordinator):
        """Tryb baterii jest prawidlowym BatteryMode."""
        result = await coordinator._async_update_data()
        assert isinstance(result.battery_mode, BatteryMode)
        assert result.battery_mode in (
            BatteryMode.CHARGE,
            BatteryMode.DISCHARGE,
            BatteryMode.STANDBY,
        )

    @pytest.mark.asyncio
    async def test_estimated_savings_is_decimal(self, coordinator):
        """Szacowane oszczednosci to Decimal."""
        result = await coordinator._async_update_data()
        assert isinstance(result.estimated_savings_pln, Decimal)

    @pytest.mark.asyncio
    async def test_is_forecast_stale_false_on_fresh_data(self, coordinator):
        """Prognoza nie jest nieaktualna przy swiezych danych."""
        result = await coordinator._async_update_data()
        assert result.is_forecast_stale is False

    @pytest.mark.asyncio
    async def test_is_forecast_stale_true_on_stale_data(
        self, mock_hass, pv_optimizer, battery_config, mock_tariff_coordinator,
        sample_forecast, consumption_profile,
    ):
        """Prognoza jest nieaktualna gdy klient zwraca stale=True."""
        stale_client = MagicMock(spec=SolarForecastClient)
        stale_client.fetch_forecast_with_fallback = AsyncMock(
            return_value=(sample_forecast, True)
        )
        coord = PVForecastCoordinator(
            hass=mock_hass,
            solar_forecast_client=stale_client,
            pv_optimizer=pv_optimizer,
            battery_config=battery_config,
            tariff_coordinator=mock_tariff_coordinator,
        )
        coord.set_consumption_profile(consumption_profile)
        result = await coord._async_update_data()
        assert result.is_forecast_stale is True

    @pytest.mark.asyncio
    async def test_autoconsumption_not_exceeds_production(self, coordinator, sample_forecast):
        """Autokonsumpcja nie przekracza produkcji PV."""
        result = await coordinator._async_update_data()
        total_production = sum(f.production_kwh for f in sample_forecast)
        assert result.autoconsumption_kwh <= total_production + 0.01

    @pytest.mark.asyncio
    async def test_autoconsumption_not_exceeds_consumption(self, coordinator, consumption_profile):
        """Autokonsumpcja nie przekracza zuzycia."""
        result = await coordinator._async_update_data()
        total_consumption = sum(consumption_profile)
        assert result.autoconsumption_kwh <= total_consumption + 0.01

    @pytest.mark.asyncio
    async def test_calls_solar_client(self, coordinator, mock_solar_client):
        """Koordynator wywoluje klienta prognoz solarnych."""
        await coordinator._async_update_data()
        mock_solar_client.fetch_forecast_with_fallback.assert_called_once()

    @pytest.mark.asyncio
    async def test_calls_tariff_coordinator(self, coordinator, mock_tariff_coordinator):
        """Koordynator pobiera koszty z TariffDataCoordinator."""
        await coordinator._async_update_data()
        mock_tariff_coordinator.get_hourly_costs.assert_called_once()



class TestPublicAPI:
    """Testy publicznego API koordynatora."""

    @pytest.mark.asyncio
    async def test_get_forecast_production_today(self, coordinator):
        """get_forecast_production_today() zwraca float."""
        await coordinator.async_refresh()
        result = coordinator.get_forecast_production_today()
        assert isinstance(result, float)
        assert result > 0

    @pytest.mark.asyncio
    async def test_get_forecast_production_tomorrow(self, coordinator):
        """get_forecast_production_tomorrow() zwraca float."""
        await coordinator.async_refresh()
        result = coordinator.get_forecast_production_tomorrow()
        assert isinstance(result, float)

    @pytest.mark.asyncio
    async def test_get_recommended_battery_mode(self, coordinator):
        """get_recommended_battery_mode() zwraca BatteryMode."""
        await coordinator.async_refresh()
        result = coordinator.get_recommended_battery_mode()
        assert isinstance(result, BatteryMode)

    @pytest.mark.asyncio
    async def test_get_estimated_savings(self, coordinator):
        """get_estimated_savings() zwraca Decimal."""
        await coordinator.async_refresh()
        result = coordinator.get_estimated_savings()
        assert isinstance(result, Decimal)

    @pytest.mark.asyncio
    async def test_is_forecast_stale_method(self, coordinator):
        """is_forecast_stale() zwraca bool."""
        await coordinator.async_refresh()
        result = coordinator.is_forecast_stale()
        assert isinstance(result, bool)
        assert result is False

    @pytest.mark.asyncio
    async def test_get_autoconsumption_today(self, coordinator):
        """get_autoconsumption_today() zwraca float."""
        await coordinator.async_refresh()
        result = coordinator.get_autoconsumption_today()
        assert isinstance(result, float)
        assert result >= 0

    def test_defaults_when_no_data(self, coordinator):
        """Domyslne wartosci gdy brak danych."""
        assert coordinator.get_forecast_production_today() == 0.0
        assert coordinator.get_forecast_production_tomorrow() == 0.0
        assert coordinator.get_recommended_battery_mode() == BatteryMode.STANDBY
        assert coordinator.get_estimated_savings() == Decimal("0.00")
        assert coordinator.is_forecast_stale() is True
        assert coordinator.get_autoconsumption_today() == 0.0



class TestInverterAdapters:
    """Testy adapterow inwerterow."""

    @pytest.mark.asyncio
    async def test_solaredge_set_battery_mode_charge(self, mock_hass):
        """SolarEdge: ustawienie trybu CHARGE."""
        adapter = SolarEdgeInverterAdapter(
            mock_hass, "sensor.solaredge_inverter", "sensor.solaredge_soc"
        )
        result = await adapter.set_battery_mode(BatteryMode.CHARGE)
        assert result is True
        mock_hass.services.async_call.assert_called_once_with(
            "solaredge_modbus",
            "set_storage_command_mode",
            {"entity_id": "sensor.solaredge_inverter", "mode": "charge_from_grid"},
            blocking=True,
        )

    @pytest.mark.asyncio
    async def test_solaredge_set_battery_mode_discharge(self, mock_hass):
        """SolarEdge: ustawienie trybu DISCHARGE."""
        adapter = SolarEdgeInverterAdapter(
            mock_hass, "sensor.solaredge_inverter", "sensor.solaredge_soc"
        )
        result = await adapter.set_battery_mode(BatteryMode.DISCHARGE)
        assert result is True
        mock_hass.services.async_call.assert_called_once_with(
            "solaredge_modbus",
            "set_storage_command_mode",
            {"entity_id": "sensor.solaredge_inverter", "mode": "discharge_to_grid"},
            blocking=True,
        )

    @pytest.mark.asyncio
    async def test_solaredge_set_battery_mode_standby(self, mock_hass):
        """SolarEdge: ustawienie trybu STANDBY."""
        adapter = SolarEdgeInverterAdapter(
            mock_hass, "sensor.solaredge_inverter", "sensor.solaredge_soc"
        )
        result = await adapter.set_battery_mode(BatteryMode.STANDBY)
        assert result is True
        mock_hass.services.async_call.assert_called_once_with(
            "solaredge_modbus",
            "set_storage_command_mode",
            {"entity_id": "sensor.solaredge_inverter", "mode": "maximize_self_consumption"},
            blocking=True,
        )

    @pytest.mark.asyncio
    async def test_huawei_solar_set_battery_mode(self, mock_hass):
        """Huawei Solar: ustawienie trybu baterii."""
        adapter = HuaweiSolarInverterAdapter(
            mock_hass, "sensor.huawei_inverter", "sensor.huawei_soc"
        )
        result = await adapter.set_battery_mode(BatteryMode.CHARGE)
        assert result is True
        mock_hass.services.async_call.assert_called_once_with(
            "huawei_solar",
            "set_storage_mode",
            {"entity_id": "sensor.huawei_inverter", "mode": "forced_charge"},
            blocking=True,
        )

    @pytest.mark.asyncio
    async def test_goodwe_set_battery_mode(self, mock_hass):
        """GoodWe: ustawienie trybu baterii."""
        adapter = GoodWeInverterAdapter(
            mock_hass, "sensor.goodwe_inverter", "sensor.goodwe_soc"
        )
        result = await adapter.set_battery_mode(BatteryMode.DISCHARGE)
        assert result is True
        mock_hass.services.async_call.assert_called_once_with(
            "goodwe",
            "set_operation_mode",
            {"entity_id": "sensor.goodwe_inverter", "mode": "eco_discharge"},
            blocking=True,
        )

    @pytest.mark.asyncio
    async def test_fronius_set_battery_mode(self, mock_hass):
        """Fronius: ustawienie trybu baterii."""
        adapter = FroniusInverterAdapter(
            mock_hass, "sensor.fronius_inverter", "sensor.fronius_soc"
        )
        result = await adapter.set_battery_mode(BatteryMode.STANDBY)
        assert result is True
        mock_hass.services.async_call.assert_called_once_with(
            "fronius",
            "set_battery_mode",
            {"entity_id": "sensor.fronius_inverter", "mode": "automatic"},
            blocking=True,
        )

    @pytest.mark.asyncio
    async def test_sma_set_battery_mode(self, mock_hass):
        """SMA: ustawienie trybu baterii."""
        adapter = SMAInverterAdapter(
            mock_hass, "sensor.sma_inverter", "sensor.sma_soc"
        )
        result = await adapter.set_battery_mode(BatteryMode.CHARGE)
        assert result is True
        mock_hass.services.async_call.assert_called_once_with(
            "sma",
            "set_battery_mode",
            {"entity_id": "sensor.sma_inverter", "mode": "charge"},
            blocking=True,
        )

    @pytest.mark.asyncio
    async def test_adapter_returns_false_on_error(self, mock_hass):
        """Adapter zwraca False gdy service call rzuci wyjatek."""
        mock_hass.services.async_call = AsyncMock(side_effect=Exception("Connection error"))
        adapter = SolarEdgeInverterAdapter(
            mock_hass, "sensor.solaredge_inverter", "sensor.solaredge_soc"
        )
        result = await adapter.set_battery_mode(BatteryMode.CHARGE)
        assert result is False

    @pytest.mark.asyncio
    async def test_get_inverter_type(self, mock_hass):
        """Adaptery zwracaja poprawny typ inwertera."""
        assert await SolarEdgeInverterAdapter(mock_hass, "e", "s").get_inverter_type() == "solaredge"
        assert await HuaweiSolarInverterAdapter(mock_hass, "e", "s").get_inverter_type() == "huawei_solar"
        assert await GoodWeInverterAdapter(mock_hass, "e", "s").get_inverter_type() == "goodwe"
        assert await FroniusInverterAdapter(mock_hass, "e", "s").get_inverter_type() == "fronius"
        assert await SMAInverterAdapter(mock_hass, "e", "s").get_inverter_type() == "sma"



class TestCreateInverterAdapter:
    """Testy fabryki adapterow inwerterow."""

    def test_create_solaredge(self, mock_hass):
        """Tworzy adapter SolarEdge."""
        adapter = create_inverter_adapter(mock_hass, "solaredge", "e1", "s1")
        assert isinstance(adapter, SolarEdgeInverterAdapter)

    def test_create_huawei_solar(self, mock_hass):
        """Tworzy adapter Huawei Solar."""
        adapter = create_inverter_adapter(mock_hass, "huawei_solar", "e1", "s1")
        assert isinstance(adapter, HuaweiSolarInverterAdapter)

    def test_create_goodwe(self, mock_hass):
        """Tworzy adapter GoodWe."""
        adapter = create_inverter_adapter(mock_hass, "goodwe", "e1", "s1")
        assert isinstance(adapter, GoodWeInverterAdapter)

    def test_create_fronius(self, mock_hass):
        """Tworzy adapter Fronius."""
        adapter = create_inverter_adapter(mock_hass, "fronius", "e1", "s1")
        assert isinstance(adapter, FroniusInverterAdapter)

    def test_create_sma(self, mock_hass):
        """Tworzy adapter SMA."""
        adapter = create_inverter_adapter(mock_hass, "sma", "e1", "s1")
        assert isinstance(adapter, SMAInverterAdapter)

    def test_raises_on_unknown_type(self, mock_hass):
        """Rzuca ValueError dla nieznanego typu inwertera."""
        with pytest.raises(ValueError, match="unknown_brand"):
            create_inverter_adapter(mock_hass, "unknown_brand", "e1", "s1")


class TestGetEntityFloat:
    """Testy helpera _get_entity_float."""

    def test_returns_float_from_state(self, mock_hass):
        """Zwraca float z poprawnego stanu encji."""
        state = MagicMock()
        state.state = "75.5"
        mock_hass.states.get = MagicMock(return_value=state)
        result = _get_entity_float(mock_hass, "sensor.battery_soc")
        assert result == 75.5

    def test_returns_none_for_unknown_state(self, mock_hass):
        """Zwraca None dla stanu unknown."""
        state = MagicMock()
        state.state = "unknown"
        mock_hass.states.get = MagicMock(return_value=state)
        result = _get_entity_float(mock_hass, "sensor.battery_soc")
        assert result is None

    def test_returns_none_for_unavailable_state(self, mock_hass):
        """Zwraca None dla stanu unavailable."""
        state = MagicMock()
        state.state = "unavailable"
        mock_hass.states.get = MagicMock(return_value=state)
        result = _get_entity_float(mock_hass, "sensor.battery_soc")
        assert result is None

    def test_returns_none_for_missing_entity(self, mock_hass):
        """Zwraca None gdy encja nie istnieje."""
        mock_hass.states.get = MagicMock(return_value=None)
        result = _get_entity_float(mock_hass, "sensor.nonexistent")
        assert result is None

    def test_returns_none_for_non_numeric_state(self, mock_hass):
        """Zwraca None dla nienumerycznego stanu."""
        state = MagicMock()
        state.state = "not_a_number"
        mock_hass.states.get = MagicMock(return_value=state)
        result = _get_entity_float(mock_hass, "sensor.battery_soc")
        assert result is None



class TestCoordinatorInverterCommunication:
    """Testy komunikacji koordynatora z inwerterem."""

    @pytest.mark.asyncio
    async def test_sends_battery_mode_to_inverter(
        self, mock_hass, mock_solar_client, pv_optimizer, battery_config,
        mock_tariff_coordinator, consumption_profile,
    ):
        """Koordynator wysyla komende trybu baterii do inwertera."""
        mock_adapter = MagicMock(spec=InverterAdapter)
        mock_adapter.set_battery_mode = AsyncMock(return_value=True)

        coord = PVForecastCoordinator(
            hass=mock_hass,
            solar_forecast_client=mock_solar_client,
            pv_optimizer=pv_optimizer,
            battery_config=battery_config,
            tariff_coordinator=mock_tariff_coordinator,
            inverter_adapter=mock_adapter,
        )
        coord.set_consumption_profile(consumption_profile)

        await coord._async_update_data()
        mock_adapter.set_battery_mode.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_inverter_call_when_adapter_none(self, coordinator):
        """Brak wywolania inwertera gdy adapter jest None."""
        result = await coordinator._async_update_data()
        assert result is not None

    @pytest.mark.asyncio
    async def test_handles_inverter_error_gracefully(
        self, mock_hass, mock_solar_client, pv_optimizer, battery_config,
        mock_tariff_coordinator, consumption_profile,
    ):
        """Koordynator obsluguje blad inwertera bez przerywania."""
        mock_adapter = MagicMock(spec=InverterAdapter)
        mock_adapter.set_battery_mode = AsyncMock(side_effect=Exception("Comm error"))

        coord = PVForecastCoordinator(
            hass=mock_hass,
            solar_forecast_client=mock_solar_client,
            pv_optimizer=pv_optimizer,
            battery_config=battery_config,
            tariff_coordinator=mock_tariff_coordinator,
            inverter_adapter=mock_adapter,
        )
        coord.set_consumption_profile(consumption_profile)

        result = await coord._async_update_data()
        assert result is not None


class TestConsumptionProfile:
    """Testy profilu zuzycia."""

    def test_set_consumption_profile_24_values(self, coordinator):
        """set_consumption_profile akceptuje 24 wartosci."""
        profile = [float(i) for i in range(24)]
        coordinator.set_consumption_profile(profile)
        assert coordinator._consumption_profile == profile

    def test_set_consumption_profile_pads_short(self, coordinator):
        """set_consumption_profile dopelnia zerami krotki profil."""
        profile = [1.0, 2.0, 3.0]
        coordinator.set_consumption_profile(profile)
        assert len(coordinator._consumption_profile) == 24
        assert coordinator._consumption_profile[:3] == [1.0, 2.0, 3.0]
        assert coordinator._consumption_profile[3:] == [0.0] * 21

    def test_set_consumption_profile_truncates_long(self, coordinator):
        """set_consumption_profile obcina dlugi profil do 24."""
        profile = [float(i) for i in range(30)]
        coordinator.set_consumption_profile(profile)
        assert len(coordinator._consumption_profile) == 24
        assert coordinator._consumption_profile == [float(i) for i in range(24)]
