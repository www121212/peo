"""Unit tests for PEO __init__.py lifecycle functions.

Tests async_setup_entry, async_unload_entry, async_remove_entry,
async_migrate_entry.

Requirements: 8.1, 8.2, 8.3, 8.4, 8.10, 8.11, 8.12
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio

from custom_components.peo.__init__ import (
    async_setup_entry,
    async_unload_entry,
    async_remove_entry,
    async_migrate_entry,
    _migrate_v0_to_v1,
    _async_options_updated,
    CONFIG_VERSION,
)
from custom_components.peo.const import (
    DOMAIN,
    CONF_MODULES_ENABLED,
    CONF_OSD_OPERATOR,
    CONF_TARIFF_TYPE,
    MODULE_PRICES,
    MODULE_TARIFF,
    MODULE_EV,
    MODULE_LOADS,
    MODULE_PV,
)


def _make_hass():
    """Create a mock HomeAssistant instance."""
    hass = MagicMock()
    hass.data = {}
    hass.bus = MagicMock()
    hass.bus.async_listen = MagicMock(return_value=MagicMock())
    hass.bus.async_fire = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_update_entry = MagicMock()
    hass.services = MagicMock()
    hass.services.has_service = MagicMock(return_value=False)
    hass.services.async_register = MagicMock()
    hass.services.async_remove = MagicMock()
    hass.helpers = MagicMock()
    hass.helpers.storage = MagicMock()
    store_mock = MagicMock()
    store_mock.async_remove = AsyncMock()
    hass.helpers.storage.Store = MagicMock(return_value=store_mock)
    return hass


def _make_entry(
    data=None,
    options=None,
    entry_id="test_entry_123",
    version=CONFIG_VERSION,
):
    """Create a mock ConfigEntry."""
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = data or {
        CONF_MODULES_ENABLED: [MODULE_PRICES, MODULE_TARIFF],
        CONF_OSD_OPERATOR: "tauron",
        CONF_TARIFF_TYPE: "G12",
    }
    entry.options = options or {}
    entry.version = version
    entry.add_update_listener = MagicMock(return_value=MagicMock())
    return entry


class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    @pytest.mark.asyncio
    async def test_setup_entry_creates_domain_data(self):
        """Setup entry creates hass.data[DOMAIN][entry_id] structure."""
        hass = _make_hass()
        entry = _make_entry()

        with patch("custom_components.peo.services.async_register_services", new_callable=AsyncMock), \
             patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value = MagicMock()
            result = await async_setup_entry(hass, entry)

        assert result is True
        assert DOMAIN in hass.data
        assert entry.entry_id in hass.data[DOMAIN]

    @pytest.mark.asyncio
    async def test_setup_entry_registers_options_listener(self):
        """Setup entry registers an options update listener."""
        hass = _make_hass()
        entry = _make_entry()

        with patch("custom_components.peo.services.async_register_services", new_callable=AsyncMock), \
             patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value = MagicMock()
            await async_setup_entry(hass, entry)

        entry.add_update_listener.assert_called_once()

    @pytest.mark.asyncio
    async def test_setup_entry_forwards_platforms(self):
        """Setup entry forwards setup to sensor and binary_sensor platforms."""
        hass = _make_hass()
        entry = _make_entry()

        with patch("custom_components.peo.services.async_register_services", new_callable=AsyncMock), \
             patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value = MagicMock()
            await async_setup_entry(hass, entry)

        hass.config_entries.async_forward_entry_setups.assert_called_once_with(
            entry, ["sensor", "binary_sensor"]
        )

    @pytest.mark.asyncio
    async def test_setup_entry_registers_services(self):
        """Setup entry registers PEO services."""
        hass = _make_hass()
        entry = _make_entry()

        with patch("custom_components.peo.services.async_register_services", new_callable=AsyncMock) as mock_reg, \
             patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value = MagicMock()
            await async_setup_entry(hass, entry)

        mock_reg.assert_called_once_with(hass, entry)

    @pytest.mark.asyncio
    async def test_setup_entry_stores_coordinators(self):
        """Setup entry stores coordinator references in runtime data."""
        hass = _make_hass()
        entry = _make_entry(data={
            CONF_MODULES_ENABLED: [MODULE_PRICES, MODULE_TARIFF],
            CONF_OSD_OPERATOR: "tauron",
            CONF_TARIFF_TYPE: "G12",
        })

        with patch("custom_components.peo.services.async_register_services", new_callable=AsyncMock), \
             patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value = MagicMock()
            await async_setup_entry(hass, entry)

        runtime_data = hass.data[DOMAIN][entry.entry_id]
        assert "coordinators" in runtime_data
        assert "price" in runtime_data["coordinators"]
        assert "tariff" in runtime_data["coordinators"]

    @pytest.mark.asyncio
    async def test_setup_entry_registers_event_listener_for_ev(self):
        """Setup entry registers price update listener when EV module enabled."""
        hass = _make_hass()
        entry = _make_entry(data={
            CONF_MODULES_ENABLED: [MODULE_PRICES, MODULE_TARIFF, MODULE_EV],
            CONF_OSD_OPERATOR: "tauron",
            CONF_TARIFF_TYPE: "G12",
        })

        with patch("custom_components.peo.services.async_register_services", new_callable=AsyncMock), \
             patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value = MagicMock()
            await async_setup_entry(hass, entry)

        hass.bus.async_listen.assert_called()


class TestAsyncUnloadEntry:
    """Tests for async_unload_entry."""

    @pytest.mark.asyncio
    async def test_unload_entry_cancels_listeners(self):
        """Unload entry cancels all registered listeners."""
        hass = _make_hass()
        entry = _make_entry()

        # Setup first
        unsub_mock = MagicMock()
        hass.data[DOMAIN] = {
            entry.entry_id: {
                "listeners": [unsub_mock],
                "coordinators": {},
            }
        }

        result = await async_unload_entry(hass, entry)

        assert result is True
        unsub_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_unload_entry_closes_http_sessions(self):
        """Unload entry closes HTTP client sessions."""
        hass = _make_hass()
        entry = _make_entry()

        http_session = MagicMock()
        http_session.close = AsyncMock()

        hass.data[DOMAIN] = {
            entry.entry_id: {
                "listeners": [],
                "coordinators": {},
                "http_session": http_session,
            }
        }

        await async_unload_entry(hass, entry)

        http_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_unload_entry_removes_domain_data(self):
        """Unload entry removes entry from hass.data[DOMAIN]."""
        hass = _make_hass()
        entry = _make_entry()

        hass.data[DOMAIN] = {
            entry.entry_id: {
                "listeners": [],
                "coordinators": {},
            }
        }

        await async_unload_entry(hass, entry)

        assert entry.entry_id not in hass.data.get(DOMAIN, {})

    @pytest.mark.asyncio
    async def test_unload_entry_unloads_platforms(self):
        """Unload entry unloads sensor and binary_sensor platforms."""
        hass = _make_hass()
        entry = _make_entry()

        hass.data[DOMAIN] = {
            entry.entry_id: {
                "listeners": [],
                "coordinators": {},
            }
        }

        await async_unload_entry(hass, entry)

        hass.config_entries.async_unload_platforms.assert_called_once_with(
            entry, ["sensor", "binary_sensor"]
        )


class TestAsyncRemoveEntry:
    """Tests for async_remove_entry."""

    @pytest.mark.asyncio
    async def test_remove_entry_removes_persistent_storage(self):
        """Remove entry removes all persistent storage files."""
        hass = _make_hass()
        entry = _make_entry()

        await async_remove_entry(hass, entry)

        # Should have created Store instances for each storage key
        assert hass.helpers.storage.Store.call_count == 4


class TestAsyncMigrateEntry:
    """Tests for async_migrate_entry."""

    @pytest.mark.asyncio
    async def test_migrate_entry_current_version_noop(self):
        """Migration is a no-op when config is at current version."""
        hass = _make_hass()
        entry = _make_entry(version=CONFIG_VERSION)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        # Should not call async_update_entry
        hass.config_entries.async_update_entry.assert_not_called()

    @pytest.mark.asyncio
    async def test_migrate_entry_future_version_fails(self):
        """Migration fails when config version is newer than supported."""
        hass = _make_hass()
        entry = _make_entry(version=CONFIG_VERSION + 1)

        result = await async_migrate_entry(hass, entry)

        assert result is False

    @pytest.mark.asyncio
    async def test_migrate_entry_v0_to_v1_succeeds(self):
        """Migration from v0 to v1 succeeds and updates entry."""
        hass = _make_hass()
        entry = _make_entry(
            version=0,
            data={"some_key": "some_value"},
            options={},
        )

        result = await async_migrate_entry(hass, entry)

        assert result is True
        hass.config_entries.async_update_entry.assert_called_once()

    @pytest.mark.asyncio
    async def test_migrate_entry_preserves_existing_data(self):
        """Migration preserves existing user data."""
        hass = _make_hass()
        entry = _make_entry(
            version=0,
            data={
                CONF_MODULES_ENABLED: [MODULE_PRICES, MODULE_EV],
                CONF_OSD_OPERATOR: "pge",
                CONF_TARIFF_TYPE: "G13",
                "custom_key": "custom_value",
            },
            options={"my_option": "my_value"},
        )

        await async_migrate_entry(hass, entry)

        call_kwargs = hass.config_entries.async_update_entry.call_args
        new_data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
        new_options = call_kwargs.kwargs.get("options") or call_kwargs[1].get("options")

        assert new_data[CONF_MODULES_ENABLED] == [MODULE_PRICES, MODULE_EV]
        assert new_data[CONF_OSD_OPERATOR] == "pge"
        assert new_data[CONF_TARIFF_TYPE] == "G13"
        assert new_data["custom_key"] == "custom_value"
        assert new_options["my_option"] == "my_value"


class TestMigrateV0ToV1:
    """Tests for _migrate_v0_to_v1 helper."""

    def test_adds_default_modules_when_missing(self):
        """Adds default modules_enabled when key is missing."""
        data, options = _migrate_v0_to_v1({}, {})
        assert CONF_MODULES_ENABLED in data
        assert MODULE_PRICES in data[CONF_MODULES_ENABLED]
        assert MODULE_TARIFF in data[CONF_MODULES_ENABLED]

    def test_adds_default_osd_when_missing(self):
        """Adds default OSD operator when key is missing."""
        data, options = _migrate_v0_to_v1({}, {})
        assert data[CONF_OSD_OPERATOR] == "tauron"

    def test_adds_default_tariff_when_missing(self):
        """Adds default tariff type when key is missing."""
        data, options = _migrate_v0_to_v1({}, {})
        assert data[CONF_TARIFF_TYPE] == "G12"

    def test_preserves_existing_modules(self):
        """Does not overwrite existing modules_enabled."""
        data, _ = _migrate_v0_to_v1(
            {CONF_MODULES_ENABLED: [MODULE_EV]}, {}
        )
        assert data[CONF_MODULES_ENABLED] == [MODULE_EV]

    def test_preserves_existing_osd(self):
        """Does not overwrite existing OSD operator."""
        data, _ = _migrate_v0_to_v1(
            {CONF_OSD_OPERATOR: "enea"}, {}
        )
        assert data[CONF_OSD_OPERATOR] == "enea"

    def test_preserves_existing_tariff(self):
        """Does not overwrite existing tariff type."""
        data, _ = _migrate_v0_to_v1(
            {CONF_TARIFF_TYPE: "G13"}, {}
        )
        assert data[CONF_TARIFF_TYPE] == "G13"


class TestAsyncOptionsUpdated:
    """Tests for _async_options_updated callback."""

    @pytest.mark.asyncio
    async def test_options_updated_refreshes_coordinators(self):
        """Options update triggers coordinator refresh."""
        hass = _make_hass()
        entry = _make_entry()

        coordinator_mock = MagicMock()
        coordinator_mock.async_refresh = AsyncMock()
        coordinator_mock.update_options = MagicMock()

        hass.data[DOMAIN] = {
            entry.entry_id: {
                "coordinators": {"price": coordinator_mock},
            }
        }

        await _async_options_updated(hass, entry)

        coordinator_mock.update_options.assert_called_once_with(entry.options)
        coordinator_mock.async_refresh.assert_called_once()
