"""Tests for NewHampshireAdapter.

New Hampshire is a chapter-document HTML source (the official New
Hampshire Revised Statutes Annotated publication at gc.nh.gov). Hierarchy
is Title -> Chapter -> Section. The title index (``/rsa/html/nhtoc.htm``)
lists the titles by Roman numeral (framework identifiers remain Arabic,
e.g. ``"16"``) and their chapter links. Chapter documents use the verified
``/rsa/html/{roman}/{chapter}/{chapter}-mrg.htm`` form (e.g.
``/rsa/html/xvi/201-a/201-a-mrg.htm`` for lettered chapter ``201-A``) and
contain the chapter's sections, each marked by a ``Section {c}:{s}``
heading followed by the section's own heading (``{c}:{s} {Caption}.``),
body, and a ``Source.`` history line. Repealed sections and repealed
ranges appear inline. ``SectionRef.identifier`` is the full
``{chapter}:{section}`` form (e.g. ``"201-A:1"``).

**SYNTHETIC fixtures**: Wayback retrieval was unavailable from the
implementation environment for this batch, so the ``nh_*`` fixtures are
synthetic and representative -- they reproduce ONLY the structures verified
by the research source of truth for this adapter (see
``docs/research/new_hampshire.md``). They are NOT official government
captures.

Section-retrieval and section-discovery tests exercise the adapter's real
fetch -> parse path against these synthetic fixtures. All tests are fully
offline: the real network boundary (``urllib.request.urlopen`` as imported
by the shared ``_fetch`` helper) is mocked, never adapter internals.
"""

from __future__ import annotations

import io
import urllib.error
from pathlib import Path

import pytest

from _mock_network import mock_urlopen, mock_urlopen_error, mock_urlopen_serving

from state_statutes_mcp.adapters.new_hampshire.adapter import NewHampshireAdapter
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

# --- SYNTHETIC fixtures: representative markup reproducing ONLY the
# --- VERIFIED New Hampshire structures (see docs/research/new_hampshire.md).
# --- NOT official government captures.
FIXTURES = Path(__file__).parent / "fixtures"

NH_TOC_HTML = (FIXTURES / "nh_nhtoc.html").read_text(encoding="utf-8")
NH_CH201_HTML = (FIXTURES / "nh_chapter201.html").read_text(encoding="utf-8")
NH_CH201A_HTML = (FIXTURES / "nh_chapter201a.html").read_text(encoding="utf-8")

BASE = "https://gc.nh.gov"

TOC_URL = f"{BASE}/rsa/html/nhtoc.htm"
CH201_URL = f"{BASE}/rsa/html/xvi/201/201-mrg.htm"
CH201A_URL = f"{BASE}/rsa/html/xvi/201-a/201-a-mrg.htm"


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the shared fetch helper will
    wrap into ``AdapterUnavailableError`` with ``__cause__`` set to it."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


def _title_ref() -> TitleRef:
    return TitleRef(state_code="NH", identifier="16")


def _chapter_ref() -> ChapterRef:
    return ChapterRef(title=_title_ref(), identifier="201")


def _chapter_ref_a() -> ChapterRef:
    return ChapterRef(title=_title_ref(), identifier="201-A")


def _make_ref(section: str) -> SectionRef:
    return SectionRef(chapter=_chapter_ref_a(), identifier=section)


def _make_ref_201(section: str) -> SectionRef:
    return SectionRef(chapter=_chapter_ref(), identifier=section)


