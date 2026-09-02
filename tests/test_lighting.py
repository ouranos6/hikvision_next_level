"""Tests for Phase 7: Supplement light controls.

Uses the _run_async pattern from test_capabilities.py for Windows
compatibility (pytest_socket / asyncio event-loop conflict).

Covers:
  * Capability discovery of light modes and brightness
  * Entity creation (only when supported)
  * Select options from opt=
  * Brightness min/max/step
  * Successful read/write via ISAPI
  * Write failure without breaking the integration
  * NVR channel mapping
"""

from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_socket

# Fixture overrides – mirror test_capabilities.py so sync tests run on Windows
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


# Imports after fixture overrides
from custom_components.hikvision_next.capabilities import (
    CapabilityState,
    HikvisionCapabilities,
    HikvisionCapabilityDiscovery,
    HikvisionCapabilityRegistry,
    NumericCapability,
    SelectCapability,
)
from custom_components.hikvision_next.isapi.const import (
    CONNECTION_TYPE_DIRECT,
    CONNECTION_TYPE_PROXIED,
    GET,
    PUT,
)
from custom_components.hikvision_next.isapi.models import CameraStreamInfo
from custom_components.hikvision_next.select import SupplementLightModeSelect
from custom_components.hikvision_next.number import SupplementLightBrightnessNumber
from custom_components.hikvision_next.isapi.utils import deep_get


# ---------------------------------------------------------------------------
# Test helpers (mirror test_capabilities.py)
# ---------------------------------------------------------------------------


@dataclass
class MockCamera:
    id: int
    name: str
    model: str
    connection_type: str = CONNECTION_TYPE_DIRECT
    streams: list[CameraStreamInfo] = field(default_factory=list)


@dataclass
class MockDeviceInfo:
    model: str = "DS-2CD2386G2-IU"
    serial_no: str = "DS-2CD2386G2-IU00000001"


@dataclass
class MockEvent:
    id: str
    channel_id: int = 0
    io_port_id: int = 0


@dataclass
class _MockCamera:
    id: int
    name: str = "cam"


class MockCapabilityDevice:
    """Fake device implementing CapabilityDevice for discovery tests."""

    def __init__(
        self,
        cameras: list[MockCamera],
        supported_events: list[MockEvent] | None = None,
        device_info: MockDeviceInfo | None = None,
        endpoint_responses: dict[str, tuple[int, dict[str, Any] | None]] | None = None,
    ):
        self.cameras = cameras
        self.supported_events = supported_events or []
        self.device_info = device_info or MockDeviceInfo()
        self._endpoints = endpoint_responses or {}
        self.async_get_capability_endpoint = AsyncMock(side_effect=self._resolve)

    async def _resolve(self, endpoint: str) -> tuple[int, dict[str, Any] | None]:
        return self._endpoints.get(endpoint, (HTTPStatus.NOT_FOUND, None))


class _MockDevice:
    """Lightweight device mock for entity tests."""

    def __init__(
        self,
        cameras=None,
        capabilities_registry=None,
        image_channel_responses=None,
        set_errors=None,
    ):
        self.cameras = cameras or []
        self.capabilities_registry = capabilities_registry or HikvisionCapabilityRegistry()
        self._image_responses = list(image_channel_responses) if image_channel_responses else []
        self._set_errors = set_errors or {}
        self.device_info = MockDeviceInfo()

        async def _get_supplement_light(channel_id):
            data = self._image_responses.pop(0) if self._image_responses else {}
            # Existing entity tests used the generic ImageChannel fixture;
            # keep those fixtures useful while production reads SupplementLight.
            if "ImageChannel" in data:
                return {"SupplementLight": data["ImageChannel"]}
            return data

        async def _set_mode(channel_id, mode):
            key = (channel_id, "mode")
            if key in self._set_errors:
                raise self._set_errors[key]
            self._mode_set = mode

        async def _set_brightness(channel_id, brightness):
            key = (channel_id, "brightness")
            if key in self._set_errors:
                raise self._set_errors[key]
            self._brightness_set = brightness

        self.get_supplement_light = AsyncMock(side_effect=_get_supplement_light)
        self.set_supplement_light_mode = AsyncMock(side_effect=_set_mode)
        self.set_supplement_light_brightness = AsyncMock(side_effect=_set_brightness)
        self.handle_exception = MagicMock()

    def hass_device_info(self, camera_id=0):
        return {"identifiers": {("hikvision_next", "serial001")}, "name": "cam"}


