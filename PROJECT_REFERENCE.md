# Hikvision Next Modernization — Project Reference

## 1. Project goal

This project is a controlled modernization of the Home Assistant custom integration:

`hikvision_next`

The starting point should be the best currently maintained fork derived from:

`maciej-or/hikvision_next`

Prefer the fork:

`itsjustdeepred/hikvision_next`

unless repository inspection shows that another fork contains more recent fixes that are clearly superior and compatible.

The objective is **not** to rewrite the integration from scratch.

The objective is to:

* keep the existing NVR and multi-camera support;
* keep existing entity behavior whenever possible;
* make the integration reliable with current Home Assistant versions;
* modernize the internal architecture where necessary;
* add a limited, clearly defined set of useful Hikvision features;
* preserve backwards compatibility with existing `hikvision_next` installations whenever reasonably possible.

Do not add unrelated features.

Do not expand the project scope beyond the functionality explicitly listed in this document.

---

# 2. Core principles

## 2.1 Preserve compatibility

Keep the existing Home Assistant domain:

```python
DOMAIN = "hikvision_next"
```

Do not rename existing entities or unique IDs unless absolutely necessary.

When a migration is required, implement an explicit migration mechanism.

Existing users should preferably be able to replace the custom component and reload Home Assistant without rebuilding the entire integration.

---

## 2.2 Do not hardcode camera models

Avoid logic such as:

```python
if model.startswith("DS-2CD"):
```

or lists of supported model names whenever possible.

Instead, detect functionality using Hikvision ISAPI capability endpoints and actual endpoint probing.

The integration must adapt dynamically to:

* camera generation;
* firmware version;
* standalone camera vs NVR channel;
* ColorVu models;
* PTZ models;
* `/SL` models;
* different ISAPI capabilities.

---

## 2.3 Capability-driven entity creation

Entities must only exist if the underlying device supports the feature.

For example, a camera without PTZ support must not expose PTZ entities.

A camera without white light must not expose white-light entities.

A camera without siren capability must not expose siren controls.

The architecture should provide a centralized capability registry rather than performing repeated capability checks in individual entity files.

---

# 3. Target architecture

The target architecture should conceptually follow:

```text
Home Assistant
      |
      +-- Entity platforms
      |
      +-- Coordinator
      |
      +-- Event Manager
              |
              +-- Event transport
              |      |
              |      +-- Legacy HTTP listener
              |      |
              |      +-- ISAPI alert stream if implemented/reliable
              |
              +-- Event parser
      |
      +-- Capability Registry
      |
      +-- Hikvision Client
              |
              +-- ISAPI
              |
              +-- Cameras
              |
              +-- NVR
```

Do not force this exact file layout if the existing project architecture makes another layout cleaner.

However, responsibilities must remain clearly separated.

---

# 4. Layer responsibilities

## Hikvision client

The Hikvision API/client layer should ideally not contain Home Assistant entity logic.

Its role is to perform operations such as:

```python
await client.get_system_info()
await client.get_capabilities()
await client.get_streams()
await client.get_snapshot(...)
await client.get_ptz_status()
await client.goto_preset(...)
await client.set_day_night_mode(...)
await client.set_supplement_light(...)
```

The client should expose clean Python objects or structured results.

---

## Capability registry

Create a central representation of device capabilities.

Conceptually:

```python
@dataclass
class HikvisionCapabilities:
    ptz: bool = False
    presets: bool = False

    ir_light: bool = False
    white_light: bool = False
    smart_hybrid_light: bool = False

    motion_detection: bool = False
    line_crossing: bool = False
    intrusion_detection: bool = False

    human_detection: bool = False
    vehicle_detection: bool = False

    day_night: bool = False

    wdr: bool = False
    blc: bool = False
    hlc: bool = False

    siren: bool = False
    microphone: bool = False
    speaker: bool = False

    alarm_inputs: bool = False
    soft_alarm_inputs: bool = False
```

This example is conceptual.

Use appropriate nested structures if they are cleaner.

---

## Coordinator

Use polling only for state that genuinely needs polling.

Examples:

