"""Tests for in-memory JPEG images attached to Hikvision events."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.hikvision_next.events import (
    HikvisionEventParser,
    HikvisionEventPayloadParser,
    HikvisionEventProcessor,
)
from custom_components.hikvision_next.image import LastEventImage
from custom_components.hikvision_next.isapi.models import IPCamera

FIXTURES = Path(__file__).parent / "fixtures" / "ISAPI" / "EventNotificationAlert"


def _event(name: str):
    """Parse a captured event fixture."""
    return HikvisionEventParser().parse((FIXTURES / f"{name}.xml").read_text(encoding="utf-8"))


class _EventImageDevice:
    """Small device double holding per-channel in-memory event images."""

    def __init__(self, cameras):
        self.cameras = cameras
        self.device_info = SimpleNamespace(serial_no="DS-7608NXI-I2/SERIAL")
        self._images: dict[int, bytes] = {}

    def get_camera_by_id(self, channel_id: int):
        return next((camera for camera in self.cameras if camera.id == channel_id), None)

    def set_last_event_image(self, channel_id: int, image: bytes) -> None:
        self._images[channel_id] = image

    def get_last_event_image(self, channel_id: int) -> bytes | None:
        return self._images.get(channel_id)

    def hass_device_info(self, _channel_id: int):
        return {"identifiers": {("hikvision_next", "test")}}


def _camera(camera_id: int, input_port: int | None = None) -> IPCamera:
    """Create a camera suitable for standalone or NVR mapping tests."""
    return IPCamera(
        id=camera_id,
        name=f"Camera {camera_id}",
        model="DS-2CD2386G2-IU",
        serial_no=f"CAMERA{camera_id}",
        input_port=input_port or camera_id,
        connection_type="Proxied" if input_port else "Direct",
        streams=[],
    )


def _processor(monkeypatch):
    """Create a processor and capture dispatcher notifications."""
    processor = HikvisionEventProcessor.__new__(HikvisionEventProcessor)
    processor.hass = SimpleNamespace()
    sent = MagicMock()
    monkeypatch.setattr("custom_components.hikvision_next.events.async_dispatcher_send", sent)
    return processor, sent


def _multipart_body(xml: bytes, jpeg: bytes, boundary: str = "event-boundary") -> tuple[bytes, str]:
    """Build a representative Hikvision multipart notification body."""
    body = b"\r\n".join(
        [
            f"--{boundary}".encode(),
            b"Content-Type: application/xml",
            b"",
            xml,
            f"--{boundary}".encode(),
            b"Content-Type: image/jpeg",
            b"",
            jpeg,
            f"--{boundary}--".encode(),
            b"",
        ]
    )
    return body, f"multipart/form-data; boundary={boundary}"


def test_multipart_jpeg_is_retained_and_mapped_to_standalone_camera(monkeypatch):
    """A multipart event updates the correct standalone camera image only."""
    jpeg = b"\xff\xd8\xffstandalone-event\xff\xd9"
    xml = (FIXTURES / "fielddetection_human.xml").read_bytes()
    body, content_type = _multipart_body(xml, jpeg)
    payload = HikvisionEventPayloadParser().parse(body, content_type)
    event = HikvisionEventParser().parse(payload.xml)
    device = _EventImageDevice([_camera(1)])
    processor, sent = _processor(monkeypatch)

    processor._store_event_image(device, event, payload.image)

    assert device.get_last_event_image(1) == jpeg
    sent.assert_called_once()


def test_nvr_event_image_is_mapped_to_the_resolved_child_camera(monkeypatch):
    """NVR channel 34 maps to child camera 2 before its JPEG is stored."""
    device = _EventImageDevice([_camera(2, input_port=2)])
    event = _event("nvr_1_fielddetection_human")
    processor, _ = _processor(monkeypatch)

    processor.resolve_event_channel(device, event)
    processor._store_event_image(device, event, b"nvr-jpeg")

    assert event.channel_id == 2
    assert device.get_last_event_image(2) == b"nvr-jpeg"


def test_event_without_jpeg_keeps_the_previous_image(monkeypatch):
    """An XML-only event must not clear the last usable event image."""
    device = _EventImageDevice([_camera(1)])
    device.set_last_event_image(1, b"previous")
    processor, sent = _processor(monkeypatch)

    processor._store_event_image(device, _event("ipc_1_fielddetection"), None)

    assert device.get_last_event_image(1) == b"previous"
    sent.assert_not_called()


def test_second_event_replaces_only_its_camera_image(monkeypatch):
    """Only one JPEG per camera is retained, independently per channel."""
    device = _EventImageDevice([_camera(1), _camera(2)])
    processor, _ = _processor(monkeypatch)
    first = _event("ipc_1_fielddetection")
    second = _event("ipc_1_fielddetection")
    second.channel_id = 2

    processor._store_event_image(device, first, b"first")
    processor._store_event_image(device, second, b"second-camera")
    processor._store_event_image(device, first, b"replacement")

    assert device.get_last_event_image(1) == b"replacement"
    assert device.get_last_event_image(2) == b"second-camera"


@pytest.mark.parametrize("fixture_name", ["fielddetection_human", "fielddetection_vehicle"])
def test_classified_event_images_are_stored_without_changing_target_handling(
    monkeypatch, fixture_name
):
    """Human and vehicle events both retain their attached JPEG."""
    device = _EventImageDevice([_camera(1)])
    processor, _ = _processor(monkeypatch)

    processor._store_event_image(device, _event(fixture_name), b"classified-jpeg")

    assert device.get_last_event_image(1) == b"classified-jpeg"


def test_event_image_entity_reads_only_its_camera_memory():
    """The image entity returns in-memory bytes and does not fetch snapshots."""
    device = _EventImageDevice([_camera(1), _camera(2)])
    device.set_last_event_image(1, b"camera-one")
    device.set_last_event_image(2, b"camera-two")

    first = LastEventImage(MagicMock(), device, _camera(1))
    second = LastEventImage(MagicMock(), device, _camera(2))

    assert first.image() == b"camera-one"
    assert second.image() == b"camera-two"
