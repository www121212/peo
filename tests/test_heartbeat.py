"""Testy jednostkowe dla HeartbeatMonitor."""

from datetime import datetime, timedelta
from decimal import Decimal
from time import time as time_time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.peo.const import FAILSAFE_TIMEOUT, HEARTBEAT_INTERVAL
from custom_components.peo.heartbeat import HeartbeatMonitor
from custom_components.peo.models import LoadConfig


def _make_load_config(
    load_id: str = "load_1",
    entity_id: str = "switch.bojler",
    failsafe_state: bool = True,
    name: str = "Bojler CWU",
) -> LoadConfig:
    """Utwórz LoadConfig do testów."""
    return LoadConfig(
        load_id=load_id,
        name=name,
        entity_id=entity_id,
        threshold_on=Decimal("0.35"),
        threshold_off=Decimal("0.55"),
        min_daily_hours=2.0,
        max_daily_hours=6.0,
        allowed_start=datetime.strptime("22:00", "%H:%M").time(),
        allowed_end=datetime.strptime("06:00", "%H:%M").time(),
        priority=1,
        power_w=2000,
        failsafe_state=failsafe_state,
    )


def _make_hass_mock() -> MagicMock:
    """Utwórz mock Home Assistant."""
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


class TestHeartbeatMonitorInit:
    """Testy inicjalizacji HeartbeatMonitor."""

    def test_init_sets_last_heartbeat_to_now(self):
        """Inicjalizacja ustawia last_heartbeat na bieżący czas."""
        hass = _make_hass_mock()
        before = datetime.now()
        monitor = HeartbeatMonitor(hass, [])
        after = datetime.now()

        assert before <= monitor.last_heartbeat <= after

    def test_init_failsafe_not_active(self):
        """Inicjalizacja — failsafe nie jest aktywny."""
        hass = _make_hass_mock()
        monitor = HeartbeatMonitor(hass, [])

        assert monitor.is_failsafe_active is False

    def test_init_stores_load_configs(self):
        """Inicjalizacja przechowuje konfiguracje odbiorników."""
        hass = _make_hass_mock()
        loads = [_make_load_config("load_1"), _make_load_config("load_2")]
        monitor = HeartbeatMonitor(hass, loads)

        assert monitor._load_configs == loads


class TestHeartbeatPulse:
    """Testy metody pulse()."""

    @pytest.mark.asyncio
    async def test_pulse_updates_timestamp(self):
        """pulse() aktualizuje timestamp heartbeat."""
        hass = _make_hass_mock()
        monitor = HeartbeatMonitor(hass, [])

        # Ustaw stary timestamp
        monitor._last_heartbeat = datetime.now() - timedelta(seconds=120)
        old_heartbeat = monitor._last_heartbeat

        await monitor.pulse()

        assert monitor.last_heartbeat > old_heartbeat

    @pytest.mark.asyncio
    async def test_pulse_resets_failsafe(self):
        """pulse() dezaktywuje failsafe jeśli był aktywny."""
        hass = _make_hass_mock()
        monitor = HeartbeatMonitor(hass, [])
        monitor._failsafe_active = True

        await monitor.pulse()

        assert monitor.is_failsafe_active is False

    @pytest.mark.asyncio
    async def test_pulse_no_effect_when_failsafe_not_active(self):
        """pulse() nie zmienia stanu failsafe gdy nie jest aktywny."""
        hass = _make_hass_mock()
        monitor = HeartbeatMonitor(hass, [])

        await monitor.pulse()

        assert monitor.is_failsafe_active is False