* CPU usage;
* RAM usage;
* uptime;
* HDD state;
* current lighting mode;
* day/night state;
* current detection configuration;
* alarm state.

Do not poll frequently for information that can be obtained through push events.

---

## Event Manager

Events must be handled independently from the polling coordinator.

The event manager should process normalized events such as:

```python
@dataclass
class HikvisionEvent:
    device_id: str
    channel: int | None
    event_type: str
    active: bool

    target_type: str | None
    region_id: int | None

    timestamp: datetime | None

    image: bytes | None
```

The parser may internally retain additional Hikvision metadata when useful.

---

# 5. Scope

Only the following functional areas are in scope.

## Priority 1 — Event listener compatible with current aiohttp / Home Assistant

## Priority 2 — Automatic capability detection

## Priority 3 — Human and Vehicle events

## Priority 4 — Automatic high-resolution snapshots

## Priority 5 — White light / IR / Smart Hybrid Light control

## Priority 6 — PTZ and presets

## Priority 7 — Detection sensitivity and trigger timing

## Priority 8 — Day / Night / Auto control

## Priority 9 — Image controls

## Priority 10 — Audio and siren

## Priority 11 — Health monitoring

## Priority 12 — Event images

## Priority 13 — NVR Soft Alarm Inputs

Anything outside this list is out of scope unless explicitly requested later.

In particular, do not implement:

* recording browser;
* firmware update;
* ANPR;
* face recognition;
* media browser;
* complex playback management;
* advanced two-way audio streaming;
* unrelated ONVIF features.

---

# 6. Development phases

Each phase must be completed and validated before moving to the next one.

Do not implement several phases simultaneously unless there is a strong architectural reason.

---

# PHASE 0 — Repository audit

Before modifying code:

1. inspect the complete repository;
2. inspect open fixes already present in the selected fork;
3. identify code inherited from upstream;
4. identify current Home Assistant deprecated APIs;
5. identify current tests;
6. identify current event architecture;
7. identify current ISAPI client architecture;
8. identify NVR/channel mapping;
9. identify current entity ID / unique ID behavior.

Produce an internal implementation plan before modifying code.

Do not start feature development during this phase.

---

# PHASE 1 — Baseline compatibility and regression tests

Objective:

Create a known stable baseline before architectural modifications.

Tasks:

* ensure the integration loads correctly on current Home Assistant;
* preserve existing configuration entries;
* fix clear deprecated Home Assistant APIs;
* fix entity ID generation problems;
* preserve existing unique IDs when possible;
* verify unload/reload behavior;
* verify startup/shutdown behavior;
* ensure async operations do not block the HA event loop.

Add regression tests around existing behavior before refactoring major code.

Important:

Do not add new functionality yet.

Acceptance criteria:

* existing supported entities still load;
* existing configurations are not silently destroyed;
* integration unload/reload works;
* tests pass;
* no new obvious Home Assistant deprecation warnings are introduced.

---

# PHASE 2 — Event architecture refactor

Objective:

Separate Hikvision event parsing from Home Assistant HTTP handling.

Create conceptually:

```text
event transport
    |
event parser
    |
normalized HikvisionEvent
    |
EventManager
    |
Home Assistant entities/events
```

The same parser must be reusable regardless of how the HTTP/event payload was received.

Do not mix:

* socket handling;
* HTTP parsing;
* XML parsing;
* HA entity updates.

Acceptance criteria:

A stored raw Hikvision event fixture can be parsed without requiring a running Home Assistant HTTP server.

---

# PHASE 3 — Modern Hikvision event listener

This phase addresses the current Home Assistant/aiohttp incompatibility.

Some Hikvision devices send malformed or legacy HTTP requests such as:

* HTTP/1.1 without a `Host` header;
* unexpected `Content-Type`;
* XML labeled as `application/x-www-form-urlencoded`;
* multipart messages containing XML and JPEG.

Modern aiohttp can reject malformed HTTP before Home Assistant integration code receives the request.

Therefore do not attempt to globally weaken aiohttp validation.

Do not monkey-patch aiohttp.

Do not modify Home Assistant core.

Instead implement a dedicated compatibility listener if necessary.

Preferred implementation:

```python
asyncio.start_server(...)
```

The compatibility listener should understand only the limited subset of HTTP required for Hikvision notifications.

Example endpoint:

```text
POST /api/hikvision
```

The listener must support HTTP requests with missing `Host`.

Security requirements:

* POST only;
* expected path only;
* configurable/local port;
* payload size limit;
* header size limit;
* read timeout;
* connection timeout;
* source validation when possible;
* no arbitrary proxy behavior;
* no Internet exposure requirement.

Possible defaults:

```text
MAX_HEADER_SIZE ≈ 16 KB
MAX_PAYLOAD_SIZE ≈ 16 MB
READ_TIMEOUT ≈ 10 seconds
```

Use reasonable values based on observed Hikvision payloads.

Do not blindly trust `Content-Type`.

If the payload clearly contains XML such as:

```xml
<EventNotificationAlert>
```

it should be parsed as XML even if Hikvision sends an incorrect MIME type.

Acceptance tests must include at least:

```text
normal XML request
missing Host header
application/x-www-form-urlencoded containing XML
multipart XML event
multipart XML + JPEG event
malformed request
oversized request
unsupported path
unsupported method
```

---

# PHASE 4 — Capability discovery

Objective:

Create a reliable capability discovery system.

Use:

* ISAPI capability endpoints;
* endpoint probing;
* returned XML capability structures.

Avoid guessing capabilities from model names.

The capability system should support standalone cameras and cameras behind NVRs.

Capabilities should be cached after discovery.

Provide a controlled rediscovery mechanism if needed.

Possible entity:

```text
button.<device>_rediscover_capabilities
```

This may be diagnostic/disabled by default.

Do not continuously reload the config entry.

Acceptance criteria:

Two cameras with different features produce different appropriate entity sets.

Unsupported entities must not be created.

---

# PHASE 5 — Human and Vehicle events

Normalize Hikvision target classification.

Expose at least:

```text
human
vehicle
```

Do not assume every camera supports both.

Possible Home Assistant entities:

```text
binary_sensor.<camera>_person
binary_sensor.<camera>_vehicle
```

These binary sensors should activate from Hikvision events.

Also include the target type in the existing rich HA event if appropriate.

Example:

```yaml
event_type: line_crossing
target: human
channel: 1
region: 2
```

Preserve raw event data only where useful and safe.

These entities must work well for Home Assistant automations and Frigate integration.

---

# PHASE 6 — Event images

Hikvision event notifications may contain:

```text
XML event
+
JPEG image
```

Do not discard JPEG parts.

The parser should retain the event image when one is supplied.

Expose the last event image using an appropriate Home Assistant `image` entity.

Example:

```text
image.<camera>_last_event
```

Requirements:

* do not write unnecessary permanent files;
* prefer in-memory handling;
* replace previous event image;
* avoid unbounded memory use;
* correctly map images to device/channel;
* handle events without image.

Acceptance test:

Multipart event containing XML + JPEG should update both:

```text
event state
image.<camera>_last_event
```

---

# PHASE 7 — High-resolution snapshots

Fix snapshot resolution automatically.

Do not assume that:

```text
/ISAPI/Streaming/channels/101/picture
```

always returns the maximum configured resolution.

Discover the main stream resolution from the relevant ISAPI configuration.

Then request an appropriately sized snapshot if required by the device/NVR.

The logic must support:

* standalone cameras;
* NVR channels;
* different stream IDs.

Avoid user configuration when the correct resolution can be discovered automatically.

Acceptance criteria:

The snapshot matches or closely corresponds to the configured main-stream resolution where supported.

---

# PHASE 8 — Supplement light controls

Implement capability-driven controls for:

* infrared light;
* white light;
* Smart Hybrid Light;
* light brightness where supported.

Prefer Home Assistant entities such as:

```text
select.<camera>_supplement_light_mode
number.<camera>_white_light_brightness
number.<camera>_ir_light_brightness
```

Possible modes depend on actual device capabilities.

Examples:

```text
Off
IR
White light
Smart
Auto
```

Do not expose unsupported modes.

Do not assume the same ISAPI XML schema exists on every firmware.

