# Phase 5 Report — Human / Vehicle Event Classification

## Repository path verification

Confirmed: the actual integration directory is `custom_components/hikvision_next/`
(correct spelling). The `hikision_next` spelling in the Phase 4 report was a
**report-only typo**. No production files or imports were ever created under the
misspelled path.

The HA domain remains `hikvision_next`.

## Implementation

### Target normalisation (events.py)

A central `HikvisionDetectionTarget(StrEnum)` is defined with `HUMAN = "human"`
and `VEHICLE = "vehicle"`. `normalize_detection_target()` maps known aliases
(`person`→`human`, `car`→`vehicle`) case-insensitively. Unknown values are
lower-cased and passed through so parsing never crashes.

The parser applies normalisation when reading `detectionTarget` from the XML:

```python
detection_target=normalize_detection_target(
    deep_get(alert, "DetectionRegionList.DetectionRegionEntry.detectionTarget")
),
```

### Person / vehicle binary sensors (binary_sensor.py)

`TargetBinarySensor` — a `BinarySensorEntity` with `BinarySensorDeviceClass.OCCUPANCY`
and `translation_key` "person" / "vehicle". It uses `PLATFORM_SCHEMA`-free entity
setup via `async_setup_entry`.

Capability-driven entity creation:

```python
def _should_create_target_entity(state, has_target_events):
    if state is CapabilityState.SUPPORTED: return True
    if state is CapabilityState.UNSUPPORTED: return False
    return has_target_events  # UNKNOWN → conservative
```

Per camera, `human_filter` capability → person sensor; `vehicle_filter` capability
→ vehicle sensor. Cameras that lack target-event types (`fielddetection`,
`linedetection`, `intrusion`) are skipped when capabilities are UNKNOWN.

### Event state behaviour

`_trigger_target_sensor` in `HikvisionEventProcessor`:

* Maps `HIKVISION_DETECTION_TARGET.HUMAN` → person sensor, `VEHICLE` → vehicle sensor.
* `event_state == "active"` → `STATE_ON`; otherwise → `STATE_OFF`.
* Called from `_trigger_sensor` after the existing EventBinarySensor update,
  so existing sensors remain ON (unchanged) while target sensors update with
  proper on/off semantics.

### NVR channel correctness

`resolve_event_channel` (existing Phase 2 logic) maps NVR channel IDs (>32) to
child camera IDs. `_trigger_target_sensor` uses the resolved `event.channel_id`
to build the unique_id, so an NVR event updates the correct child camera's
person/vehicle sensor, not the NVR itself.

### Backwards compatibility

The `hikvision_next_event` HA event payload is unchanged. `detection_target` key
is preserved. `HikvisionEvent` dataclass keeps all existing fields. Existing
`EventBinarySensor` entities keep their IDs, unique IDs, and always-ON behaviour.

## Unique IDs

New entities use the same slug scheme as existing sensors:

```
binary_sensor.<slugify(serial_no)>_<channel_id>_<person|vehicle>
```

e.g. `binary_sensor.ds_2cd2386g2_iu000001_1_person`

## Capability policy

| Capability state | has target events | Create entity |
|---|---|---|
| SUPPORTED | any | yes |
| UNSUPPORTED | any | no |
| UNKNOWN | yes | yes (conservative) |
| UNKNOWN | no | no |

## NVR behaviour

An NVR-received event with `channelID >= 34` is mapped to the correct child camera
(channel 34 → 2, etc.) via `resolve_event_channel`. The target sensor updated
belongs to the child camera, verified by `test_nvr_target_event_updates_child_sensor`.

## Tests

Command:

```
python -m pytest tests/test_detection_targets.py tests/test_capabilities.py -q
```

Result: **61 passed**

New test file `tests/test_detection_targets.py` (36 tests):

- `normalize_detection_target`: canonical values, aliases, case-insensitivity, None
- Parser: human/vehicle active/inactive, unknown target, NVR without/with target
- `_should_create_target_entity`: SUPPORTED/UNKNOWN/UNSUPPORTED × has/not-target-events
- `_trigger_target_sensor`: person ON/OFF, vehicle ON/OFF, cross-target isolation, unknown/no-target skip
- `TargetBinarySensor`: unique_id format, OCCUPANCY device class, no-polling
- NVR channel resolution for target sensors

Existing test files:

- `tests/test_capabilities.py` (25 tests): all pass
- `tests/test_events.py` (9 tests): **pre-existing Windows/pytest_socket errors** (async
  fixtures require socket-based event loop creation blocked by pytest_socket). These
  failures are not caused by Phase 5 changes. Confirmed by running test_events.py
  against original (stashed) code — same 9 errors.

Additional fixtures created:

- `fielddetection_human_inactive.xml`
- `fielddetection_vehicle_inactive.xml`
- `fielddetection_unknown_target.xml`
- `nvr_1_fielddetection_human.xml`

## Real hardware validation

Not performed in this session (no remote HA instance / camera access available).

## Known limitations

1. **Multiple simultaneous targets**: Hikvision XML payloads in fixtures contain a
   single `DetectionRegionEntry.detectionTarget`. The parser extracts only that
   one value. If a payload ever contains multiple regions with different targets
   in a single event, only the first is captured. This matches the existing
   single-target parsing behaviour and does not introduce new regressions.

2. **Event lifecycle dependency**: Person/vehicle sensors rely entirely on
   Hikvision sending explicit `active`/`inactive` events. No timeout fallback is
   implemented because no evidence of unreliable inactive notifications was found
   in the fixtures.

3. **Windows test infrastructure**: Async integration tests in `test_events.py`
   cannot run on Windows due to `pytest_socket` blocking event-loop creation.
   This is a pre-existing issue (documented in Phase 4 report). All Phase 5
   tests are written as synchronous tests using mock hass state to work around
   this constraint.

## Phase 6 readiness

Phase 5 is ready for Phase 6 (automatic high-resolution snapshots).
The target sensors provide deterministic `binary_sensor.<camera>_person` /
`_vehicle` entities that can be used in automations to trigger snapshot
capture when a person or vehicle is detected. The `hikvision_next_event`
payload includes `channel_id`, `region_id`, and `detection_target` for
correlating snapshots with specific detection events.
