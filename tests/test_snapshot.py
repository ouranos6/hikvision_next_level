"""Tests for Phase 6: Automatic high-resolution snapshots.

These tests validate ``ISAPIClient.get_camera_image`` resolution-parameter
logic without requiring a full HA integration setup.  Uses ``_run_async``
pattern from ``test_capabilities.py`` for Windows compatibility.
"""

from unittest.mock import MagicMock

import pytest
import pytest_socket

# Fixture overrides – mirror test_capabilities.py so sync tests run on Windows
@pytest.fixture(autouse=True)
def enable_event_loop_debug():
    pass


@pytest.fixture(autouse=True)
def verify_cleanup():
    pass


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations():
    yield


@pytest.fixture(autouse=True)
def expected_lingering_tasks():
    return True


@pytest.fixture(autouse=True)
def expected_lingering_timers():
    return True


def _run_async(coro):
    """Run *coro* with sockets temporarily unblocked."""
    import asyncio

    pytest_socket.enable_socket()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)
        pytest_socket.disable_socket()


# Imports after fixture overrides
from custom_components.hikvision_next.isapi import ISAPIClient
from custom_components.hikvision_next.isapi.models import CameraStreamInfo
from tests.conftest import TEST_HOST

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _MockRequestBytes:
    """Mock for ISAPIClient.request_bytes that captures call args.

    Supports sequential responses for testing retry and fallback logic.
    """

    def __init__(self, responses=None):
        if responses is None:
            self._responses: list[bytes] = []
        elif isinstance(responses, (bytes, bytearray)):
            self._responses = [bytes(responses)]
        else:
            self._responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, method: str, full_url: str, **kwargs):
        self.calls.append(
            {
                "method": method,
                "url": full_url,
                "params": kwargs.get("params", {}),
            }
        )
        data = self._responses.pop(0) if self._responses else b"image data"

        async def _async_gen():
            yield data

        return _async_gen()


def _make_isapi() -> ISAPIClient:
    """Create ISAPIClient with auth bypassed."""
    isapi = ISAPIClient(
        host=TEST_HOST,
        username="u1",
        password="***",
    )
    isapi._auth_method = MagicMock()
    return isapi


def _make_stream(
    width: int = 1920,
    height: int = 1080,
    stream_id: int = 101,
    alternate_url: bool = False,
) -> CameraStreamInfo:
    return CameraStreamInfo(
        id=stream_id,
        name="Main",
        type_id=1,
        type="Main Stream",
        enabled=True,
        codec="H.264",
        width=width,
        height=height,
        audio=False,
        use_alternate_picture_url=alternate_url,
    )


_DEVICE_ERROR_XML = (
    b"<?xml version='1.0'?>"
    b"<ResponseStatus><statusCode>3</statusCode></ResponseStatus>"
)

_BAD_XML_ERROR_XML = (
    b"<?xml version='1.0'?>"
    b"<ResponseStatus><statusCode>6</statusCode></ResponseStatus>"
)


# ---------------------------------------------------------------------------
# _has_known_resolution static method
# ---------------------------------------------------------------------------


def test_has_known_resolution_positive():
    """Valid non-zero resolution returns True."""
    stream = _make_stream(1920, 1080)
    assert ISAPIClient._has_known_resolution(stream) is True


def test_has_known_resolution_zero():
    """Zero-width and zero-height returns False."""
    stream = _make_stream(0, 0)
    assert ISAPIClient._has_known_resolution(stream) is False


def test_has_known_resolution_partial():
    """One dimension zero returns False."""
    stream = _make_stream(1920, 0)
    assert ISAPIClient._has_known_resolution(stream) is False


def test_has_known_resolution_none():
    """None dimensions return False."""
    stream = CameraStreamInfo(
        id=101,
        name="Main",
        type_id=1,
        type="Main",
        enabled=True,
        codec="H.264",
        width=None,
        height=None,
        audio=False,
    )
    assert ISAPIClient._has_known_resolution(stream) is False


def test_has_known_resolution_invalid_string():
    """Malformed cached dimensions fall back to the legacy snapshot request."""
    stream = _make_stream("invalid", "1080")
    assert ISAPIClient._has_known_resolution(stream) is False


# ---------------------------------------------------------------------------
# Resolution params are sent when stream has known resolution
# ---------------------------------------------------------------------------


def test_snapshot_known_resolution_1920():
    """1920x1080 stream requests snapshot with matching resolution params."""
    isapi = _make_isapi()
    mock = _MockRequestBytes(b"binary image data")
    isapi.request_bytes = mock
    stream = _make_stream(1920, 1080)

    result = _run_async(isapi.get_camera_image(stream))

    assert result == b"binary image data"
    assert len(mock.calls) == 1
    assert mock.calls[0]["params"] == {"videoResolutionWidth": 1920, "videoResolutionHeight": 1080}


