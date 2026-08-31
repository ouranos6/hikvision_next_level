"""Hikvision event payload parsing and Home Assistant event processing."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import logging
import socket
from typing import Final
from urllib.parse import urlparse
from xml.parsers.expat import ExpatError

import xmltodict
from requests_toolbelt.multipart import MultipartDecoder

from homeassistant.const import STATE_ON, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import async_get
from homeassistant.util import slugify

from .const import DOMAIN, HIKVISION_EVENT
from .hikvision_device import HikvisionDevice
from .isapi import IPCamera
from .isapi.const import EVENT_IO, EVENTS, EVENTS_ALTERNATE_ID
from .isapi.utils import deep_get

_LOGGER = logging.getLogger(__name__)

CONTENT_TYPE_XML: Final = ("application/xml", "text/xml")
CONTENT_TYPE_IMAGE_JPEG: Final = "image/jpeg"
XML_ROOT: Final = b"<EventNotificationAlert"


class HikvisionEventError(ValueError):
    """Base error for Hikvision event handling."""


class HikvisionEventPayloadError(HikvisionEventError):
    """Raised when an HTTP body does not contain a Hikvision event XML payload."""


class HikvisionEventParseError(HikvisionEventError):
    """Raised when Hikvision event XML cannot be normalized."""


@dataclass(slots=True)
class ParsedEventPayload:
    """Hikvision event data extracted from an HTTP payload."""

    xml: str
    image: bytes | None = None


@dataclass(slots=True)
class HikvisionEvent:
    """Normalized Hikvision event notification."""

    event_id: str
    channel_id: int
    io_port_id: int
    device_serial_no: str | None
    device_mac: str | None
    device_ip: str | None
    region_id: int
    detection_target: str | None
    event_state: str | None


class HikvisionEventPayloadParser:
    """Extract Hikvision event XML and an optional JPEG from HTTP payload bytes."""

    def parse(self, body: bytes, content_type: str | None) -> ParsedEventPayload:
        """Parse an event payload independently from aiohttp."""
        if not body:
            raise HikvisionEventPayloadError("Empty event payload")

        if self._looks_like_xml(body):
            return ParsedEventPayload(xml=self._decode_xml(body))

        normalized_content_type = (content_type or "").lower()
        if normalized_content_type.startswith("multipart/"):
            return self._parse_multipart(body, content_type)

        raise HikvisionEventPayloadError(
            f"Unsupported event Content-Type {content_type or '<missing>'}"
        )

    @staticmethod
    def _looks_like_xml(data: bytes) -> bool:
        """Return whether bytes plausibly contain an XML event document."""
        stripped = data.lstrip()
        return stripped.startswith(b"<?xml") or XML_ROOT in stripped

    @staticmethod
    def _decode_xml(data: bytes) -> str:
        """Decode XML payload bytes."""
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError as ex:
            raise HikvisionEventPayloadError("Event XML is not UTF-8") from ex

    def _parse_multipart(self, body: bytes, content_type: str | None) -> ParsedEventPayload:
        """Extract XML and JPEG parts without relying on their order."""
        try:
            decoder = MultipartDecoder(body, content_type)
        except (AttributeError, ValueError, TypeError) as ex:
            raise HikvisionEventPayloadError("Invalid multipart event payload") from ex

        xml: str | None = None
        image: bytes | None = None
        for part in decoder.parts:
            part_content_type = part.headers.get(b"Content-Type", b"").decode(
                "ascii", errors="ignore"
            ).lower()
            if self._looks_like_xml(part.content) or part_content_type.startswith(CONTENT_TYPE_XML):
                xml = self._decode_xml(part.content)
            elif (
                part_content_type.startswith(CONTENT_TYPE_IMAGE_JPEG)
                or part.content.startswith(b"\xff\xd8\xff")
            ):
                image = part.content

        if xml is None:
            raise HikvisionEventPayloadError("Multipart payload does not contain event XML")
        return ParsedEventPayload(xml=xml, image=image)


class HikvisionEventParser:
    """Normalize Hikvision EventNotificationAlert XML."""

    def parse(self, xml: str) -> HikvisionEvent:
        """Parse XML into an event independent from HTTP transport."""
        try:
            # Preserve the legacy tolerance for cameras that do not escape ampersands.
            data = xmltodict.parse(xml.replace("&", "&amp;"))
            alert = data["EventNotificationAlert"]
        except (ExpatError, KeyError, TypeError, ValueError) as ex:
            raise HikvisionEventParseError("Invalid EventNotificationAlert XML") from ex

        event_id = alert.get("eventType")
        if not event_id or event_id == "duration":
            try:
                event_id = alert["DurationList"]["Duration"]["relationEvent"]
            except (KeyError, TypeError) as ex:
                raise HikvisionEventParseError("Event notification has no event type") from ex
        event_id = event_id.lower()
        event_id = EVENTS_ALTERNATE_ID.get(event_id, event_id)
        if event_id not in EVENTS:
            raise HikvisionEventParseError(f"Unsupported event {event_id}")

        try:
            channel_id = int(alert.get("channelID", alert.get("dynChannelID", 0)))
            io_port_id = int(alert.get("inputIOPortID", 0))
            region_id = int(deep_get(alert, "DetectionRegionList.DetectionRegionEntry.regionID", 0))
        except (TypeError, ValueError) as ex:
            raise HikvisionEventParseError("Event notification has invalid numeric data") from ex

        return HikvisionEvent(
            event_id=event_id,
            channel_id=channel_id,
            io_port_id=io_port_id,
            device_serial_no=deep_get(alert, "Extensions.serialNumber.#text"),
            device_mac=alert.get("macAddress"),
            device_ip=alert.get("ipAddress"),
            region_id=region_id,
            detection_target=deep_get(
                alert, "DetectionRegionList.DetectionRegionEntry.detectionTarget"
            ),
            event_state=alert.get("eventState"),
        )


class HikvisionEventProcessor:
    """Resolve normalized events and apply the existing Home Assistant behavior."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the processor."""
        self.hass = hass

    async def async_process(self, event: HikvisionEvent, source_ip: str | None) -> None:
        """Resolve the target device and update Home Assistant."""
        device = await self._async_get_device(source_ip, event)
        self.resolve_event_channel(device, event)
        self._trigger_sensor(device, event)

    async def _async_get_device(
        self, source_ip: str | None, event: HikvisionEvent
    ) -> HikvisionDevice:
        """Find the integration instance matching a notification."""
        integration_entries = self.hass.config_entries.async_entries(DOMAIN)
        instance_identifiers: list[str | None] = []
        entry = None
        if len(integration_entries) == 1:
            entry = integration_entries[0]
        else:
            for item in integration_entries:
                if item.disabled_by:
                    continue
                item_mac_address = item.runtime_data.device_info.mac_address
                instance_identifiers.append(item_mac_address)
                if item_mac_address == event.device_mac:
                    entry = item
                    break

            if not entry:
                for item in integration_entries:
                    if item.disabled_by:
                        continue
                    url = item.runtime_data.host
                    instance_identifiers.append(url)
                    if source_ip and await self._async_get_ip(urlparse(url).hostname) == source_ip:
                        entry = item
                        break

        if not entry:
            raise HikvisionEventError(
                f"Cannot find ISAPI instance for device {source_ip} in {instance_identifiers}"
            )
        return entry.runtime_data

    async def _async_get_ip(self, host: str | None) -> str:
        """Return a literal IP or asynchronously resolve a hostname."""
        if not host:
            return ""
        try:
            ipaddress.ip_address(host)
            return host
        except ValueError:
            resolved_hostname = await self.hass.async_add_executor_job(socket.gethostbyname, host)
            _LOGGER.debug("Resolve host %s resolves to IP %s", host, resolved_hostname)
            return resolved_hostname

    @staticmethod
    def resolve_event_channel(device: HikvisionDevice, event: HikvisionEvent) -> None:
        """Map a NVR notification channel to its camera channel."""
        if event.channel_id <= 32:
            return
        try:
            event.channel_id = next(
                camera.id
                for camera in device.cameras
                if isinstance(camera, IPCamera) and camera.input_port == event.channel_id - 32
            )
        except StopIteration:
            event.channel_id -= 32

    def _trigger_sensor(self, device: HikvisionDevice, event: HikvisionEvent) -> None:
        """Set the matching binary sensor and fire the legacy HA event."""
        serial_no = device.device_info.serial_no.lower()
        device_id_param = (
            f"_{event.channel_id}" if event.channel_id != 0 and event.event_id != EVENT_IO else ""
        )
        io_port_id_param = f"_{event.io_port_id}" if event.io_port_id != 0 else ""
        unique_id = (
            f"binary_sensor.{slugify(serial_no)}{device_id_param}{io_port_id_param}_{event.event_id}"
        )

        entity_registry = async_get(self.hass)
        entity_id = entity_registry.async_get_entity_id(Platform.BINARY_SENSOR, DOMAIN, unique_id)
        if not entity_id:
            raise HikvisionEventError(f"Entity not found {entity_id}")

        entity = self.hass.states.get(entity_id)
        if not entity:
            return
        self.hass.states.async_set(entity_id, STATE_ON, entity.attributes)
        self._fire_hass_event(device, event)

    def _fire_hass_event(self, device: HikvisionDevice, event: HikvisionEvent) -> None:
        """Fire the existing hikvision_next_event payload."""
        camera_name = ""
        if camera := device.get_camera_by_id(event.channel_id):
            camera_name = camera.name

        message = {
            "channel_id": event.channel_id,
            "io_port_id": event.io_port_id,
            "camera_name": camera_name,
            "event_id": event.event_id,
        }
        if event.detection_target:
            message["detection_target"] = event.detection_target
            message["region_id"] = event.region_id

        self.hass.bus.fire(HIKVISION_EVENT, message)