Use capability/probing logic.

---

# PHASE 9 — PTZ and presets

Implement PTZ only when supported.

Required functionality:

* pan;
* tilt;
* zoom;
* stop;
* goto preset;
* preset discovery.

Use Hikvision ISAPI where practical.

Possible HA representation:

```text
service/action hikvision_next.ptz
select.<camera>_ptz_preset
```

or another native HA-friendly model if more appropriate.

Do not create dozens of preset buttons unnecessarily.

Preset names should be discovered dynamically when possible.

Support NVR-connected PTZ cameras where ISAPI permits.

Acceptance criteria:

The integration can:

1. discover presets;
2. move to a preset;
3. issue manual PTZ movement;
4. stop movement.

---

# PHASE 10 — Detection configuration

Expose detection parameters only when supported.

Initial scope:

* motion sensitivity;
* human filtering;
* vehicle filtering;
* start trigger delay;
* end trigger delay.

Where supported, extend the same pattern to:

* line crossing;
* intrusion.

Prefer entities such as:

```text
number.<camera>_motion_sensitivity
number.<camera>_motion_start_delay
number.<camera>_motion_end_delay

switch.<camera>_detect_human
switch.<camera>_detect_vehicle
```

or equivalent Home Assistant-native entities.

Do not invent ranges.

Read min/max/step values from Hikvision capability responses wherever possible.

---

# PHASE 11 — Day / Night controls

Implement:

```text
Auto
Day
Night
```

and additional supported modes only if exposed by the device.

Possible entity:

```text
select.<camera>_day_night_mode
```

If available, also expose:

```text
day/night sensitivity
day/night switching delay
```

Do not expose meaningless configuration on cameras where switching is automatic/fixed.

---

# PHASE 12 — Image controls

Only expose image controls that can be reliably discovered.

Candidate features:

```text
brightness
contrast
saturation
sharpness

WDR
WDR level

BLC
HLC
HLC level

gain
shutter

noise reduction
defog
```

Do not assume all controls can be active simultaneously.

Respect device compatibility rules.

Example:

If the camera reports that WDR and BLC are mutually exclusive, prevent invalid state combinations.

Whenever possible:

* detect allowed values;
* detect ranges;
* detect incompatible modes;
* expose native `number`, `switch` or `select` entities.

Do not implement obscure image parameters unless already present in capabilities.

---

# PHASE 13 — Audio and siren

Implement only capabilities exposed by the device.

Potential entities:

```text
siren.<camera>
number.<camera>_alarm_volume
select.<camera>_alarm_tone
number.<camera>_alarm_duration

number.<camera>_microphone_volume
number.<camera>_speaker_volume
```

Do not implement full two-way audio streaming in this project phase.

The goal is control of the camera's built-in acoustic warning functionality, especially Hikvision `/SL` models.

---

# PHASE 14 — Health monitoring

Expose useful diagnostic information where supported.

Candidate values:

```text
CPU usage
RAM usage
uptime
reboot count
active streams
stream count
device online state
channel online state
storage state
recording state
```

Do not poll aggressively.

Health data should generally be exposed as:

```python
EntityCategory.DIAGNOSTIC
```

and low-value sensors may be disabled by default.

---

# PHASE 15 — NVR Soft Alarm Inputs

Investigate Hikvision NVR virtual/soft alarm input APIs.

When supported, allow Home Assistant to trigger these inputs.

Use an appropriate entity type such as:

```text
button
```

or another momentary action model.

Example:

```text
button.<nvr>_soft_alarm_input_1
```

The goal is to allow Home Assistant to trigger Hikvision's internal NVR actions, for example:

```text
Home Assistant event
        |
Soft Alarm Input
        |
Hikvision NVR
        |
PTZ preset / recording / alarm action
```

Detect the number and availability of soft alarm inputs dynamically.

Do not expose physical alarm inputs as writable unless the API clearly supports it.

---

# 7. Home Assistant integration standards

Follow current Home Assistant development practices.

Use async APIs.

Avoid blocking the event loop.

Use modern ConfigEntry patterns where practical.

Prefer typed runtime data over unstructured global dictionaries.

