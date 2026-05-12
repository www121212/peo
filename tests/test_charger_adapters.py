"""Testy adapterów ładowarek EV — retry logic i interfejs abstrakcyjny."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.peo.charger_adapters import (
    ChargerAdapter,
    ChargerLimits,
    ChargerStatus,
    OCPPChargerAdapter,
    OpenEVSEChargerAdapter,
    TeslaChargerAdapter,
    WallboxChargerAdapter,
    with_retry,
)
from custom_components.peo.const import CHARGER_RETRY_COUNT, CHARGER_RETRY_INTERVAL


# --- Test abstract interface ---


class TestChargerAdapterInterface:
    """Testy interfejsu abstrakcyjnego ChargerAdapter."""

    def test_cannot_instantiate_abstract_class(self):
        """ChargerAdapter nie może być instancjonowany bezpośrednio."""
        with pytest.raises(TypeError):
            ChargerAdapter()  # type: ignore[abstract]

    def test_concrete_adapters_are_subclasses(self):
        """Wszystkie konkretne adaptery dziedziczą po ChargerAdapter."""
        assert issubclass(OCPPChargerAdapter, ChargerAdapter)
        assert issubclass(TeslaChargerAdapter, ChargerAdapter)
        assert issubclass(WallboxChargerAdapter, ChargerAdapter)
        assert issubclass(OpenEVSEChargerAdapter, ChargerAdapter)

    def test_adapter_constructor_stores_params(self):
        """Adapter przechowuje host, api_key i entity_id."""
        adapter = OCPPChargerAdapter(
            host="192.168.1.100",
            api_key="test_key",
            entity_id="sensor.charger_1",
        )
        assert adapter.host == "192.168.1.100"
        assert adapter.api_key == "test_key"
        assert adapter.entity_id == "sensor.charger_1"

    def test_adapter_constructor_defaults_to_none(self):
        """Adapter domyślnie ustawia parametry na None."""
        adapter = TeslaChargerAdapter()
        assert adapter.host is None
        assert adapter.api_key is None
        assert adapter.entity_id is None


# --- Test retry logic ---


class TestRetryDecorator:
    """Testy dekoratora retry."""

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_first_attempt(self):
        """Retry zwraca wynik natychmiast gdy funkcja się powiedzie."""
        mock_func = AsyncMock(return_value=True)
        decorated = with_retry(mock_func)

        result = await decorated()

        assert result is True
        assert mock_func.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self):
        """Retry ponawia próbę i zwraca wynik po drugim wywołaniu."""
        mock_func = AsyncMock(side_effect=[RuntimeError("fail"), True])
        decorated = with_retry(mock_func)

        with patch("custom_components.peo.charger_adapters.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            result = await decorated()

        assert result is True
        assert mock_func.call_count == 2
        mock_sleep.assert_called_once_with(CHARGER_RETRY_INTERVAL)

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_third_attempt(self):
        """Retry ponawia próbę i zwraca wynik po trzecim wywołaniu."""
        mock_func = AsyncMock(
            side_effect=[RuntimeError("fail1"), RuntimeError("fail2"), True]
        )
        decorated = with_retry(mock_func)

        with patch("custom_components.peo.charger_adapters.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            result = await decorated()

        assert result is True
        assert mock_func.call_count == 3
        assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_raises_after_all_attempts_exhausted(self):
        """Retry rzuca wyjątek po wyczerpaniu wszystkich prób."""
        error = RuntimeError("persistent failure")
        mock_func = AsyncMock(side_effect=error)
        decorated = with_retry(mock_func)

        with patch("custom_components.peo.charger_adapters.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with pytest.raises(RuntimeError, match="persistent failure"):
                await decorated()

        assert mock_func.call_count == CHARGER_RETRY_COUNT
        assert mock_sleep.call_count == CHARGER_RETRY_COUNT - 1

    @pytest.mark.asyncio
    async def test_retry_uses_correct_interval(self):
        """Retry czeka CHARGER_RETRY_INTERVAL (10s) między próbami."""
        mock_func = AsyncMock(
            side_effect=[RuntimeError("fail"), RuntimeError("fail"), True]
        )
        decorated = with_retry(mock_func)

        with patch("custom_components.peo.charger_adapters.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            await decorated()

        # Verify each sleep call used the correct interval
        for call in mock_sleep.call_args_list:
            assert call[0][0] == CHARGER_RETRY_INTERVAL

    @pytest.mark.asyncio
    async def test_retry_count_matches_const(self):
        """Liczba prób retry odpowiada CHARGER_RETRY_COUNT (3)."""
        assert CHARGER_RETRY_COUNT == 3

    @pytest.mark.asyncio
    async def test_retry_interval_matches_const(self):
        """Interwał retry odpowiada CHARGER_RETRY_INTERVAL (10s)."""
        assert CHARGER_RETRY_INTERVAL == 10


# --- Test concrete adapters with retry ---


class TestOCPPChargerAdapter:
    """Testy adaptera OCPP."""

    @pytest.mark.asyncio
    async def test_start_charging_retries_on_failure(self):
        """OCPP start_charging wykonuje retry przy niepowodzeniu."""
        adapter = OCPPChargerAdapter(host="192.168.1.100")

        with patch("custom_components.peo.charger_adapters.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with pytest.raises(NotImplementedError):
                await adapter.start_charging(7.4)

        # Should have slept CHARGER_RETRY_COUNT - 1 times between retries
        assert mock_sleep.call_count == CHARGER_RETRY_COUNT - 1

    @pytest.mark.asyncio
    async def test_stop_charging_retries_on_failure(self):
        """OCPP stop_charging wykonuje retry przy niepowodzeniu."""
        adapter = OCPPChargerAdapter(host="192.168.1.100")

        with patch("custom_components.peo.charger_adapters.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with pytest.raises(NotImplementedError):
                await adapter.stop_charging()

        assert mock_sleep.call_count == CHARGER_RETRY_COUNT - 1

    @pytest.mark.asyncio
    async def test_get_status_retries_on_failure(self):
        """OCPP get_status wykonuje retry przy niepowodzeniu."""
        adapter = OCPPChargerAdapter(host="192.168.1.100")

        with patch("custom_components.peo.charger_adapters.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with pytest.raises(NotImplementedError):
                await adapter.get_status()

        assert mock_sleep.call_count == CHARGER_RETRY_COUNT - 1

    @pytest.mark.asyncio
    async def test_get_limits_retries_on_failure(self):
        """OCPP get_limits wykonuje retry przy niepowodzeniu."""
        adapter = OCPPChargerAdapter(host="192.168.1.100")

        with patch("custom_components.peo.charger_adapters.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with pytest.raises(NotImplementedError):
                await adapter.get_limits()

        assert mock_sleep.call_count == CHARGER_RETRY_COUNT - 1


class TestTeslaChargerAdapter:
    """Testy adaptera Tesla."""

    @pytest.mark.asyncio
    async def test_start_charging_retries(self):
        """Tesla start_charging wykonuje retry przy niepowodzeniu."""
        adapter = TeslaChargerAdapter(api_key="tesla_token")

        with patch("custom_components.peo.charger_adapters.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with pytest.raises(NotImplementedError):
                await adapter.start_charging(11.0)

        assert mock_sleep.call_count == CHARGER_RETRY_COUNT - 1


class TestWallboxChargerAdapter:
    """Testy adaptera Wallbox."""

    @pytest.mark.asyncio
    async def test_start_charging_retries(self):
        """Wallbox start_charging wykonuje retry przy niepowodzeniu."""
        adapter = WallboxChargerAdapter(host="wallbox.local", api_key="wb_key")

        with patch("custom_components.peo.charger_adapters.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with pytest.raises(NotImplementedError):
                await adapter.start_charging(7.4)

        assert mock_sleep.call_count == CHARGER_RETRY_COUNT - 1


class TestOpenEVSEChargerAdapter:
    """Testy adaptera OpenEVSE."""

    @pytest.mark.asyncio
    async def test_start_charging_retries(self):
        """OpenEVSE start_charging wykonuje retry przy niepowodzeniu."""
        adapter = OpenEVSEChargerAdapter(host="openevse.local")

        with patch("custom_components.peo.charger_adapters.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with pytest.raises(NotImplementedError):
                await adapter.start_charging(7.4)

        assert mock_sleep.call_count == CHARGER_RETRY_COUNT - 1


# --- Test dataclasses ---


class TestChargerDataclasses:
    """Testy dataclass ChargerStatus i ChargerLimits."""

    def test_charger_status_defaults(self):
        """ChargerStatus ma opcjonalne pola temperature i error."""
        status = ChargerStatus(is_charging=True, current_power_kw=7.4)
        assert status.is_charging is True
        assert status.current_power_kw == 7.4
        assert status.temperature is None
        assert status.error is None

    def test_charger_status_with_all_fields(self):
        """ChargerStatus z wszystkimi polami."""
        status = ChargerStatus(
            is_charging=False,
            current_power_kw=0.0,
            temperature=35.5,
            error="Overcurrent",
        )
        assert status.is_charging is False
        assert status.current_power_kw == 0.0
        assert status.temperature == 35.5
        assert status.error == "Overcurrent"

    def test_charger_limits(self):
        """ChargerLimits przechowuje limity mocy."""
        limits = ChargerLimits(
            max_power_kw=22.0,
            max_current_a=32.0,
            min_power_kw=1.4,
        )
        assert limits.max_power_kw == 22.0
        assert limits.max_current_a == 32.0
        assert limits.min_power_kw == 1.4