# ---------------------------------------------------------------------------
# Capability discovery: light modes
# ---------------------------------------------------------------------------


def _image_xml(modes: str, brightness_min=1, brightness_max=100, brightness_step=1):
    """Build an ImageChannel capability response dict."""
    return {
        "ImageChannel": {
            "supplementLightMode": {"@opt": modes},
            "supplementLightBrightness": {
                "@min": str(brightness_min),
                "@max": str(brightness_max),
                "@step": str(brightness_step),
            },
        }
    }


def _supplement_light_xml(modes: str, brightness_min=1, brightness_max=100, brightness_step=1):
    """Build a dedicated ColorVu supplement-light capability response."""
    return {
        "SupplementLight": {
            "supplementLightMode": {"@opt": modes},
            "whiteLightBrightness": {
                "@min": str(brightness_min),
                "@max": str(brightness_max),
                "@step": str(brightness_step),
            },
        }
    }


def test_discover_colorvu_supplement_light_resource():
    """ColorVu uses the dedicated supplementLight resource and vendor mode names."""
    camera = MockCamera(id=1, name="cam", model="DS-2CD2T87G2-L", streams=[])
    device = MockCapabilityDevice(
        cameras=[camera],
        endpoint_responses={
            "Image/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
            "Image/channels/1/supplementLight/capabilities": (
                HTTPStatus.OK,
                _supplement_light_xml("colorVuWhiteLight,irLight,close", 0, 100, 5),
            ),
        },
    )

    caps = _run_async(HikvisionCapabilityDiscovery().async_discover(device, {})).for_channel(1)

    assert caps.supplement_light_mode.options == ("colorVuWhiteLight", "irLight", "close")
    assert caps.white_light is CapabilityState.SUPPORTED
    assert caps.ir_light is CapabilityState.SUPPORTED
    assert caps.light_brightness == NumericCapability(CapabilityState.SUPPORTED, 0, 100, 5)


def test_discover_ir_only_camera():
    """IR-only camera: ir_light SUPPORTED, others UNSUPPORTED."""
    camera = MockCamera(id=1, name="cam", model="DS-2CD2532F-IWS", connection_type=CONNECTION_TYPE_DIRECT, streams=[])
    device = MockCapabilityDevice(
        cameras=[camera],
        supported_events=[],
        endpoint_responses={
            "Image/channels/1/capabilities": (HTTPStatus.OK, _image_xml("off,ir")),
            "PTZCtrl/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
            "System/Audio/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
        },
    )
    registry = _run_async(
        HikvisionCapabilityDiscovery().async_discover(device, {})
    )
    caps = registry.for_channel(1)
    assert caps.ir_light == CapabilityState.SUPPORTED
    assert caps.white_light == CapabilityState.UNSUPPORTED
    assert caps.smart_hybrid_light == CapabilityState.UNSUPPORTED
    assert caps.supplement_light_mode.state == CapabilityState.SUPPORTED
    assert caps.supplement_light_mode.options == ("off", "ir")


def test_discover_white_light_camera():
    """White-light camera: white_light SUPPORTED, others UNSUPPORTED."""
    camera = MockCamera(id=1, name="cam", model="DS-2CD2T86G2-ISU", connection_type=CONNECTION_TYPE_DIRECT, streams=[])
    device = MockCapabilityDevice(
        cameras=[camera],
        supported_events=[],
        endpoint_responses={
            "Image/channels/1/capabilities": (HTTPStatus.OK, _image_xml("off,ir,white")),
            "PTZCtrl/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
            "System/Audio/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
        },
    )
    registry = _run_async(
        HikvisionCapabilityDiscovery().async_discover(device, {})
    )
    caps = registry.for_channel(1)
    assert caps.ir_light == CapabilityState.SUPPORTED
    assert caps.white_light == CapabilityState.SUPPORTED
    assert caps.smart_hybrid_light == CapabilityState.UNSUPPORTED
    assert caps.supplement_light_mode.options == ("off", "ir", "white")


