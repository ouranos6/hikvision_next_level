"""Tests for capability discovery.

These tests use mock devices (AsyncMock) and do not open real network
connections.  The autouse ``_allow_sockets`` fixture below temporarily
re-enables sockets so that asyncio can create an event loop on Windows
(python-socket otherwise blocks socket.socketpair used by the loop
self-pipe).
"""

from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_socket


# ---------------------------------------------------------------------------
# The Home Assistant test plugin registers several autouse fixtures that
# depend on ``event_loop`` (e.g. ``enable_event_loop_debug``,
# ``verify_cleanup``, “auto_enable_custom_integrations``).  Because
# ``pytest_socket`` (also enabled by the HA test plugin) blocks all socket
# usage at ``pytest_runtest_setup`` time – before any fixtures run – the
# event loop creation inside ``event_loop`` raises ``SocketBlockedError``.
#
# We override all HA autouse fixtures to no-ops so that ``event_loop`` is
# never implicitly requested.  Tests that need async behaviour use the
# ``_run_async`` helper below, which temporarily re-enables sockets.
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


def _run_async(coro):
    """Run *coro* with sockets temporarily unblocked.

    This avoids the pytest_socket / asyncio event-loop conflict on Windows.
    Tests that call this helper use only mocked endpoints, so no real
    network traffic occurs.
    """
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


from custom_components.hikvision_next.capabilities import (
    CapabilityState,
    HikvisionCapabilities,
    HikvisionCapabilityDiscovery,
    HikvisionCapabilityRegistry,
    NumericCapability,
    SelectCapability,
    StreamCapabilities,
)
from custom_components.hikvision_next.isapi.const import (
    CONNECTION_TYPE_DIRECT,
    CONNECTION_TYPE_PROXIED,
)
from custom_components.hikvision_next.isapi.models import (
    CameraStreamInfo,
)
from custom_components.hikvision_next.isapi.utils import deep_get


@dataclass
class MockCamera:
    """Minimal camera mock matching the CapabilityDevice.cameras interface."""
    id: int
    name: str
    model: str
    connection_type: str = CONNECTION_TYPE_DIRECT
    streams: list[CameraStreamInfo] = field(default_factory=list)


@dataclass
class MockDeviceInfo:
    model: str = "DS-2CD2146G2-ISU"


@dataclass
class MockEvent:
    id: str
    channel_id: int = 0
    io_port_id: int = 0


class MockCapabilityDevice:
    """Fake device implementing CapabilityDevice for focused discovery tests."""

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


def _make_system_capabilities(include_ptz: bool = False, include_thermal: bool = False) -> dict[str, Any]:
    caps = {
        "SysCap": {
            "AudioCap": {"audioInputNums": "1", "audioOutputNums": "1"},
            "IOCap": {"IOInputPortNums": "2", "IOOutputPortNums": "1"},
            "VideoCap": {"videoInputPortNums": "0"},
        },
        "EventCap": {
            "isSupportMotionDetection": "true",
        },
        "SmartCap": {
            "isSupportLineDetection": "true",
            "isSupportFieldDetection": "true",
        },
    }
    if include_ptz:
        caps["PTZCtrlCap"] = {"isSupportPatrols": "true"}
    return caps


# ---------------------------------------------------------------------------
# Pure parsing helpers
# ---------------------------------------------------------------------------

def test_state_from_true():
    from custom_components.hikvision_next.capabilities import _state_from_value
    assert _state_from_value("true") == CapabilityState.SUPPORTED


def test_state_from_false():
    from custom_components.hikvision_next.capabilities import _state_from_value
    assert _state_from_value("false") == CapabilityState.UNSUPPORTED


def test_state_from_unknown():
    from custom_components.hikvision_next.capabilities import _state_from_value
    assert _state_from_value("maybe") == CapabilityState.UNKNOWN
    assert _state_from_value(None) == CapabilityState.UNKNOWN


def test_count_state_positive():
    from custom_components.hikvision_next.capabilities import _count_state
    assert _count_state({"a": {"b": "3"}}, "a.b") == CapabilityState.SUPPORTED


def test_count_state_zero():
    from custom_components.hikvision_next.capabilities import _count_state
    assert _count_state({"a": {"b": "0"}}, "a.b") == CapabilityState.UNSUPPORTED


