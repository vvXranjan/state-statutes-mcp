"""Tests for OregonAdapter.

Oregon is a chapter-document HTML source (the official Oregon Revised
Statutes at oregonlegislature.gov/bills_laws/ors). Each chapter's page is
``ors{NNN}.html`` where ``{NNN}`` is the chapter's zero-padded numeric
prefix (``1`` -> ``ors001.html``, ``72A`` -> ``ors072A.html``). Sections
are ``{chapter}.{NNN}`` identifiers (e.g. ``1.001``) embedded in their
chapter document, each opened by a heading paragraph
``<p class=MsoNormal>...<b><span ...>NNN.xxx Caption.</span></b>...``.
The section's own amendment history is the final bracketed session-law
string in the core body; repealed sections (e.g. ``1.100``) return with
an empty body and their bracketed history.

Oregon pages are Windows-1252 (latin-1) encoded; the fixtures preserve
the raw bytes and the adapter decodes them as ``windows-1252``.

Title/chapter discovery is BLOCKED BY DESIGN: the ORS title index is
PDF-only, so ``list_titles`` and ``list_chapters`` raise
``AdapterUnavailableError`` directly (see ``docs/research/oregon.md``).

**REAL trimmed fixtures**: the ``or_*`` fixtures are real trimmed
captures of the official host from a Wayback Machine snapshot
(``20260224045708id_``); they are NOT synthetic. ``or_ors004.html`` is
the full real capture; ``or_ors001_trimmed.html`` preserves only a
subset of the chapter's section blocks.

Section-retrieval and section-discovery tests exercise the adapter's real
fetch -> parse path against these fixtures. All tests are fully offline:
the real network boundary (``urllib.request.urlopen``) is mocked, never
adapter internals.
"""

from __future__ import annotations

import io
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pytest

from _mock_network import PATCH_TARGET

from state_statutes_mcp.adapters.oregon.adapter import OregonAdapter
from state_statutes_mcp.core.exceptions import (
    AdapterUnavailableError,
    NormalizationError,
    RefMismatchError,
    RefNotFoundError,
    UnsupportedRefError,
)
from state_statutes_mcp.models.documents import ParsedDocument
from state_statutes_mcp.models.hierarchy import HierarchyLevel
from state_statutes_mcp.models.refs import ChapterRef, SectionRef, TitleRef

# --- REAL trimmed fixtures: captures of the official host from a Wayback
# --- snapshot (20260224045708id_). Raw Windows-1252 bytes preserved.
FIXTURES = Path(__file__).parent / "fixtures"

ORS001_BYTES = (FIXTURES / "or_ors001_trimmed.html").read_bytes()
ORS004_BYTES = (FIXTURES / "or_ors004.html").read_bytes()

BASE = "https://www.oregonlegislature.gov/bills_laws/ors"

ORS001_URL = f"{BASE}/ors001.html"
ORS004_URL = f"{BASE}/ors004.html"


class _FakeResponse(io.BytesIO):
    """A raw-bytes-backed response that behaves as a context manager,
    matching how ``urllib.request.urlopen`` responses are used."""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


@contextmanager
def _serve_bytes(url_to_bytes: dict[str, bytes]):
    """Serve specific URLs from ``url_to_bytes`` (raw bytes); fail on any
    unexpected URL.

    Oregon pages are Windows-1252, so the mock serves raw bytes rather than
    the UTF-8-encoding helper. ``urlopen`` is patched on the shared
    ``urllib.request`` module object, so the adapter's own
    ``urllib.request.urlopen`` call is intercepted too.
    """

    def _target(url):
        return url.full_url if isinstance(url, urllib.request.Request) else url

    def fake_urlopen(url, timeout=None):
        target = _target(url)
        if target not in url_to_bytes:
            raise AssertionError(f"Unexpected URL fetched in test: {target!r}")
        return _FakeResponse(url_to_bytes[target])

    with mock.patch(PATCH_TARGET, side_effect=fake_urlopen):
        yield


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the adapter will map to
    ``RefNotFoundError`` (404) or ``AdapterUnavailableError`` (other)."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


def _title_ref() -> TitleRef:
    return TitleRef(state_code="OR", identifier="1")


def _chapter_ref() -> ChapterRef:
    return ChapterRef(title=_title_ref(), identifier="1")


def _make_ref(section: str) -> SectionRef:
    return SectionRef(chapter=_chapter_ref(), identifier=section)


