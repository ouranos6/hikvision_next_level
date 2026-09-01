# Phase 7 Report: Supplement Light Controls

## Summary

Implemented capability-driven entity creation for Hikvision supplementary lighting
(IR, white, Smart Hybrid Light) with mode selection and brightness control.

## Endpoints used

| Purpose | Endpoint | Method |
|---------|----------|--------|
| Read capabilities | `Image/channels/{N}/capabilities` | GET (already in Phase 4) |
| Read current settings | `Image/channels/{N}` | GET |
| Write settings | `Image/channels/{N}` | PUT |

The `Image/channels/{N}` endpoint returns an `ImageChannel` XML document containing
`supplementLightMode` and `supplementLightBrightness` fields among others. Changes
are applied by fetching the full XML, modifying the target field, and PUT-ing back.

## Entities added

### `select.<camera>_supplement_light_mode`

Created when `supplement_light_mode` capability is SUPPORTED and has non-empty options.
Only exposes modes reported by the device via `opt=` (e.g. `off,ir,white,smart`).

### `number.<camera>_ir_light_brightness`

Created when `ir_light` is SUPPORTED and `light_brightness` numeric capability is SUPPORTED.

### `number.<camera>_white_light_brightness`

Created when `white_light` is SUPPORTED and `light_brightness` numeric capability is SUPPORTED.

Both brightness entities share the same underlying ISAPI `supplementLightBrightness`
field but have distinct unique IDs and entity names.

## Capability mapping

| Capability field | Source | Interpretation |
|---|---|---|
| `supplement_light_mode` | `Image/channels/{N}/capabilities` → `supplementLightMode.@opt` | Parse comma-separated options |
| `ir_light` | Same options, contains "ir" or "infrared" | SUPPORTED |
| `white_light` | Options contains "white" or "whitelight" | SUPPORTED |
| `smart_hybrid_light` | Options contains "smart" or "hybrid" | SUPPORTED |
| `light_brightness` | `Image/channels/{N}/capabilities` → `supplementLightBrightness.@min/@max/@step` | NumericCapability with range |

### Device examples

| Device | Modes | Brightness |
|---|---|---|
| DS-2CD2386G2-IU | off,ir,white,smart | 1-100, step 1 |
| DS-2CD2T86G2-ISU (/SL) | off,ir,white | 1-100, step 1 |
| DS-2CD2532F-IWS | off,ir | 1-100, step 1 |
| DS-2CD2146G2-ISU | off,ir | 1-100, step 1 |

## Standalone/NVR behavior

- **Standalone cameras**: Image capabilities probed via `Image/channels/{N}/capabilities`.
  Read/write via `Image/channels/{N}`.
- **NVR proxy cameras**: Same endpoints, channel ID maps to the proxy channel number
  (e.g. camera ID 1 → `Image/channels/1`). Entities are attached to the per-camera
  device info so the NVR structure is preserved in the device registry.

## Files changed

| File | Change |
|---|---|
| `custom_components/hikvision_next/capabilities.py` | Added `supplement_light_mode: SelectCapability` field; stored full select capability; moved SelectCapability loop inside non-SUPPORTED branch (bug fix) |
| `custom_components/hikvision_next/isapi/isapi.py` | Added `get_image_channel`, `set_supplement_light_mode`, `set_supplement_light_brightness` |
| `custom_components/hikvision_next/__init__.py` | Added `Platform.SELECT` and `Platform.NUMBER` |
| `custom_components/hikvision_next/select.py` | NEW — `SupplementLightModeSelect` entity |
| `custom_components/hikvision_next/number.py` | NEW — `SupplementLightBrightnessNumber` entity |
| `custom_components/hikvision_next/strings.json` | Added entity translation strings |
| `tests/fixtures/devices/*.json` | Added `Image/channels/{N}` and `Image/channels/{N}/capabilities` endpoints |

## Bug fix in capabilities.py

The original `_apply_image_probe` had a latent `UnboundLocalError`: the SelectCapability
loop (which uses `state`) was positioned outside the `if probe.state is not SUPPORTED`
guard, so `state` was undefined when the probe returned SUPPORTED. Moving the loop
(and the `return`) inside the guard fixes this. This bug was present in the Phase 4
codebase but not triggered by earlier tests because the SelectCapability loop
returned after its first iteration.

## Tests

19 tests in `tests/test_lighting.py`, all passing:

| Test | Scenario |
|---|---|
| `test_discover_ir_only_camera` | IR-only: options = off,ir |
| `test_discover_white_light_camera` | IR+White: options = off,ir,white |
| `test_discover_smart_hybrid_light_camera` | IR+White+Smart: options = off,ir,white,smart |
| `test_discover_unsupported_light_control` | 404 → all light caps UNKNOWN/UNSUPPORTED |
| `test_brightness_min_max_step_from_opt` | min=0, max=100, step=5 preserved |
| `test_select_options_preserved_from_opt` | Options tuple matches opt= values |
| `test_select_entity_created_when_supported` | Select entity created, current_option read |
| `test_select_entity_not_created_when_unsupported` | No entity when unsupported |
| `test_number_entity_created_for_ir` | IR brightness entity, correct range |
| `test_number_entity_created_for_white` | White brightness entity |
| `test_number_entities_created_for_both_types` | Both created when both supported |
| `test_no_number_entity_when_brightness_unsupported` | No entity when brightness unsupported |
| `test_select_write_calls_isapi` | `async_select_option` calls `set_supplement_light_mode` |
| `test_number_write_calls_isapi` | `async_set_native_value` calls `set_supplement_light_brightness` |
| `test_select_write_failure_does_not_break` | Exception caught, `handle_exception` called, state unchanged |
| `test_number_write_failure_does_not_break` | Same for brightness |
| `test_nvr_ir_camera_entities` | NVR proxy channel 1 → IR entities |
| `test_nvr_white_camera_entities` | NVR proxy channel 101 → White entities |
| `test_404_image_endpoint_stays_unknown` | 404 keeps light capabilities UNKNOWN |

Run command (per AUDIT_PHASE_7.md):
```
python -m pytest tests/test_lighting.py tests/test_capabilities.py -q
============================= 44 passed ==============================
```

## Validation

- `python -m compileall -q custom_components tests` — passes
- `git diff --check` — passes
- `pytest tests/test_lighting.py tests/test_capabilities.py -q` — 44 passed

## Known limitations

- No polling coordinator: current values are read on `async_added_to_hass` and after writes.
  The Hikvision ISAPI does not push supplement light state changes.
- Two brightness entities (IR + white) share the same ISAPI `supplementLightBrightness`
  field. Changing one updates the other's displayed value on next read.
- Standalone/NVR proxy cameras both use `Image/channels/{N}` — verified with fixture data
  but not yet tested on real hardware.

## Real hardware validation

Not performed in this phase. Ready for deployment to HA dev instance.
