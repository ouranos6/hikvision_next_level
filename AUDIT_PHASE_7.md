# Phase 7 — Supplement Light Controls

Read first:

* `PROJECT_REFERENCE.md`
* `PHASE_4_REPORT.md`
* `PHASE_6_REPORT.md`

## Goal

Add capability-driven controls for Hikvision supplementary lighting:

* IR light
* White light
* Smart / Smart Hybrid Light
* brightness where supported

Do not add unrelated features.

## Requirements

1. Reuse the Phase 4 capability discovery.

2. Inspect the actual Hikvision ISAPI endpoints and XML already available in the project/fixtures before implementing.

3. Support standalone cameras and NVR-connected cameras when ISAPI allows it.

4. Create entities only when supported.

Preferred HA entities:

```text
select.<camera>_supplement_light_mode
number.<camera>_white_light_brightness
number.<camera>_ir_light_brightness
```

Possible modes may include:

```text
Off
IR
White
Smart
Auto
```

Only expose modes actually reported by the device.

5. Preserve `opt=` values and numeric min/max/step from capability discovery.

6. Reading and writing must use the existing ISAPI client. Entity code must not build raw URLs or XML directly.

7. After a successful write, update state cleanly without requiring a full integration reload.

8. If one light feature fails, do not break the camera or other entities.

9. Do not change:

* domain
* existing entity IDs
* existing unique IDs
* event architecture
* legacy HTTP listener
* snapshot logic
* Human/Vehicle sensors

10. New entity unique IDs must be deterministic and stable, but do not copy old `binary_sensor.xxx`-style unique IDs unnecessarily.

## Tests

Add targeted tests for:

* IR-only camera
* White-light camera
* Smart Hybrid Light camera
* unsupported light control
* select options from `opt=`
* brightness min/max/step
* successful read/write
* write failure without breaking the integration
* NVR channel mapping

Run:

```text
python -m pytest tests/test_lighting.py tests/test_capabilities.py -q
python -m compileall -q custom_components tests
git diff --check
```

If available, deploy to the HA dev instance and validate on real hardware.

## Real hardware validation

For each tested camera, record:

* model
* firmware
* detected modes
* current mode
* successful mode change
* brightness support
* whether the Hikvision web UI reflects the HA change

Do not expose credentials.

## Report

Create `PHASE_7_REPORT.md` with:

* endpoints used
* entities added
* capability mapping
* standalone/NVR behavior
* tests/results
* real hardware result
* known limitations

Do not start Day/Night, PTZ, image controls, or audio/siren.

Final message:

```text
Phase 7 complete.
See PHASE_7_REPORT.md
```