def _serve_all() -> dict[str, bytes]:
    return {
        ORS001_URL: ORS001_BYTES,
        ORS004_URL: ORS004_BYTES,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert OregonAdapter.__abstractmethods__ == frozenset()
        adapter = OregonAdapter()
        assert adapter.state_code == "OR"
        assert adapter.state_name == "Oregon"


class TestPadIdentifier:
    def test_plain_chapter_zero_pads(self) -> None:
        assert OregonAdapter._pad_identifier("1") == "001"

    def test_three_digit_chapter_unchanged(self) -> None:
        assert OregonAdapter._pad_identifier("161") == "161"

    def test_lettered_chapter_keeps_suffix(self) -> None:
        assert OregonAdapter._pad_identifier("72A") == "072A"

    def test_malformed_identifier_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="expected a numeric"):
            OregonAdapter._pad_identifier("abc")


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = OregonAdapter()

    def test_chapter_ref_url_zero_pads(self) -> None:
        assert self.adapter.build_url(_chapter_ref()) == ORS001_URL

    def test_lettered_chapter_ref_url(self) -> None:
        ref = ChapterRef(
            title=TitleRef(state_code="OR", identifier="72"), identifier="72A"
        )
        assert self.adapter.build_url(ref) == f"{BASE}/ors072A.html"

    def test_section_ref_url_is_chapter_document(self) -> None:
        # Sections are embedded in their chapter document, so the chapter
        # document is the closest real resource.
        assert self.adapter.build_url(_make_ref("1.001")) == ORS001_URL

    def test_title_ref_raises_unsupported(self) -> None:
        # VERIFIED: there is no Oregon title HTML page (index is PDF-only).
        with pytest.raises(UnsupportedRefError, match="cannot address a title"):
            self.adapter.build_url(_title_ref())

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestDiscoveryBlocked:
    def setup_method(self) -> None:
        self.adapter = OregonAdapter()

    def test_list_titles_raises_adapter_unavailable(self) -> None:
        # BLOCKED BY DESIGN: the ORS title index is PDF-only.
        with pytest.raises(AdapterUnavailableError, match="PDF"):
            self.adapter.list_titles()

    def test_list_chapters_raises_adapter_unavailable(self) -> None:
        # BLOCKED BY DESIGN: no HTML chapter listing exists.
        with pytest.raises(AdapterUnavailableError, match="PDF"):
            self.adapter.list_chapters(_title_ref())


class TestListSections:
    def test_returns_sections_from_chapter_document(self) -> None:
        adapter = OregonAdapter()
        with _serve_bytes({ORS001_URL: ORS001_BYTES}):
            sections = adapter.list_sections(_chapter_ref())

        # Repealed 1.100 remains in the document even though the header's
        # chapter list omits it.
        assert [n.identifier for n in sections] == [
            "1.001",
            "1.002",
            "1.020",
            "1.100",
            "1.175",
            "1.212",
        ]
        assert sections[0].name == "State policy for courts."
        assert sections[3].name == "1.100"  # no caption; identifier fallback
        assert all(n.level == HierarchyLevel.SECTION for n in sections)
        assert all(n.ref.chapter == _chapter_ref() for n in sections)

    def test_full_capture_lists_many_sections(self) -> None:
        adapter = OregonAdapter()
        with _serve_bytes({ORS004_URL: ORS004_BYTES}):
            sections = adapter.list_sections(
                ChapterRef(title=_title_ref(), identifier="4")
            )

        assert len(sections) == 24
        assert sections[0].identifier == "4.010"
        assert sections[-1].identifier == "4.410"

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = OregonAdapter()
        with mock.patch(PATCH_TARGET, side_effect=_raise(_http_error(ORS001_URL))):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_sections(_chapter_ref())

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = OregonAdapter()
        with _serve_bytes({ORS001_URL: b"<html><body>none</body></html>"}):
            with pytest.raises(AdapterUnavailableError, match="no usable section"):
                adapter.list_sections(_chapter_ref())

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = OregonAdapter()
        with mock.patch(
            PATCH_TARGET,
            side_effect=_raise(urllib.error.URLError("simulated network failure")),
        ):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_sections(_chapter_ref())


