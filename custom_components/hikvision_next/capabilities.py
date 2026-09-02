"""Centralized, conservative Hikvision feature capability discovery."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from http import HTTPStatus
import logging
from typing import Any, Protocol

from .isapi.const import CONNECTION_TYPE_DIRECT, GET
from .isapi.models import CameraStreamInfo, EventInfo
from .isapi.utils import deep_get

_LOGGER = logging.getLogger(__name__)

MAX_CAPABILITY_PROBES = 3


class CapabilityState(str, Enum):
    """Whether support was confirmed, disproved, or could not be determined."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class NumericCapability:
    """A supported numeric setting and its device-advertised range."""

    state: CapabilityState = CapabilityState.UNKNOWN
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None


@dataclass(slots=True)
class SelectCapability:
    """A supported select setting and its device-advertised values."""

    state: CapabilityState = CapabilityState.UNKNOWN
    options: tuple[str, ...] = ()


@dataclass(slots=True)
class StreamCapabilities:
    """Availability of Hikvision's standard stream slots."""

    main: CapabilityState = CapabilityState.UNKNOWN
    sub: CapabilityState = CapabilityState.UNKNOWN
    third: CapabilityState = CapabilityState.UNKNOWN


@dataclass(slots=True)
class HikvisionCapabilities:
    """Capabilities belonging to one device or one physical/proxy channel."""

    streams: StreamCapabilities = field(default_factory=StreamCapabilities)
    ptz: CapabilityState = CapabilityState.UNKNOWN
    ptz_presets: CapabilityState = CapabilityState.UNKNOWN
    ir_light: CapabilityState = CapabilityState.UNKNOWN
    white_light: CapabilityState = CapabilityState.UNKNOWN
    smart_hybrid_light: CapabilityState = CapabilityState.UNKNOWN
    supplement_light_mode: SelectCapability = field(default_factory=SelectCapability)
    light_brightness: NumericCapability = field(default_factory=NumericCapability)
    motion_detection: CapabilityState = CapabilityState.UNKNOWN
    motion_sensitivity: NumericCapability = field(default_factory=NumericCapability)
    motion_start_delay: NumericCapability = field(default_factory=NumericCapability)
    motion_end_delay: NumericCapability = field(default_factory=NumericCapability)
    motion_human_filter: CapabilityState = CapabilityState.UNKNOWN
    motion_vehicle_filter: CapabilityState = CapabilityState.UNKNOWN
    line_crossing: CapabilityState = CapabilityState.UNKNOWN
    intrusion_detection: CapabilityState = CapabilityState.UNKNOWN
    human_filter: CapabilityState = CapabilityState.UNKNOWN
    vehicle_filter: CapabilityState = CapabilityState.UNKNOWN
    day_night: SelectCapability = field(default_factory=SelectCapability)
    brightness: NumericCapability = field(default_factory=NumericCapability)
    contrast: NumericCapability = field(default_factory=NumericCapability)
    saturation: NumericCapability = field(default_factory=NumericCapability)
    sharpness: NumericCapability = field(default_factory=NumericCapability)
    wdr: SelectCapability = field(default_factory=SelectCapability)
    blc: SelectCapability = field(default_factory=SelectCapability)
    hlc: SelectCapability = field(default_factory=SelectCapability)
    gain: NumericCapability = field(default_factory=NumericCapability)
    shutter: SelectCapability = field(default_factory=SelectCapability)
    noise_reduction: SelectCapability = field(default_factory=SelectCapability)
    defog: SelectCapability = field(default_factory=SelectCapability)
    microphone: CapabilityState = CapabilityState.UNKNOWN
    speaker: CapabilityState = CapabilityState.UNKNOWN
    siren: CapabilityState = CapabilityState.UNKNOWN
    alarm_inputs: CapabilityState = CapabilityState.UNKNOWN
    soft_alarm_inputs: CapabilityState = CapabilityState.UNKNOWN


@dataclass(slots=True)
class HikvisionCapabilityRegistry:
    """Cached global and per-channel capabilities for one configured device."""

    device: HikvisionCapabilities = field(default_factory=HikvisionCapabilities)
    channels: dict[int, HikvisionCapabilities] = field(default_factory=dict)

    def for_channel(self, channel_id: int) -> HikvisionCapabilities:
        """Return capabilities for a discovered physical or proxy channel."""
        return self.channels.get(channel_id, HikvisionCapabilities())


