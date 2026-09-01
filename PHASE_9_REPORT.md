# Phase 9 Report — Event-Attached Images

## Files changed

- `custom_components/hikvision_next/events.py` — accepts an optional JPEG alongside
  the normalized event, stores it after the existing channel resolution, and sends
  a camera-specific internal dispatcher signal.
- `custom_components/hikvision_next/notifications.py` and `legacy_http.py` — pass
  `ParsedEventPayload.image` to the shared processor; no multipart parsing is
  duplicated.
- `custom_components/hikvision_next/hikvision_device.py` — keeps one in-memory
  JPEG per resolved camera channel.
- `custom_components/hikvision_next/image.py` — adds `LastEventImage` entities.
- `custom_components/hikvision_next/strings.json` and `translations/en.json` — add
  the `last_event` image translation.
- `tests/test_event_images.py` — new Phase 9 coverage.

## Image entity design

`LastEventImage` is created only for cameras with supported event definitions.
Its deterministic unique ID is:

```text
<slugified-nvr-or-camera-serial>_<camera-channel>_last_event
```

It reads from `HikvisionDevice` memory only.  It never requests a snapshot and
never writes an image to disk.  Each camera channel has one dictionary entry, so
a new JPEG replaces only that camera's preceding JPEG.

## Event-to-camera mapping

Both transports retain their existing chain:

```text
HTTP body → ParsedEventPayload → HikvisionEvent → processor channel resolution
```

The JPEG is stored only after `resolve_event_channel()`.  Thus an NVR event on
channel 34 maps to its proxy child camera (for example channel 2) before the
event-image entity is notified.  XML-only notifications continue through the
normal binary-sensor and Home Assistant event paths without clearing an image.

## Memory handling

Only the latest `bytes` value is retained per discovered camera channel.  The
number of retained JPEGs is therefore bounded by the number of configured camera
channels; no persistent files or growing event history are created.

## Tests and validation

```text
python -m pytest tests/test_event_images.py tests/test_events.py tests/test_legacy_http.py -q
31 passed

python -m compileall -q custom_components tests
git diff --check
```

The tests cover multipart XML + JPEG, standalone mapping, NVR child mapping,
XML-only events, replacement, separate cameras, and human/vehicle events.

## Real hardware validation

Not performed: no Home Assistant development instance or Hikvision device was
available in this workspace.

## Known limitations

- A camera needs an event definition before its event-image entity is created.
- The image remains available until Home Assistant reloads the integration; this
  is intentional because Phase 9 requires memory-only storage.
- The implementation keeps one JPEG per event, not a history or media browser.
