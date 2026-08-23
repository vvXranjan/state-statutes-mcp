"""Tests for NewMexicoAdapter.

The New Mexico Statutes Annotated (NMSA) 1978 at nmonesource.com is the
framework's third PDF-family source: discovery is server-rendered HTML
navigation pages listing all 84 chapters, and each chapter's full text is
served as one PDF document.

``TitleRef.identifier`` is the single synthetic title ``"NMSA"`` (the NMSA
has no Title level); ``ChapterRef.identifier`` is the chapter number
(``"1"``, ``"22A"``); ``SectionRef.identifier`` is the full
``{chapter}-{article}-{section}`` citation (``"1-2-1"``, ``"1-1-1.1"``),
with the Article level folded into the section identifier. The chapter's
opaque item ID is resolved dynamically from the navigation pages (never
hardcoded).

**Repealed behavior (VERIFIED)**: a repealed section renders as
``{citation}. Repealed.`` with no body, then a ``History:`` block (e.g.
``repealed by Laws 2019...``). Per the framework's prose-only-repeal rule
(same as Nebraska/Massachusetts/Kentucky), the catchline is the ``heading``,
``text=""``, ``status=UNKNOWN``, and the history is preserved in
``amendment_notes``.

**REAL trimmed fixtures**: the ``nm_*`` fixtures are verbatim captures of
the official host fetched live on Aug 23 2026 (see
``docs/research/new_mexico.md``). ``nm_ch1_sections.pdf`` and
``nm_ch2_sections.pdf`` are page-range subsets of the official chapter PDFs
re-saved with pypdf (the trimmed-capture pattern); ``nm_nav_page*.html`` are
the four official navigation pages.

Network tests mock the real network boundary
(``urllib.request.urlopen`` as imported by the shared ``_fetch`` helper),
never adapter internals. PDF fixtures are served as raw bytes via
``mock_urlopen_serving_bytes``.
"""

from __future__ import annotations

import io
import urllib.error
from pathlib import Path

import pytest

from _mock_network import mock_urlopen_error, mock_urlopen_serving_bytes

from state_statutes_mcp.adapters.new_mexico.adapter import NewMexicoAdapter
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

# --- REAL live fixtures: verbatim captures of the official host
# --- (nmonesource.com, fetched Aug 23 2026; see docs/research/new_mexico.md).
FIXTURES = Path(__file__).parent / "fixtures"

NAV_PAGE_1 = (FIXTURES / "nm_nav_page1.html").read_bytes()
NAV_PAGE_2 = (FIXTURES / "nm_nav_page2.html").read_bytes()
NAV_PAGE_3 = (FIXTURES / "nm_nav_page3.html").read_bytes()
NAV_PAGE_4 = (FIXTURES / "nm_nav_page4.html").read_bytes()
CH1_PDF = (FIXTURES / "nm_ch1_sections.pdf").read_bytes()
CH2_PDF = (FIXTURES / "nm_ch2_sections.pdf").read_bytes()

BASE = "https://nmonesource.com/nmos/nmsa/en"
NAV_URLS = {f"{BASE}/nav_date.do?iframe=true&page={i}": html for i, html in enumerate(
    [NAV_PAGE_1, NAV_PAGE_2, NAV_PAGE_3, NAV_PAGE_4], start=1
)}
CH1_URL = f"{BASE}/4351/1/document.do"
CH2_URL = f"{BASE}/4359/1/document.do"


def _title_ref(identifier: str = "NMSA") -> TitleRef:
    return TitleRef(state_code="NM", identifier=identifier)


def _chapter_ref(title: str = "NMSA", chapter: str = "1") -> ChapterRef:
    return ChapterRef(title=_title_ref(title), identifier=chapter)


def _make_ref(chapter: str = "1", section: str = "1-1-1") -> SectionRef:
    return SectionRef(chapter=_chapter_ref(chapter=chapter), identifier=section)


def _serve_all() -> dict[str, bytes]:
    """Serve every fixture used by the discovery + retrieval tests."""
    return {**NAV_URLS, CH1_URL: CH1_PDF, CH2_URL: CH2_PDF}


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert NewMexicoAdapter.__abstractmethods__ == frozenset()
        adapter = NewMexicoAdapter()
        assert adapter.state_code == "NM"
        assert adapter.state_name == "New Mexico"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = NewMexicoAdapter()

    def test_title_ref_url_is_first_nav_page(self) -> None:
        assert self.adapter.build_url(_title_ref()) == f"{BASE}/nav_date.do?iframe=true&page=1"

    def test_chapter_ref_url_resolves_opaque_item_id(self) -> None:
        with mock_urlopen_serving_bytes(NAV_URLS):
            assert self.adapter.build_url(_chapter_ref()) == CH1_URL

    def test_section_ref_url_resolves_to_chapter_pdf(self) -> None:
        with mock_urlopen_serving_bytes(NAV_URLS):
            assert self.adapter.build_url(_make_ref()) == CH1_URL

    def test_unknown_chapter_raises_ref_not_found(self) -> None:
        ref = _chapter_ref(chapter="999")
        with mock_urlopen_serving_bytes(NAV_URLS):
            with pytest.raises(RefNotFoundError, match="not listed"):
                self.adapter.build_url(ref)

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestChapterMap:
    def test_discovers_all_84_chapters(self) -> None:
        adapter = NewMexicoAdapter()
        with mock_urlopen_serving_bytes(NAV_URLS):
            mapping = adapter._chapter_map()
        assert len(mapping) == 84
        assert mapping["1"] == "4351"
        assert mapping["2"] == "4359"
        assert "22A" in mapping

    def test_no_rows_raises_adapter_unavailable(self) -> None:
        adapter = NewMexicoAdapter()
        empty = {k: b"<html></html>" for k in NAV_URLS}
        with mock_urlopen_serving_bytes(empty):
            with pytest.raises(AdapterUnavailableError, match="no usable chapter"):
                adapter._chapter_map()