def test_discover_smart_hybrid_light_camera():
    """ColorVu camera: ir, white, smart all SUPPORTED."""
    camera = MockCamera(id=1, name="cam", model="DS-2CD2386G2-IU", connection_type=CONNECTION_TYPE_DIRECT, streams=[])
    device = MockCapabilityDevice(
        cameras=[camera],
        supported_events=[],
        endpoint_responses={
            "Image/channels/1/capabilities": (HTTPStatus.OK, _image_xml("off,ir,white,smart")),
            "PTZCtrl/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
            "System/Audio/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
        },
    )
    registry = _run_async(
        HikvisionCapabilityDiscovery().async_discover(device, {})
    )
    caps = registry.for_channel(1)
    assert caps.ir_light == CapabilityState.SUPPORTED
    assert caps.white_light == CapabilityState.SUPPORTED
    assert caps.smart_hybrid_light == CapabilityState.SUPPORTED
    assert caps.supplement_light_mode.options == ("off", "ir", "white", "smart")


def test_discover_unsupported_light_control():
    """No Image endpoint → light capabilities stay UNKNOWN/UNSUPPORTED."""
    camera = MockCamera(id=1, name="cam", model="DS-2CD2146G2-ISU", connection_type=CONNECTION_TYPE_DIRECT, streams=[])
    device = MockCapabilityDevice(
        cameras=[camera],
        supported_events=[],
        endpoint_responses={
            "Image/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
            "PTZCtrl/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
            "System/Audio/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
        },
    )
    registry = _run_async(
        HikvisionCapabilityDiscovery().async_discover(device, {})
    )
    caps = registry.for_channel(1)
    assert caps.ir_light == CapabilityState.UNKNOWN
    assert caps.white_light == CapabilityState.UNKNOWN
    assert caps.smart_hybrid_light == CapabilityState.UNKNOWN
    assert caps.supplement_light_mode.state == CapabilityState.UNSUPPORTED
    assert caps.light_brightness.state == CapabilityState.UNSUPPORTED


def test_brightness_min_max_step_from_opt():
    """Brightness min/max/step preserved from capability response."""
    camera = MockCamera(id=1, name="cam", model="DS-2CD2386G2-IU", connection_type=CONNECTION_TYPE_DIRECT, streams=[])
    device = MockCapabilityDevice(
        cameras=[camera],
        supported_events=[],
        endpoint_responses={
            "Image/channels/1/capabilities": (HTTPStatus.OK, _image_xml("off,ir,white,smart", 0, 100, 5)),
            "PTZCtrl/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
            "System/Audio/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
        },
    )
    registry = _run_async(
        HikvisionCapabilityDiscovery().async_discover(device, {})
    )
    caps = registry.for_channel(1)
    assert caps.light_brightness.state == CapabilityState.SUPPORTED
    assert caps.light_brightness.minimum == 0.0
    assert caps.light_brightness.maximum == 100.0
    assert caps.light_brightness.step == 5.0


# ---------------------------------------------------------------------------
# Select options from opt=
# ---------------------------------------------------------------------------


def test_select_options_preserved_from_opt():
    """opt= values preserved as options tuple on supplement_light_mode."""
    camera = MockCamera(id=1, name="cam", model="DS-2CD2386G2-IU", connection_type=CONNECTION_TYPE_DIRECT, streams=[])
    device = MockCapabilityDevice(
        cameras=[camera],
        supported_events=[],
        endpoint_responses={
            "Image/channels/1/capabilities": (HTTPStatus.OK, _image_xml("off,ir,white,smart")),
            "PTZCtrl/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
            "System/Audio/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
        },
    )
    registry = _run_async(
        HikvisionCapabilityDiscovery().async_discover(device, {})
    )
    caps = registry.for_channel(1)
    assert caps.supplement_light_mode.state == CapabilityState.SUPPORTED
    assert caps.supplement_light_mode.options == ("off", "ir", "white", "smart")


# ---------------------------------------------------------------------------
# Entity creation: select and number entities
# ---------------------------------------------------------------------------


class _AsyncIter:
    """Wrap a dict in an async-returning callable for get_image_channel."""

    @staticmethod
    def _return(data):
        async def _gen():
            return data
        return _gen()


