"""Tests for NebraskaAdapter.

Nebraska Revised Statutes are a per-section HTML source (the Family A
model) at nebraskalegislature.gov. Each chapter's section index is
``/laws/browse-chapters.php?chapter={n}`` and each section has ONE static
HTML document at ``/laws/statutes.php?statute={ch}-{sec}``.
``SectionRef.identifier`` is the full ``{ch}-{sec}`` citation (e.g.
``"77-1801"``, ``"77-202.12"``). History is the page's ``Source`` block;
case ``Annotations`` are excluded from the statute text; repealed sections
are returned with the repeal note as the heading and empty text.

The Revised Statutes have **no title level**; the adapter exposes a single
synthetic ``TitleRef`` (identifier ``"REVISED STATUTES"``) above every
chapter (the MinnesotaAdapter synthetic-title precedent). Title/chapter
discovery is fully supported: ``list_titles`` returns that one title,
``list_chapters`` enumerates chapters from ``browse-statutes.php``, and
``list_sections`` enumerates sections from the chapter index.

**REAL trimmed fixtures**: the ``ne_*`` fixtures are real trimmed captures
of the official host from Wayback Machine snapshots (see
``docs/research/nebraska.md``); they are NOT synthetic. The browse and
chapter-index fixtures preserve the real page header plus a contiguous
subset of the real rows; the section-document fixtures are full real
captures.

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

from _mock_network import PATCH_TARGET, mock_urlopen_error, mock_urlopen_serving

from state_statutes_mcp.adapters.nebraska.adapter import NebraskaAdapter
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
# --- Machine snapshots (see docs/research/nebraska.md).
FIXTURES = Path(__file__).parent / "fixtures"

BROWSE_HTML = (FIXTURES / "ne_browse_statutes_trimmed.html").read_text(
    encoding="utf-8"
)
CH77_HTML = (FIXTURES / "ne_ch77_trimmed.html").read_text(encoding="utf-8")
SEC77_1801_HTML = (FIXTURES / "ne_section_77-1801.html").read_text(encoding="utf-8")
SEC77_202_12_HTML = (FIXTURES / "ne_section_77-202.12.html").read_text(
    encoding="utf-8"
)
SEC77_202_13_HTML = (FIXTURES / "ne_section_77-202.13.html").read_text(
    encoding="utf-8"
)

BASE = "https://nebraskalegislature.gov"
BROWSE_URL = f"{BASE}/laws/browse-statutes.php"
CH77_URL = f"{BASE}/laws/browse-chapters.php?chapter=77"


def _section_url(section: str) -> str:
    return f"{BASE}/laws/statutes.php?statute={section}"


SEC77_1801_URL = _section_url("77-1801")
SEC77_202_12_URL = _section_url("77-202.12")
SEC77_202_13_URL = _section_url("77-202.13")


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the adapter's fetch wrapper
    will map to ``RefNotFoundError`` (404)."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


def _synthetic_title() -> TitleRef:
    return TitleRef(state_code="NE", identifier="REVISED STATUTES")


def _chapter_ref() -> ChapterRef:
    return ChapterRef(title=_synthetic_title(), identifier="77")


def _make_ref(section: str) -> SectionRef:
    return SectionRef(chapter=_chapter_ref(), identifier=section)


def _serve_all() -> dict[str, str]:
    return {
        BROWSE_URL: BROWSE_HTML,
        CH77_URL: CH77_HTML,
        SEC77_1801_URL: SEC77_1801_HTML,
        SEC77_202_12_URL: SEC77_202_12_HTML,
        SEC77_202_13_URL: SEC77_202_13_HTML,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert NebraskaAdapter.__abstractmethods__ == frozenset()
        adapter = NebraskaAdapter()
        assert adapter.state_code == "NE"
        assert adapter.state_name == "Nebraska"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = NebraskaAdapter()

    def test_section_ref_url(self) -> None:
        assert self.adapter.build_url(_make_ref("77-1801")) == SEC77_1801_URL

    def test_decimal_section_ref_url(self) -> None:
        assert self.adapter.build_url(_make_ref("77-202.12")) == SEC77_202_12_URL

    def test_chapter_ref_url(self) -> None:
        assert self.adapter.build_url(_chapter_ref()) == CH77_URL

    def test_title_ref_raises_unsupported(self) -> None:
        # The synthetic title has no source page.
        with pytest.raises(UnsupportedRefError, match="no title level"):
            self.adapter.build_url(_synthetic_title())

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestListTitles:
    def test_returns_single_synthetic_title(self) -> None:
        adapter = NebraskaAdapter()
        titles = adapter.list_titles()

        assert len(titles) == 1
        node = titles[0]
        assert node.level == HierarchyLevel.TITLE
        assert node.identifier == "REVISED STATUTES"
        assert node.name == "Nebraska Revised Statutes"
        assert node.ref == TitleRef(state_code="NE", identifier="REVISED STATUTES")


class TestListChapters:
    def test_returns_chapters_from_browse_page(self) -> None:
        adapter = NebraskaAdapter()
        with mock_urlopen_serving({BROWSE_URL: BROWSE_HTML}):
            chapters = adapter.list_chapters(_synthetic_title())

        # The trimmed fixture keeps the first 12 chapter rows verbatim.
        assert [c.identifier for c in chapters] == [
            "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12",
        ]
        assert chapters[0].name == "ACCOUNTANTS"
        assert all(c.level == HierarchyLevel.CHAPTER for c in chapters)
        assert all(c.ref.title == _synthetic_title() for c in chapters)

    def test_wrong_title_raises_ref_not_found(self) -> None:
        adapter = NebraskaAdapter()
        foreign = TitleRef(state_code="NE", identifier="BOGUS")
        with pytest.raises(RefNotFoundError, match="only title"):
            adapter.list_chapters(foreign)

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = NebraskaAdapter()
        with mock_urlopen_error(_http_error(BROWSE_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_chapters(_synthetic_title())

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = NebraskaAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_chapters(_synthetic_title())

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = NebraskaAdapter()
        with mock_urlopen_serving({BROWSE_URL: "<html><body>none</body></html>"}):
            with pytest.raises(AdapterUnavailableError, match="no usable chapter"):
                adapter.list_chapters(_synthetic_title())


class TestListSections:
    def test_returns_sections_from_chapter_index(self) -> None:
        adapter = NebraskaAdapter()
        with mock_urlopen_serving({CH77_URL: CH77_HTML}):
            sections = adapter.list_sections(_chapter_ref())

        # The trimmed fixture keeps the first 12 section rows verbatim.
        assert [s.identifier for s in sections] == [
            "77-101",
            "77-102",
            "77-103",
            "77-103.01",
            "77-104",
            "77-105",
            "77-106",
            "77-107",
            "77-108",
            "77-109",
            "77-110",
            "77-111",
        ]
        assert sections[0].name == "Definitions, where found."
        assert sections[3].identifier == "77-103.01"
        assert all(s.level == HierarchyLevel.SECTION for s in sections)
        assert all(s.ref.chapter == _chapter_ref() for s in sections)

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = NebraskaAdapter()
        with mock_urlopen_error(_http_error(CH77_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_sections(_chapter_ref())

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = NebraskaAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_sections(_chapter_ref())

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = NebraskaAdapter()
        with mock_urlopen_serving({CH77_URL: "<html><body>none</body></html>"}):
            with pytest.raises(AdapterUnavailableError, match="no usable section"):
                adapter.list_sections(_chapter_ref())


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = NebraskaAdapter()

    def test_full_retrieval_with_history(self) -> None:
        ref = _make_ref("77-1801")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Neb. Rev. Stat. § 77-1801"
        assert section.citation.state_code == "NE"
        assert section.ref == ref
        assert section.heading == "Real property taxes; collection by sale; when."
        assert section.text.startswith(
            "Except for delinquent taxes on mobile homes"
        )
        assert section.amendment_notes == (
            "Laws 1903, c. 73, § 193, p. 459; R.S.1913, § 6521; C.S.1922, "
            "§ 6049; C.S.1929, § 77-2001; Laws 1933, c. 136, § 4, p. 518; "
            "Laws 1937, c. 167, § 23, p. 655; Laws 1939, c. 98, § 23, p. 442; "
            "Laws 1941, c. 157, § 23, p. 626; C.S.Supp.,1941, § 77-2001; "
            "R.S.1943, § 77-1801; Laws 1986, LB 531, § 1; Laws 2000, LB 968, § 70."
        )
        assert section.status.value == "unknown"
        assert section.source_url == SEC77_1801_URL
        assert section.retrieved_at is not None

    def test_decimal_section_multi_paragraph_body(self) -> None:
        # VERIFIED: a decimal identifier (77-202.12) parses with a
        # multi-paragraph body whose paragraphs are block-separated.
        ref = _make_ref("77-202.12")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Neb. Rev. Stat. § 77-202.12"
        assert section.heading == (
            "Public property; taxation status; county assessor; duties; appeal."
        )
        assert "\n\n" in section.text
        assert section.text.startswith("(1) On or before March 1,")
        assert section.amendment_notes == (
            "Laws 1999, LB 271, § 9; Laws 2000, LB 968, § 32; Laws 2005, "
            "LB 263, § 5; Laws 2007, LB334, § 21; Laws 2011, LB384, § 4."
        )

    def test_annotations_excluded_from_text(self) -> None:
        # The case-law Annotations block is not statute text and must not
        # leak into `text`.
        ref = _make_ref("77-1801")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert "Continental Resources" not in section.text
        assert "Annotations" not in section.text

    def test_repealed_section_empty_body_with_heading(self) -> None:
        # VERIFIED: a repealed section (77-202.13) renders a repeal caption
        # as the heading with no body and no Source. Per the documented
        # deviation (same decision as NorthCarolinaAdapter), it is returned
        # with empty text rather than raising NormalizationError.
        ref = _make_ref("77-202.13")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Neb. Rev. Stat. § 77-202.13"
        assert section.heading == "Repealed. Laws 2008, LB 965, § 27."
        assert section.text == ""
        assert section.amendment_notes is None
        assert section.status.value == "unknown"

    def test_section_number_mismatch_raises_ref_mismatch_error(self) -> None:
        # The page's own <h2> number must equal ref.identifier.
        html = (
            "<html><body><div class=\"statute\">"
            "<h2>77-9999.</h2><h3>Other.</h3><p class=\"text-justify\">Body.</p>"
            "</div></body></html>"
        )
        with mock_urlopen_serving({SEC77_1801_URL: html}):
            with pytest.raises(RefMismatchError, match="does not match"):
                self.adapter.retrieve_section(_make_ref("77-1801"))

    def test_no_statute_region_raises_normalization_error(self) -> None:
        html = "<html><body><p>nothing here</p></body></html>"
        with mock_urlopen_serving({SEC77_1801_URL: html}):
            with pytest.raises(NormalizationError, match="no statute content"):
                self.adapter.retrieve_section(_make_ref("77-1801"))

    def test_no_section_number_raises_normalization_error(self) -> None:
        html = (
            "<html><body><div class=\"statute\">"
            "<h3>Only a heading.</h3><p class=\"text-justify\">Body.</p>"
            "</div></body></html>"
        )
        with mock_urlopen_serving({SEC77_1801_URL: html}):
            with pytest.raises(NormalizationError, match="no section number"):
                self.adapter.retrieve_section(_make_ref("77-1801"))

    def test_no_heading_raises_normalization_error(self) -> None:
        # A page with the right number but no <h3> caption is malformed.
        html = (
            "<html><body><div class=\"statute\">"
            "<h2>77-1801.</h2><p class=\"text-justify\">Body.</p>"
            "</div></body></html>"
        )
        with mock_urlopen_serving({SEC77_1801_URL: html}):
            with pytest.raises(NormalizationError, match="no heading element"):
                self.adapter.retrieve_section(_make_ref("77-1801"))

    def test_missing_section_404_maps_to_ref_not_found(self) -> None:
        ref = _make_ref("77-9999")
        with mock_urlopen_error(_http_error(_section_url("77-9999"))):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        ref = _make_ref("77-1801")
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = NebraskaAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("77-1801")
        parsed = ParsedDocument(
            raw_citation="Neb. Rev. Stat. § 77-1801",
            heading="Real property taxes; collection by sale; when.",
            text="Except for delinquent taxes ...",
            amendment_notes="Laws 1903, c. 73, § 193, p. 459; ...",
            source_url=SEC77_1801_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "Neb. Rev. Stat. § 77-1801"
        assert section.citation.state_code == "NE"
        assert section.heading == "Real property taxes; collection by sale; when."
        assert section.amendment_notes == "Laws 1903, c. 73, § 193, p. 459; ..."
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="NV", identifier="REVISED STATUTES"),
                identifier="77",
            ),
            identifier="77-1801",
        )
        parsed = ParsedDocument(
            raw_citation="Neb. Rev. Stat. § 77-1801",
            text="Some text.",
        )
        with pytest.raises(NormalizationError, match="expected 'NE'"):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("77-1801")
        parsed = ParsedDocument(
            raw_citation="Neb. Rev. Stat. § 77-1802",
            text="Some text.",
        )
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, ref)


class TestHierarchyMapping:
    def test_synthetic_title_is_the_only_title(self) -> None:
        # Nebraska-specific hierarchy behavior: exactly one synthetic title
        # and every chapter/section ref descends from it.
        adapter = NebraskaAdapter()
        titles = adapter.list_titles()
        assert len(titles) == 1
        title = titles[0].ref
        assert isinstance(title, TitleRef)
        assert title.state_code == "NE"
        assert title.identifier == "REVISED STATUTES"

        with mock_urlopen_serving({BROWSE_URL: BROWSE_HTML, CH77_URL: CH77_HTML}):
            chapters = adapter.list_chapters(title)
            assert all(c.ref.title == title for c in chapters)
            sections = adapter.list_sections(_chapter_ref())
            assert all(s.ref.chapter.title == title for s in sections)