def _serve_all() -> dict[str, str]:
    return {
        TOC_URL: NH_TOC_HTML,
        CH201_URL: NH_CH201_HTML,
        CH201A_URL: NH_CH201A_HTML,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert NewHampshireAdapter.__abstractmethods__ == frozenset()
        adapter = NewHampshireAdapter()
        assert adapter.state_code == "NH"
        assert adapter.state_name == "New Hampshire"


class TestRomanConversion:
    def test_arabic_to_roman_16_is_xvi(self) -> None:
        # VERIFIED: source title directories use Roman numerals (16 -> xvi).
        assert NewHampshireAdapter._arabic_to_roman(16) == "xvi"

    def test_arabic_to_roman_17_is_xvii(self) -> None:
        assert NewHampshireAdapter._arabic_to_roman(17) == "xvii"

    def test_roman_to_arabic_xvi_is_16(self) -> None:
        assert NewHampshireAdapter._roman_to_arabic("XVI") == 16

    def test_roman_round_trip(self) -> None:
        for number in (1, 4, 9, 16, 17, 40, 52):
            roman = NewHampshireAdapter._arabic_to_roman(number)
            assert NewHampshireAdapter._roman_to_arabic(roman) == number


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = NewHampshireAdapter()

    def test_title_ref_url_is_nhtoc(self) -> None:
        assert (
            self.adapter.build_url(_title_ref())
            == "https://gc.nh.gov/rsa/html/nhtoc.htm"
        )

    def test_chapter_ref_url_uses_roman_title_directory(self) -> None:
        # VERIFIED example: /rsa/html/xvi/201-a/201-a-mrg.htm -- the title
        # directory is the Roman numeral (16 -> xvi).
        assert (
            self.adapter.build_url(_chapter_ref())
            == "https://gc.nh.gov/rsa/html/xvi/201/201-mrg.htm"
        )

    def test_lettered_chapter_ref_url_lowercases_directory(self) -> None:
        # VERIFIED: lettered chapter 201-A -> directory 201-a.
        assert (
            self.adapter.build_url(_chapter_ref_a())
            == "https://gc.nh.gov/rsa/html/xvi/201-a/201-a-mrg.htm"
        )

    def test_section_ref_url_is_chapter_document(self) -> None:
        # Sections are embedded in their chapter document, so the chapter
        # document is the closest real resource.
        assert (
            self.adapter.build_url(_make_ref("201-A:1"))
            == "https://gc.nh.gov/rsa/html/xvi/201-a/201-a-mrg.htm"
        )

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestListTitles:
    def test_returns_titles_with_arabic_identifiers(self) -> None:
        adapter = NewHampshireAdapter()
        with mock_urlopen_serving({TOC_URL: NH_TOC_HTML}):
            titles = adapter.list_titles()

        # VERIFIED: framework identifiers remain Arabic even though the
        # source title directories use Roman numerals.
        assert [n.identifier for n in titles] == ["16", "17"]
        assert titles[0].name == "Libraries and Archives"
        assert titles[1].name == "Conservation"
        assert all(n.level == HierarchyLevel.TITLE for n in titles)
        assert all(n.ref.state_code == "NH" for n in titles)

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = NewHampshireAdapter()
        with mock_urlopen("<html><body>no titles</body></html>"):
            with pytest.raises(AdapterUnavailableError, match="no usable title"):
                adapter.list_titles()

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = NewHampshireAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_titles()


class TestListChapters:
    def test_returns_chapters_under_title(self) -> None:
        adapter = NewHampshireAdapter()
        with mock_urlopen_serving({TOC_URL: NH_TOC_HTML}):
            chapters = adapter.list_chapters(_title_ref())

        assert [n.identifier for n in chapters] == ["201", "201-A"]
        assert chapters[0].name == "Library Directors"
        assert chapters[1].name == "Library Trustees"
        assert all(n.level == HierarchyLevel.CHAPTER for n in chapters)
        assert all(n.ref.title == _title_ref() for n in chapters)

    def test_lettered_chapter_identifier_preserved(self) -> None:
        adapter = NewHampshireAdapter()
        with mock_urlopen_serving({TOC_URL: NH_TOC_HTML}):
            chapters = adapter.list_chapters(_title_ref())
        by_id = {n.identifier: n for n in chapters}
        assert "201-A" in by_id

    def test_unknown_title_raises_ref_not_found(self) -> None:
        adapter = NewHampshireAdapter()
        ref = TitleRef(state_code="NH", identifier="99")
        with mock_urlopen_serving({TOC_URL: NH_TOC_HTML}):
            with pytest.raises(RefNotFoundError, match="lists no title '99'"):
                adapter.list_chapters(ref)

    def test_title_with_no_chapters_raises_adapter_unavailable(self) -> None:
        adapter = NewHampshireAdapter()
        html = "<html><body><p><b>TITLE XVI</b> Empty</p></body></html>"
        with mock_urlopen_serving({TOC_URL: html}):
            with pytest.raises(AdapterUnavailableError, match="no usable chapter"):
                adapter.list_chapters(_title_ref())

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = NewHampshireAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_chapters(_title_ref())


class TestListSections:
    def test_returns_sections_from_chapter_document(self) -> None:
        adapter = NewHampshireAdapter()
        with mock_urlopen_serving({CH201_URL: NH_CH201_HTML}):
            sections = adapter.list_sections(_chapter_ref())

        assert [n.identifier for n in sections] == ["201:1", "201:2"]
        assert sections[0].name == "Definitions."
        assert sections[1].name == "Library Directors."
        assert all(n.level == HierarchyLevel.SECTION for n in sections)
        assert all(n.ref.chapter == _chapter_ref() for n in sections)

    def test_lettered_chapter_includes_repealed_inline(self) -> None:
        # VERIFIED: repealed sections and repealed ranges appear inline.
        adapter = NewHampshireAdapter()
        with mock_urlopen_serving({CH201A_URL: NH_CH201A_HTML}):
            sections = adapter.list_sections(_chapter_ref_a())

        assert [n.identifier for n in sections] == ["201-A:1", "201-A:2", "201-A:3"]
        assert sections[0].name == "Definitions."
        # The repealed single section and the repealed range keep their
        # annotations verbatim in the listing names.
        assert "Repealed" in sections[1].name
        assert "Repealed" in sections[2].name
        assert sections[2].name == "to 201-A:5 [Repealed.]"

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = NewHampshireAdapter()
        with mock_urlopen_error(_http_error(CH201A_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_sections(_chapter_ref_a())

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = NewHampshireAdapter()
        with mock_urlopen_serving({CH201A_URL: "<html><body>none</body></html>"}):
            with pytest.raises(AdapterUnavailableError, match="no usable section"):
                adapter.list_sections(_chapter_ref_a())


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = NewHampshireAdapter()

    def test_lettered_chapter_full_retrieval(self) -> None:
        ref = _make_ref("201-A:1")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "RSA 201-A:1"
        assert section.citation.state_code == "NH"
        assert section.ref == ref
        assert section.heading == "Definitions."
        assert '"trustee" means a member of a board of library trustees.' in (
            section.text
        )
        # VERIFIED: history is a 'Source.' line.
        assert section.amendment_notes == "Source. 1971, 224:1, eff. Aug. 22, 1971."
        assert section.status.value == "unknown"
        assert section.source_url == CH201A_URL
        assert section.retrieved_at is not None

    def test_unlettered_chapter_retrieval(self) -> None:
        ref = _make_ref_201("201:2")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "RSA 201:2"
        assert section.heading == "Library Directors."
        assert "shall appoint a library director" in section.text
        assert section.amendment_notes == (
            "Source. 1971, 224:1. 1981, 456:3, eff. June 23, 1981."
        )

    def test_repealed_single_section_inline(self) -> None:
        ref = _make_ref("201-A:2")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "RSA 201-A:2"
        assert section.heading == "[Repealed 2005, 210:1, eff. Jan. 1, 2006.]"
        assert section.text == "Repealed."
        # Repealed sections have no 'Source.' line; the annotation is
        # prose-level, so status stays UNKNOWN per the framework rule.
        assert section.amendment_notes is None
        assert section.status.value == "unknown"

    def test_repealed_range_inline(self) -> None:
        ref = _make_ref("201-A:3")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "RSA 201-A:3"
        assert section.heading == "to 201-A:5 [Repealed.]"
        assert section.text == "Repealed."
        assert section.status.value == "unknown"

    def test_missing_section_raises_ref_not_found(self) -> None:
        ref = _make_ref("201-A:99")
        with mock_urlopen_serving({CH201A_URL: NH_CH201A_HTML}):
            with pytest.raises(RefNotFoundError, match="contains no section"):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        ref = _make_ref("201-A:1")
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)


class TestParseEdgeCases:
    def setup_method(self) -> None:
        self.adapter = NewHampshireAdapter()

    def test_heading_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        # The marker resolves the section, but its own heading names a
        # different citation -- a silent mismatch the adapter must reject.
        ref = _make_ref("201-A:1")
        html = (
            "<html><body>"
            "<p><b>Section 201-A:1</b></p>"
            "<p><b>201-A:9 Different section.</b></p>"
            "<p>Some body text.</p>"
            "</body></html>"
        )
        with mock_urlopen_serving({CH201A_URL: html}):
            with pytest.raises(RefMismatchError, match="does not match"):
                self.adapter.retrieve_section(ref)

    def test_missing_heading_raises_normalization_error(self) -> None:
        ref = _make_ref("201-A:1")
        html = (
            "<html><body>"
            "<p><b>Section 201-A:1</b></p>"
            "<p>Body with no heading element.</p>"
            "</body></html>"
        )
        with mock_urlopen_serving({CH201A_URL: html}):
            with pytest.raises(NormalizationError, match="no heading element"):
                self.adapter.retrieve_section(ref)

    def test_empty_body_raises_normalization_error(self) -> None:
        ref = _make_ref("201-A:1")
        html = (
            "<html><body>"
            "<p><b>Section 201-A:1</b></p>"
            "<p><b>201-A:1 Definitions.</b></p>"
            "</body></html>"
        )
        with mock_urlopen_serving({CH201A_URL: html}):
            with pytest.raises(NormalizationError, match="body text was empty"):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = NewHampshireAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("201-A:1")
        parsed = ParsedDocument(
            raw_citation="RSA 201-A:1",
            heading="Definitions.",
            text="In this chapter ...",
            amendment_notes="Source. 1971, 224:1.",
            source_url=CH201A_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "RSA 201-A:1"
        assert section.citation.state_code == "NH"
        assert section.heading == "Definitions."
        assert section.amendment_notes == "Source. 1971, 224:1."
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="NV", identifier="x"), identifier="220"
            ),
            identifier="201-A:1",
        )
        parsed = ParsedDocument(
            raw_citation="RSA 201-A:1",
            text="Some text.",
        )
        with pytest.raises(NormalizationError, match="expected 'NH'"):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("201-A:1")
        parsed = ParsedDocument(
            raw_citation="RSA 201-A:2",
            text="Some other section's text.",
        )
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, ref)