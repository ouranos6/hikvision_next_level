# Phase 4 Report — Automatic Capability Discovery

## Existing work found

When this phase began, no capability discovery implementation existed in the
repository.  The capabilities.py file, the async_get_capability_endpoint
method on ISAPIClient, the wiring in __init__.py, and the capabilities_registry
attribute on HikvisionDevice were all written during this phase.

## Corrections made

### 1. Added async_get_capability_endpoint to ISAPIClient

**File:** custom_components/hikision_next/isapi/isapi.py:723

Added a new async method that reads a feature-specific ISAPI capability endpoint
(e.g. Image/channels/1/capabilities, PTZCtrl/channels/1/capabilities,
System/Audio/channels/1/capabilities) and returns a (status_code, parsed_data_or_None)
tuple. The method reuses the existing ISAPIClient session, authentication, and
timeout infrastructure. Network errors are logged and re-raised so the caller
can treat them as UNKNOWN.

### 2. Stored system_capabilities on ISAPIClient

**File:** custom_components/hikision_next/isapi/isapi.py:103

The System/capabilities response is now stored on self.system_capabilities so
the discovery engine can read device-level facts without a duplicate request.

### 3. Wired discovery into async_setup_entry

**File:** custom_components/hikision_next/__init__.py:83

After the device object is created and before coordinator initialisation,
HikvisionCapabilityDiscovery().async_discover(device, device.system_capabilities)
is called. The resulting HikvisionCapabilityRegistry is stored on
device.capabilities_registry. Any exception is caught and logged at DEBUG level.

### 4. Added capabilities_registry attribute to HikvisionDevice

**File:** custom_components/hikision_next/hikvision_device.py:68

Initialised to None in __init__, populated during setup.

### 5. Fixed probe override of system-level facts

**File:** custom_components/hikision_next/capabilities.py:255 (_apply_audio_probe)

Previously, when a channel-specific audio endpoint returned non-OK, the probe
state would overwrite system-level SUPPORTED facts. Fix: only write to
microphone, speaker, siren when their current value is UNKNOWN.

### 6. Fixed PTZ probe override of system-level facts

**File:** custom_components/hikision_next/capabilities.py:243 (_apply_ptz_probe)

Same bug as audio. Fix: only write to ptz and ptz_presets when UNKNOWN.

### 7. Removed image probe override of light capabilities

**File:** custom_components/hikision_next/capabilities.py:270 (_apply_image_probe)

A 404 on Image/channels/N/capabilities no longer sets ir_light, white_light,
and smart_hybrid_light to UNSUPPORTED. These are only set from a successful
200 response containing supplementLightMode.

### 8. Added soft_alarm_inputs discovery

**File:** custom_components/hikision_next/capabilities.py:158

Both _build_device_capabilities and _apply_system_channel_facts now call
_count_state(system, 'SysCap.IOCap.SoftIOInputPortNums').

### 9. Fixed for_channel KeyError on unknown channel

**File:** custom_components/hikision_next/capabilities.py:100

Changed self.channels[channel_id] to self.channels.get(channel_id,
HikvisionCapabilities()).

## Final architecture

### Capability model

A single HikvisionCapabilities dataclass (slots-based) represents all
discoverable feature states. Each field is either a CapabilityState
(supported/unsupported/unknown) or a NumericCapability/SelectCapability.

HikvisionCapabilityRegistry stores a device-level HikvisionCapabilities
(nvr-wide facts) and a channels dict keyed by channel ID.

### Discovery flow

`
async_setup_entry
  └─ HikvisionCapabilityDiscovery().async_discover(device, system_capabilities)
       ├─ _build_device_capabilities → device-level facts from System/capabilities
       ├─ asyncio.gather(_async_discover_channel[camera_1..N])
       │    ├─ _stream_capabilities(camera.streams) → main/sub/third
       │    ├─ _apply_system_channel_facts (DIRECT cameras only)
       │    ├─ _apply_event_facts
       │    ├─ _async_probe('Image/channels/N/capabilities')
       │    ├─ _async_probe('PTZCtrl/channels/N/capabilities')
       │    └─ _async_probe('System/Audio/channels/N/capabilities')
       └─ HikvisionCapabilityRegistry(device=..., channels={1: ..., 2: ...})
`