class CapabilityDevice(Protocol):
    """Narrow device API used by discovery and easily replaceable in tests."""

    cameras: list[Any]
    supported_events: list[EventInfo]
    device_info: Any

    async def async_get_capability_endpoint(self, endpoint: str) -> tuple[int, dict[str, Any] | None]:
        """Read a capability endpoint without making setup fail on its errors."""


@dataclass(slots=True)
class _ProbeResult:
    """Internal representation of one feature-specific endpoint result."""

    state: CapabilityState
    data: dict[str, Any] | None = None


class HikvisionCapabilityDiscovery:
    """Discover static capabilities once at setup and cache the resulting registry."""

    def __init__(self, max_concurrent_probes: int = MAX_CAPABILITY_PROBES) -> None:
        """Initialize bounded probing for heterogeneous Hikvision firmware."""
        self._semaphore = asyncio.Semaphore(max_concurrent_probes)

    async def async_discover(
        self, device: CapabilityDevice, system_capabilities: dict[str, Any]
    ) -> HikvisionCapabilityRegistry:
        """Build capabilities without allowing an optional endpoint to break setup."""
        registry = HikvisionCapabilityRegistry(
            device=self._build_device_capabilities(device, system_capabilities)
        )
        channel_tasks = [
            self._async_discover_channel(device, camera, system_capabilities)
            for camera in device.cameras
        ]
        for channel_id, capabilities in await asyncio.gather(*channel_tasks):
            registry.channels[channel_id] = capabilities

        _LOGGER.debug(
            "Discovered Hikvision capabilities for %s: channels=%s",
            getattr(device.device_info, "model", "unknown device"),
            ", ".join(str(channel_id) for channel_id in sorted(registry.channels)),
        )
        return registry

    def _build_device_capabilities(
        self, device: CapabilityDevice, system: dict[str, Any]
    ) -> HikvisionCapabilities:
        """Build only global facts that System/capabilities can safely establish."""
        capabilities = HikvisionCapabilities()
        capabilities.microphone = _count_state(system, "SysCap.AudioCap.audioInputNums")
        capabilities.speaker = _count_state(system, "SysCap.AudioCap.audioOutputNums")
        capabilities.alarm_inputs = _count_state(system, "SysCap.IOCap.IOInputPortNums")
        capabilities.soft_alarm_inputs = _count_state(system, "SysCap.IOCap.SoftIOInputPortNums")
        capabilities.ptz_presets = _state_at(system, "PTZCtrlCap.isSupportPatrols")
        capabilities.ptz = capabilities.ptz_presets
        capabilities.motion_detection = _state_at(system, "EventCap.isSupportMotionDetection")
        capabilities.line_crossing = _state_at(system, "SmartCap.isSupportLineDetection")
        capabilities.intrusion_detection = _state_at(system, "SmartCap.isSupportFieldDetection")
        perimeter_filter = _state_at(system, "EventCap.isSupportPerimeterAlgoTargetFilterParams")
        capabilities.human_filter = perimeter_filter
        capabilities.vehicle_filter = perimeter_filter
        return capabilities

    async def _async_discover_channel(
        self,
        device: CapabilityDevice,
        camera: Any,
        system: dict[str, Any],
    ) -> tuple[int, HikvisionCapabilities]:
        """Discover a channel using its existing mapped channel id, never a model name."""
        capabilities = HikvisionCapabilities(
            streams=_stream_capabilities(getattr(camera, "streams", []))
        )
        is_direct = getattr(camera, "connection_type", None) == CONNECTION_TYPE_DIRECT
        if is_direct:
            self._apply_system_channel_facts(capabilities, system)
        self._apply_event_facts(capabilities, device.supported_events, int(camera.id))

        image_probe, supplement_light_probe, ptz_probe, audio_probe, motion_probe = await asyncio.gather(
            self._async_probe(device, f"Image/channels/{camera.id}/capabilities"),
            self._async_probe(device, f"Image/channels/{camera.id}/supplementLight/capabilities"),
            self._async_probe(device, f"PTZCtrl/channels/{camera.id}/capabilities"),
            self._async_probe(device, f"System/Audio/channels/{camera.id}/capabilities"),
            self._async_probe(
                device,
                f"System/Video/inputs/channels/{camera.id}/motionDetection/capabilities",
            ),
        )
        self._apply_image_probe(capabilities, image_probe)
        self._apply_supplement_light_probe(capabilities, supplement_light_probe)
        self._apply_ptz_probe(capabilities, ptz_probe)
        self._apply_audio_probe(capabilities, audio_probe)
        self._apply_motion_probe(capabilities, motion_probe)
        return int(camera.id), capabilities

    async def _async_probe(self, device: CapabilityDevice, endpoint: str) -> _ProbeResult:
        """Classify a probe without treating permissions as feature absence."""
        async with self._semaphore:
            try:
                status, data = await device.async_get_capability_endpoint(endpoint)
            except Exception as ex:  # pragma: no cover - device boundary safeguard
                _LOGGER.debug("Capability probe failed for %s: %s", endpoint, ex)
                return _ProbeResult(CapabilityState.UNKNOWN)

        if status == HTTPStatus.OK:
            return _ProbeResult(CapabilityState.SUPPORTED, data)
        if status in {HTTPStatus.NOT_FOUND, HTTPStatus.METHOD_NOT_ALLOWED}:
            return _ProbeResult(CapabilityState.UNSUPPORTED)
        if status == HTTPStatus.FORBIDDEN:
            _LOGGER.debug("Capability probe forbidden for %s; keeping capability unknown", endpoint)
        else:
            _LOGGER.debug("Capability probe unavailable for %s: HTTP %s", endpoint, status)
        return _ProbeResult(CapabilityState.UNKNOWN)

    @staticmethod
    def _apply_system_channel_facts(capabilities: HikvisionCapabilities, system: dict[str, Any]) -> None:
        """Copy System/capabilities facts only when they belong to a direct camera."""
        capabilities.microphone = _count_state(system, "SysCap.AudioCap.audioInputNums")
        capabilities.speaker = _count_state(system, "SysCap.AudioCap.audioOutputNums")
        capabilities.motion_detection = _state_at(system, "EventCap.isSupportMotionDetection")
        capabilities.line_crossing = _state_at(system, "SmartCap.isSupportLineDetection")
        capabilities.intrusion_detection = _state_at(system, "SmartCap.isSupportFieldDetection")
        perimeter_filter = _state_at(system, "EventCap.isSupportPerimeterAlgoTargetFilterParams")
        capabilities.human_filter = perimeter_filter
        capabilities.vehicle_filter = perimeter_filter
        capabilities.ptz_presets = _state_at(system, "PTZCtrlCap.isSupportPatrols")
        capabilities.ptz = capabilities.ptz_presets
        capabilities.alarm_inputs = _count_state(system, "SysCap.IOCap.IOInputPortNums")
        capabilities.soft_alarm_inputs = _count_state(system, "SysCap.IOCap.SoftIOInputPortNums")

    @staticmethod
    def _apply_event_facts(
        capabilities: HikvisionCapabilities, events: list[EventInfo], channel_id: int
    ) -> None:
        """Use already-enumerated event channels as positive capability evidence."""
        event_ids = {event.id for event in events if event.channel_id == channel_id}
        if "motiondetection" in event_ids:
            capabilities.motion_detection = CapabilityState.SUPPORTED
        if "linedetection" in event_ids:
            capabilities.line_crossing = CapabilityState.SUPPORTED
        if "fielddetection" in event_ids:
            capabilities.intrusion_detection = CapabilityState.SUPPORTED

    @staticmethod
    def _apply_ptz_probe(capabilities: HikvisionCapabilities, probe: _ProbeResult) -> None:
        """Apply evidence from the feature-specific PTZ endpoint."""
        if probe.state is not CapabilityState.SUPPORTED:
            for attr in ("ptz", "ptz_presets"):
                current = getattr(capabilities, attr)
                if current is CapabilityState.UNKNOWN:
                    setattr(capabilities, attr, probe.state)
            return
        capabilities.ptz = CapabilityState.SUPPORTED
        capabilities.ptz_presets = _find_state(probe.data, "isSupportPreset", "isSupportPresets")

    @staticmethod
    def _apply_audio_probe(capabilities: HikvisionCapabilities, probe: _ProbeResult) -> None:
        """Apply audio endpoint evidence, preserving system-level SUPPORTED facts."""
        if probe.state is not CapabilityState.SUPPORTED:
            for attr in ("microphone", "speaker", "siren"):
                current = getattr(capabilities, attr)
                if current is CapabilityState.UNKNOWN:
                    setattr(capabilities, attr, probe.state)
            return
        capabilities.microphone = _find_state(probe.data, "isSupportMicrophone", "microphone")
        capabilities.speaker = _find_state(probe.data, "isSupportSpeaker", "speaker")
        capabilities.siren = _find_state(probe.data, "isSupportSiren", "siren")

    @staticmethod
    def _apply_motion_probe(capabilities: HikvisionCapabilities, probe: _ProbeResult) -> None:
        """Apply only explicit motion-detection configuration capabilities.

        The ISAPI motion-detection capability resource advertises the numeric
        ranges and optional target-type filtering. Missing metadata remains
        UNKNOWN; entity code must never synthesize a Home Assistant range.
        """
        if probe.state is not CapabilityState.SUPPORTED:
            for name in ("motion_sensitivity", "motion_start_delay", "motion_end_delay"):
                setattr(capabilities, name, NumericCapability(state=probe.state))
            capabilities.motion_human_filter = probe.state
            capabilities.motion_vehicle_filter = probe.state
            return

        capabilities.motion_detection = CapabilityState.SUPPORTED
        capabilities.motion_sensitivity = _find_numeric(probe.data, "sensitivityLevel")
        capabilities.motion_start_delay = _find_numeric(probe.data, "startTriggerTime")
        capabilities.motion_end_delay = _find_numeric(probe.data, "endTriggerTime")

        target_type = _find_select(probe.data, "targetType")
        if target_type.state is CapabilityState.SUPPORTED:
            options = {option.lower() for option in target_type.options}
            capabilities.motion_human_filter = _presence_state("human" in options)
            capabilities.motion_vehicle_filter = _presence_state("vehicle" in options)

    @staticmethod
    def _apply_image_probe(capabilities: HikvisionCapabilities, probe: _ProbeResult) -> None:
        """Apply range and opt metadata from the image capability response."""
        if probe.state is not CapabilityState.SUPPORTED:
            state = probe.state
            for name in ("brightness", "contrast", "saturation", "sharpness", "gain", "light_brightness"):
                setattr(capabilities, name, NumericCapability(state=state))
            for name in ("day_night", "wdr", "blc", "hlc", "shutter", "noise_reduction", "defog", "supplement_light_mode"):
                setattr(capabilities, name, SelectCapability(state=state))
            # ir_light / white_light / smart_hybrid_light are only meaningful
            # when the image endpoint returns 200 and contains a
            # supplementLightMode field.  A 404 or 403 must not downgrade
            # them to UNSUPPORTED – they stay at their current (UNKNOWN or
            # system-level) value.
            return

        for name, aliases in {
            "brightness": ("brightness",),
            "contrast": ("contrast",),
            "saturation": ("saturation",),
            "sharpness": ("sharpness",),
            "gain": ("gain",),
            "light_brightness": ("supplementLightBrightness", "lightBrightness"),
        }.items():
            setattr(capabilities, name, _find_numeric(probe.data, *aliases))
        for name, aliases in {
            "day_night": ("dayNight", "dayNightMode", "IrcutFilterType"),
            "wdr": ("wdr", "WDR"),
            "blc": ("blc", "BLC"),
            "hlc": ("hlc", "HLC"),
            "shutter": ("shutter",),
            "noise_reduction": ("noiseReduce", "noiseReduction"),
            "defog": ("defog",),
        }.items():
            setattr(capabilities, name, _find_select(probe.data, *aliases))
        light_mode = _find_select(probe.data, "supplementLightMode", "lightMode")
        capabilities.supplement_light_mode = light_mode
        options = {option.lower() for option in light_mode.options}
        capabilities.ir_light = _state_for_option(options, "ir", "infrared")
        capabilities.white_light = _state_for_option(options, "white", "whitelight")
        capabilities.smart_hybrid_light = _state_for_option(options, "smart", "hybrid")

    @staticmethod
    def _apply_supplement_light_probe(capabilities: HikvisionCapabilities, probe: _ProbeResult) -> None:
        """Apply the dedicated supplement-light resource used by ColorVu firmware.

        Some cameras expose light controls only at
        ``Image/channels/{id}/supplementLight``.  Keep generic image capability
        results as a fallback when that optional resource is unavailable.
        """
        if probe.state is not CapabilityState.SUPPORTED:
            return

        light_mode = _find_select(probe.data, "supplementLightMode", "lightMode")
        if light_mode.state is CapabilityState.SUPPORTED:
            capabilities.supplement_light_mode = light_mode
            options = {option.lower() for option in light_mode.options}
            capabilities.ir_light = _state_for_option(options, "ir", "infrared", "irlight")
            capabilities.white_light = _state_for_option(
                options, "white", "whitelight", "colorvuwhitelight"
            )
            capabilities.smart_hybrid_light = _state_for_option(
                options, "smart", "hybrid", "mixed", "duallight", "eventintelligence"
            )

        light_brightness = _find_numeric(
            probe.data,
            "supplementLightBrightness",
            "lightBrightness",
            "whiteLightBrightness",
        )
        if light_brightness.state is CapabilityState.SUPPORTED:
            capabilities.light_brightness = light_brightness