def test_snapshot_known_resolution_3840():
    """3840x2160 stream requests snapshot with matching resolution params."""
    isapi = _make_isapi()
    mock = _MockRequestBytes(b"binary image data")
    isapi.request_bytes = mock
    stream = _make_stream(3840, 2160)

    result = _run_async(isapi.get_camera_image(stream))

    assert result == b"binary image data"
    assert len(mock.calls) == 1
    assert mock.calls[0]["params"] == {"videoResolutionWidth": 3840, "videoResolutionHeight": 2160}


# ---------------------------------------------------------------------------
# No resolution params when stream resolution is unknown
# ---------------------------------------------------------------------------


def test_snapshot_unknown_resolution_no_params():
    """Stream with zero resolution should not send resolution params."""
    isapi = _make_isapi()
    mock = _MockRequestBytes(b"binary image data")
    isapi.request_bytes = mock
    stream = _make_stream(0, 0)

    result = _run_async(isapi.get_camera_image(stream))

    assert result == b"binary image data"
    assert len(mock.calls) == 1
    assert mock.calls[0]["params"] == {}


def test_snapshot_invalid_resolution_no_params():
    """A non-numeric resolution must not prevent a legacy snapshot request."""
    isapi = _make_isapi()
    mock = _MockRequestBytes(b"binary image data")
    isapi.request_bytes = mock
    stream = _make_stream("invalid", "1080")

    result = _run_async(isapi.get_camera_image(stream))

    assert result == b"binary image data"
    assert mock.calls[0]["params"] == {}


# ---------------------------------------------------------------------------
# Device Error fallback (statusCode 3)
# ---------------------------------------------------------------------------


def test_snapshot_device_error_fallback():
    """XML error response with statusCode 3 falls back to legacy request."""
    isapi = _make_isapi()
    mock = _MockRequestBytes([_DEVICE_ERROR_XML, _DEVICE_ERROR_XML, _DEVICE_ERROR_XML, b"binary image data"])
    isapi.request_bytes = mock
    stream = _make_stream(1920, 1080)

    result = _run_async(isapi.get_camera_image(stream))

    assert result == b"binary image data"
    # First 3 calls are retries with resolution params
    for i in range(3):
        assert mock.calls[i]["params"] == {"videoResolutionWidth": 1920, "videoResolutionHeight": 1080}
    # 4th call is the fallback (use_resolution=False) → no resolution params
    assert mock.calls[3]["params"] == {}


# ---------------------------------------------------------------------------
# Small explicit width/height → no resolution params
# ---------------------------------------------------------------------------


def test_snapshot_explicit_small_width_no_params():
    """When explicit width <= 100 is provided, no resolution params sent."""
    isapi = _make_isapi()
    mock = _MockRequestBytes(b"binary image data")
    isapi.request_bytes = mock
    stream = _make_stream(1920, 1080)

    result = _run_async(isapi.get_camera_image(stream, width=50, height=50))

    assert result == b"binary image data"
    assert mock.calls[0]["params"] == {}


# ---------------------------------------------------------------------------
# NVR alternate URL
# ---------------------------------------------------------------------------


def test_snapshot_nvr_alternate_url():
    """NVR proxy camera uses ContentMgmt/StreamingProxy URL."""
    isapi = _make_isapi()
    mock = _MockRequestBytes(b"binary image data")
    isapi.request_bytes = mock
    stream = _make_stream(3840, 2160, stream_id=101, alternate_url=True)

    result = _run_async(isapi.get_camera_image(stream))

    assert result == b"binary image data"
    assert "/ContentMgmt/StreamingProxy/channels/101/picture" in mock.calls[0]["url"]


# ---------------------------------------------------------------------------
# Bad XML Content (statusCode 6) switches to alternate URL
# ---------------------------------------------------------------------------


def test_snapshot_bad_xml_switches_to_alternate_url():
    """statusCode 6 triggers switch to alternate picture URL."""
    isapi = _make_isapi()
    mock = _MockRequestBytes([_BAD_XML_ERROR_XML, b"binary image data"])
    isapi.request_bytes = mock
    stream = _make_stream(1920, 1080, stream_id=101)

    result = _run_async(isapi.get_camera_image(stream))

    assert result == b"binary image data"
    # First call: regular URL with resolution params
    assert "/Streaming/channels/101/picture" in mock.calls[0]["url"]
    assert mock.calls[0]["params"] == {"videoResolutionWidth": 1920, "videoResolutionHeight": 1080}
    # Second call: alternate URL (same resolution params passed through)
    assert "/ContentMgmt/StreamingProxy/channels/101/picture" in mock.calls[1]["url"]
    assert stream.use_alternate_picture_url is True


# ---------------------------------------------------------------------------
# Default URL (no resolution params sent) uses Streaming URL
# ---------------------------------------------------------------------------


def test_snapshot_default_url():
    """Default camera uses Streaming/channels URL."""
    isapi = _make_isapi()
    mock = _MockRequestBytes(b"binary image data")
    isapi.request_bytes = mock
    stream = _make_stream(1920, 1080, stream_id=101, alternate_url=False)

    result = _run_async(isapi.get_camera_image(stream))

    assert result == b"binary image data"
    assert "/Streaming/channels/101/picture" in mock.calls[0]["url"]
