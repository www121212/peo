"""Property-based tests for services and events.

**Validates: Requirements 12.2, 12.4**

Property 30: Zdarzenia HA zawierają wymagane pola
Dla dowolnego wyzwolonego zdarzenia PEO, payload powinien zawierać co najmniej:
znacznik czasu (timestamp), identyfikator encji źródłowej oraz dane kontekstowe
specyficzne dla typu zdarzenia.

Property 31: Walidacja parametrów usług HA
Dla dowolnego wywołania usługi PEO z nieprawidłowymi parametrami (poza zdefiniowanym
schematem), system powinien zwrócić ServiceValidationError z komunikatem przyczyny,
bez zmiany stanu systemu.
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch
from hypothesis import given, settings, assume
from hypothesis.strategies import (
    text,
    integers,
    floats,
    booleans,
    composite,
    sampled_from,
    one_of,
    just,
    none,
    lists,
    dictionaries,
)

import voluptuous as vol

from custom_components.peo.services import (
    ServiceValidationError,
    SCHEMA_START_EV_CHARGING,
    SCHEMA_STOP_EV_CHARGING,
    SCHEMA_SET_LOAD_THRESHOLD,
    SCHEMA_FORCE_LOAD_ON,
    SCHEMA_FORCE_LOAD_OFF,
    SCHEMA_RECALCULATE_SCHEDULE,
)
from custom_components.peo.binary_sensors import (
    CheapWindowBinarySensor,
    EVChargingActiveBinarySensor,
    PVSurplusActiveBinarySensor,
    PEOScheduleSensor,
    fire_load_shifted_event,
)
from custom_components.peo.const import (
    DOMAIN,
    EVENT_CHARGING_STARTED,
    EVENT_CHARGING_COMPLETED,
    EVENT_LOAD_SHIFTED,
    EVENT_PRICE_THRESHOLD_CROSSED,
    EVENT_SCHEDULE_UPDATED,
)

# Minimum 200 iterations per property test as per design doc
PROPERTY_TEST_SETTINGS = settings(max_examples=200, deadline=None)


# --- Helper: mock HA objects ---

def _make_mock_hass():
    """Create a mock HomeAssistant instance that captures fired events."""
    hass = MagicMock()
    hass.fired_events = []

    def _capture_event(event_type, data):
        hass.fired_events.append({"event_type": event_type, "data": data})

    hass.bus.async_fire = _capture_event
    hass.data = {}
    return hass


def _make_mock_entry(entry_id="test_entry_123", options=None):
    """Create a mock ConfigEntry."""
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {"modules_enabled": ["prices", "ev", "pv"]}
    entry.options = options or {"price_threshold_cheap": "0.40"}
    return entry


# --- Strategies for generating invalid service params ---

@composite
def invalid_start_ev_params(draw):
    """Generate invalid parameters for start_ev_charging service."""
    invalid_type = draw(sampled_from([
        # Missing required vehicle_id
        {"power_kw": 7.0},
        # vehicle_id wrong type
        {"vehicle_id": draw(integers(min_value=-1000, max_value=1000))},
        # power_kw out of range (too low)
        {"vehicle_id": "ev_1", "power_kw": draw(floats(min_value=-100.0, max_value=1.3, allow_nan=False, allow_infinity=False))},
        # power_kw out of range (too high)
        {"vehicle_id": "ev_1", "power_kw": draw(floats(min_value=22.1, max_value=1000.0, allow_nan=False, allow_infinity=False))},
        # target_soc out of range (too low)
        {"vehicle_id": "ev_1", "target_soc": draw(integers(min_value=-100, max_value=9))},
        # target_soc out of range (too high)
        {"vehicle_id": "ev_1", "target_soc": draw(integers(min_value=101, max_value=1000))},
    ]))
    return invalid_type


@composite
def invalid_stop_ev_params(draw):
    """Generate invalid parameters for stop_ev_charging service."""
    return draw(sampled_from([
        # Missing required vehicle_id
        {},
        # vehicle_id wrong type
        {"vehicle_id": draw(integers(min_value=-1000, max_value=1000))},
    ]))


@composite
def invalid_set_load_threshold_params(draw):
    """Generate invalid parameters for set_load_threshold service."""
    return draw(sampled_from([
        # Missing required load_id
        {"threshold_on": 0.5},
        # Missing required threshold_on
        {"load_id": "load_1"},
        # threshold_on out of range (too low)
        {"load_id": "load_1", "threshold_on": draw(floats(min_value=-100.0, max_value=0.0, allow_nan=False, allow_infinity=False))},
        # threshold_on out of range (too high)
        {"load_id": "load_1", "threshold_on": draw(floats(min_value=5.1, max_value=1000.0, allow_nan=False, allow_infinity=False))},
        # threshold_off out of range
        {"load_id": "load_1", "threshold_on": 0.5, "threshold_off": draw(floats(min_value=5.1, max_value=1000.0, allow_nan=False, allow_infinity=False))},
    ]))


@composite
def invalid_force_load_params(draw):
    """Generate invalid parameters for force_load_on/off services."""
    return draw(sampled_from([
        # Missing required load_id
        {"duration_minutes": 60},
        # load_id wrong type
        {"load_id": draw(integers(min_value=-1000, max_value=1000))},
        # duration_minutes out of range (too low)
        {"load_id": "load_1", "duration_minutes": draw(integers(min_value=-1000, max_value=0))},
        # duration_minutes out of range (too high)
        {"load_id": "load_1", "duration_minutes": draw(integers(min_value=1441, max_value=100000))},
    ]))


@composite
def invalid_recalculate_params(draw):
    """Generate invalid parameters for recalculate_schedule service."""
    return draw(sampled_from([
        # modules contains invalid value
        {"modules": ["invalid_module"]},
        {"modules": [draw(integers(min_value=1, max_value=100))]},
        # modules is not a list
        {"modules": "ev"},
    ]))


# --- Property 30: HA Events contain required fields ---

class TestProperty30EventsContainRequiredFields:
    """Property 30: Zdarzenia HA zawierają wymagane pola.

    Every HA event fired by PEO contains: timestamp (ISO 8601),
    entity_id, and context-specific data.
    """

    @given(
        price=floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
        threshold=floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    @PROPERTY_TEST_SETTINGS
    def test_price_threshold_crossed_event_has_required_fields(self, price, threshold):
        """Price threshold crossed event contains timestamp, entity_id, and context data.

        **Validates: Requirements 12.2**
        """
        # Only fires when state changes, so we need price to cross threshold
        assume(abs(price - threshold) > 0.001)

        hass = _make_mock_hass()
        entry = _make_mock_entry(options={"price_threshold_cheap": str(threshold)})
        sensor = CheapWindowBinarySensor(hass, entry)

        # Set initial state to opposite of what the price would trigger
        if price < threshold:
            # Will turn ON, so start OFF (set a price above threshold first)
            sensor.update_price(Decimal(str(threshold + 1.0)))
            hass.fired_events.clear()
            sensor.update_price(Decimal(str(price)))
        else:
            # Will turn OFF, so start ON (set a price below threshold first)
            sensor.update_price(Decimal(str(threshold - 1.0)))
            hass.fired_events.clear()
            sensor.update_price(Decimal(str(price)))

        # Should have fired exactly one event
        assert len(hass.fired_events) == 1
        event = hass.fired_events[0]

        assert event["event_type"] == EVENT_PRICE_THRESHOLD_CROSSED
        data = event["data"]

        # Required fields
        assert "timestamp" in data, "Event missing 'timestamp' field"
        assert "entity_id" in data, "Event missing 'entity_id' field"

        # Timestamp must be valid ISO 8601
        ts = data["timestamp"]
        datetime.fromisoformat(ts)  # Raises if invalid

        # entity_id must be non-empty string
        assert isinstance(data["entity_id"], str)
        assert len(data["entity_id"]) > 0

        # Context-specific data for price threshold event
        assert "current_price" in data
        assert "threshold" in data
        assert "direction" in data
        assert data["direction"] in ("below", "above")

    @given(
        vehicle_id=text(min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz0123456789_"),
    )
    @PROPERTY_TEST_SETTINGS
    def test_charging_started_event_has_required_fields(self, vehicle_id):
        """Charging started event contains timestamp, entity_id, and context data.

        **Validates: Requirements 12.2**
        """
        hass = _make_mock_hass()
        entry = _make_mock_entry()
        sensor = EVChargingActiveBinarySensor(hass, entry)

        # Trigger charging started (transition from OFF to ON)
        sensor.set_charging_active(True, vehicle_id=vehicle_id)

        assert len(hass.fired_events) == 1
        event = hass.fired_events[0]

        assert event["event_type"] == EVENT_CHARGING_STARTED
        data = event["data"]

        # Required fields
        assert "timestamp" in data
        assert "entity_id" in data

        # Timestamp must be valid ISO 8601
        datetime.fromisoformat(data["timestamp"])

        # entity_id must be non-empty
        assert isinstance(data["entity_id"], str)
        assert len(data["entity_id"]) > 0

        # Context-specific: vehicle_id
        assert "vehicle_id" in data
        assert data["vehicle_id"] == vehicle_id

    @given(
        vehicle_id=text(min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz0123456789_"),
    )
    @PROPERTY_TEST_SETTINGS
    def test_charging_completed_event_has_required_fields(self, vehicle_id):
        """Charging completed event contains timestamp, entity_id, and context data.

        **Validates: Requirements 12.2**
        """
        hass = _make_mock_hass()
        entry = _make_mock_entry()
        sensor = EVChargingActiveBinarySensor(hass, entry)

        # First start charging, then stop
        sensor.set_charging_active(True, vehicle_id=vehicle_id)
        hass.fired_events.clear()
        sensor.set_charging_active(False, vehicle_id=vehicle_id)

        assert len(hass.fired_events) == 1
        event = hass.fired_events[0]

        assert event["event_type"] == EVENT_CHARGING_COMPLETED
        data = event["data"]

        # Required fields
        assert "timestamp" in data
        assert "entity_id" in data

        # Timestamp must be valid ISO 8601
        datetime.fromisoformat(data["timestamp"])

        # entity_id must be non-empty
        assert isinstance(data["entity_id"], str)
        assert len(data["entity_id"]) > 0

        # Context-specific: vehicle_id
        assert "vehicle_id" in data

    @given(
        load_id=text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz0123456789_"),
        entity_id=text(min_size=5, max_size=40, alphabet="abcdefghijklmnopqrstuvwxyz0123456789_."),
        action=sampled_from(["on", "off"]),
        reason=text(min_size=1, max_size=50),
    )
    @PROPERTY_TEST_SETTINGS
    def test_load_shifted_event_has_required_fields(self, load_id, entity_id, action, reason):
        """Load shifted event contains timestamp, entity_id, and context data.

        **Validates: Requirements 12.2**
        """
        hass = _make_mock_hass()

        fire_load_shifted_event(
            hass,
            load_id=load_id,
            entity_id=entity_id,
            action=action,
            reason=reason,
            cost_pln_kwh="0.45",
        )

        assert len(hass.fired_events) == 1
        event = hass.fired_events[0]

        assert event["event_type"] == EVENT_LOAD_SHIFTED
        data = event["data"]

        # Required fields
        assert "timestamp" in data
        assert "entity_id" in data

        # Timestamp must be valid ISO 8601
        datetime.fromisoformat(data["timestamp"])

        # entity_id must be non-empty
        assert isinstance(data["entity_id"], str)
        assert len(data["entity_id"]) > 0

        # Context-specific data
        assert "load_id" in data
        assert "action" in data
        assert "reason" in data

    @given(
        schedule_type=text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz_"),
    )
    @PROPERTY_TEST_SETTINGS
    def test_schedule_updated_event_has_required_fields(self, schedule_type):
        """Schedule updated event contains timestamp, entity_id, and context data.

        **Validates: Requirements 12.2**
        """
        hass = _make_mock_hass()
        entry = _make_mock_entry()
        sensor = PEOScheduleSensor(hass, entry)

        sensor.update_schedule({"type": schedule_type, "windows": []})

        assert len(hass.fired_events) == 1
        event = hass.fired_events[0]

        assert event["event_type"] == EVENT_SCHEDULE_UPDATED
        data = event["data"]

        # Required fields
        assert "timestamp" in data
        assert "entity_id" in data

        # Timestamp must be valid ISO 8601
        datetime.fromisoformat(data["timestamp"])

        # entity_id must be non-empty
        assert isinstance(data["entity_id"], str)
        assert len(data["entity_id"]) > 0

        # Context-specific data
        assert "schedule_type" in data


# --- Property 31: Service parameter validation ---

class TestProperty31ServiceValidation:
    """Property 31: Walidacja parametrów usług HA.

    For any invalid service call parameters, the service returns
    ServiceValidationError without changing system state.
    """

    @given(params=invalid_start_ev_params())
    @PROPERTY_TEST_SETTINGS
    def test_start_ev_charging_rejects_invalid_params(self, params):
        """start_ev_charging raises vol.Invalid for invalid parameters.

        **Validates: Requirements 12.4**
        """
        with pytest.raises((vol.Invalid, vol.MultipleInvalid)):
            SCHEMA_START_EV_CHARGING(params)

    @given(params=invalid_stop_ev_params())
    @PROPERTY_TEST_SETTINGS
    def test_stop_ev_charging_rejects_invalid_params(self, params):
        """stop_ev_charging raises vol.Invalid for invalid parameters.

        **Validates: Requirements 12.4**
        """
        with pytest.raises((vol.Invalid, vol.MultipleInvalid)):
            SCHEMA_STOP_EV_CHARGING(params)

    @given(params=invalid_set_load_threshold_params())
    @PROPERTY_TEST_SETTINGS
    def test_set_load_threshold_rejects_invalid_params(self, params):
        """set_load_threshold raises vol.Invalid for invalid parameters.

        **Validates: Requirements 12.4**
        """
        with pytest.raises((vol.Invalid, vol.MultipleInvalid)):
            SCHEMA_SET_LOAD_THRESHOLD(params)

    @given(params=invalid_force_load_params())
    @PROPERTY_TEST_SETTINGS
    def test_force_load_on_rejects_invalid_params(self, params):
        """force_load_on raises vol.Invalid for invalid parameters.

        **Validates: Requirements 12.4**
        """
        with pytest.raises((vol.Invalid, vol.MultipleInvalid)):
            SCHEMA_FORCE_LOAD_ON(params)

    @given(params=invalid_force_load_params())
    @PROPERTY_TEST_SETTINGS
    def test_force_load_off_rejects_invalid_params(self, params):
        """force_load_off raises vol.Invalid for invalid parameters.

        **Validates: Requirements 12.4**
        """
        with pytest.raises((vol.Invalid, vol.MultipleInvalid)):
            SCHEMA_FORCE_LOAD_OFF(params)

    @given(params=invalid_recalculate_params())
    @PROPERTY_TEST_SETTINGS
    def test_recalculate_schedule_rejects_invalid_params(self, params):
        """recalculate_schedule raises vol.Invalid for invalid parameters.

        **Validates: Requirements 12.4**
        """
        with pytest.raises((vol.Invalid, vol.MultipleInvalid)):
            SCHEMA_RECALCULATE_SCHEDULE(params)