def _stream_capabilities(streams: list[CameraStreamInfo]) -> StreamCapabilities:
    """Represent standard stream availability from the existing stream inventory."""
    stream_ids = {stream.type_id for stream in streams}
    return StreamCapabilities(
        main=_presence_state(1 in stream_ids),
        sub=_presence_state(2 in stream_ids),
        third=_presence_state(3 in stream_ids),
    )


def _presence_state(present: bool) -> CapabilityState:
    """Convert an explicit inventory fact into a capability state."""
    return CapabilityState.SUPPORTED if present else CapabilityState.UNSUPPORTED


def _count_state(data: dict[str, Any], path: str) -> CapabilityState:
    """Return support from an explicit ISAPI count, preserving missing data as unknown."""
    value = deep_get(data, path)
    if value is None:
        return CapabilityState.UNKNOWN
    try:
        return _presence_state(int(value) > 0)
    except (TypeError, ValueError):
        return CapabilityState.UNKNOWN


def _state_at(data: dict[str, Any], path: str) -> CapabilityState:
    """Read an ISAPI boolean at a known System/capabilities path."""
    return _state_from_value(deep_get(data, path))


def _state_from_value(value: Any) -> CapabilityState:
    """Convert Hikvision boolean forms into a conservative state."""
    if isinstance(value, dict):
        value = value.get("#text")
    if isinstance(value, bool):
        return _presence_state(value)
    if isinstance(value, str):
        normalized = value.lower()
        if normalized == "true":
            return CapabilityState.SUPPORTED
        if normalized == "false":
            return CapabilityState.UNSUPPORTED
    return CapabilityState.UNKNOWN