class TestCheckFailsafe:
    """Testy metody check_failsafe()."""

    @pytest.mark.asyncio
    async def test_check_failsafe_returns_false_when_recent(self):
        """check_failsafe() zwraca False gdy heartbeat jest aktualny."""
        hass = _make_hass_mock()
        monitor = HeartbeatMonitor(hass, [])

        # Heartbeat właśnie ustawiony w __init__
        result = await monitor.check_failsafe()

        assert result is False

    @pytest.mark.asyncio
    async def test_check_failsafe_returns_true_when_timeout_exceeded(self):
        """check_failsafe() zwraca True gdy timeout przekroczony."""
        hass = _make_hass_mock()
        loads = [_make_load_config()]
        monitor = HeartbeatMonitor(hass, loads)

        # Symuluj stary heartbeat (ponad 5 minut temu)
        monitor._last_heartbeat = datetime.now() - timedelta(seconds=FAILSAFE_TIMEOUT + 10)

        result = await monitor.check_failsafe()

        assert result is True

    @pytest.mark.asyncio
    async def test_check_failsafe_activates_failsafe_on_timeout(self):
        """check_failsafe() aktywuje failsafe przy timeout."""
        hass = _make_hass_mock()
        loads = [_make_load_config()]
        monitor = HeartbeatMonitor(hass, loads)

        monitor._last_heartbeat = datetime.now() - timedelta(seconds=FAILSAFE_TIMEOUT + 10)

        await monitor.check_failsafe()

        assert monitor.is_failsafe_active is True

    @pytest.mark.asyncio
    async def test_check_failsafe_does_not_reactivate_if_already_active(self):
        """check_failsafe() nie aktywuje ponownie jeśli już aktywny."""
        hass = _make_hass_mock()
        loads = [_make_load_config()]
        monitor = HeartbeatMonitor(hass, loads)

        monitor._last_heartbeat = datetime.now() - timedelta(seconds=FAILSAFE_TIMEOUT + 10)
        monitor._failsafe_active = True

        # Nie powinno wywoływać activate_failsafe ponownie
        result = await monitor.check_failsafe()

        assert result is True
        # async_call nie powinno być wywołane (failsafe już aktywny)
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_failsafe_returns_false_just_under_boundary(self):
        """check_failsafe() zwraca False tuż przed granicą timeout."""
        hass = _make_hass_mock()
        monitor = HeartbeatMonitor(hass, [])

        # Tuż pod granicą (1 sekunda przed timeout)
        monitor._last_heartbeat = datetime.now() - timedelta(seconds=FAILSAFE_TIMEOUT - 1)

        result = await monitor.check_failsafe()

        assert result is False


