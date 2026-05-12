"""Konfiguracja testów — mockowanie modułów Home Assistant."""

import sys
from unittest.mock import MagicMock

# Mock homeassistant modules that are not installed in test environment
ha_mock = MagicMock()
ha_core_mock = MagicMock()
ha_persistent_notification_mock = MagicMock()
ha_helpers_mock = MagicMock()
ha_helpers_storage_mock = MagicMock()

sys.modules.setdefault("homeassistant", ha_mock)
sys.modules.setdefault("homeassistant.core", ha_core_mock)
sys.modules.setdefault("homeassistant.components", MagicMock())
sys.modules.setdefault(
    "homeassistant.components.persistent_notification",
    ha_persistent_notification_mock,
)
sys.modules.setdefault("homeassistant.helpers", ha_helpers_mock)
sys.modules.setdefault("homeassistant.helpers.storage", ha_helpers_storage_mock)