class TestListTitles:
    def test_returns_synthetic_title(self) -> None:
        adapter = NewMexicoAdapter()
        titles = adapter.list_titles()
        assert len(titles) == 1
        assert titles[0].identifier == "NMSA"
        assert titles[0].name == "New Mexico Statutes Annotated 1978"
        assert titles[0].level == HierarchyLevel.TITLE


class TestListChapters:
    def test_returns_84_chapters(self) -> None:
        adapter = NewMexicoAdapter()
        with mock_urlopen_serving_bytes(NAV_URLS):
            chapters = adapter.list_chapters(_title_ref())

        assert len(chapters) == 84
        ch1 = next(c for c in chapters if c.identifier == "1")
        assert ch1.name == "Chapter 1"
        assert any(c.identifier == "22A" for c in chapters)
        assert all(c.level == HierarchyLevel.CHAPTER for c in chapters)
        assert all(c.ref.title == _title_ref() for c in chapters)

    def test_non_synthetic_title_raises_ref_not_found(self) -> None:
        adapter = NewMexicoAdapter()
        with pytest.raises(RefNotFoundError, match="synthetic title"):
            adapter.list_chapters(_title_ref("NOTNMSA"))


class TestListSections:
    def test_returns_sections_from_chapter_pdf(self) -> None:
        adapter = NewMexicoAdapter()
        chapter = _chapter_ref()
        served = {**NAV_URLS, CH1_URL: CH1_PDF}
        with mock_urlopen_serving_bytes(served):
            sections = adapter.list_sections(chapter)

        ids = [s.identifier for s in sections]
        assert "1-1-1" in ids and "1-1-1.1" in ids and "1-2-8" in ids
        s111 = next(s for s in sections if s.identifier == "1-1-1")
        assert s111.name == "Election Code."
        assert all(s.level == HierarchyLevel.SECTION for s in sections)
        assert all(s.ref.chapter == chapter for s in sections)

    def test_unknown_chapter_raises_ref_not_found(self) -> None:
        adapter = NewMexicoAdapter()
        chapter = _chapter_ref(chapter="999")
        with mock_urlopen_serving_bytes(NAV_URLS):
            with pytest.raises(RefNotFoundError, match="not listed"):
                adapter.list_sections(chapter)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = NewMexicoAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_sections(_chapter_ref())


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = NewMexicoAdapter()

    def test_full_retrieval_normal_section(self) -> None:
        ref = _make_ref()
        with mock_urlopen_serving_bytes(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "NM Stat. Ann. 1-1-1"
        assert section.citation.state_code == "NM"
        assert section.ref == ref
        assert section.heading == "Election Code."
        assert section.text == (
            'Chapter 1 NMSA 1978 may be cited as the "Election Code".'
        )
        assert section.status.value == "unknown"
        assert section.amendment_notes == (
            "1953 Comp., § 3-1-1, enacted by Laws 1969, ch. 240, § 1; "
            "1975, ch. 255, § 1."
        )
        assert section.source_url == CH1_URL
        assert section.retrieved_at is not None

    def test_decimal_section_retrieval(self) -> None:
        ref = _make_ref(section="1-1-1.1")
        with mock_urlopen_serving_bytes(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "NM Stat. Ann. 1-1-1.1"
        assert section.heading == "Purpose of [Election] Code."
        assert section.text.startswith(
            "It is the purpose of the Election Code"
        )
        assert section.amendment_notes == (
            "1978 Comp., § 1-1-1.1, enacted by Laws 1979, ch. 74, § 1."
        )

    def test_repealed_section_empty_body_with_history(self) -> None:
        ref = _make_ref(section="1-2-8")
        with mock_urlopen_serving_bytes(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "NM Stat. Ann. 1-2-8"
        assert section.heading == "Repealed."
        assert section.text == ""
        assert section.status.value == "unknown"
        assert "repealed by Laws 2019, ch. 212, § 284" in section.amendment_notes

    def test_section_boundary_does_not_consume_next_section(self) -> None:
        # 1-1-1 must end before 1-1-1.1, and 1-2-1 (multi-subsection) must
        # not leak into 1-2-2.
        ref = _make_ref(section="1-1-1")
        with mock_urlopen_serving_bytes(_serve_all()):
            section = self.adapter.retrieve_section(ref)
        assert "1-1-1.1" not in section.text
        assert "Purpose of" not in section.text

        ref = _make_ref(section="1-2-1")
        with mock_urlopen_serving_bytes(_serve_all()):
            section = self.adapter.retrieve_section(ref)
        assert section.heading == "Secretary of state; chief election officer; rules."
        assert section.text.startswith("A. The secretary of state is the chief election officer")
        assert "1-2-2" not in section.text

    def test_cross_chapter_section_retrieval(self) -> None:
        ref = _make_ref(chapter="2", section="2-1-1")
        served = {**NAV_URLS, CH2_URL: CH2_PDF}
        with mock_urlopen_serving_bytes(served):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "NM Stat. Ann. 2-1-1"
        assert section.heading == "[Resignation of members.]"
        assert section.text.startswith("Any member of the legislature")

    def test_missing_section_raises_ref_not_found(self) -> None:
        ref = _make_ref(section="1-2-99")
        with mock_urlopen_serving_bytes(_serve_all()):
            with pytest.raises(RefNotFoundError, match="not find section"):
                self.adapter.retrieve_section(ref)

    def test_wrong_chapter_prefix_raises_ref_not_found(self) -> None:
        # Requesting a chapter-2 citation while pointing at chapter 1 must
        # not silently return content: the chapter prefix must match.
        ref = _make_ref(section="2-1-1")
        with mock_urlopen_serving_bytes(_serve_all()):
            with pytest.raises(RefNotFoundError, match="not find section"):
                self.adapter.retrieve_section(ref)

    def test_chapter_404_maps_to_ref_not_found(self) -> None:
        ref = _make_ref()
        error = urllib.error.HTTPError(CH1_URL, 404, "Not Found", {}, io.BytesIO(b""))

        from unittest import mock

        class _Fake:
            def __init__(self, d=None, exc=None):
                self._d = d
                self._exc = exc

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

            def read(self):
                if self._exc is not None:
                    raise self._exc
                return self._d

        def fake_urlopen(requested_url, timeout=None):
            if requested_url in NAV_URLS:
                return _Fake(d=NAV_URLS[requested_url])
            raise error

        with mock.patch(
            "state_statutes_mcp.adapters._fetch.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            with pytest.raises(RefNotFoundError, match="HTTP 404"):
                self.adapter.retrieve_section(ref)

    def test_non_pdf_response_raises_ref_not_found(self) -> None:
        ref = _make_ref()
        served = {**NAV_URLS, CH1_URL: b"<html>not a pdf</html>"}
        with mock_urlopen_serving_bytes(served):
            with pytest.raises(RefNotFoundError, match="non-PDF"):
                self.adapter.retrieve_section(ref)

    def test_malformed_pdf_raises_adapter_unavailable(self) -> None:
        ref = _make_ref()
        served = {**NAV_URLS, CH1_URL: b"%PDF-1.4 garbage not a real pdf"}
        with mock_urlopen_serving_bytes(served):
            with pytest.raises(AdapterUnavailableError, match="Could not extract"):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        ref = _make_ref()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = NewMexicoAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref()
        parsed = ParsedDocument(
            raw_citation="NM Stat. Ann. 1-1-1",
            heading="Election Code.",
            text="Chapter 1 NMSA 1978 may be cited as the Election Code.",
            amendment_notes="1953 Comp., § 3-1-1",
            source_url=CH1_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "NM Stat. Ann. 1-1-1"
        assert section.citation.state_code == "NM"
        assert section.heading == "Election Code."
        assert section.status.value == "unknown"
        assert section.amendment_notes == "1953 Comp., § 3-1-1"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="NV", identifier="NMSA"),
                identifier="1",
            ),
            identifier="1-1-1",
        )
        parsed = ParsedDocument(raw_citation="NM Stat. Ann. 1-1-1", text="Some text.")
        with pytest.raises(NormalizationError, match="expected 'NM'"):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref()
        parsed = ParsedDocument(raw_citation="NM Stat. Ann. 1-1-2", text="Some text.")
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, ref)


class TestHierarchyMapping:
    def test_title_chapter_section_chain_descends(self) -> None:
        adapter = NewMexicoAdapter()
        with mock_urlopen_serving_bytes(_serve_all()):
            titles = adapter.list_titles()
            title = titles[0].ref
            assert isinstance(title, TitleRef)
            assert title.state_code == "NM"

            chapters = adapter.list_chapters(title)
            assert all(c.ref.title == title for c in chapters)
            chapter = next(c.ref for c in chapters if c.identifier == "1")
            assert isinstance(chapter, ChapterRef)
            assert chapter.title == title

            sections = adapter.list_sections(chapter)
            assert all(s.ref.chapter.title == title for s in sections)
            assert all(s.ref.chapter == chapter for s in sections)

            section = next(s.ref for s in sections if s.identifier == "1-1-1")
            retrieved = adapter.retrieve_section(section)
            assert retrieved.citation.raw == "NM Stat. Ann. 1-1-1"
            assert retrieved.heading == "Election Code."