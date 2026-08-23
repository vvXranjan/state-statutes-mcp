"""Shared test helper for mocking the real network boundary.

Mocks ``urllib.request.urlopen`` as imported by the shared fetch helper
(``state_statutes_mcp.adapters._fetch``) -- the actual network boundary,
not any adapter-internal method such as ``_fetch_text``. Every adapter's
retrieval goes through that boundary once the shared fetch refactor is in
place, so patching here exercises each adapter's real fetch -> parse path.

The rule this module exists to enforce: tests must mock
``urllib.request.urlopen``, never adapter internals.
"""

from __future__ import annotations

import io
from contextlib import contextmanager
from unittest import mock

PATCH_TARGET = "state_statutes_mcp.adapters._fetch.urllib.request.urlopen"


class _FakeResponse(io.BytesIO):
    """A bytes-backed response that also behaves as a context manager,
    matching how ``urllib.request.urlopen`` responses are used."""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


@contextmanager
def mock_urlopen(html_text: str):
    """Serve ``html_text`` (as UTF-8 bytes) for ANY urlopen call.

    Args:
        html_text: The HTML/text to return, regardless of which URL is
            fetched.
    """
    def fake_urlopen(url, timeout=None):
        return _FakeResponse(html_text.encode("utf-8"))

    with mock.patch(PATCH_TARGET, side_effect=fake_urlopen):
        yield


@contextmanager
def mock_urlopen_serving(url_to_html: dict[str, str]):
    """Serve specific URLs from ``url_to_html``; fail on any unexpected URL.

    Args:
        url_to_html: Mapping of exact URL string to the HTML/text to
            serve for it.
    """
    def fake_urlopen(url, timeout=None):
        if url not in url_to_html:
            raise AssertionError(f"Unexpected URL fetched in test: {url!r}")
        return _FakeResponse(url_to_html[url].encode("utf-8"))

    with mock.patch(PATCH_TARGET, side_effect=fake_urlopen):
        yield


@contextmanager
def mock_urlopen_serving_bytes(url_to_bytes: dict[str, bytes]):
    """Serve specific URLs from ``url_to_bytes`` as raw bytes; fail on any
    unexpected URL.

    Identical to :func:`mock_urlopen_serving` but serves the given bytes
    verbatim instead of UTF-8-encoding strings — required for binary
    fixtures (e.g. the PDF documents returned by PDF-family state sources,
    whose raw bytes must reach the adapter unmodified).

    Args:
        url_to_bytes: Mapping of exact URL string to the raw bytes to
            serve for it.
    """
    def fake_urlopen(url, timeout=None):
        if url not in url_to_bytes:
            raise AssertionError(f"Unexpected URL fetched in test: {url!r}")
        return _FakeResponse(url_to_bytes[url])

    with mock.patch(PATCH_TARGET, side_effect=fake_urlopen):
        yield


@contextmanager
def mock_urlopen_error(error: Exception):
    """Simulate a network failure by making urlopen raise ``error``.

    Args:
        error: The exception to raise from urlopen, typically
            ``urllib.error.URLError`` or ``TimeoutError``.
    """
    def fake_urlopen(url, timeout=None):
        raise error

    with mock.patch(PATCH_TARGET, side_effect=fake_urlopen):
        yield