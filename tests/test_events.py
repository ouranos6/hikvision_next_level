"""Tests for transport-independent Hikvision event parsing and processing."""

from pathlib import Path

import pytest

from homeassistant.const import STATE_ON
from homeassistant.core import Event, HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hikvision_next.const import HIKVISION_EVENT
from custom_components.hikvision_next.events import (
    HikvisionEventParseError,
    HikvisionEventParser,
    HikvisionEventPayloadParser,
    HikvisionEventProcessor,
)
from tests.conftest import TEST_HOST_IP

FIXTURES = Path(__file__).parent / "fixtures" / "ISAPI" / "EventNotificationAlert"


def event_xml(name: str) -> str:
    """Load a captured Hikvision event fixture."""
    return (FIXTURES / f"{name}.xml").read_text(encoding="utf-8")


@pytest.mark.parametrize("content_type", ["application/xml", "text/xml"])
def test_xml_payload_is_extracted_and_normalized(content_type: str) -> None:
    """XML payload types must produce the existing event data."""
    payload = HikvisionEventPayloadParser().parse(
        event_xml("fielddetection_human").encode(), content_type
    )
    event = HikvisionEventParser().parse(payload.xml)

    assert event.event_id == "fielddetection"
    assert event.channel_id == 1
    assert event.detection_target == "human"
    assert event.region_id == 3
    assert payload.image is None


def test_xml_is_detected_despite_incorrect_form_content_type() -> None:
    """Hikvision XML mislabeled as form data must not be discarded."""
    payload = HikvisionEventPayloadParser().parse(
        event_xml("fielddetection_vehicle").encode(), "application/x-www-form-urlencoded"
    )

    event = HikvisionEventParser().parse(payload.xml)
    assert event.detection_target == "vehicle"
    assert event.region_id == 2


def test_multipart_retains_xml_and_jpeg_without_assuming_part_order() -> None:
    """A multipart event retains the JPEG internally for a later phase."""
    boundary = "hikvision-boundary"
    jpeg = b"\xff\xd8\xffevent-image\xff\xd9"
    body = b"\r\n".join(
        [
            f"--{boundary}".encode(),
            b"Content-Type: image/jpeg",
            b"",
            jpeg,
            f"--{boundary}".encode(),
            b"Content-Type: application/xml; charset=UTF-8",
            b"",
            event_xml("ipc_1_fielddetection").encode(),
            f"--{boundary}--".encode(),
            b"",
        ]
    )

    payload = HikvisionEventPayloadParser().parse(
        body, f"multipart/form-data; boundary={boundary}"
    )

    assert HikvisionEventParser().parse(payload.xml).event_id == "fielddetection"
    assert payload.image == jpeg


@pytest.mark.parametrize(
    ("fixture", "event_id"),
    [
        ("ipc_thermometry_motiondetection", "motiondetection"),
        ("ipc_1_fielddetection", "fielddetection"),
    ],
)
def test_captured_events_keep_normalized_event_types(fixture: str, event_id: str) -> None:
    """Existing Hikvision event variants retain their normalized event type."""
    event = HikvisionEventParser().parse(event_xml(fixture))
    assert event.event_id == event_id


def test_line_crossing_event_is_normalized() -> None:
    """Line crossing XML uses the same normalized model as captured events."""
    event = HikvisionEventParser().parse(
        "<EventNotificationAlert><eventType>lineDetection</eventType>"
        "<channelID>4</channelID><eventState>active</eventState>"
        "</EventNotificationAlert>"
    )

    assert event.event_id == "linedetection"
    assert event.channel_id == 4
    assert event.event_state == "active"


def test_malformed_event_raises_controlled_error() -> None:
    """Malformed XML must not escape the event parser as an implementation error."""
    with pytest.raises(HikvisionEventParseError):
        HikvisionEventParser().parse("<EventNotificationAlert>")


@pytest.mark.parametrize("init_integration", ["DS-7608NXI-I2"], indirect=True)
async def test_processor_preserves_nvr_binary_sensor_and_ha_event(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    """A normalized NVR event reaches the same entity and HA bus event as before."""
    event = HikvisionEventParser().parse(event_xml("nvr_2_fielddetection"))
    bus_events: list[Event] = []
    hass.bus.async_listen(HIKVISION_EVENT, bus_events.append)

    await HikvisionEventProcessor(hass).async_process(event, TEST_HOST_IP)
    await hass.async_block_till_done()

    entity_id = "binary_sensor.ds_7608nxi_i0_0p_s0000000000ccrrj00000000wcvu_2_fielddetection"
    assert hass.states.get(entity_id).state == STATE_ON
    assert len(bus_events) == 1
    assert bus_events[0].data == {
        "channel_id": 2,
        "io_port_id": 0,
        "camera_name": "home",
        "event_id": "fielddetection",
    }
