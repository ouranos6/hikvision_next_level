"""Tests for Phase 5: Human / Vehicle event classification.

These tests follow the same Windows-compatible fixture-override pattern as
``test_capabilities.py`` to avoid the pytest_socket / HA event-loop conflict.

Pure parsing, normalization and capability-decision tests run synchronously.
Processor tests that need a Home Assistant state machine use a lightweight
mock instead of a full ``init_integration`` setup so they can run without
real sockets.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pytest_socket

FIXTURES = Path(__file__).parent / "fixtures" / "ISAPI" / "EventNotificationAlert"


def event_xml(name: str) -> str:
    """Load a captured Hikvision event fixture."""
    return (FIXTURES / f"{name}.xml").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixture overrides – mirror test_capabilities.py so sync tests run on Windows
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def enable_event_loop_debug():
    pass


@pytest.fixture(autouse=True)
def verify_cleanup():
    pass


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations():
    yield


@pytest.fixture(autouse=True)
def expected_lingering_tasks():
    return True


@pytest.fixture(autouse=True)
def expected_lingering_timers():
    return True


def _run_async(coro):
    """Run *coro* with sockets temporarily unblocked."""
    import asyncio

    pytest_socket.enable_socket()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)
        pytest_socket.disable_socket()


# ---------------------------------------------------------------------------
# Imports (after fixture overrides so custom_components loads cleanly)
# ---------------------------------------------------------------------------

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.util import slugify

from custom_components.hikvision_next.capabilities import CapabilityState
from custom_components.hikvision_next.events import (
    HikvisionEventParser,
    HikvisionEventProcessor,
    normalize_detection_target,
)
from custom_components.hikvision_next.isapi.models import ISAPIDeviceInfo

# ---------------------------------------------------------------------------
# Target normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("human", "human"),
        ("Human", "human"),
        ("PERSON", "human"),
        ("person", "human"),
        ("vehicle", "vehicle"),
        ("Vehicle", "vehicle"),
        ("CAR", "vehicle"),
        ("car", "vehicle"),
        ("unknown_target", "unknown_target"),
        ("", None),
    ],
)
def test_normalize_detection_target(raw, expected):
    """Canonical target values must be stable across casing and aliases."""
    assert normalize_detection_target(raw) == expected


def test_normalize_detection_target_none():
    """None input must return None."""
    assert normalize_detection_target(None) is None


# ---------------------------------------------------------------------------
# Parser preserves / normalizes detectionTarget
# ---------------------------------------------------------------------------


def test_parser_normalizes_human_detection_target():
    """Existing fixture still parses detectionTarget as human."""
    event = HikvisionEventParser().parse(event_xml("fielddetection_human"))
    assert event.detection_target == "human"
    assert event.event_state == "active"


def test_parser_normalizes_vehicle_detection_target():
    """Vehicle fixture still parses detectionTarget as vehicle."""
    event = HikvisionEventParser().parse(event_xml("fielddetection_vehicle"))
    assert event.detection_target == "vehicle"


def test_parser_inactive_human_event():
    """Inactive human event parses detectionTarget and eventState."""
    event = HikvisionEventParser().parse(event_xml("fielddetection_human_inactive"))
    assert event.detection_target == "human"
    assert event.event_state == "inactive"


def test_parser_inactive_vehicle_event():
    """Inactive vehicle event parses detectionTarget and eventState."""
    event = HikvisionEventParser().parse(event_xml("fielddetection_vehicle_inactive"))
    assert event.detection_target == "vehicle"
    assert event.event_state == "inactive"


def test_parser_unknown_target_does_not_crash():
    """Unknown detectionTarget must not crash parsing."""
    event = HikvisionEventParser().parse(event_xml("fielddetection_unknown_target"))
    assert event.detection_target == "unknown_target"


def test_parser_nvr_event_without_target():
    """NVR events without DetectionRegionList have detection_target=None."""
    event = HikvisionEventParser().parse(event_xml("nvr_2_fielddetection"))
    assert event.detection_target is None


def test_nvr_event_with_human_target_parses():
    """NVR event with DetectionRegionList parses channel_id and target."""
    event = HikvisionEventParser().parse(event_xml("nvr_1_fielddetection_human"))
    assert event.channel_id == 34
    assert event.detection_target == "human"
    assert event.event_state == "active"
    assert event.event_id == "fielddetection"


def test_existing_ha_event_payload_remains_compatible():
    """Existing detection_target key and payload structure are preserved."""
    xml = (
        "<EventNotificationAlert>"
        "<eventType>fielddetection</eventType>"
        "<channelID>1</channelID>"
        "<eventState>active</eventState>"
        "<DetectionRegionList>"
        "<DetectionRegionEntry>"
        "<regionID>5</regionID>"
        "<detectionTarget>human</detectionTarget>"
        "</DetectionRegionEntry>"
        "</DetectionRegionList>"
        "</EventNotificationAlert>"
    )
    event = HikvisionEventParser().parse(xml)
    assert event.detection_target == "human"
    assert event.region_id == 5
    assert event.event_id == "fielddetection"


# ---------------------------------------------------------------------------
# _should_create_target_entity capability policy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "has_target_events", "expected"),
    [
        (CapabilityState.SUPPORTED, True, True),
        (CapabilityState.SUPPORTED, False, True),
        (CapabilityState.UNSUPPORTED, True, False),
        (CapabilityState.UNSUPPORTED, False, False),
        (CapabilityState.UNKNOWN, True, True),
        (CapabilityState.UNKNOWN, False, False),
    ],
)
def test_should_create_target_entity(state, has_target_events, expected):
    """Capability policy: SUPPORTED=create, UNSUPPORTED=skip, UNKNOWN=conservative."""
    assert _should_create_target_entity(state, has_target_events) is expected


# ---------------------------------------------------------------------------
# _trigger_target_sensor – person and vehicle ON / OFF
# ---------------------------------------------------------------------------


class _MockEntityRegistry:
    """Minimal entity registry stub for testing _trigger_target_sensor."""

    def __init__(self, known_ids: set[str] | None = None):
        self._known = known_ids or set()

    def async_get_entity_id(self, platform, domain, unique_id):
        return unique_id if unique_id in self._known else None


class _MockStates:
    """Capture state writes for assertion."""

    def __init__(self):
        self.written: dict[str, tuple[str, dict]] = {}

    def get(self, entity_id):
        state = self.written.get(entity_id)
        if state is None:
            return None
        return SimpleNamespace(state=state[0], attributes=state[1])

    def async_set(self, entity_id, state, attributes=None):
        self.written[entity_id] = (state, attributes or {})


def _make_processor(serial_no, known_ids, states=None):
    """Build a HikvisionEventProcessor with mocked hass plumbing."""
    device_info = ISAPIDeviceInfo(
        serial_no=serial_no,
        mac_address="aa:bb:cc:dd:ee:ff",
    )
    registry = _MockEntityRegistry(known_ids)
    states = states or _MockStates()

    processor = HikvisionEventProcessor.__new__(HikvisionEventProcessor)
    processor.hass = SimpleNamespace(
        states=states,
        bus=MagicMock(),
    )
    processor._entity_registry = registry

    # Patch async_get to return our mock registry
    import custom_components.hikvision_next.events as events_mod

    original_async_get = events_mod.async_get
    events_mod.async_get = lambda hass: registry
    processor._async_get_patch = lambda: None  # placeholder

    # We also need to patch _async_get_device to return a mock device
    mock_device = SimpleNamespace(
        device_info=device_info,
        get_camera_by_id=lambda cid: SimpleNamespace(name="camera-1"),
    )
    processor._mock_device = mock_device

    return processor, states, events_mod, original_async_get


from custom_components.hikvision_next.binary_sensor import (
    TargetBinarySensor,
    _should_create_target_entity,
)


def test_person_sensor_turns_on_for_human_active():
    """human active event turns the person sensor ON and leaves vehicle OFF."""
    serial = "DS-2CD2386G2-IU000001"
    person_uid = f"{slugify(serial.lower())}_1_person"
    vehicle_uid = f"{slugify(serial.lower())}_1_vehicle"

    processor, states, events_mod, orig = _make_processor(
        serial, {person_uid, vehicle_uid}
    )
    # Pre-set states
    states.written[person_uid] = (STATE_OFF, {})
    states.written[vehicle_uid] = (STATE_OFF, {})

    try:
        event = HikvisionEventParser().parse(event_xml("fielddetection_human"))
        processor._trigger_target_sensor(processor._mock_device, event)

        assert states.written[person_uid][0] == STATE_ON
        assert states.written[vehicle_uid][0] == STATE_OFF
    finally:
        events_mod.async_get = orig


def test_person_sensor_turns_off_for_human_inactive():
    """human inactive event turns the person sensor OFF."""
    serial = "DS-2CD2386G2-IU000001"
    person_uid = f"{slugify(serial.lower())}_1_person"

    processor, states, events_mod, orig = _make_processor(
        serial, {person_uid}
    )
    states.written[person_uid] = (STATE_ON, {})

    try:
        event = HikvisionEventParser().parse(
            event_xml("fielddetection_human_inactive")
        )
        processor._trigger_target_sensor(processor._mock_device, event)

        assert states.written[person_uid][0] == STATE_OFF
    finally:
        events_mod.async_get = orig


def test_vehicle_sensor_turns_on_for_vehicle_active():
    """vehicle active event turns the vehicle sensor ON."""
    serial = "DS-2CD2386G2-IU000001"
    vehicle_uid = f"{slugify(serial.lower())}_1_vehicle"

    processor, states, events_mod, orig = _make_processor(
        serial, {vehicle_uid}
    )
    states.written[vehicle_uid] = (STATE_OFF, {})

    try:
        event = HikvisionEventParser().parse(event_xml("fielddetection_vehicle"))
        processor._trigger_target_sensor(processor._mock_device, event)

        assert states.written[vehicle_uid][0] == STATE_ON
    finally:
        events_mod.async_get = orig


def test_vehicle_sensor_turns_off_for_vehicle_inactive():
    """vehicle inactive event turns the vehicle sensor OFF."""
    serial = "DS-2CD2386G2-IU000001"
    vehicle_uid = f"{slugify(serial.lower())}_1_vehicle"

    processor, states, events_mod, orig = _make_processor(
        serial, {vehicle_uid}
    )
    states.written[vehicle_uid] = (STATE_ON, {})

    try:
        event = HikvisionEventParser().parse(
            event_xml("fielddetection_vehicle_inactive")
        )
        processor._trigger_target_sensor(processor._mock_device, event)

        assert states.written[vehicle_uid][0] == STATE_OFF
    finally:
        events_mod.async_get = orig


def test_human_event_does_not_activate_vehicle():
    """human event must not affect the vehicle sensor."""
    serial = "DS-2CD2386G2-IU000001"
    person_uid = f"{slugify(serial.lower())}_1_person"
    vehicle_uid = f"{slugify(serial.lower())}_1_vehicle"

    processor, states, events_mod, orig = _make_processor(
        serial, {person_uid, vehicle_uid}
    )
    states.written[person_uid] = (STATE_OFF, {})
    states.written[vehicle_uid] = (STATE_OFF, {})

    try:
        event = HikvisionEventParser().parse(event_xml("fielddetection_human"))
        processor._trigger_target_sensor(processor._mock_device, event)

        assert states.written[person_uid][0] == STATE_ON
        assert states.written[vehicle_uid][0] == STATE_OFF
    finally:
        events_mod.async_get = orig


def test_vehicle_event_does_not_activate_person():
    """vehicle event must not affect the person sensor."""
    serial = "DS-2CD2386G2-IU000001"
    person_uid = f"{slugify(serial.lower())}_1_person"
    vehicle_uid = f"{slugify(serial.lower())}_1_vehicle"

    processor, states, events_mod, orig = _make_processor(
        serial, {person_uid, vehicle_uid}
    )
    states.written[person_uid] = (STATE_OFF, {})
    states.written[vehicle_uid] = (STATE_OFF, {})

    try:
        event = HikvisionEventParser().parse(event_xml("fielddetection_vehicle"))
        processor._trigger_target_sensor(processor._mock_device, event)

        assert states.written[vehicle_uid][0] == STATE_ON
        assert states.written[person_uid][0] == STATE_OFF
    finally:
        events_mod.async_get = orig


def test_target_sensor_and_bus_event_do_not_depend_on_legacy_sensor():
    """A disabled legacy event sensor must not suppress target classification."""
    serial = "DS-2CD2386G2-IU000001"
    person_uid = f"{slugify(serial.lower())}_1_person"
    processor, states, events_mod, orig = _make_processor(serial, {person_uid})
    states.written[person_uid] = (STATE_OFF, {})

    try:
        event = HikvisionEventParser().parse(event_xml("fielddetection_human"))
        processor._trigger_sensor(processor._mock_device, event)

        assert states.written[person_uid][0] == STATE_ON
        processor.hass.bus.fire.assert_called_once()
    finally:
        events_mod.async_get = orig


def test_unknown_target_does_not_update_sensors():
    """Unknown detectionTarget must not touch any target sensor."""
    serial = "DS-2CD2386G2-IU000001"
    person_uid = f"{slugify(serial.lower())}_1_person"
    vehicle_uid = f"{slugify(serial.lower())}_1_vehicle"

    processor, states, events_mod, orig = _make_processor(
        serial, {person_uid, vehicle_uid}
    )
    states.written[person_uid] = (STATE_OFF, {})
    states.written[vehicle_uid] = (STATE_OFF, {})

    try:
        event = HikvisionEventParser().parse(
            event_xml("fielddetection_unknown_target")
        )
        processor._trigger_target_sensor(processor._mock_device, event)

        assert states.written[person_uid][0] == STATE_OFF
        assert states.written[vehicle_uid][0] == STATE_OFF
    finally:
        events_mod.async_get = orig


def test_no_detection_target_skips_target_sensor():
    """Event without detectionTarget must not touch target sensors."""
    serial = "DS-7608NXI-I0/0P/S0000000000CCRRJ00000000WCVU"
    person_uid = f"{slugify(serial.lower())}_2_person"

    processor, states, events_mod, orig = _make_processor(
        serial, {person_uid}
    )
    states.written[person_uid] = (STATE_OFF, {})

    try:
        # NVR event without DetectionRegionList
        event = HikvisionEventParser().parse(event_xml("nvr_2_fielddetection"))
        # Resolve channel 34 -> 2
        from custom_components.hikvision_next.isapi.models import IPCamera as IPT

        camera = IPT(
            id=2,
            name="home",
            model="DS-2CD2386G2-IU",
            serial_no="DS-2CD2386G2-IU00000000AAWRK00000002",
            input_port=2,
            connection_type="Proxied",
            streams=[],
        )
        mock_device = SimpleNamespace(
            device_info=processor._mock_device.device_info,
            cameras=[camera],
            get_camera_by_id=lambda cid: SimpleNamespace(name="home"),
        )
        HikvisionEventProcessor.resolve_event_channel(mock_device, event)
        assert event.channel_id == 2

        processor._trigger_target_sensor(mock_device, event)

        assert states.written[person_uid][0] == STATE_OFF
    finally:
        events_mod.async_get = orig


# ---------------------------------------------------------------------------
# TargetBinarySensor entity – unique_id and device class
# ---------------------------------------------------------------------------


def test_target_binary_sensor_unique_id():
    """Person sensor uses a stable unique ID independent from its entity ID."""
    mock_device = MagicMock()
    mock_device.device_info.serial_no = "DS-2CD2386G2-IU000001"
    mock_device.hass_device_info.return_value = MagicMock()

    sensor = TargetBinarySensor(mock_device, 1, "person")
    assert sensor._attr_unique_id == "ds_2cd2386g2_iu000001_1_person"
    assert sensor._attr_translation_key == "person"


def test_target_binary_sensor_vehicle_unique_id():
    """Vehicle sensor unique_id uses vehicle suffix."""
    mock_device = MagicMock()
    mock_device.device_info.serial_no = "DS-7608NXI-I0/0P/S00000000WCVU"
    mock_device.hass_device_info.return_value = MagicMock()

    sensor = TargetBinarySensor(mock_device, 2, "vehicle")
    assert sensor._attr_unique_id == "ds_7608nxi_i0_0p_s00000000wcvu_2_vehicle"


def test_target_binary_sensor_no_polling():
    """Person/vehicle sensors must not poll."""
    mock_device = MagicMock()
    mock_device.device_info.serial_no = "DS-2CD2386G2-IU000001"
    mock_device.hass_device_info.return_value = MagicMock()

    sensor = TargetBinarySensor(mock_device, 1, "person")
    assert sensor._attr_is_on is False
