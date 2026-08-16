"""Tests for NorthCarolinaAdapter.

North Carolina is a per-section HTML source (the Family A model): the
official General Statutes of North Carolina at ncleg.gov. Each chapter's
section listing is ``/Laws/GeneralStatuteSections/Chapter{ch}`` (e.g.
``Chapter15``, ``Chapter15A``), and each section has ONE static HTML
document at
``/EnactedLegislation/Statutes/HTML/BySection/Chapter_{ch}/GS_{file}.html``
where ``{file}`` is the citation with spaces replaced by underscores
(``15-1`` -> ``GS_15-1.html``, ``15-10.1`` -> ``GS_15-10.1.html``, and a
range ``15-2 through 15-3`` -> ``GS_15-2_through_15-3.html``).
``SectionRef.identifier`` is the full ``{ch}-{sec}`` citation (e.g.
``"15-1"``, ``"15-2 through 15-3"``). History is an inline parenthetical
at the end of the body; repealed/reserved sections are catchline-only
documents returned with empty text and the repeal/reservation note as the
heading.

North Carolina section documents are served in two encodings (UTF-8 with
``&sect;`` entities and Windows-1252 with literal bytes); the fixtures
preserve the raw bytes and the adapter decodes each per its declared
charset.

Title/chapter discovery is BLOCKED BY DESIGN: the modern G.S. has no
title hierarchy, so ``list_titles`` and ``list_chapters`` raise
``AdapterUnavailableError`` directly (see ``docs/research/north_carolina.md``).

**REAL trimmed fixtures**: the ``nc_*`` fixtures are real trimmed captures
of the official host from Wayback Machine snapshots (see
``docs/research/north_carolina.md``); they are NOT synthetic. The
chapter-discovery fixtures preserve the real page header plus a contiguous
subset of the real section rows; the section-document fixtures are the
full real captures.

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

from state_statutes_mcp.adapters.north_carolina.adapter import NorthCarolinaAdapter
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

# --- REAL trimmed fixtures: captures of the official host from Wayback
# --- Machine snapshots (see docs/research/north_carolina.md). Raw bytes
# --- preserved (both UTF-8 and Windows-1252 documents).
FIXTURES = Path(__file__).parent / "fixtures"

CH15_HTML = (FIXTURES / "nc_ch15_trimmed.html").read_bytes()
CH15A_HTML = (FIXTURES / "nc_ch15a_trimmed.html").read_bytes()
SEC15_1_BYTES = (FIXTURES / "nc_section_15-1.html").read_bytes()
SEC15_9_BYTES = (FIXTURES / "nc_section_15-9.html").read_bytes()
SEC15_RANGE_BYTES = (FIXTURES / "nc_section_15-2_through_15-3.html").read_bytes()
SEC15_10_1_BYTES = (FIXTURES / "nc_section_15-10.1.html").read_bytes()
SEC15A_101_BYTES = (FIXTURES / "nc_section_15A-101.html").read_bytes()
SEC15A_RESERVED_BYTES = (
    FIXTURES / "nc_section_15A-1_through_15A-100.html"
).read_bytes()

BASE = "https://www.ncleg.gov"

CH15_URL = f"{BASE}/Laws/GeneralStatuteSections/Chapter15"
CH15A_URL = f"{BASE}/Laws/GeneralStatuteSections/Chapter15A"


def _section_url(chapter: str, file_stem: str) -> str:
    return (
        f"{BASE}/EnactedLegislation/Statutes/HTML/BySection/"
        f"Chapter_{chapter}/GS_{file_stem}.html"
    )


SEC15_1_URL = _section_url("15", "15-1")
SEC15_9_URL = _section_url("15", "15-9")
SEC15_RANGE_URL = _section_url("15", "15-2_through_15-3")
SEC15_10_1_URL = _section_url("15", "15-10.1")
SEC15A_101_URL = _section_url("15A", "15A-101")
SEC15A_RESERVED_URL = _section_url("15A", "15A-1_through_15A-100")


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

    North Carolina section documents are served in two encodings, so the
    mock serves raw bytes rather than the UTF-8-encoding helper.
    ``urlopen`` is patched on the shared ``urllib.request`` module object,
    so the adapter's own ``urllib.request.urlopen`` call is intercepted
    too.
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


def _raise(exc: Exception):
    def _side_effect(url, timeout=None):
        raise exc

    return _side_effect


def _title_ref() -> TitleRef:
    return TitleRef(state_code="NC", identifier="15")


def _chapter_ref() -> ChapterRef:
    return ChapterRef(title=_title_ref(), identifier="15")


def _chapter_ref_15a() -> ChapterRef:
    return ChapterRef(title=_title_ref(), identifier="15A")


def _make_ref(section: str) -> SectionRef:
    return SectionRef(chapter=_chapter_ref(), identifier=section)


def _serve_all() -> dict[str, bytes]:
    return {
        CH15_URL: CH15_HTML,
        CH15A_URL: CH15A_HTML,
        SEC15_1_URL: SEC15_1_BYTES,
        SEC15_9_URL: SEC15_9_BYTES,
        SEC15_RANGE_URL: SEC15_RANGE_BYTES,
        SEC15_10_1_URL: SEC15_10_1_BYTES,
        SEC15A_101_URL: SEC15A_101_BYTES,
        SEC15A_RESERVED_URL: SEC15A_RESERVED_BYTES,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert NorthCarolinaAdapter.__abstractmethods__ == frozenset()
        adapter = NorthCarolinaAdapter()
        assert adapter.state_code == "NC"
        assert adapter.state_name == "North Carolina"


class TestCharsetDetection:
    def test_declared_utf8(self) -> None:
        assert (
            NorthCarolinaAdapter._detect_charset(
                b'<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />'
            )
            == "utf-8"
        )

    def test_declared_windows1252(self) -> None:
        assert (
            NorthCarolinaAdapter._detect_charset(
                b'<meta http-equiv=Content-Type content="text/html; charset=windows-1252">'
            )
            == "windows-1252"
        )

    def test_no_declaration_defaults_to_utf8(self) -> None:
        assert NorthCarolinaAdapter._detect_charset(b"<html><head></head>") == "utf-8"


class TestCaptionFromCatchline:
    def test_plain_identifier_caption(self) -> None:
        assert (
            NorthCarolinaAdapter._caption_from_catchline(
                "§ 15-1.  Statute of limitations for misdemeanors.", "15-1"
            )
            == "Statute of limitations for misdemeanors."
        )

    def test_range_identifier_caption(self) -> None:
        assert (
            NorthCarolinaAdapter._caption_from_catchline(
                "§§ 15-2 through 15-3.  Repealed by Session Laws 1973, c. 1286, s. 26.",
                "15-2 through 15-3",
            )
            == "Repealed by Session Laws 1973, c. 1286, s. 26."
        )

    def test_decimal_identifier_caption(self) -> None:
        assert (
            NorthCarolinaAdapter._caption_from_catchline(
                "§ 15-10.1.  Detainer; purpose; manner of use.", "15-10.1"
            )
            == "Detainer; purpose; manner of use."
        )

    def test_mismatched_identifier_returns_none(self) -> None:
        assert (
            NorthCarolinaAdapter._caption_from_catchline("§ 15-2. Other.", "15-1")
            is None
        )

    def test_no_caption_returns_none(self) -> None:
        assert NorthCarolinaAdapter._caption_from_catchline("§ 15-1.", "15-1") is None


class TestStripTrailingParenthetical:
    def test_nested_parenthetical_lifted(self) -> None:
        body, amendment = NorthCarolinaAdapter._strip_trailing_parenthetical(
            "(5) G.S. 14-318.6.  (1826, c. 11; s. 17.8.(a); s. 2(a).)"
        )
        assert body == "(5) G.S. 14-318.6."
        assert amendment == "(1826, c. 11; s. 17.8.(a); s. 2(a).)"

    def test_no_trailing_parenthetical(self) -> None:
        body, amendment = NorthCarolinaAdapter._strip_trailing_parenthetical(
            "(a) Some body text."
        )
        assert body == "(a) Some body text."
        assert amendment is None

    def test_leading_parenthetical_is_not_lifted(self) -> None:
        # Only a TRAILING balanced parenthetical is lifted; an interior
        # balanced pair stays in the body.
        body, amendment = NorthCarolinaAdapter._strip_trailing_parenthetical(
            "x (a (b)). y"
        )
        assert body == "x (a (b)). y"
        assert amendment is None


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = NorthCarolinaAdapter()

    def test_chapter_ref_url(self) -> None:
        assert self.adapter.build_url(_chapter_ref()) == CH15_URL

    def test_lettered_chapter_ref_url(self) -> None:
        assert self.adapter.build_url(_chapter_ref_15a()) == CH15A_URL

    def test_section_ref_url_plain(self) -> None:
        assert self.adapter.build_url(_make_ref("15-1")) == SEC15_1_URL

    def test_section_ref_url_decimal(self) -> None:
        # VERIFIED: the decimal point is preserved in the file name.
        assert self.adapter.build_url(_make_ref("15-10.1")) == SEC15_10_1_URL

    def test_section_ref_url_range_replaces_spaces_with_underscores(self) -> None:
        # VERIFIED: a range lives in one GS_{a}_through_{b}.html document.
        assert self.adapter.build_url(_make_ref("15-2 through 15-3")) == SEC15_RANGE_URL

    def test_lettered_chapter_section_ref_url(self) -> None:
        assert (
            self.adapter.build_url(
                SectionRef(chapter=_chapter_ref_15a(), identifier="15A-101")
            )
            == SEC15A_101_URL
        )

    def test_title_ref_raises_unsupported(self) -> None:
        # BLOCKED BY DESIGN: the modern G.S. has no title hierarchy.
        with pytest.raises(UnsupportedRefError, match="no title hierarchy"):
            self.adapter.build_url(_title_ref())

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestDiscoveryBlocked:
    def setup_method(self) -> None:
        self.adapter = NorthCarolinaAdapter()

    def test_list_titles_raises_adapter_unavailable(self) -> None:
        # BLOCKED BY DESIGN: no title hierarchy in the modern G.S.
        with pytest.raises(AdapterUnavailableError, match="no title hierarchy"):
            self.adapter.list_titles()

    def test_list_chapters_raises_adapter_unavailable(self) -> None:
        # BLOCKED BY DESIGN: no title to anchor chapters under.
        with pytest.raises(AdapterUnavailableError, match="no title hierarchy"):
            self.adapter.list_chapters(_title_ref())


class TestListSections:
    def test_returns_sections_from_chapter_page(self) -> None:
        adapter = NorthCarolinaAdapter()
        with _serve_bytes({CH15_URL: CH15_HTML}):
            sections = adapter.list_sections(_chapter_ref())

        # The trimmed fixture preserves the first 20 section rows verbatim.
        assert [n.identifier for n in sections] == [
            "15-1",
            "15-2 through 15-3",
            "15-4",
            "15-4.1 through 15-5.1",
            "15-5.2",
            "15-5.3 through 15-5.4",
            "15-6",
            "15-6.1",
            "15-6.2",
            "15-6.3",
            "15-7",
            "15-8",
            "15-9",
            "15-10",
            "15-10.1",
            "15-10.2",
            "15-10.3",
            "15-10.4",
            "15-11",
            "15-11.1",
        ]
        assert sections[0].name == "Statute of limitations for misdemeanors."
        # VERIFIED: a repealed range lists with the range citation and the
        # repeal note as the name.
        assert sections[1].identifier == "15-2 through 15-3"
        assert sections[1].name == (
            "Repealed by Session Laws 1973, c. 1286, s. 26."
        )
        assert sections[14].identifier == "15-10.1"
        assert sections[14].name == "Detainer; purpose; manner of use."
        assert all(n.level == HierarchyLevel.SECTION for n in sections)
        assert all(n.ref.chapter == _chapter_ref() for n in sections)

    def test_lettered_chapter_page_lists_ranges_and_decimals(self) -> None:
        adapter = NorthCarolinaAdapter()
        with _serve_bytes({CH15A_URL: CH15A_HTML}):
            sections = adapter.list_sections(_chapter_ref_15a())

        assert [n.identifier for n in sections] == [
            "15A-1 through 15A-100",
            "15A-101",
            "15A-101.1",
        ]
        assert sections[0].name == "Reserved for future codification purposes."
        assert sections[1].name == "Definitions."

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = NorthCarolinaAdapter()
        with mock.patch(PATCH_TARGET, side_effect=_raise(_http_error(CH15_URL))):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_sections(_chapter_ref())

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = NorthCarolinaAdapter()
        with _serve_bytes({CH15_URL: b"<html><body>none</body></html>"}):
            with pytest.raises(AdapterUnavailableError, match="no usable section"):
                adapter.list_sections(_chapter_ref())

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = NorthCarolinaAdapter()
        with mock.patch(
            PATCH_TARGET,
            side_effect=_raise(urllib.error.URLError("simulated network failure")),
        ):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_sections(_chapter_ref())


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = NorthCarolinaAdapter()

    def test_full_retrieval_with_amendment(self) -> None:
        ref = _make_ref("15-1")
        with _serve_bytes(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "G.S. 15-1"
        assert section.citation.state_code == "NC"
        assert section.ref == ref
        assert section.heading == "Statute of limitations for misdemeanors."
        assert section.text.startswith("(a) The crimes of deceit")
        assert section.amendment_notes == (
            "(1826, c. 11; R.C., c. 35, s. 8; Code, s. 1177; Rev., s. 3147; "
            "1907, c. 408; C.S., s. 4512; 1943, c. 543; 2017-57, s. 17.8.(a); "
            "2017-212, s. 5.3; 2019-245, s. 2(a).)"
        )
        assert section.status.value == "unknown"
        assert section.source_url == SEC15_1_URL
        assert section.retrieved_at is not None

    def test_decimal_section_retrieval(self) -> None:
        # VERIFIED: a decimal identifier (15-10.1) parses from the
        # Windows-1252 document with its own history.
        ref = _make_ref("15-10.1")
        with _serve_bytes(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "G.S. 15-10.1"
        assert section.heading == "Detainer; purpose; manner of use."
        assert section.text.startswith(
            "Any person confined in the State prison system of North Carolina"
        )
        assert section.amendment_notes.startswith("(1949, c. 303;")

    def test_lettered_chapter_section_retrieval(self) -> None:
        ref = SectionRef(chapter=_chapter_ref_15a(), identifier="15A-101")
        with _serve_bytes(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "G.S. 15A-101"
        assert section.heading == "Definitions."
        assert section.text.startswith("Unless the context clearly requires otherwise")
        assert section.amendment_notes.startswith("(1973, c. 1286, s. 1;")

    def test_repealed_section_empty_body_with_heading(self) -> None:
        # VERIFIED: a repealed single section is a catchline-only document;
        # the repeal note is the heading and the body is empty. Deliberate,
        # documented deviation from the blanket "empty text + no amendment
        # -> NormalizationError" rule.
        ref = _make_ref("15-9")
        with _serve_bytes(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.heading == "Repealed by Session Laws 1973, c. 1286, s. 26."
        assert section.text == ""
        assert section.amendment_notes is None
        assert section.status.value == "unknown"

    def test_repealed_range_section_empty_body_with_heading(self) -> None:
        ref = _make_ref("15-2 through 15-3")
        with _serve_bytes(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "G.S. 15-2 through 15-3"
        assert section.heading == "Repealed by Session Laws 1973, c. 1286, s. 26."
        assert section.text == ""
        assert section.amendment_notes is None

    def test_reserved_range_section_empty_body_with_heading(self) -> None:
        ref = SectionRef(chapter=_chapter_ref_15a(), identifier="15A-1 through 15A-100")
        with _serve_bytes(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "G.S. 15A-1 through 15A-100"
        assert section.heading == "Reserved for future codification purposes."
        assert section.text == ""
        assert section.amendment_notes is None

    def test_no_amendment_section(self) -> None:
        # Serve a catchline with body but no trailing parenthetical.
        html = (
            b"<html><body>"
            b'<p class="x"><span>&sect; 15-1.&nbsp; Offense.</span></p>'
            b'<p class="y"><span>(a) The body has no history.</span></p>'
            b"</body></html>"
        )
        with _serve_bytes({SEC15_1_URL: html}):
            section = self.adapter.retrieve_section(_make_ref("15-1"))

        assert section.heading == "Offense."
        assert section.text == "(a) The body has no history."
        assert section.amendment_notes is None

    def test_missing_section_404_maps_to_ref_not_found(self) -> None:
        # A section whose file does not exist (e.g. a range's single-file
        # form, or a non-existent section) returns HTTP 404 -> RefNotFound.
        ref = _make_ref("15-2")
        with mock.patch(PATCH_TARGET, side_effect=_raise(_http_error(SEC15_1_URL))):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        ref = _make_ref("15-1")
        with mock.patch(
            PATCH_TARGET,
            side_effect=_raise(urllib.error.URLError("simulated network failure")),
        ):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)


class TestParseEdgeCases:
    def setup_method(self) -> None:
        self.adapter = NorthCarolinaAdapter()

    def test_no_catchline_raises_normalization_error(self) -> None:
        ref = _make_ref("15-1")
        html = b"<html><body><p>Just a paragraph.</p></body></html>"
        with _serve_bytes({SEC15_1_URL: html}):
            with pytest.raises(NormalizationError, match="no catchline"):
                self.adapter.retrieve_section(ref)

    def test_catchline_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("15-1")
        html = (
            b"<html><body>"
            b'<p class="x"><span>&sect; 15-2.&nbsp; Other section.</span></p>'
            b'<p class="y"><span>Some other body.</span></p>'
            b"</body></html>"
        )
        with _serve_bytes({SEC15_1_URL: html}):
            with pytest.raises(RefMismatchError, match="does not begin with"):
                self.adapter.retrieve_section(ref)

    def test_prefix_collision_catchline_raises_ref_mismatch_error(self) -> None:
        # "15-1" must not match a catchline that begins "15-10 ...".
        ref = _make_ref("15-1")
        html = (
            b"<html><body>"
            b'<p class="x"><span>&sect; 15-10.&nbsp; Speedy trial.</span></p>'
            b'<p class="y"><span>Body.</span></p>'
            b"</body></html>"
        )
        with _serve_bytes({SEC15_1_URL: html}):
            with pytest.raises(RefMismatchError, match="does not begin with"):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = NorthCarolinaAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("15-1")
        parsed = ParsedDocument(
            raw_citation="G.S. 15-1",
            heading="Statute of limitations for misdemeanors.",
            text="(a) The crimes ...",
            amendment_notes="(1826, c. 11; ...)",
            source_url=SEC15_1_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "G.S. 15-1"
        assert section.citation.state_code == "NC"
        assert section.heading == "Statute of limitations for misdemeanors."
        assert section.amendment_notes == "(1826, c. 11; ...)"
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="NV", identifier="x"), identifier="15"
            ),
            identifier="15-1",
        )
        parsed = ParsedDocument(
            raw_citation="G.S. 15-1",
            text="Some text.",
        )
        with pytest.raises(NormalizationError, match="expected 'NC'"):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("15-1")
        parsed = ParsedDocument(
            raw_citation="G.S. 15-2",
            text="Some other section's text.",
        )
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, ref)