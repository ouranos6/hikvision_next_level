"""Home Assistant HTTP transport for Hikvision event notifications."""

from __future__ import annotations

from http import HTTPStatus
import logging

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.const import CONTENT_TYPE_TEXT_PLAIN
from homeassistant.core import HomeAssistant

from .const import ALARM_SERVER_PATH, DOMAIN
from .events import (
    HikvisionEventError,
    HikvisionEventParser,
    HikvisionEventPayloadParser,
    HikvisionEventProcessor,
)

_LOGGER = logging.getLogger(__name__)


class EventNotificationsView(HomeAssistantView):
    """Receive an HTTP event and delegate parsing and processing."""

    def __init__(self, hass: HomeAssistant):
        """Initialize the HTTP transport."""
        self.requires_auth = False
        self.url = ALARM_SERVER_PATH
        self.name = DOMAIN
        self.hass = hass
        self._payload_parser = HikvisionEventPayloadParser()
        self._event_parser = HikvisionEventParser()
        self._processor = HikvisionEventProcessor(hass)

    async def post(self, request: web.Request) -> web.Response:
        """Accept a POST request from an NVR or IP camera."""
        try:
            body = await request.read()
            content_type = request.headers.get("Content-Type")
            _LOGGER.debug(
                "Incoming Hikvision event: source=%s content_type=%s payload_length=%s",
                request.remote,
                content_type,
                len(body),
            )
            payload = self._payload_parser.parse(body, content_type)
            event = self._event_parser.parse(payload.xml)
            _LOGGER.debug(
                "Parsed Hikvision event: event=%s channel=%s target=%s",
                event.event_id,
                event.channel_id,
                event.detection_target,
            )
            await self._processor.async_process(event, request.remote, image=payload.image)
        except HikvisionEventError as ex:
            _LOGGER.warning("Cannot process Hikvision event: %s", ex)
        except Exception as ex:  # pylint: disable=broad-except
            _LOGGER.warning("Unexpected Hikvision event processing error: %s", ex)

        return web.Response(status=HTTPStatus.OK, content_type=CONTENT_TYPE_TEXT_PLAIN)