For example:

```python
@dataclass
class HikvisionRuntimeData:
    client: HikvisionClient
    coordinator: HikvisionCoordinator
    event_manager: HikvisionEventManager
    capabilities: HikvisionCapabilities
```

Use:

```text
EntityCategory.CONFIG
EntityCategory.DIAGNOSTIC
```

where appropriate.

Use `has_entity_name = True` and modern device/entity naming patterns if compatible with existing entities.

Do not break existing unique IDs without a migration.

---

# 8. Configuration philosophy

Keep initial configuration simple.

Preferred initial setup:

```text
Host
Username
Password
```

Advanced configuration belongs in an Options Flow.

Possible advanced options:

```text
Event transport
Notification listener port
Notification host override
Polling interval
Advanced diagnostics
```

Do not put normal camera controls into Options Flow.

Things such as:

```text
IR mode
brightness
PTZ preset
day/night mode
motion sensitivity
```

must be Home Assistant entities.

---

# 9. Diagnostics

Implement Home Assistant diagnostics.

Diagnostics should include useful technical state such as:

```text
integration version
device model
firmware version

discovered capabilities
event transport
listener status

last event timestamp
events received
parse errors

streams discovered
ISAPI endpoints supported
```

Sensitive data must be redacted.

Never expose:

```text
password
authentication tokens
Authorization headers
camera credentials
```

Diagnostic entities may include:

```text
sensor.<device>_event_transport
sensor.<device>_last_event
sensor.<device>_events_received
sensor.<device>_event_parse_errors
binary_sensor.<device>_event_receiver
```

Avoid clutter.

Disable purely technical entities by default where appropriate.

---

# 10. Error handling

The integration must degrade gracefully.

Examples:

If PTZ endpoint fails:

```text
disable/not create PTZ capability
```

Do not fail the entire camera integration.

If image settings are not supported:

```text
do not create the corresponding entities
```

If the event listener stops:

```text
report diagnostic problem
```

but keep camera entities functioning.

If one NVR channel fails:

```text
do not break all other channels
```

---

# 11. Logging

Normal logging should remain concise.

Use debug logging for:

* capability discovery;
* ISAPI endpoint selection;
* event parsing details;
* event transport state.

Never log passwords or authentication headers.

Avoid continuously logging complete image payloads or huge XML bodies.

When an event cannot be parsed, log enough information to diagnose:

```text
device
source IP
Content-Type
payload length
event parser stage
```

but do not dump megabytes of binary data.

---

# 12. Testing requirements

Every important Hikvision quirk discovered during development should become a regression fixture.

At minimum create fixtures/tests for:

```text
normal XML event
missing Host header
incorrect Content-Type
multipart XML event
multipart XML + JPEG event

motion event
line crossing human event
line crossing vehicle event
intrusion event

standalone camera
NVR channel

capability with PTZ
capability without PTZ

camera with white light
camera without white light
```

Tests must cover:

* parsing;
* capability detection;
* entity creation;
* config entry setup;
* unload/reload;
* malformed requests;
* event image handling.

Do not only test happy paths.

---

# 13. Security

The custom compatibility listener intentionally accepts some legacy Hikvision HTTP behavior rejected by modern aiohttp.

Therefore it must be narrowly scoped.

Requirements:

* no generic HTTP server behavior;
* no arbitrary URL routing;
* no proxy capabilities;
* strict method checking;
* strict path checking;
* payload limits;
* header limits;
* timeouts;
* source validation when possible.

The compatibility listener should be intended for trusted LAN use.

Do not expose it automatically to the Internet.

---

# 14. Performance

Avoid:

```text
high-frequency polling
repeated capability scans
frequent ConfigEntry reloads
unbounded image caching
unbounded event queues
```

Prefer event-driven updates.

Capability discovery should normally happen during setup.

A manual rediscovery function is preferable to frequent background rediscovery unless a reliable need is identified.

---

# 15. NVR architecture

Preserve the existing strength of `hikvision_next` regarding NVRs.

Maintain logical relationships such as:

```text
NVR
 |
 +-- Camera channel 1
 |
 +-- Camera channel 2
 |
 +-- Camera channel 3
 |
 +-- Storage
```

