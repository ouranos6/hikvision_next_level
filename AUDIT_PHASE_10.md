# Phase 10 — Detection Settings

Read first:

* `PROJECT_REFERENCE.md`
* `PHASE_4_REPORT.md`
* `PHASE_5_REPORT.md`
* `PHASE_9_REPORT.md`

## Goal

Add capability-driven controls for Hikvision detection settings.

Initial scope:

* motion sensitivity
* start trigger delay
* end trigger delay
* human filter
* vehicle filter

If clearly supported by existing capability data, apply the same pattern to:

* intrusion detection
* line crossing

Do not add unrelated detection features.

## Requirements

1. Reuse Phase 4 capability discovery.

2. Inspect the real ISAPI endpoints/XML before implementation.

3. Use the existing ISAPI client for all reads/writes. Entity code must not build raw XML or URLs.

4. Create entities only when supported.

Preferred entities:

```text
number.<camera>_motion_sensitivity
number.<camera>_motion_start_delay
number.<camera>_motion_end_delay
switch.<camera>_detect_human
switch.<camera>_detect_vehicle
```

5. Preserve min/max/step from capabilities. Do not invent ranges.

6. Support standalone and NVR-connected cameras where ISAPI allows it.

7. After a successful write, refresh/update state without requiring integration reload.

8. A failure on one setting must not break the camera or other entities.

9. Do not change:

* domain
* existing IDs
* event architecture
* legacy listener
* event images
* snapshots
* lighting

## Tests

Add tests for:

* unsupported detection settings
* motion sensitivity range
* start/end delay range
* human filter
* vehicle filter
* successful read/write
* failed write
* NVR channel mapping

Run:

```text
python -m pytest tests/test_detection_settings.py tests/test_capabilities.py -q
python -m compileall -q custom_components tests
git diff --check
```

If HA dev is available, validate on real hardware.

## Real hardware validation

Record:

* model
* firmware
* detected settings
* current values
* successful change
* whether Hikvision web UI reflects the change

No credentials.

## Report

Create `PHASE_10_REPORT.md` with:

* endpoints used
* entities added
* capability mapping
* standalone/NVR behavior
* tests/results
* real hardware validation
* known limitations

Do not start Day/Night, image controls, audio/siren, health monitoring, or soft alarm inputs.

Final message:

```text
Phase 10 complete.
See PHASE_10_REPORT.md
```