def test_count_state_missing():
    from custom_components.hikvision_next.capabilities import _count_state
    assert _count_state({"a": {}}, "a.b") == CapabilityState.UNKNOWN


def test_options_split():
    from custom_components.hikvision_next.capabilities import _options
    assert _options("auto,day,night") == ("auto", "day", "night")


def test_options_empty():
    from custom_components.hikvision_next.capabilities import _options
    assert _options("") == ()
    assert _options(None) == ()


def test_find_numeric_with_attributes():
    from custom_components.hikvision_next.capabilities import _find_numeric
    data = {"brightness": {"@min": "0", "@max": "100", "@step": "1", "@opt": "true"}}
    result = _find_numeric(data, "brightness")
    assert result.state == CapabilityState.SUPPORTED
    assert result.minimum == 0.0
    assert result.maximum == 100.0
    assert result.step == 1.0


def test_find_select_with_opt():
    from custom_components.hikvision_next.capabilities import _find_select
    data = {"dayNight": {"@opt": "auto,day,night"}}
    result = _find_select(data, "dayNight")
    assert result.state == CapabilityState.SUPPORTED
    assert result.options == ("auto", "day", "night")


def test_find_select_with_text_value():
    from custom_components.hikvision_next.capabilities import _find_select
    data = {"wdr": {"#text": "true", "@opt": "true,false"}}
    result = _find_select(data, "wdr")
    assert result.state == CapabilityState.SUPPORTED
    assert result.options == ("true", "false")


# ---------------------------------------------------------------------------
# Fixed camera discovery
# ---------------------------------------------------------------------------

def _fixed_camera_streams() -> list[CameraStreamInfo]:
    return [
        CameraStreamInfo(id=101, name="Main", type_id=1, type="Main Stream", enabled=True,
                         codec="H.264", width=2560, height=1440, audio=False),
        CameraStreamInfo(id=102, name="Sub", type_id=2, type="Sub-stream", enabled=True,
                         codec="H.264", width=640, height=480, audio=False),
    ]


def test_discover_fixed_camera():
    """Fixed camera: no PTZ, IR/Day-Night supported via system caps."""
    system = _make_system_capabilities(include_ptz=False)
    camera = MockCamera(id=1, name="cam", model="DS-2CD2346G2-ISU",
                        connection_type=CONNECTION_TYPE_DIRECT,
                        streams=_fixed_camera_streams())
    image_xml = {
        "ImageChannel": {
            "brightness": {"@min": "0", "@max": "100", "@step": "1"},
            "dayNight": {"@opt": "auto,day,night"},
        }
    }
    device = MockCapabilityDevice(
        cameras=[camera],
        supported_events=[MockEvent(id="motiondetection", channel_id=1)],
        endpoint_responses={
            "Image/channels/1/capabilities": (HTTPStatus.OK, image_xml),
            "PTZCtrl/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
            "System/Audio/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
        },
    )
    registry = _run_async(HikvisionCapabilityDiscovery().async_discover(device, system))

    # Device-level capabilities from System/capabilities
    assert registry.device.microphone == CapabilityState.SUPPORTED
    assert registry.device.speaker == CapabilityState.SUPPORTED
    assert registry.device.alarm_inputs == CapabilityState.SUPPORTED
    assert registry.device.motion_detection == CapabilityState.SUPPORTED
    assert registry.device.line_crossing == CapabilityState.SUPPORTED
    assert registry.device.intrusion_detection == CapabilityState.SUPPORTED
    assert registry.device.ptz == CapabilityState.UNKNOWN
    assert registry.device.ptz_presets == CapabilityState.UNKNOWN

    caps = registry.for_channel(1)
    assert caps.streams.main == CapabilityState.SUPPORTED
    assert caps.streams.sub == CapabilityState.SUPPORTED
    assert caps.streams.third == CapabilityState.UNSUPPORTED
    assert caps.ptz == CapabilityState.UNSUPPORTED
    assert caps.ptz_presets == CapabilityState.UNSUPPORTED
    assert caps.motion_detection == CapabilityState.SUPPORTED
    assert caps.line_crossing == CapabilityState.SUPPORTED
    assert caps.intrusion_detection == CapabilityState.SUPPORTED
    assert caps.brightness.state == CapabilityState.SUPPORTED
    assert caps.brightness.minimum == 0.0
    assert caps.brightness.maximum == 100.0
    assert caps.brightness.step == 1.0
    assert caps.day_night.state == CapabilityState.SUPPORTED
    assert caps.day_night.options == ("auto", "day", "night")
    assert caps.microphone == CapabilityState.SUPPORTED
    assert caps.speaker == CapabilityState.SUPPORTED
    assert caps.siren == CapabilityState.UNSUPPORTED


