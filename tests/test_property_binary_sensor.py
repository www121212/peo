"""Property-based tests for binary sensor "tanie okno".

**Validates: Requirements 12.5**

Property 32: Binary sensor "tanie okno"
Dla dowolnej ceny energii i skonfigurowanego progu cenowego, binary sensor
"tanie okno" powinien być w stanie ON gdy cena < próg, i OFF gdy cena ≥ próg.
"""

import pytest
from decimal import Decimal
from unittest.mock import MagicMock
from hypothesis import given, settings, assume
from hypothesis.strategies import (
    floats,
    composite,
)

from custom_components.peo.binary_sensors import CheapWindowBinarySensor

# Minimum 200 iterations per property test as per design doc
PROPERTY_TEST_SETTINGS = settings(max_examples=200, deadline=None)


# --- Helper: mock HA objects ---

def _make_mock_hass():
    """Create a mock HomeAssistant instance."""
    hass = MagicMock()
    hass.fired_events = []

    def _capture_event(event_type, data):
        hass.fired_events.append({"event_type": event_type, "data": data})

    hass.bus.async_fire = _capture_event
    hass.data = {}
    return hass


def _make_mock_entry(threshold: str = "0.40"):
    """Create a mock ConfigEntry with given threshold."""
    entry = MagicMock()
    entry.entry_id = "test_entry_binary"
    entry.data = {"modules_enabled": ["prices"]}
    entry.options = {"price_threshold_cheap": threshold}
    return entry


# --- Property 32: Binary sensor "tanie okno" ---

class TestProperty32CheapWindowBinarySensor:
    """Property 32: Binary sensor "tanie okno".

    For any price and configured threshold:
    - price < threshold → sensor is ON
    - price >= threshold → sensor is OFF
    """

    @given(
        price=floats(min_value=0.001, max_value=5.0, allow_nan=False, allow_infinity=False),
        threshold=floats(min_value=0.001, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    @PROPERTY_TEST_SETTINGS
    def test_cheap_window_on_when_price_below_threshold(self, price, threshold):
        """Sensor is ON when current price < configured threshold.

        **Validates: Requirements 12.5**
        """
        assume(abs(price - threshold) > 1e-9)  # Avoid exact equality edge case

        hass = _make_mock_hass()
        entry = _make_mock_entry(threshold=str(threshold))
        sensor = CheapWindowBinarySensor(hass, entry)

        sensor.update_price(Decimal(str(price)))

        if price < threshold:
            assert sensor.is_on is True, (
                f"Sensor should be ON when price ({price}) < threshold ({threshold})"
            )
        else:
            assert sensor.is_on is False, (
                f"Sensor should be OFF when price ({price}) >= threshold ({threshold})"
            )

    @given(
        price=floats(min_value=0.001, max_value=2.0, allow_nan=False, allow_infinity=False),
        threshold=floats(min_value=2.001, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    @PROPERTY_TEST_SETTINGS
    def test_cheap_window_always_on_when_price_strictly_below(self, price, threshold):
        """Sensor is always ON when price is strictly below threshold.

        **Validates: Requirements 12.5**
        """
        # price is always < threshold by construction
        hass = _make_mock_hass()
        entry = _make_mock_entry(threshold=str(threshold))
        sensor = CheapWindowBinarySensor(hass, entry)

        sensor.update_price(Decimal(str(price)))

        assert sensor.is_on is True, (
            f"Sensor must be ON: price={price} < threshold={threshold}"
        )

    @given(
        price=floats(min_value=2.001, max_value=5.0, allow_nan=False, allow_infinity=False),
        threshold=floats(min_value=0.001, max_value=2.0, allow_nan=False, allow_infinity=False),
    )
    @PROPERTY_TEST_SETTINGS
    def test_cheap_window_always_off_when_price_above(self, price, threshold):
        """Sensor is always OFF when price is above or equal to threshold.

        **Validates: Requirements 12.5**
        """
        # price is always > threshold by construction
        hass = _make_mock_hass()
        entry = _make_mock_entry(threshold=str(threshold))
        sensor = CheapWindowBinarySensor(hass, entry)

        sensor.update_price(Decimal(str(price)))

        assert sensor.is_on is False, (
            f"Sensor must be OFF: price={price} >= threshold={threshold}"
        )

    @given(
        threshold=floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    @PROPERTY_TEST_SETTINGS
    def test_cheap_window_off_when_price_equals_threshold(self, threshold):
        """Sensor is OFF when price exactly equals threshold (not strictly less).

        **Validates: Requirements 12.5**
        """
        hass = _make_mock_hass()
        entry = _make_mock_entry(threshold=str(threshold))
        sensor = CheapWindowBinarySensor(hass, entry)

        # Price == threshold → should be OFF (condition is price < threshold)
        sensor.update_price(Decimal(str(threshold)))

        assert sensor.is_on is False, (
            f"Sensor must be OFF when price equals threshold ({threshold})"
        )

    @given(
        price=floats(min_value=0.001, max_value=5.0, allow_nan=False, allow_infinity=False),
        threshold=floats(min_value=0.001, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    @PROPERTY_TEST_SETTINGS
    def test_cheap_window_threshold_update_recalculates_state(self, price, threshold):
        """Updating threshold recalculates sensor state correctly.

        **Validates: Requirements 12.5**
        """
        assume(abs(price - threshold) > 1e-9)

        hass = _make_mock_hass()
        # Start with a different threshold
        initial_threshold = "2.50"
        entry = _make_mock_entry(threshold=initial_threshold)
        sensor = CheapWindowBinarySensor(hass, entry)

        # Set price first
        sensor.update_price(Decimal(str(price)))

        # Now update threshold
        sensor.update_threshold(Decimal(str(threshold)))

        # State should reflect new threshold
        expected_on = price < threshold
        assert sensor.is_on == expected_on, (
            f"After threshold update: price={price}, new_threshold={threshold}, "
            f"expected is_on={expected_on}, got is_on={sensor.is_on}"
        )
