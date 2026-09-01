# Phase 10 Report — Detection Settings

## Scope delivered

Capability-driven controls were added for supported motion-detection settings:

- `number.<camera>_motion_sensitivity`
- `number.<camera>_motion_start_delay`
- `number.<camera>_motion_end_delay`
- `switch.<camera>_detect_human`
- `switch.<camera>_detect_vehicle`

Numbers are created only when the motion capability response provides all of
`min`, `max`, and `step`; no fallback range is invented. Target switches are
created only when that same response explicitly advertises `human` and/or
`vehicle` in `targetType`.

## ISAPI resources inspected and used

The implementation was checked against the ISAPI motion-detection schema and
an observed complete response before coding. It uses these resources through
the existing `ISAPIClient` only:

| Purpose | Resource |
| --- | --- |
| Capability discovery | `GET /ISAPI/System/Video/inputs/channels/{channel}/motionDetection/capabilities` |
| Read current configuration | `GET /ISAPI/System/Video/inputs/channels/{channel}/motionDetection` |
| Update configuration | `PUT /ISAPI/System/Video/inputs/channels/{channel}/motionDetection` |

The full `MotionDetection` document is read, one supported value is changed,
then the complete XML is PUT back. This preserves required grid/layout and
linkage fields. The fields used are:

- `MotionDetection.MotionDetectionLayout.sensitivityLevel`
- `MotionDetection.startTriggerTime`
- `MotionDetection.endTriggerTime`
- `MotionDetection.MotionDetectionLayout.targetType` (`human,vehicle`)

## Capability mapping

| ISAPI capability field | Integration capability | Entity |
| --- | --- | --- |
| `sensitivityLevel @min/@max/@step` | `motion_sensitivity` | motion sensitivity number |
| `startTriggerTime @min/@max/@step` | `motion_start_delay` | start delay number |
| `endTriggerTime @min/@max/@step` | `motion_end_delay` | end delay number |
| `targetType @opt` includes `human` | `motion_human_filter` | human switch |
| `targetType @opt` includes `vehicle` | `motion_vehicle_filter` | vehicle switch |

The new motion-filter capabilities are deliberately separate from the existing
human/vehicle *event* capabilities added in Phase 5. Thus event classification
does not accidentally create a writable configuration control.

## State and failure behaviour

On a successful write each new entity re-reads its device value and updates
itself immediately; no integration reload is needed. A read or write error is
handled through the device error handler and leaves other entities operational.

## Standalone and NVR behaviour

Discovery and reads/writes use the existing discovered `camera.id` without
model matching or a second channel mapping layer. This is the same per-camera
ID used by the existing ISAPI client for direct cameras and NVR input-proxy
channels. The NVR path is covered by tests using proxy channel `101`.

## Tests and validation

```text
python -m pytest tests/test_detection_settings.py tests/test_capabilities.py -q
34 passed

python -m compileall -q custom_components tests
git diff --check
```

`tests/test_detection_settings.py` covers unsupported settings, advertised
numeric ranges, start/end timing values, human/vehicle filters, successful
read/write refresh, failed write isolation, client XML preservation, and NVR
channel handling.

## Real hardware validation

Not performed: this workspace has no accessible Home Assistant development
instance or Hikvision camera/NVR. No credentials were requested or recorded.

## Known limitations

- The controls are intentionally absent when a camera omits complete numeric
  metadata or the `targetType` option list, even if another capability suggests
  it may produce person/vehicle events.
- Intrusion and line-crossing configuration was not added. No uniform writable
  capability/configuration schema for those rules was verified here, so adding
  controls would require guessing paths or XML fields.
- Firmware can expose a different target-filter resource than the documented
  motion-detection `targetType` model; it remains unsupported until its
  capability and read/write payload can be verified.