# ---------------------------------------------------------------------------
# ColorVu / Smart Hybrid Light camera
# ---------------------------------------------------------------------------

def test_discover_colorvu_camera():
    """ColorVu camera with white light, IR, Smart Hybrid Light, brightness control."""
    image_xml = {
        "ImageChannel": {
            "brightness": {"@min": "0", "@max": "100", "@step": "1"},
            "supplementLightMode": {"@opt": "off,ir,white,smart"},
        }
    }
    audio_xml = {
        "Audio": {"isSupportMicrophone": "true", "isSupportSpeaker": "true", "isSupportSiren": "false"},
    }
    camera = MockCamera(id=1, name="cam", model="DS-2CD2346G2-I",
                        connection_type=CONNECTION_TYPE_DIRECT,
                        streams=[CameraStreamInfo(id=101, name="Main", type_id=1, type="Main",
                                                  enabled=True, codec="H.264", width=2560, height=1440, audio=False)])
    device = MockCapabilityDevice(
        cameras=[camera],
        supported_events=[],
        endpoint_responses={
            "Image/channels/1/capabilities": (HTTPStatus.OK, image_xml),
            "PTZCtrl/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
            "System/Audio/channels/1/capabilities": (HTTPStatus.OK, audio_xml),
        },
    )
    registry = _run_async(HikvisionCapabilityDiscovery().async_discover(device, {}))

    caps = registry.for_channel(1)
    assert caps.ir_light == CapabilityState.SUPPORTED
    assert caps.white_light == CapabilityState.SUPPORTED
    assert caps.smart_hybrid_light == CapabilityState.SUPPORTED
    assert caps.brightness.state == CapabilityState.SUPPORTED
    assert caps.brightness.minimum == 0.0
    assert caps.brightness.maximum == 100.0
    assert caps.microphone == CapabilityState.SUPPORTED
    assert caps.speaker == CapabilityState.SUPPORTED
    assert caps.siren == CapabilityState.UNSUPPORTED


# ---------------------------------------------------------------------------
# PTZ camera
# ---------------------------------------------------------------------------

def test_discover_ptz_camera():
    """PTZ camera with presets discovered."""
    ptz_xml = {
        "PTZCtrlChannel": {
            "isSupportPreset": "true",
            "isSupportPatrol": "true",
            "isSupportPattern": "true",
        }
    }
    camera = MockCamera(id=1, name="cam", model="DS-2DE4225IW-DE",
                        connection_type=CONNECTION_TYPE_DIRECT,
                        streams=[CameraStreamInfo(id=101, name="Main", type_id=1, type="Main",
                                                  enabled=True, codec="H.264", width=1920, height=1080, audio=False)])
    device = MockCapabilityDevice(
        cameras=[camera],
        endpoint_responses={
            "Image/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
            "PTZCtrl/channels/1/capabilities": (HTTPStatus.OK, ptz_xml),
            "System/Audio/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
        },
    )
    registry = _run_async(HikvisionCapabilityDiscovery().async_discover(device, {}))

    caps = registry.for_channel(1)
    assert caps.ptz == CapabilityState.SUPPORTED
    assert caps.ptz_presets == CapabilityState.SUPPORTED


# ---------------------------------------------------------------------------
# NVR with mixed channel capabilities
# ---------------------------------------------------------------------------

