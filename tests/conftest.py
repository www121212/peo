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
