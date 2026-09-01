"""Focused tests for capability-driven motion-detection configuration."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_socket
import xmltodict


@pytest.fixture(autouse=True)
def enable_event_loop_debug():
    """Avoid the HA autouse fixture's Windows socket dependency."""


@pytest.fixture(autouse=True)
def verify_cleanup():
    """Avoid the HA autouse fixture's Windows socket dependency."""


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations():
    """Keep these focused unit tests independent from HA setup."""
    yield


def _run(coro):
    pytest_socket.enable_socket()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)
        pytest_socket.disable_socket()


from custom_components.hikvision_next.capabilities import (
    CapabilityState,
    HikvisionCapabilityDiscovery,
    HikvisionCapabilityRegistry,
    NumericCapability,
)
from custom_components.hikvision_next.isapi.const import CONNECTION_TYPE_PROXIED, GET, PUT
from custom_components.hikvision_next.isapi.isapi import ISAPIClient
from custom_components.hikvision_next.number import MotionDetectionNumber, _has_complete_range
from custom_components.hikvision_next.number import async_setup_entry as async_setup_numbers
from custom_components.hikvision_next.switch import MotionTargetFilterSwitch


MOTION_CAPABILITIES = {
    "MotionDetection": {
        "startTriggerTime": {"@min": "0", "@max": "10000", "@step": "100"},
        "endTriggerTime": {"@min": "0", "@max": "10000", "@step": "100"},
        "MotionDetectionLayout": {
            "sensitivityLevel": {"@min": "1", "@max": "100", "@step": "1"},
            "targetType": {"@opt": "human,vehicle"},
        },
    }
}


def _motion_settings(
    sensitivity: str = "60", start: str = "500", end: str = "1000", targets: str = "human"
) -> dict:
    return {
        "MotionDetection": {
            "@version": "2.0",
            "@xmlns": "http://www.isapi.org/ver20/XMLSchema",
            "startTriggerTime": start,
            "endTriggerTime": end,
            "MotionDetectionLayout": {
                "sensitivityLevel": sensitivity,
                "targetType": targets,
            },
        }
    }


@dataclass
class _Camera:
    id: int
    connection_type: str = CONNECTION_TYPE_PROXIED
    streams: list = None

    def __post_init__(self):
        if self.streams is None:
            self.streams = []


class _DiscoveryDevice:
    def __init__(self, response):
        self.cameras = [_Camera(101)]
        self.supported_events = []
        self.device_info = SimpleNamespace(model="NVR")
        self._response = response

    async def async_get_capability_endpoint(self, endpoint):
        if endpoint.endswith("motionDetection/capabilities"):
            return self._response
        return HTTPStatus.NOT_FOUND, None


class _EntityDevice:
    def __init__(self, channel_id=1, settings=None, fail=False):
        self.device_info = SimpleNamespace(serial_no="DS-2CD-TEST")
        self._settings = settings or _motion_settings()
        self._fail = fail
        self.set_motion_detection_number = AsyncMock(side_effect=self._set_number)
        self.set_motion_detection_target_filter = AsyncMock(side_effect=self._set_filter)
        self.handle_exception = MagicMock()

    def hass_device_info(self, _camera_id):
        return None

    async def get_motion_detection(self, _camera_id):
        return deepcopy(self._settings)

    async def _set_number(self, _channel_id, setting, value):
        if self._fail:
            raise RuntimeError("write failed")
        motion = self._settings["MotionDetection"]
        if setting == "sensitivity":
            motion["MotionDetectionLayout"]["sensitivityLevel"] = str(int(value))
        elif setting == "start_delay":
            motion["startTriggerTime"] = str(int(value))
        else:
            motion["endTriggerTime"] = str(int(value))

    async def _set_filter(self, _channel_id, target, enabled):
        if self._fail:
            raise RuntimeError("write failed")
        selected = {
            value for value in self._settings["MotionDetection"]["MotionDetectionLayout"]["targetType"].split(",") if value
        }
        if enabled:
            selected.add(target)
        else:
            selected.discard(target)
        self._settings["MotionDetection"]["MotionDetectionLayout"]["targetType"] = ",".join(
            target for target in ("human", "vehicle") if target in selected
        )


def test_unsupported_detection_settings_create_no_number_entities():
    """A 404 capability response cannot create a number with guessed bounds."""
    registry = _run(
        HikvisionCapabilityDiscovery().async_discover(
            _DiscoveryDevice((HTTPStatus.NOT_FOUND, None)), {}
        )
    )
    caps = registry.for_channel(101)
    assert caps.motion_sensitivity.state is CapabilityState.UNSUPPORTED
    assert not _has_complete_range(caps.motion_sensitivity)
    assert caps.motion_human_filter is CapabilityState.UNSUPPORTED
    assert caps.motion_vehicle_filter is CapabilityState.UNSUPPORTED


