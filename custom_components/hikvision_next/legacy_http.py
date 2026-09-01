"""Minimal asyncio HTTP transport for legacy Hikvision event notifications."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from http import HTTPStatus
import logging
from typing import Any

from .const import ALARM_SERVER_PATH, DEFAULT_LEGACY_EVENT_HOST, DEFAULT_LEGACY_EVENT_PORT
from .events import (
    HikvisionEventError,
    HikvisionEventParser,
    HikvisionEventPayloadParser,
    HikvisionEventProcessor,
)

_LOGGER = logging.getLogger(__name__)

MAX_HEADER_SIZE = 16 * 1024
MAX_PAYLOAD_SIZE = 16 * 1024 * 1024
HEADER_TIMEOUT = 10
BODY_TIMEOUT = 10
MAX_CONCURRENT_CONNECTIONS = 20


class LegacyHttpTransportError(ValueError):
    """An invalid request handled by the minimal legacy HTTP transport."""

    def __init__(self, status: HTTPStatus, message: str) -> None:
        """Initialize a response-safe transport error."""
        super().__init__(message)
        self.status = status


@dataclass(slots=True)
class LegacyHttpRequest:
    """Validated subset of an HTTP request required by Hikvision notifications."""

    method: str
    path: str
    content_type: str | None
    content_length: int
    body_prefix: bytes


class HikvisionLegacyHttpListener:
    """Serve only legacy Hikvision POST notifications on a dedicated local port."""

    def __init__(
        self,
        hass: Any,
        host: str = DEFAULT_LEGACY_EVENT_HOST,
        port: int = DEFAULT_LEGACY_EVENT_PORT,
        payload_parser: HikvisionEventPayloadParser | None = None,
        event_parser: HikvisionEventParser | None = None,
        processor: HikvisionEventProcessor | None = None,
    ) -> None:
        """Initialize a listener with reusable phase 2 event components."""
        self._host = host
        self._port = port
        self._payload_parser = payload_parser or HikvisionEventPayloadParser()
        self._event_parser = event_parser or HikvisionEventParser()
        self._processor = processor or HikvisionEventProcessor(hass)
        self._server: asyncio.AbstractServer | None = None
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_CONNECTIONS)
        self.connections_received = 0
        self.events_processed = 0
        self.parse_errors = 0
        self.transport_errors = 0

    @property
    def port(self) -> int:
        """Return the configured port, or the ephemeral bound port after startup."""
        return self._port

    @property
    def is_running(self) -> bool:
        """Return whether the listener socket is open."""
        return self._server is not None

    async def async_start(self) -> None:
        """Start the dedicated listener exactly once."""
        if self._server is not None:
            return

        self._server = await asyncio.start_server(self._handle_client, self._host, self._port)
        if self._server.sockets:
            self._port = self._server.sockets[0].getsockname()[1]
        _LOGGER.info("Started Hikvision legacy event listener on %s:%s", self._host, self._port)

    async def async_stop(self) -> None:
        """Close the listener socket and release its bound port."""
        if self._server is None:
            return

        server, self._server = self._server, None
        server.close()
        await server.wait_closed()
        _LOGGER.debug("Stopped Hikvision legacy event listener")

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Process one connection and always close it after one response."""
        if self._semaphore.locked():
            await self._async_respond(writer, HTTPStatus.SERVICE_UNAVAILABLE)
            return

        async with self._semaphore:
            self.connections_received += 1
            source_ip = self._get_source_ip(writer)
            try:
                request = await self._async_read_request(reader)
                self._validate_route(request)
                body = await self._async_read_body(reader, request)
                _LOGGER.debug(
                    "Legacy Hikvision event: source=%s method=%s path=%s content_type=%s content_length=%s",
                    source_ip,
                    request.method,
                    request.path,
                    request.content_type,
                    request.content_length,
                )
                try:
                    payload = self._payload_parser.parse(body, request.content_type)
                    event = self._event_parser.parse(payload.xml)
                    await self._processor.async_process(event, source_ip, image=payload.image)
                except HikvisionEventError as ex:
                    self.parse_errors += 1
                    _LOGGER.warning("Cannot process legacy Hikvision event from %s: %s", source_ip, ex)
                else:
                    self.events_processed += 1
                    _LOGGER.debug(
                        "Processed legacy Hikvision event: source=%s event=%s channel=%s",
                        source_ip,
                        event.event_id,
                        event.channel_id,
                    )
                await self._async_respond(writer, HTTPStatus.OK)
            except LegacyHttpTransportError as ex:
                self.transport_errors += 1
                _LOGGER.warning("Rejected legacy Hikvision request from %s: %s", source_ip, ex)
                await self._async_respond(writer, ex.status)
            except asyncio.TimeoutError:
                self.transport_errors += 1
                _LOGGER.warning("Timed out reading legacy Hikvision request from %s", source_ip)
                await self._async_respond(writer, HTTPStatus.REQUEST_TIMEOUT)
            except Exception:  # pragma: no cover - defensive connection boundary
                self.transport_errors += 1
                _LOGGER.exception("Unexpected legacy Hikvision listener error from %s", source_ip)
                await self._async_respond(writer, HTTPStatus.INTERNAL_SERVER_ERROR)

    async def _async_read_request(self, reader: asyncio.StreamReader) -> LegacyHttpRequest:
        """Read a bounded HTTP request header without requiring Host."""
        header_data = bytearray()
        async with asyncio.timeout(HEADER_TIMEOUT):
            while b"\r\n\r\n" not in header_data:
                if len(header_data) >= MAX_HEADER_SIZE:
                    raise LegacyHttpTransportError(
                        HTTPStatus.REQUEST_HEADER_FIELDS_TOO_LARGE, "HTTP headers exceed limit"
                    )
                chunk = await reader.read(min(4096, MAX_HEADER_SIZE - len(header_data) + 1))
                if not chunk:
                    raise LegacyHttpTransportError(HTTPStatus.BAD_REQUEST, "Incomplete HTTP headers")
                header_data.extend(chunk)

        separator = header_data.find(b"\r\n\r\n")
        if separator < 0 or separator > MAX_HEADER_SIZE:
            raise LegacyHttpTransportError(
                HTTPStatus.REQUEST_HEADER_FIELDS_TOO_LARGE, "HTTP headers exceed limit"
            )

        try:
            header_lines = bytes(header_data[:separator]).decode("iso-8859-1").split("\r\n")
            method, path, version = header_lines[0].split(" ", 2)
        except (IndexError, UnicodeDecodeError, ValueError) as ex:
            raise LegacyHttpTransportError(HTTPStatus.BAD_REQUEST, "Malformed request line") from ex

        if version not in {"HTTP/1.0", "HTTP/1.1"}:
            raise LegacyHttpTransportError(HTTPStatus.BAD_REQUEST, "Unsupported HTTP version")

        headers: dict[str, str] = {}
        for line in header_lines[1:]:
            if not line or ":" not in line:
                raise LegacyHttpTransportError(HTTPStatus.BAD_REQUEST, "Malformed HTTP header")
            key, value = line.split(":", 1)
            key = key.strip().lower()
            if not key or key in headers:
                raise LegacyHttpTransportError(HTTPStatus.BAD_REQUEST, "Invalid HTTP header")
            headers[key] = value.strip()

        transfer_encoding = headers.get("transfer-encoding")
        if transfer_encoding:
            raise LegacyHttpTransportError(
                HTTPStatus.NOT_IMPLEMENTED, "Transfer-Encoding is not supported"
            )

        content_length_text = headers.get("content-length")
        if content_length_text is None or not content_length_text.isdecimal():
            raise LegacyHttpTransportError(HTTPStatus.BAD_REQUEST, "Invalid Content-Length")
        content_length = int(content_length_text)
        if content_length > MAX_PAYLOAD_SIZE:
            raise LegacyHttpTransportError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Payload exceeds limit")

        return LegacyHttpRequest(
            method=method,
            path=path,
            content_type=headers.get("content-type"),
            content_length=content_length,
            body_prefix=bytes(header_data[separator + 4 :]),
        )

    @staticmethod
    def _validate_route(request: LegacyHttpRequest) -> None:
        """Restrict the listener to its only supported method and path."""
        if request.method != "POST":
            raise LegacyHttpTransportError(HTTPStatus.METHOD_NOT_ALLOWED, "Only POST is supported")
        if request.path != ALARM_SERVER_PATH:
            raise LegacyHttpTransportError(HTTPStatus.NOT_FOUND, "Unknown request path")

    @staticmethod
    async def _async_read_body(
        reader: asyncio.StreamReader, request: LegacyHttpRequest
    ) -> bytes:
        """Read exactly Content-Length bytes under a bounded timeout."""
        if len(request.body_prefix) > request.content_length:
            raise LegacyHttpTransportError(HTTPStatus.BAD_REQUEST, "Unexpected body length")

        remaining = request.content_length - len(request.body_prefix)
        try:
            async with asyncio.timeout(BODY_TIMEOUT):
                body = request.body_prefix + await reader.readexactly(remaining)
        except asyncio.IncompleteReadError as ex:
            raise LegacyHttpTransportError(HTTPStatus.BAD_REQUEST, "Incomplete HTTP body") from ex
        return body

    @staticmethod
    def _get_source_ip(writer: asyncio.StreamWriter) -> str | None:
        """Extract an IP address from asyncio's peer information."""
        peername = writer.get_extra_info("peername")
        return peername[0] if isinstance(peername, tuple) and peername else None

    @staticmethod
    async def _async_respond(writer: asyncio.StreamWriter, status: HTTPStatus) -> None:
        """Return an empty deterministic response and close the connection."""
        response = (
            f"HTTP/1.1 {status.value} {status.phrase}\r\n"
            "Content-Length: 0\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii")
        try:
            writer.write(response)
            await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
