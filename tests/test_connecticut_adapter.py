"""Tests for ConnecticutAdapter.

Connecticut is a chapter-document HTML source (the official Connecticut
General Statutes "current" publication at cga.ct.gov/current/pub).
Hierarchy is Title -> Chapter -> Section. The title index (``titles.htm``)
lists the titles; each title's page (``title_{id}.htm``) lists that
title's chapters (``chap_{id}.htm``, except Title 42a -- the UCC -- whose
"chapters" are articles at ``art_{id}.htm``). Sections are embedded in
their chapter document, each opened by a catchline span
``<span class="catchln" id="sec_{id}">Sec. {id}. {Caption}.</span>``.
Repealed-range blocks (``secs_`` ids) are genuine block boundaries but
are NOT individually retrievable sections. ``SectionRef.identifier`` is
the citation form ``{chapter}-{section}`` (e.g. ``"53a-24"``; UCC form
``{article}-{part}-{section}`` e.g. ``"42a-1-101"``).

**REAL trimmed fixtures**: the ``ct_*`` fixtures are real trimmed
captures of the official host from a Wayback Machine snapshot
(``20260811192527id_``); they are NOT synthetic (see
``docs/research/connecticut.md``). The trimmed chapter fixtures preserve
only a subset of each chapter's section blocks, so ``list_sections`` on
them returns only the included sections.

Section-retrieval and section-discovery tests exercise the adapter's real
fetch -> parse path against these fixtures. All tests are fully offline:
the real network boundary (``urllib.request.urlopen`` as imported by the
shared ``_fetch`` helper) is mocked, never adapter internals.
"""

from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest

from _mock_network import mock_urlopen, mock_urlopen_error, mock_urlopen_serving

from state_statutes_mcp.adapters.connecticut.adapter import ConnecticutAdapter
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
# --- snapshot (20260811192527id_). NOT synthetic.
FIXTURES = Path(__file__).parent / "fixtures"

CT_TITLES_HTML = (FIXTURES / "ct_titles.html").read_text(encoding="utf-8")
CT_TITLE53A_HTML = (FIXTURES / "ct_title53a.html").read_text(encoding="utf-8")
CT_TITLE42A_HTML = (FIXTURES / "ct_title42a.html").read_text(encoding="utf-8")
CT_CH952_HTML = (FIXTURES / "ct_chap952_trimmed.html").read_text(encoding="utf-8")
CT_ART001_HTML = (FIXTURES / "ct_art001_trimmed.html").read_text(encoding="utf-8")

BASE = "https://www.cga.ct.gov/current/pub"

TITLES_URL = f"{BASE}/titles.htm"
TITLE53A_URL = f"{BASE}/title_53a.htm"
TITLE42A_URL = f"{BASE}/title_42a.htm"
CH952_URL = f"{BASE}/chap_952.htm"
ART001_URL = f"{BASE}/art_001.htm"


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the shared fetch helper will
    wrap into ``AdapterUnavailableError`` with ``__cause__`` set to it."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, None)


def _title_ref() -> TitleRef:
    return TitleRef(state_code="CT", identifier="53a")


def _chapter_ref() -> ChapterRef:
    return ChapterRef(title=_title_ref(), identifier="952")


def _chapter_ref_42a() -> ChapterRef:
    return ChapterRef(
        title=TitleRef(state_code="CT", identifier="42a"), identifier="001"
    )


def _make_ref(section: str) -> SectionRef:
    return SectionRef(chapter=_chapter_ref(), identifier=section)


