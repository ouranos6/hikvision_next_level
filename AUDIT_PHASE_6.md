# Phase 6 — Automatic High-Resolution Snapshots

Read first:

* `PROJECT_REFERENCE.md`
* `AUDIT_PHASE_0.md`
* `PHASE_1_REPORT.md`
* `PHASE_2_REPORT.md`
* `PHASE_3_REPORT.md`
* `PHASE_4_REPORT.md`
* `PHASE_5_REPORT.md`

## Goal

Improve the existing Hikvision snapshot entities so they automatically request the configured main-stream resolution when supported.

Do not add new entities or features.

## Requirements

1. Inspect the current snapshot flow and reuse the existing ISAPI client and NVR/channel mapping.

2. Detect the main-stream resolution from the relevant streaming channel configuration:

   * `videoResolutionWidth`
   * `videoResolutionHeight`

3. Cache the detected resolution. Do not query stream configuration on every snapshot request.

4. When width/height are known, request the snapshot with explicit resolution parameters supported by Hikvision.

5. If the high-resolution request fails or the resolution is unknown, automatically fall back to the current legacy snapshot request.

6. Support:

   * standalone cameras;
   * NVR channels;
   * different resolutions per NVR channel.

7. Do not change:

   * domain;
   * entity IDs;
   * unique IDs;
   * event handling;
   * Human/Vehicle sensors;
   * legacy HTTP listener.

8. Do not mix this with event-attached JPEG images. Those are a separate feature.

## Tests

Add targeted tests for:

* 1920×1080 stream;
* 3840×2160 stream;
* missing/invalid resolution;
* standalone camera;
* two NVR channels with different resolutions;
* explicit-resolution request failure → legacy fallback.

Run:

```text
python -m compileall -q custom_components tests
git diff --check
```

Run relevant pytest tests if available.

If the HA dev instance is accessible, validate on real hardware and verify the actual JPEG dimensions, not only HTTP 200.

## Report

Create `PHASE_6_REPORT.md` with:

* files changed;
* resolution discovery method;
* NVR mapping behavior;
* fallback behavior;
* tests/results;
* real hardware result if available;
* known limitations.

Do not start the next phase.

Final message:

```text
Phase 6 complete.
See PHASE_6_REPORT.md
```