def _make_registry_for_channel(channel_id, ir=True, white=True, smart=True, brightness=True):
    caps = HikvisionCapabilities()
    if ir:
        caps.ir_light = CapabilityState.SUPPORTED
    if white:
        caps.white_light = CapabilityState.SUPPORTED
    if smart:
        caps.smart_hybrid_light = CapabilityState.SUPPORTED
    if brightness:
        caps.light_brightness = NumericCapability(
            state=CapabilityState.SUPPORTED, minimum=1.0, maximum=100.0, step=1.0
        )
    caps.supplement_light_mode = SelectCapability(
        state=CapabilityState.SUPPORTED,
        options=("off", "ir", "white", "smart") if smart else ("off", "ir", "white") if white else ("off", "ir"),
    )
    reg = HikvisionCapabilityRegistry()
    reg.channels[channel_id] = caps
    return reg


def test_select_entity_created_when_supported():
    """Select entity created when supplement_light_mode is SUPPORTED."""
    reg = _make_registry_for_channel(1, ir=True, white=True, smart=True)
    device = _MockDevice(
        cameras=[_MockCamera(id=1, name="cam")],
        capabilities_registry=reg,
        image_channel_responses=[
            {"ImageChannel": {"supplementLightMode": "ir"}}
        ],
    )

    entities = _run_async(_async_create_select_entities(device))
    assert len(entities) == 1
    entity = entities[0]
    assert isinstance(entity, SupplementLightModeSelect)
    assert entity.current_option == "ir"
    assert entity.options == ["off", "ir", "white", "smart"]


def test_select_entity_not_created_when_unsupported():
    """No select entity when supplement_light_mode is UNSUPPORTED."""
    reg = HikvisionCapabilityRegistry()
    device = _MockDevice(
        cameras=[_MockCamera(id=1, name="cam")],
        capabilities_registry=reg,
        image_channel_responses=[],
    )

    entities = _run_async(_async_create_select_entities(device))
    assert len(entities) == 0


async def _async_create_select_entities(device):
    """Replicate select.async_setup_entry entity creation logic."""
    entities = []
    caps_registry = device.capabilities_registry
    for camera in device.cameras:
        caps = caps_registry.for_channel(camera.id) if caps_registry else HikvisionCapabilities()
        if caps.supplement_light_mode.state is CapabilityState.SUPPORTED and caps.supplement_light_mode.options:
            entity = SupplementLightModeSelect(device, camera.id, caps)
            entity.async_write_ha_state = MagicMock()
            await entity.async_added_to_hass()
            entities.append(entity)
    return entities


def test_number_entity_created_for_ir():
    """Number entity created for IR when ir_light is SUPPORTED."""
    reg = _make_registry_for_channel(1, ir=True, white=False, smart=False)
    device = _MockDevice(
        cameras=[_MockCamera(id=1, name="cam")],
        capabilities_registry=reg,
        image_channel_responses=[
            {"ImageChannel": {"supplementLightBrightness": "50"}}
        ],
    )

    entities = _run_async(_async_create_number_entities(device))
    assert len(entities) == 1
    entity = entities[0]
    assert isinstance(entity, SupplementLightBrightnessNumber)
    assert entity._light_type == "ir"
    assert entity.native_value == 50.0
    assert entity.native_min_value == 1
    assert entity.native_max_value == 100
    assert entity.native_step == 1


def test_number_entity_created_for_white():
    """Number entity created for white light when white_light is SUPPORTED."""
    reg = _make_registry_for_channel(1, ir=False, white=True, smart=False)
    device = _MockDevice(
        cameras=[_MockCamera(id=1, name="cam")],
        capabilities_registry=reg,
        image_channel_responses=[
            {"ImageChannel": {"supplementLightBrightness": "80"}}
        ],
    )

    entities = _run_async(_async_create_number_entities(device))
    assert len(entities) == 1
    assert entities[0]._light_type == "white"


def test_number_entities_created_for_both_types():
    """Both IR and white brightness entities created when both supported."""
    reg = _make_registry_for_channel(1, ir=True, white=True, smart=True)
    device = _MockDevice(
        cameras=[_MockCamera(id=1, name="cam")],
        capabilities_registry=reg,
        image_channel_responses=[
            {"ImageChannel": {"supplementLightBrightness": "50"}},
            {"ImageChannel": {"supplementLightBrightness": "50"}},
        ],
    )

    entities = _run_async(_async_create_number_entities(device))
    assert len(entities) == 2
    light_types = {e._light_type for e in entities}
    assert light_types == {"ir", "white"}