def _serve_all() -> dict[str, str]:
    return {
        TITLES_URL: CT_TITLES_HTML,
        TITLE53A_URL: CT_TITLE53A_HTML,
        TITLE42A_URL: CT_TITLE42A_HTML,
        CH952_URL: CT_CH952_HTML,
        ART001_URL: CT_ART001_HTML,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert ConnecticutAdapter.__abstractmethods__ == frozenset()
        adapter = ConnecticutAdapter()
        assert adapter.state_code == "CT"
        assert adapter.state_name == "Connecticut"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = ConnecticutAdapter()

    def test_title_ref_url(self) -> None:
        assert self.adapter.build_url(_title_ref()) == TITLE53A_URL

    def test_chapter_ref_url(self) -> None:
        assert self.adapter.build_url(_chapter_ref()) == CH952_URL

    def test_ucc_article_chapter_ref_url(self) -> None:
        # VERIFIED: Title 42a (UCC) uses art_{id}.htm, not chap_{id}.htm.
        assert self.adapter.build_url(_chapter_ref_42a()) == ART001_URL

    def test_section_ref_url_is_chapter_document(self) -> None:
        # Sections are embedded in their chapter document, so the chapter
        # document is the closest real resource.
        assert self.adapter.build_url(_make_ref("53a-24")) == CH952_URL

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestCaptionStrip:
    def test_plain_identifier_caption(self) -> None:
        assert (
            ConnecticutAdapter._strip_caption_prefix(
                "Sec. 53a-24. Offense defined.", "53a-24"
            )
            == "Offense defined."
        )

    def test_lettered_identifier_renders_italic_space(self) -> None:
        # VERIFIED: the lettered-section heading renders the italic digit
        # with spaces around it: "Sec. 53a-117 l . Damage...".
        assert (
            ConnecticutAdapter._strip_caption_prefix(
                "Sec. 53a-117 l . Damage to railroad property.", "53a-117l"
            )
            == "Damage to railroad property."
        )

    def test_no_caption_returns_none(self) -> None:
        assert (
            ConnecticutAdapter._strip_caption_prefix("Sec. 53a-90.", "53a-90")
            is None
        )


class TestListTitles:
    def test_returns_all_titles_with_names(self) -> None:
        adapter = ConnecticutAdapter()
        with mock_urlopen_serving({TITLES_URL: CT_TITLES_HTML}):
            titles = adapter.list_titles()

        assert [n.identifier for n in titles] == [
            "01",
            "02",
            "02c",
            "03",
            "04",
            "04a",
            "04b",
            "04c",
            "04d",
            "04e",
            "05",
            "06",
            "07",
            "08",
            "09",
            "10",
            "10a",
            "11",
            "12",
            "13",
            "13a",
            "13b",
            "14",
            "15",
            "16",
            "16a",
            "17",
            "17a",
            "17b",
            "18",
            "19",
            "19a",
            "20",
            "21",
            "21a",
            "22",
            "22a",
            "23",
            "24",
            "25",
            "26",
            "27",
            "28",
            "29",
            "30",
            "31",
            "32",
            "33",
            "34",
            "35",
            "36",
            "36a",
            "36b",
            "37",
            "38",
            "38a",
            "39",
            "40",
            "41",
            "42",
            "42a",
            "42b",
            "43",
            "44",
            "45",
            "45a",
            "46",
            "46a",
            "46b",
            "47",
            "47a",
            "48",
            "49",
            "50",
            "50a",
            "51",
            "52",
            "53",
            "53a",
            "54",
            "55",
        ]
        assert titles[0].name == "Provisions of General Application"
        assert titles[0].identifier == "01"
        assert all(n.level == HierarchyLevel.TITLE for n in titles)
        assert all(n.ref.state_code == "CT" for n in titles)

    def test_reserved_title_2a_row_without_links_is_skipped(self) -> None:
        # VERIFIED: the reserved Title 2a row has no links and must not
        # appear as a title.
        adapter = ConnecticutAdapter()
        with mock_urlopen_serving({TITLES_URL: CT_TITLES_HTML}):
            titles = adapter.list_titles()
        assert "2a" not in {n.identifier for n in titles}

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = ConnecticutAdapter()
        with mock_urlopen("<html><body>no titles</body></html>"):
            with pytest.raises(AdapterUnavailableError, match="no usable title"):
                adapter.list_titles()

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = ConnecticutAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_titles()


class TestListChapters:
    def test_returns_chapters_under_penal_title(self) -> None:
        adapter = ConnecticutAdapter()
        with mock_urlopen_serving({TITLE53A_URL: CT_TITLE53A_HTML}):
            chapters = adapter.list_chapters(_title_ref())

        assert [n.identifier for n in chapters] == ["950", "951", "952"]
        assert chapters[0].name == "Penal Code: General Provisions"
        assert all(n.level == HierarchyLevel.CHAPTER for n in chapters)
        assert all(n.ref.title == _title_ref() for n in chapters)

    def test_ucc_title_lists_articles(self) -> None:
        # VERIFIED: Title 42a is article-based; its page lists articles.
        adapter = ConnecticutAdapter()
        with mock_urlopen_serving({TITLE42A_URL: CT_TITLE42A_HTML}):
            chapters = adapter.list_chapters(
                TitleRef(state_code="CT", identifier="42a")
            )

        assert chapters[0].identifier == "001"
        assert chapters[0].name == "General Provisions"
        assert [n.identifier for n in chapters][:4] == ["001", "002", "002a", "003"]

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = ConnecticutAdapter()
        with mock_urlopen_error(_http_error(TITLE53A_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_chapters(_title_ref())

    def test_title_with_no_chapters_raises_adapter_unavailable(self) -> None:
        adapter = ConnecticutAdapter()
        with mock_urlopen_serving({TITLE53A_URL: "<html><body>empty</body></html>"}):
            with pytest.raises(AdapterUnavailableError, match="no usable chapter"):
                adapter.list_chapters(_title_ref())


class TestListSections:
    def test_returns_sections_excluding_repealed_range(self) -> None:
        adapter = ConnecticutAdapter()
        with mock_urlopen_serving({CH952_URL: CT_CH952_HTML}):
            sections = adapter.list_sections(_chapter_ref())

        # The secs_53a-53_and_53a-54 range is a genuine block boundary but
        # is NOT an individually retrievable section, so it is excluded.
        assert [n.identifier for n in sections] == [
            "53a-24",
            "53a-25",
            "53a-26",
            "53a-27",
            "53a-90",
            "53a-117l",
        ]
        assert sections[0].name == (
            "Offense defined. Application of sentencing provisions to motor "
            "vehicle and drug selling violators."
        )
        assert all(n.level == HierarchyLevel.SECTION for n in sections)
        assert all(n.ref.chapter == _chapter_ref() for n in sections)

    def test_ucc_article_sections_use_three_part_identifiers(self) -> None:
        adapter = ConnecticutAdapter()
        with mock_urlopen_serving({ART001_URL: CT_ART001_HTML}):
            sections = adapter.list_sections(_chapter_ref_42a())

        assert [n.identifier for n in sections] == [
            "42a-1-101",
            "42a-1-102",
            "42a-1-103",
        ]
        assert sections[0].name == "Short titles."

    def test_lettered_section_listing_name_strips_prefix(self) -> None:
        adapter = ConnecticutAdapter()
        with mock_urlopen_serving({CH952_URL: CT_CH952_HTML}):
            sections = adapter.list_sections(_chapter_ref())
        by_id = {n.identifier: n for n in sections}
        assert by_id["53a-117l"].name == (
            "Damage to railroad property in the second degree: Class A "
            "misdemeanor."
        )

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = ConnecticutAdapter()
        with mock_urlopen_error(_http_error(CH952_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_sections(_chapter_ref())

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = ConnecticutAdapter()
        with mock_urlopen_serving({CH952_URL: "<html><body>none</body></html>"}):
            with pytest.raises(AdapterUnavailableError, match="no usable section"):
                adapter.list_sections(_chapter_ref())


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = ConnecticutAdapter()

    def test_full_retrieval(self) -> None:
        ref = _make_ref("53a-24")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Sec. 53a-24"
        assert section.citation.state_code == "CT"
        assert section.ref == ref
        assert section.heading == (
            "Offense defined. Application of sentencing provisions to motor "
            "vehicle and drug selling violators."
        )
        assert section.text.startswith(
            "(a) The term \u201coffense\u201d means any crime or violation"
        )
        # VERIFIED: source-first + history-first are joined with a newline.
        assert section.amendment_notes.startswith("(1969, P.A. 828, S. 24;")
        assert "\nHistory: " in section.amendment_notes
        assert section.status.value == "unknown"
        assert section.source_url == CH952_URL
        assert section.retrieved_at is not None

    def test_body_excludes_annotations_cross_refs_and_nav_table(self) -> None:
        # VERIFIED: annotation, cross-ref, front-note, and nav_tbl content
        # are excluded from the body text.
        ref = _make_ref("53a-25")
        with mock_urlopen_serving({CH952_URL: CT_CH952_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert "See Secs. 53a-35 and 53a-35a" not in section.text
        assert "History:" not in section.text
        assert "nav" not in section.text.lower()

    def test_no_caption_transferred_section(self) -> None:
        # VERIFIED: 53a-90 has no caption and a transfer-note body.
        ref = _make_ref("53a-90")
        with mock_urlopen_serving({CH952_URL: CT_CH952_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert section.heading is None
        assert "Transferred to Chapter 961, Part II, Sec. 54-102a" in section.text
        assert section.amendment_notes is None

    def test_lettered_section_caption(self) -> None:
        # VERIFIED: the italic lettered digit renders with spaces; the
        # caption prefix strip handles it.
        ref = _make_ref("53a-117l")
        with mock_urlopen_serving({CH952_URL: CT_CH952_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert section.heading == (
            "Damage to railroad property in the second degree: Class A "
            "misdemeanor."
        )

    def test_ucc_article_section_retrieval(self) -> None:
        ref = SectionRef(chapter=_chapter_ref_42a(), identifier="42a-1-101")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Sec. 42a-1-101"
        assert section.heading == "Short titles."
        assert section.text.startswith(
            "(a) This title may be cited as the \u201cUniform Commercial Code\u201d"
        )
        assert section.amendment_notes.startswith("(1959, P.A. 133, S. 1-101;")

    def test_missing_section_raises_ref_not_found(self) -> None:
        ref = _make_ref("53a-999")
        with mock_urlopen_serving({CH952_URL: CT_CH952_HTML}):
            with pytest.raises(RefNotFoundError, match="contains no section"):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        ref = _make_ref("53a-24")
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)


class TestParseEdgeCases:
    def setup_method(self) -> None:
        self.adapter = ConnecticutAdapter()

    def test_empty_body_raises_normalization_error(self) -> None:
        ref = _make_ref("53a-24")
        html = (
            "<html><body>"
            '<span class="catchln" id="sec_53a-24">Sec. 53a-24. Offense.</span>'
            '<table class="nav_tbl"><tr><td>nav</td></tr></table>'
            "</body></html>"
        )
        with mock_urlopen_serving({CH952_URL: html}):
            with pytest.raises(NormalizationError, match="body text was empty"):
                self.adapter.retrieve_section(ref)

    def test_catchline_block_without_span_raises_normalization_error(self) -> None:
        ref = _make_ref("53a-24")
        html = (
            "<html><body>"
            '<span class="catchln" id="sec_53a-99">Sec. 53a-99. Other.</span>'
            "<p>Body.</p>"
            "</body></html>"
        )
        with mock_urlopen_serving({CH952_URL: html}):
            with pytest.raises(RefNotFoundError, match="contains no section"):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = ConnecticutAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("53a-24")
        parsed = ParsedDocument(
            raw_citation="Sec. 53a-24",
            heading="Offense defined.",
            text="(a) The term ...",
            amendment_notes="(1969, P.A. 828, S. 24.)",
            source_url=CH952_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "Sec. 53a-24"
        assert section.citation.state_code == "CT"
        assert section.heading == "Offense defined."
        assert section.amendment_notes == "(1969, P.A. 828, S. 24.)"
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="NV", identifier="x"), identifier="220"
            ),
            identifier="53a-24",
        )
        parsed = ParsedDocument(
            raw_citation="Sec. 53a-24",
            text="Some text.",
        )
        with pytest.raises(NormalizationError, match="expected 'CT'"):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("53a-24")
        parsed = ParsedDocument(
            raw_citation="Sec. 53a-25",
            text="Some other section's text.",
        )
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, ref)