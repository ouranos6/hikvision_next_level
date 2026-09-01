# Phase 9 — Event-Attached Images

Read first:

* `PROJECT_REFERENCE.md`
* `PHASE_2_REPORT.md`
* `PHASE_5_REPORT.md`
* `PHASE_7_REPORT.md`

## Goal

Expose the JPEG image already received inside Hikvision event notifications.

Phase 2 already retains multipart JPEG data in:

```text
ParsedEventPayload.image
```

This phase must connect that image to the correct camera/channel and expose it in Home Assistant.

## Requirements

1. Do not fetch a new snapshot when an event already includes a JPEG.

2. Keep the image in memory only. No permanent disk writes.

3. Map the image to the same resolved camera/channel used by `HikvisionEventProcessor`, including NVR child cameras.

4. Add one image entity per supported camera:

```text
image.<camera>_last_event
```

Only create it where event images are relevant.

5. On a new event with JPEG:

   * replace the previous image;
   * update the entity;
   * keep the existing `hikvision_next_event` payload unchanged.

6. Events without JPEG must continue to work normally and must not clear the previous image unless there is a clear reason.

7. Avoid unbounded memory usage. Keep only the latest JPEG per camera.

8. Do not change:

* domain
* existing entity IDs
* existing unique IDs
* event parser format
* legacy listener
* snapshots
* lighting
* Human/Vehicle sensors

9. Reuse existing event parsing and processor logic. Do not duplicate multipart handling.

## Tests

Add targeted tests for:

* multipart XML + JPEG
* JPEG mapped to standalone camera
* JPEG mapped to correct NVR child camera
* event without JPEG
* second event replaces previous JPEG
* Human event with JPEG
* Vehicle event with JPEG
* multiple cameras keep separate last-event images

Run:

```text
python -m pytest tests/test_event_images.py tests/test_events.py -q
python -m compileall -q custom_components tests
git diff --check
```

If HA dev is available, validate with a real Hikvision event containing an attached JPEG.

## Real hardware validation

Record:

* model
* firmware
* event type
* target if present
* JPEG received yes/no
* image entity updated yes/no
* actual image dimensions if easy to inspect

No credentials.

## Report

Create `PHASE_9_REPORT.md` with:

* files changed
* image entity design
* event-to-camera mapping
* memory handling
* NVR behavior
* tests/results
* real hardware validation
* known limitations

Do not start detection settings, Day/Night, image controls, audio/siren, or health monitoring.

Final message:

```text
Phase 9 complete.
See PHASE_9_REPORT.md
```