def test_discover_nvr_mixed_channels():
    """A mixed-camera NVR must not inherit one channel's capabilities across all."""
    channels = [
        MockCamera(id=1, name="fixed", model="DS-2CD2346G2-ISU",
                   connection_type=CONNECTION_TYPE_PROXIED,
                   streams=[CameraStreamInfo(id=101, name="Main", type_id=1, type="Main",
                                              enabled=True, codec="H.264", width=2560, height=1440, audio=False)]),
        MockCamera(id=2, name="ptz", model="DS-2DE4225IW-DE",
                   connection_type=CONNECTION_TYPE_PROXIED,
                   streams=[CameraStreamInfo(id=201, name="Main", type_id=1, type="Main",
                                              enabled=True, codec="H.264", width=1920, height=1080, audio=False)]),
        MockCamera(id=3, name="colorvu", model="DS-2CD2346G2-I",
                   connection_type=CONNECTION_TYPE_PROXIED,
                   streams=[CameraStreamInfo(id=301, name="Main", type_id=1, type="Main",
                                              enabled=True, codec="H.264", width=2560, height=1440, audio=False)]),
    ]
    image_xml_colorvu = {"ImageChannel": {"supplementLightMode": {"@opt": "off,ir,white,smart"}}}
    ptz_xml = {"PTZCtrlChannel": {"isSupportPreset": "true"}}
    device = MockCapabilityDevice(
        cameras=channels,
        endpoint_responses={
            "Image/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
            "Image/channels/2/capabilities": (HTTPStatus.NOT_FOUND, None),
            "Image/channels/3/capabilities": (HTTPStatus.OK, image_xml_colorvu),
            "PTZCtrl/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
            "PTZCtrl/channels/2/capabilities": (HTTPStatus.OK, ptz_xml),
            "PTZCtrl/channels/3/capabilities": (HTTPStatus.NOT_FOUND, None),
            "System/Audio/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
            "System/Audio/channels/2/capabilities": (HTTPStatus.NOT_FOUND, None),
            "System/Audio/channels/3/capabilities": (HTTPStatus.NOT_FOUND, None),
        },
    )
    registry = _run_async(HikvisionCapabilityDiscovery().async_discover(device, {}))

    fixed_caps = registry.for_channel(1)
    ptz_caps = registry.for_channel(2)
    colorvu_caps = registry.for_channel(3)

    # Channel 1: fixed camera, no PTZ
    assert fixed_caps.ptz == CapabilityState.UNSUPPORTED
    assert fixed_caps.ptz_presets == CapabilityState.UNSUPPORTED
    assert fixed_caps.ir_light == CapabilityState.UNKNOWN
    assert fixed_caps.white_light == CapabilityState.UNKNOWN

    # Channel 2: PTZ camera
    assert ptz_caps.ptz == CapabilityState.SUPPORTED
    assert ptz_caps.ptz_presets == CapabilityState.SUPPORTED

    # Channel 3: ColorVu camera
    assert colorvu_caps.ptz == CapabilityState.UNSUPPORTED
    assert colorvu_caps.ir_light == CapabilityState.SUPPORTED
    assert colorvu_caps.white_light == CapabilityState.SUPPORTED
    assert colorvu_caps.smart_hybrid_light == CapabilityState.SUPPORTED

    # Device-level: only from System/capabilities (empty here → UNKNOWN)
    assert registry.device.ptz == CapabilityState.UNKNOWN


# ---------------------------------------------------------------------------
# 403 permission case → UNKNOWN, not UNSUPPORTED
# ---------------------------------------------------------------------------

def test_403_forbidden_is_unknown():
    """403 Forbidden must not mean unsupported; it means unknown."""
    system = _make_system_capabilities()
    camera = MockCamera(id=1, name="cam", model="DS-2CD2346G2-ISU",
                        connection_type=CONNECTION_TYPE_DIRECT,
                        streams=[])
    device = MockCapabilityDevice(
        cameras=[camera],
        supported_events=[],
        endpoint_responses={
            "Image/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
            "PTZCtrl/channels/1/capabilities": (HTTPStatus.FORBIDDEN, None),
            "System/Audio/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
        },
    )
    registry = _run_async(HikvisionCapabilityDiscovery().async_discover(device, system))

    caps = registry.for_channel(1)
    assert caps.ptz == CapabilityState.UNKNOWN
    assert caps.ptz_presets == CapabilityState.UNKNOWN


# ---------------------------------------------------------------------------
# 404 unsupported case
# ---------------------------------------------------------------------------

def test_404_is_unsupported():
    """404 on a feature endpoint → unsupported."""
    camera = MockCamera(id=1, name="cam", model="DS-2CD2346G2-ISU",
                        connection_type=CONNECTION_TYPE_DIRECT,
                        streams=[])
    device = MockCapabilityDevice(
        cameras=[camera],
        supported_events=[],
        endpoint_responses={
            "Image/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
            "PTZCtrl/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
            "System/Audio/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
        },
    )
    registry = _run_async(HikvisionCapabilityDiscovery().async_discover(device, {}))

    caps = registry.for_channel(1)
    assert caps.ptz == CapabilityState.UNSUPPORTED
    assert caps.ptz_presets == CapabilityState.UNSUPPORTED
    assert caps.brightness.state == CapabilityState.UNSUPPORTED
    assert caps.day_night.state == CapabilityState.UNSUPPORTED


