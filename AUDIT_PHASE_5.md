# Phase 5 — Human / Vehicle Event Classification

You are continuing the `hikvision_next_level` project.

Before making changes, read:

* `PROJECT_REFERENCE.md`
* `PHASE_4_REPORT.md`

Also inspect the current Git diff and repository state.

Do not repeat previous audits unless necessary.

---

## 0. Verify repository path first

Before any development, verify that the actual Home Assistant integration directory is exactly:

```text
custom_components/hikvision_next/
```

The Phase 4 report contains several references to:

```text
custom_components/hikision_next/
```

Determine whether this is only a report typo.

If any actual production files or imports were created under the misspelled `hikision_next` path, fix that first without changing the Home Assistant domain.

The domain must remain:

```text
hikvision_next
```

Document the result briefly in the Phase 5 report.

---

# Objective

Expose Hikvision AI target classification cleanly so Home Assistant can distinguish at least:

```text
human
vehicle
```

from existing Hikvision events.

This phase should make these classifications easy to consume from Home Assistant automations and later from Frigate.

The existing generic Hikvision events must remain backwards compatible.

---

# Existing architecture to preserve

Do not redesign the event stack.

The current event path must remain:

```text
aiohttp / legacy HTTP
    ↓
HikvisionEventPayloadParser
    ↓
HikvisionEventParser
    ↓
HikvisionEvent
    ↓
HikvisionEventProcessor
    ↓
Home Assistant
```

Phase 4 capability discovery must also remain intact.

Do not change:

* domain;
* existing unique IDs;
* existing entity IDs;
* NVR channel mapping;
* legacy listener;
* existing HA event name;
* existing HA event payload keys.

---

# 1. Inspect existing detection_target parsing

Before modifying code, locate how:

```text
detectionTarget
```

is currently extracted from Hikvision XML.

Confirm the actual values observed in fixtures/code.

Likely examples may include:

```text
human
vehicle
```

but do not assume exact capitalization or spelling.

Normalize only values supported by evidence from existing Hikvision payloads or fixtures.

---

# 2. Normalize target classification centrally

Target normalization belongs in the event parser/model layer, not inside individual Home Assistant entities.

Provide a clean normalized value.

Example conceptual representation:

```python
class HikvisionDetectionTarget(StrEnum):
    HUMAN = "human"
    VEHICLE = "vehicle"
```

A plain normalized string is also acceptable if it better matches the existing architecture.

Do not overengineer.

Unknown Hikvision target values must not crash parsing.

They should remain usable as raw/normalized unknown values or be safely ignored depending on current behavior.

---

# 3. Preserve existing HA event compatibility

The existing event:

```text
hikvision_next_event
```

must continue to work.

Existing payload fields must remain unchanged.

If the integration already emits:

```yaml
detection_target: human
```

preserve that key.

Do not rename it.

The normalized target should improve consistency, not create an incompatible event schema.

---

# 4. Add dedicated person and vehicle binary sensors

Expose dedicated Home Assistant binary sensors where appropriate:

```text
binary_sensor.<camera>_person
binary_sensor.<camera>_vehicle
```

Use standard Home Assistant entity naming/device classes where appropriate.

Do not hardcode entity IDs manually unless required for compatibility.

Use stable unique IDs derived from the same device/channel identity scheme already used by the project.

New entities have no legacy compatibility requirement, but their unique IDs must be deterministic.

---

# 5. Capability-driven creation

Use the Phase 4 capability registry when reliable.

Conceptually:

```text
human_filter supported
→ person binary sensor available

vehicle_filter supported
→ vehicle binary sensor available
```

However, do not suppress valid target events purely because capability discovery returned:

```text
UNKNOWN
```

Hikvision firmware capability reporting is inconsistent.

Recommended behavior:

```text
SUPPORTED → create entity
UNKNOWN + target events known/possible → conservative creation if justified
UNSUPPORTED → normally do not create
```

Choose the least surprising behavior based on actual integration architecture and document it.

Do not remove existing entities.

---

# 6. Event state behavior

Person/vehicle binary sensors must follow the actual Hikvision event lifecycle.

For example:

```text
eventState = active
+ detectionTarget = human
→ person ON
```

and corresponding inactive event:

```text
eventState = inactive
+ detectionTarget = human
→ person OFF
```