def test_no_number_entity_when_brightness_unsupported():
    """No brightness entity when light_brightness capability is UNSUPPORTED."""
    reg = _make_registry_for_channel(1, ir=True, white=True, smart=False, brightness=False)
    device = _MockDevice(
        cameras=[_MockCamera(id=1, name="cam")],
        capabilities_registry=reg,
        image_channel_responses=[],
    )

    entities = _run_async(_async_create_number_entities(device))
    assert len(entities) == 0


async def _async_create_number_entities(device):
    """Replicate number.async_setup_entry entity creation logic."""
    entities = []
    caps_registry = device.capabilities_registry
    for camera in device.cameras:
        caps = caps_registry.for_channel(camera.id) if caps_registry else HikvisionCapabilities()
        light_caps = caps.light_brightness
        if light_caps.state is not CapabilityState.SUPPORTED:
            continue
        if caps.ir_light is CapabilityState.SUPPORTED:
            entity = SupplementLightBrightnessNumber(device, camera.id, light_caps, "ir")
            entity.async_write_ha_state = MagicMock()
            await entity.async_added_to_hass()
            entities.append(entity)
        if caps.white_light is CapabilityState.SUPPORTED:
            entity = SupplementLightBrightnessNumber(device, camera.id, light_caps, "white")
            entity.async_write_ha_state = MagicMock()
            await entity.async_added_to_hass()
            entities.append(entity)
    return entities


# ---------------------------------------------------------------------------
# Read / write behavior
# ---------------------------------------------------------------------------


def test_select_write_calls_isapi():
    """Selecting an option calls set_supplement_light_mode with correct args."""
    reg = _make_registry_for_channel(1, ir=True, white=True, smart=True)
    device = _MockDevice(
        cameras=[_MockCamera(id=1, name="cam")],
        capabilities_registry=reg,
        image_channel_responses=[
            {"ImageChannel": {"supplementLightMode": "off"}},
        ],
    )

    entity = SupplementLightModeSelect(device, 1, reg.for_channel(1))
    entity.async_write_ha_state = MagicMock()
    _run_async(entity.async_added_to_hass())
    assert entity.current_option == "off"

    _run_async(entity.async_select_option("ir"))

    device.set_supplement_light_mode.assert_called_once_with(1, "ir")
    assert entity.current_option == "ir"


def test_number_write_calls_isapi():
    """Setting brightness calls set_supplement_light_brightness with correct args."""
    reg = _make_registry_for_channel(1, ir=True, white=False, smart=False)
    device = _MockDevice(
        cameras=[_MockCamera(id=1, name="cam")],
        capabilities_registry=reg,
        image_channel_responses=[
            {"ImageChannel": {"supplementLightBrightness": "50"}},
        ],
    )

    entity = SupplementLightBrightnessNumber(device, 1, reg.for_channel(1).light_brightness, "ir")
    entity.async_write_ha_state = MagicMock()
    _run_async(entity.async_added_to_hass())
    assert entity.native_value == 50.0

    _run_async(entity.async_set_native_value(75))

    device.set_supplement_light_brightness.assert_called_once_with(1, 75)
    assert entity.native_value == 75.0


# ---------------------------------------------------------------------------
# Write failure without breaking integration
# ---------------------------------------------------------------------------


def test_select_write_failure_does_not_break():
    """Write failure is caught and handle_exception called."""
    reg = _make_registry_for_channel(1, ir=True, white=True, smart=True)
    device = _MockDevice(
        cameras=[_MockCamera(id=1, name="cam")],
        capabilities_registry=reg,
        image_channel_responses=[
            {"ImageChannel": {"supplementLightMode": "off"}},
        ],
        set_errors={(1, "mode"): RuntimeError("network down")},
    )

    entity = SupplementLightModeSelect(device, 1, reg.for_channel(1))
    entity.async_write_ha_state = MagicMock()
    _run_async(entity.async_added_to_hass())

    _run_async(entity.async_select_option("ir"))

    device.handle_exception.assert_called_once()
    assert entity.current_option == "off"