# ---------------------------------------------------------------------------
# Malformed capability XML → does not crash
# ---------------------------------------------------------------------------

def test_malformed_capability_xml_does_not_crash():
    """Malformed capability XML must not crash discovery."""
    camera = MockCamera(id=1, name="cam", model="DS-2CD2346G2-ISU",
                        connection_type=CONNECTION_TYPE_DIRECT,
                        streams=[])
    device = MockCapabilityDevice(
        cameras=[camera],
        supported_events=[],
        endpoint_responses={
            "Image/channels/1/capabilities": (HTTPStatus.OK, {"broken": None}),
            "PTZCtrl/channels/1/capabilities": (HTTPStatus.OK, {"bad": None}),
            "System/Audio/channels/1/capabilities": (HTTPStatus.OK, {"bad": None}),
        },
    )
    registry = _run_async(HikvisionCapabilityDiscovery().async_discover(device, {}))

    caps = registry.for_channel(1)
    # No crash; capabilities that couldn't be determined from the malformed
    # response data remain UNKNOWN (only PTZ is unconditionally SUPPORTED
    # because the endpoint returned 200)
    assert caps.ptz == CapabilityState.SUPPORTED
    assert caps.ptz_presets == CapabilityState.UNKNOWN
    assert caps.brightness.state == CapabilityState.UNKNOWN
    assert caps.day_night.state == CapabilityState.UNKNOWN


# ---------------------------------------------------------------------------
# Select opt parsing and numeric ranges
# ---------------------------------------------------------------------------

def test_select_opt_parsing():
    """opt='auto,day,night' should be retained as options tuple."""
    from custom_components.hikvision_next.capabilities import _find_select
    data = {"dayNight": {"@opt": "auto,day,night"}}
    result = _find_select(data, "dayNight")
    assert result.state == CapabilityState.SUPPORTED
    assert result.options == ("auto", "day", "night")


def test_numeric_range_parsing():
    """min/max/step should be retained from capability response."""
    from custom_components.hikvision_next.capabilities import _find_numeric
    data = {"brightness": {"@min": "0", "@max": "100", "@step": "1"}}
    result = _find_numeric(data, "brightness")
    assert result.state == CapabilityState.SUPPORTED
    assert result.minimum == 0.0
    assert result.maximum == 100.0
    assert result.step == 1.0


# ---------------------------------------------------------------------------
# Partial discovery failure
# ---------------------------------------------------------------------------

def test_partial_discovery_failure_does_not_break():
    """A failure discovering one capability must not break others."""
    image_xml = {"ImageChannel": {"brightness": {"@min": "0", "@max": "100", "@step": "1"}}}
    ptz_xml = {"PTZCtrlChannel": {"isSupportPreset": "true"}}
    camera = MockCamera(id=1, name="cam", model="DS-2CD2346G2-ISU",
                        connection_type=CONNECTION_TYPE_DIRECT,
                        streams=[CameraStreamInfo(id=101, name="Main", type_id=1,
                                                  type="Main", enabled=True,
                                                  codec="H.264", width=2560, height=1440, audio=False)])

    async def _faulty_resolve(endpoint: str):
        if endpoint == "System/Audio/channels/1/capabilities":
            raise ConnectionError("network unreachable")
        responses = {
            "Image/channels/1/capabilities": (HTTPStatus.OK, image_xml),
            "PTZCtrl/channels/1/capabilities": (HTTPStatus.OK, ptz_xml),
        }
        return responses.get(endpoint, (HTTPStatus.NOT_FOUND, None))

    device = MockCapabilityDevice(
        cameras=[camera],
        supported_events=[],
    )
    device.async_get_capability_endpoint = AsyncMock(side_effect=_faulty_resolve)

    registry = _run_async(HikvisionCapabilityDiscovery().async_discover(device, {}))

    caps = registry.for_channel(1)
    # Image capability still discovered despite audio probe failure
    assert caps.brightness.state == CapabilityState.SUPPORTED
    # PTZ capability still discovered
    assert caps.ptz == CapabilityState.SUPPORTED
    assert caps.ptz_presets == CapabilityState.SUPPORTED
    # Audio capability is UNKNOWN (probe raised exception)
    assert caps.microphone == CapabilityState.UNKNOWN