class TestActivateFailsafe:
    """Testy metody activate_failsafe()."""

    @pytest.mark.asyncio
    async def test_activate_failsafe_sets_flag(self):
        """activate_failsafe() ustawia flagę failsafe_active."""
        hass = _make_hass_mock()
        monitor = HeartbeatMonitor(hass, [])

        await monitor.activate_failsafe()

        assert monitor.is_failsafe_active is True

    @pytest.mark.asyncio
    async def test_activate_failsafe_turns_on_device(self):
        """activate_failsafe() włącza urządzenie z failsafe_state=True."""
        hass = _make_hass_mock()
        load = _make_load_config(entity_id="switch.bojler", failsafe_state=True)
        monitor = HeartbeatMonitor(hass, [load])

        await monitor.activate_failsafe()

        hass.services.async_call.assert_called_once_with(
            "switch",
            "turn_on",
            {"entity_id": "switch.bojler"},
            blocking=True,
        )

    @pytest.mark.asyncio
    async def test_activate_failsafe_turns_off_device(self):
        """activate_failsafe() wyłącza urządzenie z failsafe_state=False."""
        hass = _make_hass_mock()
        load = _make_load_config(entity_id="switch.pompa", failsafe_state=False)
        monitor = HeartbeatMonitor(hass, [load])

        await monitor.activate_failsafe()

        hass.services.async_call.assert_called_once_with(
            "switch",
            "turn_off",
            {"entity_id": "switch.pompa"},
            blocking=True,
        )

    @pytest.mark.asyncio
    async def test_activate_failsafe_handles_multiple_loads(self):
        """activate_failsafe() obsługuje wiele odbiorników."""
        hass = _make_hass_mock()
        loads = [
            _make_load_config("load_1", "switch.bojler", True, "Bojler"),
            _make_load_config("load_2", "switch.pompa", False, "Pompa"),
            _make_load_config("load_3", "light.ogrod", True, "Oświetlenie"),
        ]
        monitor = HeartbeatMonitor(hass, loads)

        await monitor.activate_failsafe()

        assert hass.services.async_call.call_count == 3

    @pytest.mark.asyncio
    async def test_activate_failsafe_extracts_domain_from_entity_id(self):
        """activate_failsafe() wyciąga domenę z entity_id."""
        hass = _make_hass_mock()
        load = _make_load_config(entity_id="light.ogrod", failsafe_state=True)
        monitor = HeartbeatMonitor(hass, [load])

        await monitor.activate_failsafe()

        hass.services.async_call.assert_called_once_with(
            "light",
            "turn_on",
            {"entity_id": "light.ogrod"},
            blocking=True,
        )

    @pytest.mark.asyncio
    async def test_activate_failsafe_sends_notification(self):
        """activate_failsafe() wysyła powiadomienie persistent_notification."""
        hass = _make_hass_mock()
        monitor = HeartbeatMonitor(hass, [_make_load_config()])

        with patch(
            "custom_components.peo.heartbeat.async_create"
        ) as mock_notify:
            await monitor.activate_failsafe()

            mock_notify.assert_called_once()
            call_args = mock_notify.call_args
            assert call_args[0][0] is hass
            assert "Mechanizm awaryjny" in call_args[1]["title"]
            assert "peo_failsafe_activated" in call_args[1]["notification_id"]

    @pytest.mark.asyncio
    async def test_activate_failsafe_continues_on_service_error(self):
        """activate_failsafe() kontynuuje mimo błędu jednego urządzenia."""
        hass = _make_hass_mock()
        loads = [
            _make_load_config("load_1", "switch.bojler", True, "Bojler"),
            _make_load_config("load_2", "switch.pompa", False, "Pompa"),
        ]
        monitor = HeartbeatMonitor(hass, loads)

        # Pierwszy call rzuca wyjątek, drugi działa
        hass.services.async_call.side_effect = [
            Exception("Connection error"),
            None,
        ]

        with patch("custom_components.peo.heartbeat.async_create"):
            await monitor.activate_failsafe()

        # Oba urządzenia powinny być próbowane
        assert hass.services.async_call.call_count == 2
        assert monitor.is_failsafe_active is True

    @pytest.mark.asyncio
    async def test_activate_failsafe_notification_mentions_failed_loads(self):
        """activate_failsafe() wymienia w powiadomieniu urządzenia z błędem."""
        hass = _make_hass_mock()
        loads = [
            _make_load_config("load_1", "switch.bojler", True, "Bojler CWU"),
        ]
        monitor = HeartbeatMonitor(hass, loads)

        hass.services.async_call.side_effect = Exception("Timeout")

        with patch(
            "custom_components.peo.heartbeat.async_create"
        ) as mock_notify:
            await monitor.activate_failsafe()

            notification_msg = mock_notify.call_args[0][1]
            assert "Bojler CWU" in notification_msg

    @pytest.mark.asyncio
    async def test_activate_failsafe_with_empty_loads(self):
        """activate_failsafe() działa poprawnie bez odbiorników."""
        hass = _make_hass_mock()
        monitor = HeartbeatMonitor(hass, [])

        with patch("custom_components.peo.heartbeat.async_create"):
            await monitor.activate_failsafe()

        assert monitor.is_failsafe_active is True
        hass.services.async_call.assert_not_called()


class TestHeartbeatConstants:
    """Testy stałych heartbeat."""

    def test_heartbeat_interval_is_60_seconds(self):
        """HEARTBEAT_INTERVAL wynosi 60 sekund."""
        assert HEARTBEAT_INTERVAL == 60

    def test_failsafe_timeout_is_5_minutes(self):
        """FAILSAFE_TIMEOUT wynosi 5 minut (300 sekund)."""
        assert FAILSAFE_TIMEOUT == 300
