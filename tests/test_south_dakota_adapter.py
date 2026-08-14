"""Tests for SouthDakotaAdapter.

South Dakota is the framework's first JSON-consuming adapter whose
Title/Chapter/Section records embed a full HTML document in their ``Html``
field, so these tests exercise the JSON shape handling (listings, sorting,
dedup), the embedded-HTML listing parsing (body isolation, cross-reference
noise filtering, lettered chapters, repealed-section merged blocks), and the
end-to-end section retrieval. All retrieval tests are fully offline: the
real network boundary (``urllib.request.urlopen`` as imported by the shared
``_fetch`` helper) is mocked, so the adapter's real fetch -> parse path runs
against the JSON below.

All JSON/HTML below is **synthetic** -- hand-written to match the confirmed
response shapes documented in ``SouthDakotaAdapter``'s module docstring and
in ``docs/research/south_dakota.md`` (titles as a JSON array of
``{"Statute","CatchLine","Type":"Title"}``; the title/chapter records as a
dict with an embedded ``Html`` field linking chapters/sections via
``Statute=`` anchors; the section record as a flat dict with ``Type:
"Section"``, a ``parents`` array, and a full XHTML ``Html``). It is NOT a
saved real government fixture.
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from _mock_network import mock_urlopen, mock_urlopen_error, mock_urlopen_serving

from state_statutes_mcp.adapters.south_dakota.adapter import SouthDakotaAdapter
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

# --- SYNTHETIC mock JSON payloads -- NOT real government fixtures. ---

# Titles: a JSON array. Lettered titles (e.g. "23A") coexist with numeric
# titles; the adapter must re-sort numerically so 22 < 23A < 24.
SYNTHETIC_TITLES_JSON = [
    {"StatuteId": 1, "Statute": "1", "Type": "Title", "CatchLine": "STATE AFFAIRS AND GOVERNMENT", "Title": 1, "TitleLetter": None, "Repealed": False},
    {"StatuteId": 2, "Statute": "22", "Type": "Title", "CatchLine": "CRIMES", "Title": 22, "TitleLetter": None, "Repealed": False},
    {"StatuteId": 3, "Statute": "24", "Type": "Title", "CatchLine": "PUBLIC MUNICIPALITIES", "Title": 24, "TitleLetter": None, "Repealed": False},
    {"StatuteId": 4, "Statute": "23A", "Type": "Title", "CatchLine": "GAMING", "Title": 23, "TitleLetter": "A", "Repealed": False},
]

# Title 22 record: the embedded Html links every chapter as
# "Statute=22-{chapter}" anchors with the zero-padded number and name in
# the surrounding text. Lettered chapter 4A exercises the unpadded href id
# vs padded link text. Cross-reference noise lives BOTH after </body>
# (which must be isolated away) and inside the body (a section-form link,
# which must not match the chapter pattern). Chapter 22-1 appears twice in
# the body to exercise keep-first dedup.
SYNTHETIC_TITLE_22_HTML = (
    "<html><head><style>span { white-space: pre-wrap; }</style></head><body>"
    "<p>TITLE 22</p>"
    "<p>CRIMES</p>"
    "<p>Chapter</p>"
    '<p dir="ltr" class="sB"><a href="https://sdlegislature.gov/Statutes/Codified_Laws/DisplayStatute.aspx?Type=Statute&amp;Statute=22-1"><span class="sSC">01</span></a><span xml:space="preserve" class="sS">\u00a0\u00a0\u00a0\u00a0Definitions And General Provisions </span></p>'
    '<p dir="ltr" class="sB"><a href="https://sdlegislature.gov/Statutes/Codified_Laws/DisplayStatute.aspx?Type=Statute&amp;Statute=22-1"><span class="sSC">01</span></a><span xml:space="preserve" class="sS">\u00a0\u00a0\u00a0\u00a0Definitions And General Provisions (duplicate)</span></p>'
    '<p dir="ltr" class="sB"><a href="https://sdlegislature.gov/Statutes/Codified_Laws/DisplayStatute.aspx?Type=Statute&amp;Statute=22-10"><span class="sSC">10</span></a><span xml:space="preserve" class="sS">\u00a0\u00a0\u00a0\u00a0Arson</span></p>'
    '<p dir="ltr" class="sB"><a href="https://sdlegislature.gov/Statutes/Codified_Laws/DisplayStatute.aspx?Type=Statute&amp;Statute=22-4A"><span class="sSC">04A</span></a><span xml:space="preserve" class="sS">\u00a0\u00a0\u00a0\u00a0Solicitation</span></p>'
    '<p dir="ltr" class="sB"><a href="https://sdlegislature.gov/Statutes?Statute=22-3-1"><span>22-3-1</span></a><span xml:space="preserve" class="sS">\u00a0\u00a0\u00a0\u00a0not a chapter, a section cross-ref</span></p>'
    "</body></html>"
    '<p><a href="https://sdlegislature.gov/Statutes?Statute=22-5"><span>05</span></a>noise outside the body must be ignored</p>'
)

# Chapter 22-3 record: the embedded Html links every section as
# "Statute=22-3-{section}" anchors with the full number and catchline in
# the surrounding text. Includes a repealed merged block (22-3-6 and
# 22-3-7 sharing one listing line, exactly as the site renders it) and a
# cross-reference to a section of a different title (3-5) that must not be
# parsed as a chapter-22-3 section.
SYNTHETIC_CHAPTER_22_3_HTML = (
    "<html><head><style>span { white-space: pre-wrap; }</style></head><body>"
    "<p>CHAPTER 22-3</p>"
    "<p>PARTIES TO CRIMES</p>"
    '<p dir="ltr" class="sB"><a href="https://sdlegislature.gov/Statutes?Statute=22-3-1" rel="noopener"><span class="sSC">22-3-1</span></a><span xml:space="preserve" class="sS">\u00a0\u00a0\u00a0\u00a0Persons capable of committing crimes--Exceptions.</span></p>'
    '<p dir="ltr" class="sB"><a href="https://sdlegislature.gov/Statutes?Statute=22-3-1.1" rel="noopener"><span class="sSC">22-3-1.1</span></a><span xml:space="preserve" class="sS">\u00a0\u00a0\u00a0\u00a0Voluntary consumption of alcohol or controlled substance not causing insanity.</span></p>'
    '<p dir="ltr" class="sB"><a href="https://sdlegislature.gov/Statutes?Statute=22-3-10" rel="noopener"><span class="sSC">22-3-10</span></a><span xml:space="preserve" class="sS">\u00a0\u00a0\u00a0\u00a0Arson-related cross chapter</span></p>'
    '<p dir="ltr" class="sB"><a href="https://sdlegislature.gov/Statutes?Statute=22-3-6" rel="noopener"><span class="sSC">22-3-6</span></a><span xml:space="preserve" class="sS">\u00a0\u00a0\u00a0\u00a0, </span><a href="https://sdlegislature.gov/Statutes?Statute=22-3-7" rel="noopener"><span class="sSC">22-3-7</span></a><span xml:space="preserve" class="sS">. Repealed by <a href="https://sdlegislature.gov/Statutes?Statute=3-5">SL 1976, ch 158</a>, \u00a7 3-5</span></p>'
    '<p dir="ltr" class="sB"><a href="https://sdlegislature.gov/Statutes?Statute=3-5" rel="noopener"><span class="sSC">3-5</span></a><span xml:space="preserve" class="sS">\u00a0\u00a0\u00a0\u00a0different title; must be ignored</span></p>'
    "</body></html>"
)

# Section record: the verified flat shape with Type "Section", the full
# number in "Statute", a "parents" array carrying title/chapter, and a full
# XHTML document in "Html". The body's first paragraph is the number plus
# catchline; the middle is the statute body; the last is the "Source:"
# amendment-history line. CatchLine carries a trailing space (verified),
# which the adapter must strip.
SYNTHETIC_SECTION_JSON = {
    "StatuteId": 2046938,
    "Statute": "22-3-1",
    "CatchLine": "Persons capable of committing crimes--Exceptions. ",
    "Type": "Section",
    "Repealed": False,
    "Title": 22,
    "Chapter": 3,
    "Section": 1,
    "SubSec": 0,
    "Next": "22-3-1.1",
    "Previous": "22-3",
    "parents": [
        {"StatuteId": 1, "Type": "Title", "Statute": "22"},
        {"StatuteId": 2, "Type": "Chapter", "Statute": "3"},
        {"StatuteId": 3, "Type": "Section", "Statute": "1"},
    ],
    "StatuteText": None,
    "Html": (
        "<html><head><style>span { white-space: pre-wrap; }</style></head><body>"
        '<p dir="ltr" class="sSC"><a href="https://sdlegislature.gov/Statutes?Statute=22-3-1"><span>22-3-1</span></a><span>.</span> <span>Persons capable of committing crimes--Exceptions.</span></p>'
        "<p dir=\"ltr\" class=\"sNormal\">Any person is capable of committing a crime, except the following: (1) Children under the age of ten years; (2) Persons of unsound mind; (3) Persons who committed the act charged but who did not act with the mental state required for the offense.</p>"
        '<p dir="ltr" class="sSCL"><span class="sSC">Source:</span><span class="sS"> SDC 1939, \u00a7 13.0201; SL 1968, ch 28, \u00a7\u00a7 1, 2.</span></p>'
        "</body></html>"
    ),
}

TITLES_URL = "https://sdlegislature.gov/api/Statutes/Title"
TITLE22_URL = "https://sdlegislature.gov/api/Statutes/Statute/22"
CHAPTER22_3_URL = "https://sdlegislature.gov/api/Statutes/Statute/22-3"
SECTION22_3_1_URL = "https://sdlegislature.gov/api/Statutes/Statute/22-3-1"


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the shared fetch helper will
    wrap into ``AdapterUnavailableError`` with ``__cause__`` set to it."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


def _make_ref(section: str) -> SectionRef:
    return SectionRef(
        chapter=ChapterRef(
            title=TitleRef(state_code="SD", identifier="22"),
            identifier="3",
        ),
        identifier=section,
    )


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert SouthDakotaAdapter.__abstractmethods__ == frozenset()
        adapter = SouthDakotaAdapter()
        assert adapter.state_code == "SD"
        assert adapter.state_name == "South Dakota"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = SouthDakotaAdapter()

    def test_title_ref_url(self) -> None:
        ref = TitleRef(state_code="SD", identifier="22")
        assert (
            self.adapter.build_url(ref)
            == "https://sdlegislature.gov/api/Statutes/Statute/22"
        )

    def test_chapter_ref_url(self) -> None:
        ref = ChapterRef(
            title=TitleRef(state_code="SD", identifier="22"), identifier="3"
        )
        assert (
            self.adapter.build_url(ref)
            == "https://sdlegislature.gov/api/Statutes/Statute/22-3"
        )

    def test_section_ref_url_uses_full_number(self) -> None:
        ref = _make_ref("22-3-1")
        assert (
            self.adapter.build_url(ref)
            == "https://sdlegislature.gov/api/Statutes/Statute/22-3-1"
        )

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestDiscovery:
    def setup_method(self) -> None:
        self.adapter = SouthDakotaAdapter()

    def test_list_titles_sorts_numerically_with_lettered_titles(self) -> None:
        with mock_urlopen(json.dumps(SYNTHETIC_TITLES_JSON)):
            titles = self.adapter.list_titles()

        assert [n.identifier for n in titles] == ["1", "22", "23A", "24"]
        assert [n.name for n in titles] == [
            "STATE AFFAIRS AND GOVERNMENT",
            "CRIMES",
            "GAMING",
            "PUBLIC MUNICIPALITIES",
        ]
        assert all(n.level == HierarchyLevel.TITLE for n in titles)
        assert all(n.ref.state_code == "SD" for n in titles)

    def test_list_titles_empty_array_raises(self) -> None:
        with mock_urlopen("[]"):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_titles_non_array_raises(self) -> None:
        with mock_urlopen(json.dumps({"Statute": "1"})):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_titles_network_failure_raises(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_chapters_parses_body_and_ignores_noise(self) -> None:
        title_ref = TitleRef(state_code="SD", identifier="22")
        payload = {
            "Statute": "22",
            "Type": "Title",
            "CatchLine": "CRIMES",
            "Html": SYNTHETIC_TITLE_22_HTML,
        }
        with mock_urlopen_serving({TITLE22_URL: json.dumps(payload)}):
            chapters = self.adapter.list_chapters(title_ref)

        # 22-1 deduped (keep-first); 4A is a lettered chapter; the
        # section-form cross-ref and the after-body noise are excluded.
        assert [n.identifier for n in chapters] == ["1", "4A", "10"]
        assert [n.name for n in chapters] == [
            "Definitions And General Provisions",
            "Solicitation",
            "Arson",
        ]
        assert all(n.level == HierarchyLevel.CHAPTER for n in chapters)
        assert all(n.ref.title == title_ref for n in chapters)

    def test_list_chapters_404_raises_ref_not_found(self) -> None:
        title_ref = TitleRef(state_code="SD", identifier="999")
        url = "https://sdlegislature.gov/api/Statutes/Statute/999"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_chapters(title_ref)

    def test_list_chapters_missing_html_raises(self) -> None:
        title_ref = TitleRef(state_code="SD", identifier="22")
        with mock_urlopen_serving({TITLE22_URL: json.dumps({"Statute": "22"})}):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_chapters(title_ref)

    def test_list_chapters_no_usable_entries_raises(self) -> None:
        title_ref = TitleRef(state_code="SD", identifier="22")
        payload = {"Statute": "22", "Html": "<html><body><p>nothing here</p></body></html>"}
        with mock_urlopen_serving({TITLE22_URL: json.dumps(payload)}):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_chapters(title_ref)

    def test_list_sections_parses_body_merged_repeal_and_sorts(self) -> None:
        chapter_ref = ChapterRef(
            title=TitleRef(state_code="SD", identifier="22"), identifier="3"
        )
        payload = {
            "Statute": "22-3",
            "Type": "Chapter",
            "CatchLine": "PARTIES TO CRIMES",
            "Html": SYNTHETIC_CHAPTER_22_3_HTML,
        }
        with mock_urlopen_serving({CHAPTER22_3_URL: json.dumps(payload)}):
            sections = self.adapter.list_sections(chapter_ref)

        # The merged repealed block keeps one entry for its first section
        # (22-3-6); the different-title cross-ref (3-5) is excluded. The
        # trailing sort is the shared Illinois-style key (leading integer,
        # then raw string), so 22-3-10 sorts before 22-3-6.
        assert [n.identifier for n in sections] == ["22-3-1", "22-3-1.1", "22-3-10", "22-3-6"]
        assert [n.name for n in sections] == [
            "Persons capable of committing crimes--Exceptions.",
            "Voluntary consumption of alcohol or controlled substance not causing insanity.",
            "Arson-related cross chapter",
            "22-3-7 . Repealed by SL 1976, ch 158 , § 3-5",
        ]
        assert all(n.level == HierarchyLevel.SECTION for n in sections)
        assert all(n.ref.chapter == chapter_ref for n in sections)

    def test_list_sections_404_raises_ref_not_found(self) -> None:
        chapter_ref = ChapterRef(
            title=TitleRef(state_code="SD", identifier="99"), identifier="99"
        )
        url = "https://sdlegislature.gov/api/Statutes/Statute/99-99"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_sections(chapter_ref)

    def test_list_sections_missing_html_raises(self) -> None:
        chapter_ref = ChapterRef(
            title=TitleRef(state_code="SD", identifier="22"), identifier="3"
        )
        with mock_urlopen_serving({CHAPTER22_3_URL: json.dumps({"Statute": "22-3"})}):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_sections(chapter_ref)


class TestRetrieveSection:
    """Retrieval tests against synthetic JSON that matches the verified
    shapes documented in the adapter's module docstring."""

    def setup_method(self) -> None:
        self.adapter = SouthDakotaAdapter()
        self.ref = _make_ref("22-3-1")

    def test_full_retrieval_citation_heading_body_history(self) -> None:
        with mock_urlopen_serving({SECTION22_3_1_URL: json.dumps(SYNTHETIC_SECTION_JSON)}):
            section = self.adapter.retrieve_section(self.ref)

        assert section.citation.raw == "SDCL § 22-3-1"
        assert section.citation.state_code == "SD"
        assert section.ref == self.ref
        assert (
            section.heading == "Persons capable of committing crimes--Exceptions."
        )
        assert (
            section.text
            == "Any person is capable of committing a crime, except the following: "
            "(1) Children under the age of ten years; (2) Persons of unsound mind; "
            "(3) Persons who committed the act charged but who did not act with the "
            "mental state required for the offense."
        )
        assert section.amendment_notes == "Source: SDC 1939, § 13.0201; SL 1968, ch 28, §§ 1, 2."
        assert section.status.value == "unknown"
        assert section.source_url == SECTION22_3_1_URL
        assert section.retrieved_at is not None

    def test_repealed_flag_does_not_set_status(self) -> None:
        payload = json.loads(json.dumps(SYNTHETIC_SECTION_JSON))
        payload["Repealed"] = True
        with mock_urlopen_serving({SECTION22_3_1_URL: json.dumps(payload)}):
            section = self.adapter.retrieve_section(self.ref)

        assert section.status.value == "unknown"

    def test_title_mismatch_raises_ref_mismatch_error(self) -> None:
        payload = json.loads(json.dumps(SYNTHETIC_SECTION_JSON))
        payload["parents"][0]["Statute"] = "1"
        with mock_urlopen_serving({SECTION22_3_1_URL: json.dumps(payload)}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(self.ref)

    def test_chapter_mismatch_raises_ref_mismatch_error(self) -> None:
        payload = json.loads(json.dumps(SYNTHETIC_SECTION_JSON))
        payload["parents"][1]["Statute"] = "2"
        with mock_urlopen_serving({SECTION22_3_1_URL: json.dumps(payload)}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(self.ref)

    def test_section_mismatch_raises_ref_mismatch_error(self) -> None:
        payload = json.loads(json.dumps(SYNTHETIC_SECTION_JSON))
        payload["Statute"] = "22-3-99"
        with mock_urlopen_serving({SECTION22_3_1_URL: json.dumps(payload)}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(self.ref)

    def test_non_section_type_raises_normalization_error(self) -> None:
        payload = json.loads(json.dumps(SYNTHETIC_SECTION_JSON))
        payload["Type"] = "Chapter"
        with mock_urlopen_serving({SECTION22_3_1_URL: json.dumps(payload)}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(self.ref)

    def test_missing_parents_raises_normalization_error(self) -> None:
        payload = json.loads(json.dumps(SYNTHETIC_SECTION_JSON))
        del payload["parents"]
        with mock_urlopen_serving({SECTION22_3_1_URL: json.dumps(payload)}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(self.ref)

    def test_missing_html_raises_normalization_error(self) -> None:
        payload = json.loads(json.dumps(SYNTHETIC_SECTION_JSON))
        payload["Html"] = None
        with mock_urlopen_serving({SECTION22_3_1_URL: json.dumps(payload)}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(self.ref)

    def test_empty_body_after_cleaning_raises_normalization_error(self) -> None:
        payload = json.loads(json.dumps(SYNTHETIC_SECTION_JSON))
        payload["Html"] = "<html><body><p>22-3-1 . Heading</p></body></html>"
        with mock_urlopen_serving({SECTION22_3_1_URL: json.dumps(payload)}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(self.ref)

    def test_404_raises_ref_not_found(self) -> None:
        with mock_urlopen_error(_http_error(SECTION22_3_1_URL)):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(self.ref)

    def test_malformed_json_raises_adapter_unavailable_error(self) -> None:
        with mock_urlopen("this is not json"):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(self.ref)

    def test_network_failure_raises_adapter_unavailable_error(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(self.ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = SouthDakotaAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("22-3-1")
        parsed = ParsedDocument(
            raw_citation="SDCL § 22-3-1",
            heading="Persons capable of committing crimes--Exceptions.",
            text="Any person is capable of committing a crime...",
            amendment_notes="Source: SDC 1939, § 13.0201; SL 1968, ch 28, §§ 1, 2.",
            source_url=SECTION22_3_1_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "SDCL § 22-3-1"
        assert section.citation.state_code == "SD"
        assert section.heading == "Persons capable of committing crimes--Exceptions."
        assert section.text == "Any person is capable of committing a crime..."
        assert (
            section.amendment_notes == "Source: SDC 1939, § 13.0201; SL 1968, ch 28, §§ 1, 2."
        )
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="WA", identifier="49"),
                identifier="60",
            ),
            identifier="49.60.010",
        )
        parsed = ParsedDocument(
            raw_citation="SDCL § 22-3-1",
            text="Any person is capable of committing a crime...",
        )
        with pytest.raises(NormalizationError):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("22-3-1")
        parsed = ParsedDocument(
            raw_citation="SDCL § 22-3-99",
            text="Some other section's text.",
        )
        with pytest.raises(RefMismatchError):
            self.adapter.normalize(parsed, ref)