def test_number_write_failure_does_not_break():
    """Write failure is caught and handle_exception called."""
    reg = _make_registry_for_channel(1, ir=True, white=False, smart=False)
    device = _MockDevice(
        cameras=[_MockCamera(id=1, name="cam")],
        capabilities_registry=reg,
        image_channel_responses=[
            {"ImageChannel": {"supplementLightBrightness": "50"}},
        ],
        set_errors={(1, "brightness"): RuntimeError("network down")},
    )

    entity = SupplementLightBrightnessNumber(device, 1, reg.for_channel(1).light_brightness, "ir")
    entity.async_write_ha_state = MagicMock()
    _run_async(entity.async_added_to_hass())

    _run_async(entity.async_set_native_value(75))

    device.handle_exception.assert_called_once()
    assert entity.native_value == 50.0


# ---------------------------------------------------------------------------
# NVR channel mapping
# ---------------------------------------------------------------------------


def test_nvr_ir_camera_entities():
    """NVR with proxied IR camera gets correct entities."""
    ir_caps = HikvisionCapabilities()
    ir_caps.ir_light = CapabilityState.SUPPORTED
    ir_caps.white_light = CapabilityState.UNSUPPORTED
    ir_caps.smart_hybrid_light = CapabilityState.UNSUPPORTED
    ir_caps.light_brightness = NumericCapability(
        state=CapabilityState.SUPPORTED, minimum=1.0, maximum=100.0, step=1.0
    )
    ir_caps.supplement_light_mode = SelectCapability(
        state=CapabilityState.SUPPORTED, options=("off", "ir")
    )

    reg = HikvisionCapabilityRegistry()
    reg.channels[1] = ir_caps

    device = _MockDevice(
        cameras=[_MockCamera(id=1, name="garden")],
        capabilities_registry=reg,
        image_channel_responses=[
            {"ImageChannel": {"supplementLightMode": "ir", "supplementLightBrightness": "75"}},
        ],
    )

    select_entities = _run_async(_async_create_select_entities(device))
    assert len(select_entities) == 1
    assert select_entities[0].current_option == "ir"
    assert select_entities[0].options == ["off", "ir"]

    device._image_responses.append(
        {"ImageChannel": {"supplementLightBrightness": "75"}}
    )
    number_entities = _run_async(_async_create_number_entities(device))
    assert len(number_entities) == 1
    assert number_entities[0]._light_type == "ir"
    assert number_entities[0].native_value == 75.0


def test_nvr_white_camera_entities():
    """NVR with proxied white-light camera gets white brightness entity."""
    white_caps = HikvisionCapabilities()
    white_caps.ir_light = CapabilityState.UNSUPPORTED
    white_caps.white_light = CapabilityState.SUPPORTED
    white_caps.smart_hybrid_light = CapabilityState.UNSUPPORTED
    white_caps.light_brightness = NumericCapability(
        state=CapabilityState.SUPPORTED, minimum=1.0, maximum=100.0, step=1.0
    )
    white_caps.supplement_light_mode = SelectCapability(
        state=CapabilityState.SUPPORTED, options=("off", "white")
    )

    reg = HikvisionCapabilityRegistry()
    reg.channels[101] = white_caps

    device = _MockDevice(
        cameras=[_MockCamera(id=101, name="backyard")],
        capabilities_registry=reg,
        image_channel_responses=[
            {"ImageChannel": {"supplementLightMode": "white", "supplementLightBrightness": "80"}},
        ],
    )

    select_entities = _run_async(_async_create_select_entities(device))
    assert len(select_entities) == 1
    assert select_entities[0].current_option == "white"

    number_entities = _run_async(_async_create_number_entities(device))
    assert len(number_entities) == 1
    assert number_entities[0]._light_type == "white"


def test_404_image_endpoint_stays_unknown():
    """404 on Image/capabilities keeps light capabilities UNKNOWN."""
    camera = MockCamera(id=1, name="cam", model="DS-2CD2146G2-ISU", connection_type=CONNECTION_TYPE_DIRECT, streams=[])
    device = MockCapabilityDevice(
        cameras=[camera],
        supported_events=[],
        endpoint_responses={
            "Image/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
            "PTZCtrl/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
            "System/Audio/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
        },
    )
    registry = _run_async(
        HikvisionCapabilityDiscovery().async_discover(device, {})
    )
    caps = registry.for_channel(1)
    assert caps.ir_light == CapabilityState.UNKNOWN
    assert caps.supplement_light_mode.state == CapabilityState.UNSUPPORTED
