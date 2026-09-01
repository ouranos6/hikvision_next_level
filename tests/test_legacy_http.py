"""Raw-socket tests for the isolated legacy Hikvision HTTP listener."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from custom_components.hikvision_next import legacy_http
from custom_components.hikvision_next.events import (
    HikvisionEventPayloadParser,
    ParsedEventPayload,
)
from custom_components.hikvision_next.legacy_http import HikvisionLegacyHttpListener

FIXTURES = Path(__file__).parent / "fixtures" / "ISAPI" / "EventNotificationAlert"


class RecordingProcessor:
    """Record the normalized events passed from the legacy transport."""

    def __init__(self) -> None:
        """Initialize the recording processor."""
        self.calls = []

    async def async_process(self, event, source_ip: str | None, image: bytes | None = None) -> None:
        """Record a processed event."""
        self.calls.append((event, source_ip, image))


class CapturingPayloadParser(HikvisionEventPayloadParser):
    """Keep the parsed payload available to assert JPEG retention."""

    payload: ParsedEventPayload | None = None

    def parse(self, body: bytes, content_type: str | None) -> ParsedEventPayload:
        """Parse and retain the payload."""
        self.payload = super().parse(body, content_type)
        return self.payload


def event_xml(name: str) -> bytes:
    """Load a captured Hikvision event notification."""
    return (FIXTURES / f"{name}.xml").read_bytes()


async def start_listener(
    payload_parser: HikvisionEventPayloadParser | None = None,
) -> tuple[HikvisionLegacyHttpListener, RecordingProcessor]:
    """Start an ephemeral listener with a recording processor."""
    processor = RecordingProcessor()
    listener = HikvisionLegacyHttpListener(
        hass=None,
        host="127.0.0.1",
        port=0,
        payload_parser=payload_parser,
        processor=processor,
    )
    await listener.async_start()
    return listener, processor


async def send_raw(listener: HikvisionLegacyHttpListener, request: bytes) -> bytes:
    """Send one connection-scoped raw HTTP request."""
    reader, writer = await asyncio.open_connection("127.0.0.1", listener.port)
    writer.write(request)
    await writer.drain()
    response = await reader.read()
    writer.close()
    await writer.wait_closed()
    return response


def post_request(
    body: bytes,
    content_type: str = "application/xml",
    version: str = "HTTP/1.1",
    host: str | None = None,
) -> bytes:
    """Build the only valid listener route, optionally omitting Host."""
    headers = [
        f"POST /api/hikvision {version}",
        f"Content-Type: {content_type}",
        f"Content-Length: {len(body)}",
    ]
    if host:
        headers.append(f"Host: {host}")
    return ("\r\n".join(headers) + "\r\n\r\n").encode() + body


@pytest.mark.parametrize(
    ("version", "host"),
    [("HTTP/1.1", None), ("HTTP/1.0", None), ("HTTP/1.1", "home-assistant.local")],
)
async def test_legacy_listener_accepts_hikvision_requests_without_host(
    version: str, host: str | None
) -> None:
    """HTTP/1.0 and HTTP/1.1 notifications work whether Host is present or not."""
    listener, processor = await start_listener()
    try:
        response = await send_raw(listener, post_request(event_xml("ipc_1_fielddetection"), version=version, host=host))

        assert response.startswith(b"HTTP/1.1 200 OK")
        assert len(processor.calls) == 1
        assert processor.calls[0][0].event_id == "fielddetection"
        assert processor.calls[0][1] == "127.0.0.1"
    finally:
        await listener.async_stop()


async def test_legacy_listener_accepts_xml_with_wrong_mime_type() -> None:
    """The phase 2 XML sniffing is reused by the legacy transport."""
    listener, processor = await start_listener()
    try:
        response = await send_raw(
            listener,
            post_request(
                event_xml("fielddetection_vehicle"),
                content_type="application/x-www-form-urlencoded",
            ),
        )

        assert response.startswith(b"HTTP/1.1 200 OK")
        assert processor.calls[0][0].detection_target == "vehicle"
    finally:
        await listener.async_stop()


async def test_legacy_listener_acknowledges_unrecognized_event_payload() -> None:
    """A valid HTTP notification keeps the legacy 200 retry-avoidance policy."""
    listener, processor = await start_listener()
    try:
        response = await send_raw(
            listener,
            post_request(b"<?xml version=\"1.0\"?><UnknownNotification />"),
        )

        assert response.startswith(b"HTTP/1.1 200 OK")
        assert listener.parse_errors == 1
        assert not processor.calls
    finally:
        await listener.async_stop()


async def test_legacy_listener_reuses_multipart_parser_and_retains_jpeg() -> None:
    """The transport passes multipart bytes unchanged to the phase 2 parser."""
    boundary = "hikvision-boundary"
    jpeg = b"\xff\xd8\xffevent-image\xff\xd9"
    body = b"\r\n".join(
        [
            f"--{boundary}".encode(),
            b"Content-Type: image/jpeg",
            b"",
            jpeg,
            f"--{boundary}".encode(),
            b"Content-Type: application/xml",
            b"",
            event_xml("ipc_1_fielddetection"),
            f"--{boundary}--".encode(),
            b"",
        ]
    )
    payload_parser = CapturingPayloadParser()
    listener, processor = await start_listener(payload_parser)
    try:
        response = await send_raw(
            listener, post_request(body, content_type=f"multipart/form-data; boundary={boundary}")
        )

        assert response.startswith(b"HTTP/1.1 200 OK")
        assert len(processor.calls) == 1
        assert payload_parser.payload is not None
        assert payload_parser.payload.image == jpeg
        assert processor.calls[0][2] == jpeg
    finally:
        await listener.async_stop()


@pytest.mark.parametrize(
    ("raw_request", "status"),
    [
        (b"GET /api/hikvision HTTP/1.1\r\nContent-Length: 0\r\n\r\n", b"405 Method Not Allowed"),
        (b"POST /other HTTP/1.1\r\nContent-Length: 0\r\n\r\n", b"404 Not Found"),
        (
            b"POST /api/hikvision HTTP/1.1\r\nContent-Length: banana\r\n\r\n",
            b"400 Bad Request",
        ),
        (
            b"POST /api/hikvision HTTP/1.1\r\nTransfer-Encoding: chunked\r\n"
            b"Content-Length: 0\r\n\r\n",
            b"501 Not Implemented",
        ),
    ],
)
async def test_legacy_listener_rejects_unsupported_http_transport(
    raw_request: bytes, status: bytes
) -> None:
    """Only the narrow Hikvision POST protocol is accepted."""
    listener, processor = await start_listener()
    try:
        response = await send_raw(listener, raw_request)

        assert status in response
        assert not processor.calls
    finally:
        await listener.async_stop()


async def test_legacy_listener_rejects_oversized_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Header size is bounded before a complete untrusted request is accepted."""
    monkeypatch.setattr(legacy_http, "MAX_HEADER_SIZE", 64)
    listener, processor = await start_listener()
    try:
        request = b"POST /api/hikvision HTTP/1.1\r\nX-Long: " + (b"x" * 128) + b"\r\n\r\n"
        response = await send_raw(listener, request)

        assert b"431 Request Header Fields Too Large" in response
        assert not processor.calls
    finally:
        await listener.async_stop()