# ---------------------------------------------------------------------------
# /SL camera
# ---------------------------------------------------------------------------

def test_discover_sl_camera():
    """/SL camera: speaker, siren, possibly white light."""
    audio_xml = {"Audio": {"isSupportMicrophone": "true", "isSupportSpeaker": "true", "isSupportSiren": "true"}}
    image_xml = {"ImageChannel": {"supplementLightMode": {"@opt": "off,ir,white"}}}
    camera = MockCamera(id=1, name="cam", model="DS-2CD2T86G2-ISU/SL",
                        connection_type=CONNECTION_TYPE_DIRECT,
                        streams=[CameraStreamInfo(id=101, name="Main", type_id=1,
                                                  type="Main", enabled=True,
                                                  codec="H.264", width=2560, height=1440, audio=False)])
    device = MockCapabilityDevice(
        cameras=[camera],
        supported_events=[],
        endpoint_responses={
            "Image/channels/1/capabilities": (HTTPStatus.OK, image_xml),
            "PTZCtrl/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
            "System/Audio/channels/1/capabilities": (HTTPStatus.OK, audio_xml),
        },
    )
    registry = _run_async(HikvisionCapabilityDiscovery().async_discover(device, {}))

    caps = registry.for_channel(1)
    assert caps.speaker == CapabilityState.SUPPORTED
    assert caps.siren == CapabilityState.SUPPORTED
    assert caps.white_light == CapabilityState.SUPPORTED
    assert caps.ir_light == CapabilityState.SUPPORTED


# ---------------------------------------------------------------------------
# Device-level vs channel-level separation (NVR)
# ---------------------------------------------------------------------------

def test_nvr_device_vs_channel_separation():
    """NVR-level PTZ facts should not override channel-level probe results."""
    ptz_xml = {"PTZCtrlChannel": {"isSupportPreset": "true"}}
    camera = MockCamera(id=1, name="ptz_cam", model="DS-2DE4225IW-DE",
                        connection_type=CONNECTION_TYPE_PROXIED,
                        streams=[])
    device = MockCapabilityDevice(
        cameras=[camera],
        supported_events=[],
        endpoint_responses={
            "Image/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
            "PTZCtrl/channels/1/capabilities": (HTTPStatus.OK, ptz_xml),
            "System/Audio/channels/1/capabilities": (HTTPStatus.NOT_FOUND, None),
        },
    )
    system = {"PTZCtrlCap": {"isSupportPatrols": "true"}}
    registry = _run_async(HikvisionCapabilityDiscovery().async_discover(device, system))

    # Device level: PTZ discovered from system capabilities
    assert registry.device.ptz == CapabilityState.SUPPORTED

    # Channel level: PTZ discovered from channel-specific probe
    assert registry.for_channel(1).ptz == CapabilityState.SUPPORTED
    assert registry.for_channel(1).ptz_presets == CapabilityState.SUPPORTED

    # Channel-level should not carry device-level audio (NVR device has audio, not camera)
    assert registry.for_channel(1).microphone == CapabilityState.UNSUPPORTED


# ---------------------------------------------------------------------------
# for_channel returns default for unknown channel
# ---------------------------------------------------------------------------

def test_for_channel_unknown_returns_default():
    """Querying an unknown channel should not raise."""
    registry = HikvisionCapabilityRegistry()
    caps = registry.for_channel(999)
    assert isinstance(caps, HikvisionCapabilities)
    assert caps.ptz == CapabilityState.UNKNOWN


# ---------------------------------------------------------------------------
# Soft alarm inputs from System/capabilities
# ---------------------------------------------------------------------------

def test_nvr_soft_alarm_inputs_discovery():
    """Soft alarm inputs should be discovered from System/capabilities."""
    system = {
        "SysCap": {
            "IOCap": {
                "IOInputPortNums": "4",
                "SoftIOInputPortNums": "8",
            }
        }
    }
    device = MockCapabilityDevice(cameras=[])
    registry = _run_async(HikvisionCapabilityDiscovery().async_discover(device, system))

    assert registry.device.alarm_inputs == CapabilityState.SUPPORTED
    assert registry.device.soft_alarm_inputs == CapabilityState.SUPPORTED