def _find_node(data: dict[str, Any] | None, *aliases: str) -> Any:
    """Find the first matching XML-decoded field without assuming response nesting."""
    if not data:
        return None
    expected = {alias.lower() for alias in aliases}
    stack: list[Any] = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if key.lower() in expected:
                    return value
                stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)
    return None


def _find_state(data: dict[str, Any] | None, *aliases: str) -> CapabilityState:
    """Read a state from a feature-specific capability response."""
    return _state_from_value(_find_node(data, *aliases))


def _find_numeric(data: dict[str, Any] | None, *aliases: str) -> NumericCapability:
    """Read a numeric node and preserve advertised min/max/step values."""
    node = _find_node(data, *aliases)
    if node is None:
        return NumericCapability()
    if not isinstance(node, dict):
        return NumericCapability(state=_state_from_value(node))
    return NumericCapability(
        state=CapabilityState.SUPPORTED,
        minimum=_as_float(node.get("@min") or node.get("min")),
        maximum=_as_float(node.get("@max") or node.get("max")),
        step=_as_float(node.get("@step") or node.get("step")),
    )


def _find_select(data: dict[str, Any] | None, *aliases: str) -> SelectCapability:
    """Read a select node and preserve the complete ISAPI opt= value list."""
    node = _find_node(data, *aliases)
    if node is None:
        return SelectCapability()
    if isinstance(node, dict):
        options = _options(node.get("@opt") or node.get("opt"))
        return SelectCapability(state=CapabilityState.SUPPORTED, options=options)
    return SelectCapability(state=_state_from_value(node))


def _options(value: Any) -> tuple[str, ...]:
    """Split Hikvision's comma-separated opt= attribute without adding values."""
    if not isinstance(value, str):
        return ()
    return tuple(option.strip() for option in value.split(",") if option.strip())


def _as_float(value: Any) -> float | None:
    """Parse an optional device-advertised number."""
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _state_for_option(options: set[str], *markers: str) -> CapabilityState:
    """Infer a lighting feature only from explicit advertised light-mode options."""
    if not options:
        return CapabilityState.UNKNOWN
    return _presence_state(any(marker in option for marker in markers for option in options))