def _raise(exc: Exception):
    def _side_effect(url, timeout=None):
        raise exc

    return _side_effect


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = OregonAdapter()

    def test_full_retrieval_with_amendment(self) -> None:
        ref = _make_ref("1.001")
        with _serve_bytes(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "ORS 1.001"
        assert section.citation.state_code == "OR"
        assert section.ref == ref
        assert section.heading == "State policy for courts."
        assert section.text.startswith("The Legislative Assembly hereby declares")
        assert section.amendment_notes == "[1981 s.s. c.3 §1]"
        assert section.status.value == "unknown"
        assert section.source_url == ORS001_URL
        assert section.retrieved_at is not None

    def test_long_amendment_is_sections_own_history(self) -> None:
        # VERIFIED: 1.002's amendment is its own full session history (not
        # the history of a note it references), and the note references
        # (Sec. 3 / Sec. 4 / [2025 c.88 §3]) stay in the body.
        ref = _make_ref("1.002")
        with _serve_bytes({ORS001_URL: ORS001_BYTES}):
            section = self.adapter.retrieve_section(ref)

        assert section.amendment_notes == (
            "[1959 c.552 §1; 1973 c.484 §1; 1981 s.s. c.1 §3; 1995 c.221 §1; "
            "1995 c.781 §2; 1999 c.787 §1; 2001 c.911 §1; 2007 c.129 §1; "
            "2009 c.47 §1; 2009 c.484 §1; 2009 c.885 §37a; 2013 c.2 §3; "
            "2013 c.685 §1; 2014 c.76 §1; 2021 c.199 §1; 2022 c.68 §8; "
            "2023 c.133 §1; 2025 c.88 §1; 2025 c.256 §6]"
        )
        assert section.text.startswith("(1) The Supreme Court is the")
        assert "Sec. 4." in section.text
        assert "[2025 c.88 §3]" in section.text

    def test_no_amendment_section(self) -> None:
        # VERIFIED: 1.020 genuinely carries no bracketed history.
        ref = _make_ref("1.020")
        with _serve_bytes({ORS001_URL: ORS001_BYTES}):
            section = self.adapter.retrieve_section(ref)

        assert section.heading == "Contempt punishment."
        assert section.amendment_notes is None
        assert section.text.startswith("For")
        assert "effectual exercise of the powers" in section.text

    def test_repealed_section_empty_body_with_amendment(self) -> None:
        # VERIFIED: 1.100 is repealed -- it remains in the document with no
        # body and a bracketed repeal history.
        ref = _make_ref("1.100")
        with _serve_bytes({ORS001_URL: ORS001_BYTES}):
            section = self.adapter.retrieve_section(ref)

        assert section.heading is None
        assert section.text == ""
        assert section.amendment_notes == "[Repealed by 1983 c.763 §9]"
        assert section.status.value == "unknown"

    def test_full_capture_renumbered_section(self) -> None:
        # VERIFIED: 4.410 is renumbered with no body and its bracketed
        # history.
        ref = SectionRef(
            chapter=ChapterRef(title=_title_ref(), identifier="4"),
            identifier="4.410",
        )
        with _serve_bytes({ORS004_URL: ORS004_BYTES}):
            section = self.adapter.retrieve_section(ref)

        assert section.text == ""
        assert section.amendment_notes == (
            "[Amended by 1967 c.532 §5; 1967 c.533 §15; 1971 c.777 §5; "
            "renumbered 3.238]"
        )

    def test_oath_body_preserved(self) -> None:
        # VERIFIED: 1.212's oath text is preserved verbatim.
        ref = _make_ref("1.212")
        with _serve_bytes({ORS001_URL: ORS001_BYTES}):
            section = self.adapter.retrieve_section(ref)

        assert section.heading == "Oath of office for judges."
        assert "I, ____________," in section.text
        assert section.amendment_notes == "[2003 c.518 §6]"

    def test_missing_section_raises_ref_not_found(self) -> None:
        ref = _make_ref("1.999")
        with _serve_bytes({ORS001_URL: ORS001_BYTES}):
            with pytest.raises(RefNotFoundError, match="contains no section"):
                self.adapter.retrieve_section(ref)

    def test_404_maps_to_ref_not_found(self) -> None:
        ref = _make_ref("1.001")
        with mock.patch(PATCH_TARGET, side_effect=_raise(_http_error(ORS001_URL))):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        ref = _make_ref("1.001")
        with mock.patch(
            PATCH_TARGET,
            side_effect=_raise(urllib.error.URLError("simulated network failure")),
        ):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)


class TestParseEdgeCases:
    def setup_method(self) -> None:
        self.adapter = OregonAdapter()

    def test_empty_body_no_amendment_raises_normalization_error(self) -> None:
        ref = _make_ref("1.001")
        html = (
            b"<html><body>"
            b"<p class=MsoNormal><b><span style='x'> 1.001 Caption.</span></b></p>"
            b"</body></html>"
        )
        with _serve_bytes({ORS001_URL: html}):
            with pytest.raises(NormalizationError, match="body text was empty"):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = OregonAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("1.001")
        parsed = ParsedDocument(
            raw_citation="ORS 1.001",
            heading="State policy for courts.",
            text="The Legislative Assembly ...",
            amendment_notes="[1981 s.s. c.3 §1]",
            source_url=ORS001_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "ORS 1.001"
        assert section.citation.state_code == "OR"
        assert section.heading == "State policy for courts."
        assert section.amendment_notes == "[1981 s.s. c.3 §1]"
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="NV", identifier="x"), identifier="220"
            ),
            identifier="1.001",
        )
        parsed = ParsedDocument(
            raw_citation="ORS 1.001",
            text="Some text.",
        )
        with pytest.raises(NormalizationError, match="expected 'OR'"):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("1.001")
        parsed = ParsedDocument(
            raw_citation="ORS 1.002",
            text="Some other section's text.",
        )
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, ref)