"""Konfiguracja testów — mockowanie modułów Home Assistant."""

import sys
from unittest.mock import MagicMock

# Mock homeassistant modules that are not installed in test environment
ha_mock = MagicMock()
ha_core_mock = MagicMock()
ha_persistent_notification_mock = MagicMock()
ha_helpers_mock = MagicMock()
ha_helpers_storage_mock = MagicMock()
ha_helpers_update_coordinator_mock = MagicMock()
ha_config_entries_mock = MagicMock()

sys.modules.setdefault("homeassistant", ha_mock)
sys.modules.setdefault("homeassistant.core", ha_core_mock)
sys.modules.setdefault("homeassistant.components", MagicMock())
sys.modules.setdefault(
    "homeassistant.components.persistent_notification",
    ha_persistent_notification_mock,
)
sys.modules.setdefault("homeassistant.helpers", ha_helpers_mock)
sys.modules.setdefault("homeassistant.helpers.storage", ha_helpers_storage_mock)
sys.modules.setdefault(
    "homeassistant.helpers.update_coordinator",
    ha_helpers_update_coordinator_mock,
)
sys.modules.setdefault("homeassistant.config_entries", ha_config_entries_mock)


# Provide a real base class for ConfigFlow so tests can instantiate it
class _FakeConfigFlow:
    """Fake ConfigFlow base class for testing."""

    VERSION = 1

    def __init_subclass__(cls, *, domain: str = "", **kwargs):
        """Support domain keyword argument in subclass definition."""
        super().__init_subclass__(**kwargs)
        cls._domain = domain

    def __init__(self):
        """Initialize fake config flow."""
        pass

    def async_show_form(self, *, step_id, data_schema, errors=None, description_placeholders=None):
        """Return form data dict."""
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors or {},
            "description_placeholders": description_placeholders,
        }

    def async_create_entry(self, *, title, data, options=None):
        """Return create entry result."""
        return {
            "type": "create_entry",
            "title": title,
            "data": data,
            "options": options or {},
        }


ha_config_entries_mock.ConfigFlow = _FakeConfigFlow
# Also set it on the ha_mock so `from homeassistant import config_entries` works
ha_mock.config_entries = ha_config_entries_mock


# Provide a real base class for DataUpdateCoordinator so tests can instantiate it
class _FakeDataUpdateCoordinator:
    """Fake DataUpdateCoordinator base class for testing."""

    def __init__(self, hass, logger, *, name, update_interval):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = None

    def __class_getitem__(cls, item):
        """Support generic subscripting (e.g. DataUpdateCoordinator[PriceData])."""
        return cls

    async def async_refresh(self):
        """Trigger a data refresh."""
        self.data = await self._async_update_data()

    async def _async_update_data(self):
        raise NotImplementedError


class _FakeUpdateFailed(Exception):
    """Fake UpdateFailed exception for testing."""


ha_helpers_update_coordinator_mock.DataUpdateCoordinator = _FakeDataUpdateCoordinator
ha_helpers_update_coordinator_mock.UpdateFailed = _FakeUpdateFailed