### Files changed

- custom_components/hikision_next/capabilities.py — NEW (421 lines)
- custom_components/hikision_next/isapi/isapi.py — added async_get_capability_endpoint + system_capabilities
- custom_components/hikision_next/__init__.py — wired discovery into async_setup_entry
- custom_components/hikision_next/hikvision_device.py — added capabilities_registry attribute
- tests/test_capabilities.py — NEW (25 tests)
- PHASE_4_REPORT.md — this file

### Endpoints used

| Feature | Endpoint | Interpretation |
|---------|----------|----------------|
| Device audio in | System/capabilities (SysCap.AudioCap.audioInputNums) | >0 → microphone SUPPORTED |
| Device audio out | System/capabilities (SysCap.AudioCap.audioOutputNums) | >0 → speaker SUPPORTED |
| Device alarm inputs | System/capabilities (SysCap.IOCap.IOInputPortNums) | >0 → alarm_inputs SUPPORTED |
| Device soft alarm inputs | System/capabilities (SysCap.IOCap.SoftIOInputPortNums) | >0 → soft_alarm_inputs SUPPORTED |
| Device PTZ | System/capabilities (PTZCtrlCap.isSupportPatrols) | 'true' → ptz SUPPORTED |
| Channel image settings | Image/channels/{N}/capabilities | brightness/contrast/etc min/max/step; day_night/wdr options |
| Channel PTZ | PTZCtrl/channels/{N}/capabilities | isSupportPreset → ptz_presets SUPPORTED |
| Channel audio | System/Audio/channels/{N}/capabilities | isSupportMicrophone/Speaker/Siren |
| Channel lighting | Image/channels/{N}/capabilities | supplementLightMode → ir/white/smart |

### Device/channel scope

- DIRECT cameras: System/capabilities facts applied to channel
- PROXIED (NVR) channels: Only channel-specific endpoint probes
- Registry.device: NVR-wide facts (alarm inputs, soft alarm inputs, etc.)

### Unknown vs unsupported

| Condition | State |
|-----------|-------|
| HTTP 200 from feature endpoint | SUPPORTED |
| HTTP 404/405 | UNSUPPORTED |
| HTTP 403 | UNKNOWN |
| Network error/exception | UNKNOWN |
| Field absent from 200 response | UNKNOWN |
| 404 on Image endpoint | ir/white/smart_light stay UNKNOWN |

### Numeric capabilities

NumericCapability stores state, minimum, maximum, step as floats. Parsed from
@min/@max/@step attributes.

### Select capabilities

SelectCapability stores state and options tuple. @opt values preserved.

### Cache strategy

Discovery runs once at async_setup_entry. Results stored on
device.capabilities_registry. No rediscovery in Phase 4.

### Failure handling

- Each probe isolated via asyncio.gather
- Probe exceptions → UNKNOWN
- 403 → UNKNOWN, 404 → UNSUPPORTED
- Top-level try/except in __init__.py catches any error → capabilities_registry = None

### Tests

25 tests in tests/test_capabilities.py, all passing:

`
python -m pytest tests/test_capabilities.py -v --asyncio-mode=auto
============================= 25 passed in 0.27s ==============================
`

Test infrastructure note: On Windows, the HA test plugin's autouse fixtures
(enable_event_loop_debug, verify_cleanup) depend on event_loop, which conflicts
with pytest_socket. The test file overrides these to no-ops and uses a _run_async
helper with temporarily re-enabled sockets.

### Real hardware validation

Not performed in this phase.

### Known limitations

- No rediscovery (static for config entry lifetime)
- No entity creation (discovery-only phase)
- Light capabilities for NVR proxy channels only from channel-specific probes

### Phase 5 readiness

The capability architecture is ready for Phase 5 (entity creation):

1. HikvisionCapabilityRegistry accessible via device.capabilities_registry
2. Consistent CapabilityState enum throughout
3. NumericCapability carries min/max/step for number entities
4. SelectCapability carries options for select entities
5. Channel-level and device-level properly separated
6. for_channel provides safe access for any channel ID
7. Discovery failures isolated, never block setup