async def test_legacy_listener_rejects_oversized_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """Content-Length is checked before a large body is read."""
    monkeypatch.setattr(legacy_http, "MAX_PAYLOAD_SIZE", 8)
    listener, processor = await start_listener()
    try:
        response = await send_raw(listener, post_request(b"012345678"))

        assert b"413 Request Entity Too Large" in response
        assert not processor.calls
    finally:
        await listener.async_stop()


async def test_legacy_listener_rejects_incomplete_body() -> None:
    """A connection ending before Content-Length is fully received returns 400."""
    listener, processor = await start_listener()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", listener.port)
        writer.write(
            b"POST /api/hikvision HTTP/1.1\r\nContent-Length: 500\r\n"
            b"Content-Type: application/xml\r\n\r\n<EventNotificationAlert/>"
        )
        await writer.drain()
        writer.write_eof()
        response = await reader.read()
        writer.close()
        await writer.wait_closed()

        assert b"400 Bad Request" in response
        assert not processor.calls
    finally:
        await listener.async_stop()


async def test_legacy_listener_start_stop_start_reuses_port() -> None:
    """Stopping releases the socket for a subsequent start."""
    listener, _ = await start_listener()
    port = listener.port
    await listener.async_stop()

    listener = HikvisionLegacyHttpListener(hass=None, host="127.0.0.1", port=port, processor=RecordingProcessor())
    try:
        await listener.async_start()
        assert listener.is_running
    finally:
        await listener.async_stop()


async def test_legacy_listener_processes_concurrent_notifications() -> None:
    """Each concurrent connection retains independent request state."""
    listener, processor = await start_listener()
    try:
        request = post_request(event_xml("ipc_1_fielddetection"))
        responses = await asyncio.gather(*(send_raw(listener, request) for _ in range(3)))

        assert all(response.startswith(b"HTTP/1.1 200 OK") for response in responses)
        assert len(processor.calls) == 3
        assert listener.events_processed == 3
    finally:
        await listener.async_stop()
