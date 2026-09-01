# Phase 9 — PTZ and Presets

Read first:

* `PROJECT_REFERENCE.md`
* `AUDIT_PHASE_7.md`
* `PHASE_4_REPORT.md`
* `PHASE_7_REPORT.md`

## Goal

Implement capability-driven PTZ (Pan/Tilt/Zoom) and preset controls for Hikvision
cameras that support them.

Do not add unrelated features.

## Requirements

1. The Phase 4 capability registry already exposes `ptz` and `ptz_presets` as
   `CapabilityState` values. Reuse this discovery. Do not re-probe or re-implement
   discovery logic here.

2. Inspect the actual Hikvision ISAPI endpoints and XML already available in the
   project/fixtures before implementing. There are currently no PTZ fixture
   endpoints in any device fixture file. Create what is needed.

3. Support standalone cameras and NVR-connected PTZ cameras when ISAPI allows it.

4. Required functionality:
   * pan (start / stop)
   * tilt (start / stop)
   * zoom (start / stop)
   * stop all movement
   * goto preset
   * preset discovery (name + token)

5. Create entities only when supported.

Preferred HA representation:

```text
service  hikvision_next.ptz              — pan, tilt, zoom, stop, home
select   <camera>_ptz_preset            — discover presets, goto on select
```

Do not create dozens of preset buttons. Preset names should be discovered
dynamically when possible.

6. Read and write must use the existing ISAPI client. Entity/service code must
   not build raw URLs or XML directly.

7. After a successful write, update state cleanly without requiring a full
   integration reload.

8. If a PTZ feature fails, do not break the camera or other entities.

9. Do not change:

   * domain
   * existing entity IDs
   * existing unique IDs
   * event architecture
   * legacy HTTP listener
   * snapshot logic
   * Human/Vehicle sensors
   * supplement light entities (Phase 7)

10. New entity unique IDs must be deterministic and stable, following the
    same slugify scheme used by Phase 7:
    `{serial_no}_{camera_id}_ptz_preset`

## ISAPI endpoints (Hikvision)

| Purpose | Endpoint | Method |
|---------|----------|--------|
| Preset list | `PTZCtrl/channels/{channelId}/presets` | GET |
| Goto preset | `PTZCtrl/channels/{channelId}/presets/{presetToken}` | PUT |
| PTZ continuous move | `PTZCtrl/channels/{channelId}/ptz` | GET (with query params) |

PTZ control query parameters:
* `moveReq.ptzAction` = `start` | `stop` | `precisionStart` | `precisionStop`
* `moveReq.pan` = -359.9 … 359.9 (direction -1 = left, 1 = right for continuous)
* `moveReq.tilt` = -180 … 180 (direction -1 = down, 1 = up for continuous)
* `moveReq.zoom` = 0 … 1 (direction +1 = zoom in, -1 = zoom out)

For continuous movement the typical Hikvision approach uses:
```text
GET /ISAPI/PTZCtrl/channels/1/ptz?
    moveReq.ptzAction=start&
    moveReq.leftRight=1&
    moveReq.upDown=1&
    moveReq.zoom=1
```
or absolute positioning. For this phase we focus on the simpler continuous
movement model: `start` / `stop` with pan/tilt/zoom direction flags.

## Service schema

Service: `hikvision_next.ptz`

```yaml
data:
  entity_id: <camera>           # or device_id
  action: pan|tilt|zoom|stop|home
  direction: left|right|up|down|in|out  # for pan, tilt, zoom
  speed: 1…10                  # optional, default 1
```

* `stop` — stops all PTZ movement on the channel
* `home` — moves the camera to its home position
* `pan left/right`, `tilt up/down`, `zoom in/out` — continuous start

## Select entity

`select.<camera>_ptz_preset`

* Created when `ptz_presets` capability is `SUPPORTED`.
* Options = preset names discovered from `PTZCtrl/channels/{channelId}/presets`.
* `current_option` updated from `PTZCtrl/channels/{channelId}/status` (if the
  device exposes it), otherwise cleared on select.
* Selecting an option calls `goto_preset`.
* Unique ID: `{slugify(serial_no)}_{camera_id}_ptz_preset`

## Tests

Add targeted tests for:

* PTZ capability SUPPORTED → entity created
* PTZ capability UNSUPPORTED → no entity
* PTZ capability UNKNOWN → no entity
* preset discovery (multiple presets with names)
* preset selection calls goto_preset
* service PTZ move (pan/tilt/zoom/stop)
* service move failure without breaking
* NVR proxy channel PTZ
* write failure without breaking the integration

Run:

```text
python -m compileall -q custom_components tests
python -m pytest tests/test_ptz.py tests/test_capabilities.py -q
git diff --check
```

## Report

Create `PHASE_9_REPORT.md` with:

* endpoints used
* entities added
* service added
* capability mapping
* standalone/NVR behavior
* tests/results
* known limitations

Final message:

```text
Phase 9 complete.
See PHASE_9_REPORT.md
```