def test_motion_capability_preserves_ranges_and_target_filters():
    """NVR proxy discovery uses the advertised values and per-channel endpoint."""
    registry = _run(
        HikvisionCapabilityDiscovery().async_discover(
            _DiscoveryDevice((HTTPStatus.OK, MOTION_CAPABILITIES)), {}
        )
    )
    caps = registry.for_channel(101)
    assert (caps.motion_sensitivity.minimum, caps.motion_sensitivity.maximum, caps.motion_sensitivity.step) == (1, 100, 1)
    assert (caps.motion_start_delay.minimum, caps.motion_start_delay.maximum, caps.motion_start_delay.step) == (0, 10000, 100)
    assert (caps.motion_end_delay.minimum, caps.motion_end_delay.maximum, caps.motion_end_delay.step) == (0, 10000, 100)
    assert caps.motion_human_filter is CapabilityState.SUPPORTED
    assert caps.motion_vehicle_filter is CapabilityState.SUPPORTED


def test_motion_numbers_are_created_without_light_capabilities():
    """The unrelated light capability cannot suppress detection settings."""
    device = _EntityDevice()
    device.cameras = [_Camera(1)]
    caps = _run(
        HikvisionCapabilityDiscovery().async_discover(
            _DiscoveryDevice((HTTPStatus.OK, MOTION_CAPABILITIES)), {}
        )
    ).for_channel(101)
    registry = HikvisionCapabilityRegistry(channels={1: caps})
    device.capabilities_registry = registry
    entities = []
    entry = SimpleNamespace(runtime_data=device)
    _run(async_setup_numbers(None, entry, entities.extend))
    assert [entity._setting for entity in entities if isinstance(entity, MotionDetectionNumber)] == [
        "sensitivity",
        "start_delay",
        "end_delay",
    ]


def test_number_read_write_refreshes_state():
    """A successful motion write is followed by a read of the accepted value."""
    device = _EntityDevice()
    cap = NumericCapability(CapabilityState.SUPPORTED, 1, 100, 1)
    entity = MotionDetectionNumber(device, 1, cap, "sensitivity")
    entity.async_write_ha_state = MagicMock()
    _run(entity.async_added_to_hass())
    assert entity.native_value == 60
    _run(entity.async_set_native_value(75))
    device.set_motion_detection_number.assert_awaited_once_with(1, "sensitivity", 75)
    assert entity.native_value == 75


def test_start_and_end_delay_read_write():
    """Both timing controls use their distinct ISAPI setting keys."""
    device = _EntityDevice()
    cap = NumericCapability(CapabilityState.SUPPORTED, 0, 10000, 100)
    start = MotionDetectionNumber(device, 1, cap, "start_delay")
    end = MotionDetectionNumber(device, 1, cap, "end_delay")
    start.async_write_ha_state = MagicMock()
    end.async_write_ha_state = MagicMock()
    _run(start.async_added_to_hass())
    _run(end.async_added_to_hass())
    _run(start.async_set_native_value(700))
    _run(end.async_set_native_value(1200))
    assert start.native_value == 700
    assert end.native_value == 1200


def test_human_and_vehicle_filter_read_write():
    """Independent switches preserve the other selected target type."""
    device = _EntityDevice(settings=_motion_settings(targets="human"))
    human = MotionTargetFilterSwitch(device, 1, "human")
    vehicle = MotionTargetFilterSwitch(device, 1, "vehicle")
    human.async_write_ha_state = MagicMock()
    vehicle.async_write_ha_state = MagicMock()
    _run(human.async_added_to_hass())
    _run(vehicle.async_added_to_hass())
    assert human.is_on is True
    assert vehicle.is_on is False
    _run(vehicle.async_turn_on())
    assert vehicle.is_on is True
    _run(human.async_turn_off())
    assert human.is_on is False
    assert vehicle.is_on is True


def test_failed_write_leaves_entity_state_unchanged():
    """One failed setting reports locally and does not raise into the integration."""
    device = _EntityDevice(fail=True)
    cap = NumericCapability(CapabilityState.SUPPORTED, 1, 100, 1)
    entity = MotionDetectionNumber(device, 1, cap, "sensitivity")
    entity.async_write_ha_state = MagicMock()
    _run(entity.async_added_to_hass())
    _run(entity.async_set_native_value(75))
    assert entity.native_value == 60
    device.handle_exception.assert_called_once()


def test_client_writes_complete_motion_xml_and_target_filter():
    """The ISAPI client preserves unrelated XML while updating just the setting."""
    client = ISAPIClient("http://camera", "user", "pass")
    writes = []

    async def request(method, _url, present="dict", data=None):
        if method == GET:
            return _motion_settings(targets="human,vehicle")
        assert method == PUT
        writes.append(data)
        return ""

    client.request = AsyncMock(side_effect=request)
    _run(client.set_motion_detection_number(1, "start_delay", 700))
    _run(client.set_motion_detection_target_filter(1, "vehicle", False))
    first = xmltodict.parse(writes[0])
    second = xmltodict.parse(writes[1])
    assert first["MotionDetection"]["startTriggerTime"] == "700"
    assert second["MotionDetection"]["MotionDetectionLayout"]["targetType"] == "human"


def test_nvr_channel_mapping_is_preserved_for_writes():
    """Entities use the discovered NVR proxy channel without remapping it."""
    device = _EntityDevice()
    cap = NumericCapability(CapabilityState.SUPPORTED, 1, 100, 1)
    entity = MotionDetectionNumber(device, 101, cap, "sensitivity")
    entity.async_write_ha_state = MagicMock()
    _run(entity.async_set_native_value(80))
    device.set_motion_detection_number.assert_awaited_once_with(101, "sensitivity", 80)