Do not invent arbitrary timers if Hikvision already sends active/inactive state.

If some target events do not send reliable inactive notifications, identify this explicitly before implementing any timeout fallback.

Do not add timeout behavior without evidence.

---

# 7. Event type independence

Classification should work with the supported smart event types where target information exists, for example:

```text
motion
line crossing
intrusion
```

Do not create separate entities such as:

```text
line_crossing_person
intrusion_person
motion_person
```

in this phase.

We want:

```text
person
vehicle
```

as target state, while the rich HA event continues to tell us:

```text
event_id
region_id
channel_id
```

This avoids entity explosion.

---

# 8. NVR channel correctness

This is critical.

An event received through an NVR must update the person/vehicle sensor belonging to the correct camera channel, not the NVR globally.

Preserve the existing Phase 2 processor mapping:

```text
event
→ NVR
→ channel resolution
→ child/proxy camera
→ target sensor
```

Add explicit tests for this.

---

# 9. Multiple simultaneous targets

Investigate whether Hikvision may report multiple detection targets in one event.

If supported by the actual XML structure, handle it correctly.

For example:

```text
human + vehicle
```

must not result in one classification silently overwriting the other.

Do not implement speculative multi-target behavior if the XML parser clearly supports only a single target.

Document what the current Hikvision payload format supports.

---

# 10. New entity implementation

Follow the existing binary sensor architecture.

Avoid creating a separate parallel entity framework.

If existing Hikvision event binary sensors share a base class, reuse it where sensible.

New target sensors should:

* belong to the correct camera device;
* have stable unique IDs;
* use modern HA naming conventions;
* update from push events;
* require no polling.

---

# 11. No new polling

Human and vehicle detection are event-driven.

Do not add coordinator polling for these entities.

---

# 12. No Frigate API integration yet

The purpose of these entities is to make future Frigate integration easy.

Do NOT yet:

* call Frigate APIs;
* create Frigate events;
* depend on MQTT;
* add Node-RED logic.

That comes later outside this phase.

---

# 13. Tests

Add focused tests for at least:

```text
human active → person ON
human inactive → person OFF

vehicle active → vehicle ON
vehicle inactive → vehicle OFF

human event does not activate vehicle
vehicle event does not activate person

NVR channel event updates correct child camera

existing hikvision_next_event payload remains compatible

unknown detection target does not crash processor
```

If multiple-target payloads are supported, test them.

Also verify that existing event tests still pass.

---

# 14. Capability interaction tests

Add at least one test for capability-driven entity creation.

Cover:

```text
SUPPORTED
UNKNOWN
UNSUPPORTED
```

according to the policy chosen.

Do not silently change Phase 4 capability semantics.

---

# 15. Real Home Assistant test

After local tests pass, deploy through the existing SFTP workflow to the Home Assistant development instance.

Enable DEBUG logging if needed.

Using a real Hikvision camera/NVR, trigger at least one supported AI event if practical.

Verify:

```text
binary_sensor person/vehicle
+
hikvision_next_event
```

refer to the same camera/channel.

Do not change camera settings unnecessarily.

---

# 16. Validation commands

Run at least:

```text
python -m compileall -q custom_components tests
git diff --check
python -m pytest tests/test_events.py tests/test_capabilities.py <new phase-5 tests> -q
```

If the full project suite is available and reasonably fast, run it as well.

---

# 17. Deliverable

Create:

```text
PHASE_5_REPORT.md
```

Include only:

## Repository path verification

Confirm whether `hikision_next` in the Phase 4 report was a typo or an actual filesystem issue.

## Implementation

How target classification and sensors work.

## Unique IDs

Exact format used for the new entities.

## Capability policy

How SUPPORTED / UNKNOWN / UNSUPPORTED affects entity creation.

## NVR behavior

How events map to the correct child camera.

## Tests

Commands and exact results.

## Real hardware validation

If performed.

## Known limitations

Especially target lifecycle or firmware differences.

## Phase 6 readiness

Confirm readiness for:

```text
automatic high-resolution snapshots
```

---

# Stop condition

When Phase 5 is complete, stop.

Do not implement high-resolution snapshots, lighting controls, PTZ, or other Phase 6+ features.

Finish with a concise summary and point to `PHASE_5_REPORT.md`.
