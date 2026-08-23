"""Tests for the shared binary-fetch and PDF-extraction infrastructure.

Two shared helpers are covered:

1. :func:`state_statutes_mcp.adapters._fetch.fetch_bytes` — the binary
   counterpart of ``fetch_url``. It returns raw bytes (never UTF-8
   decoded) and maps network failures to ``AdapterUnavailableError``,
   exactly like ``fetch_url``.

2. :func:`state_statutes_mcp.adapters._pdftext.extract_pdf_text` — the
   generic, state-agnostic PDF decoder. It reads every page in order and
   concatenates the extracted text; unparseable input maps to
   ``AdapterUnavailableError``; a valid PDF with no text returns ``""``
   (whether that is a legitimate stub is a consuming adapter's decision).

The PDF fixture ``tests/fixtures/infra_synthetic_test.pdf`` is a
**synthetic infrastructure test fixture** — a tiny hand-built PDF created
with pypdf's writer for these unit tests only. It is NOT an official
government capture and makes no claim to be one.

Network tests mock the real network boundary
(``urllib.request.urlopen`` as imported by the shared ``_fetch`` helper),
never the helpers themselves.
"""

from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest

from _mock_network import mock_urlopen_error

from state_statutes_mcp.adapters._fetch import fetch_bytes, fetch_url
from state_statutes_mcp.adapters._pdftext import extract_pdf_text
from state_statutes_mcp.core.exceptions import AdapterUnavailableError

# --- SYNTHETIC infrastructure test fixture: a tiny deterministic PDF
# --- built with pypdf's writer for these tests. NOT an official capture.
FIXTURES = Path(__file__).parent / "fixtures"
PDF_BYTES = (FIXTURES / "infra_synthetic_test.pdf").read_bytes()

VALID_URL = "https://example.invalid/statute.pdf"


class TestFetchBytes:
    def test_returns_exact_bytes_unchanged(self) -> None:
        from unittest import mock

        with mock.patch(
            "state_statutes_mcp.adapters._fetch.urllib.request.urlopen",
            return_value=_response(PDF_BYTES),
        ):
            result = fetch_bytes(VALID_URL, what="test PDF")

        assert result == PDF_BYTES
        assert isinstance(result, bytes)

    def test_binary_data_is_not_utf8_decoded(self) -> None:
        from unittest import mock

        # Bytes that are not valid UTF-8 must survive round-trip intact.
        raw = b"\xff\xfe\x00binary\x80payload"
        with mock.patch(
            "state_statutes_mcp.adapters._fetch.urllib.request.urlopen",
            return_value=_response(raw),
        ):
            result = fetch_bytes(VALID_URL, what="test PDF")

        assert result == raw

    def test_url_error_maps_to_adapter_unavailable(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                fetch_bytes(VALID_URL, what="test PDF")

    def test_timeout_maps_to_adapter_unavailable(self) -> None:
        with mock_urlopen_error(TimeoutError("timed out")):
            with pytest.raises(AdapterUnavailableError):
                fetch_bytes(VALID_URL, what="test PDF")

    def test_os_error_maps_to_adapter_unavailable(self) -> None:
        with mock_urlopen_error(OSError("connection refused")):
            with pytest.raises(AdapterUnavailableError):
                fetch_bytes(VALID_URL, what="test PDF")

    def test_fetch_url_unchanged_still_returns_decoded_text(self) -> None:
        # Regression guard: fetch_url must keep returning UTF-8 decoded
        # text while fetch_bytes returns bytes.
        from unittest import mock

        html = "<html><body>hello</body></html>"
        with mock.patch(
            "state_statutes_mcp.adapters._fetch.urllib.request.urlopen",
            return_value=_response(html.encode("utf-8")),
        ):
            result = fetch_url(VALID_URL, what="test page")

        assert result == html
        assert isinstance(result, str)


def _response(data: bytes):
    """A minimal context-manager response object returning ``data``."""
    import io

    class _FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    return _FakeResponse(data)


class TestExtractPdfText:
    def test_extracts_text_from_valid_pdf(self) -> None:
        text = extract_pdf_text(PDF_BYTES)
        assert isinstance(text, str)
        assert "PAGE ONE" in text
        assert "synthetic infrastructure page 1" in text

    def test_multi_page_pdf_preserves_page_order(self) -> None:
        text = extract_pdf_text(PDF_BYTES)
        assert text.find("PAGE ONE") < text.find("PAGE TWO") < text.find("PAGE THREE")

    def test_invalid_pdf_maps_to_adapter_unavailable(self) -> None:
        with pytest.raises(AdapterUnavailableError):
            extract_pdf_text(b"this is definitely not a pdf")

    def test_truncated_pdf_maps_to_adapter_unavailable(self) -> None:
        with pytest.raises(AdapterUnavailableError):
            extract_pdf_text(PDF_BYTES[: len(PDF_BYTES) // 2])

    def test_valid_pdf_with_no_text_returns_empty_string(self) -> None:
        from io import BytesIO

        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        buf = BytesIO()
        writer.write(buf)
        assert extract_pdf_text(buf.getvalue()) == ""