Use Home Assistant `via_device` relationships where appropriate.

Do not flatten all NVR channels into one device.

Standalone cameras and NVR channels should use the same internal feature architecture whenever practical.

---

# 16. Implementation workflow

For every phase:

## Step 1 — Inspect

Inspect existing implementation and relevant Hikvision ISAPI behavior.

## Step 2 — Plan

Document internally:

* files to modify;
* new abstractions;
* compatibility risks;
* migration risks;
* expected tests.

## Step 3 — Implement

Make the smallest coherent architectural change needed for that phase.

## Step 4 — Test

Run:

* existing tests;
* new regression tests;
* lint/type checks available in the repository.

## Step 5 — Review

Check for:

* Home Assistant API misuse;
* duplicated logic;
* blocking I/O;
* unnecessary model-specific conditions;
* leaked credentials;
* unbounded resources.

## Step 6 — Commit

Keep commits logically separated.

Do not create one enormous commit containing several unrelated phases.

---

# 17. Git strategy

Suggested branch structure:

```text
main
 |
 +-- phase-1-ha-compat
 |
 +-- phase-2-event-refactor
 |
 +-- phase-3-legacy-listener
 |
 +-- phase-4-capabilities
 |
 +-- phase-5-ai-events
 ...
```

Or use short-lived branches and merge each completed phase into the project development branch.

Keep commit messages descriptive.

Example:

```text
refactor: separate event parsing from HA HTTP view

fix: accept Hikvision event requests without Host header

feat: add capability-driven supplement light entities

feat: add PTZ preset discovery
```

---

# 18. Versioning strategy

Suggested milestones:

## 2.0.0-alpha1

* Home Assistant compatibility;
* regression tests;
* internal cleanup.

## 2.0.0-alpha2

* event architecture;
* compatibility event listener.

## 2.0.0-beta1

* capability registry;
* Human/Vehicle events;
* event images;
* high-resolution snapshots.

## 2.0.0

Stable modernization baseline.

Includes:

* reliable events;
* capability discovery;
* AI target events;
* event images;
* high-resolution snapshots.

## 2.1

* supplement lights;
* Day/Night.

## 2.2

* PTZ;
* presets.

## 2.3

* detection configuration;
* image controls.

## 2.4

* audio/siren;
* health monitoring;
* NVR Soft Alarm Inputs.

The actual release breakdown may be adjusted if dependencies make another grouping cleaner.

---

# 19. Out-of-scope rule

Do not opportunistically add features because an ISAPI endpoint was discovered.

If a feature is not listed in this project reference, leave it out.

It is acceptable to design architecture that could support additional capabilities later.

It is not acceptable to increase current scope without explicit instruction.

---

# 20. Final target

The desired integration should behave conceptually as:

```text
                         HIKVISION
                            |
              +-------------+-------------+
              |                           |
            ISAPI                       Events
              |                           |
      Capability discovery        Event transports
              |                     |         |
              |                     |         |
              |                 alertStream  Legacy HTTP
              |                           \   /
              |                        Event parser
              |                             |
              +--------- Device ------------+
                            |
                    Home Assistant
                            |
          +-----------------+------------------+
          |                 |                  |
       Entities          Events            Diagnostics
          |                 |
          |                 +--> Human
          |                 +--> Vehicle
          |                 +--> Motion
          |                 +--> Line crossing
          |                 +--> Intrusion
          |                 +--> Event image
          |
          +--> Camera / snapshot
          +--> IR / white light
          +--> PTZ
          +--> Day / Night
          +--> Detection config
          +--> Image controls
          +--> Siren / audio
          +--> Health
          +--> Soft Alarm Inputs
```

The result should remain recognizably `hikvision_next`, but with:

* modern Home Assistant compatibility;
* clean architecture;
* reliable Hikvision events;
* capability-driven entities;
* strong NVR support;
* useful camera controls;
* good diagnostics;
* maintainable tests.

Prefer correctness, maintainability and backwards compatibility over implementing features quickly.

Do not begin a new development phase until the previous phase is coherent and its tests pass.
