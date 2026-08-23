"""Tests for OklahomaAdapter.

The Oklahoma Statutes (oklegislature.gov) is the framework's fourth
PDF-family source: a title index lists per-title PDFs
(``OK_Statutes/CompleteTitles/os{N}.pdf``), and each title's full text is
served as one PDF.

Oklahoma's hierarchy is heterogeneous (VERIFIED):

* FLAT titles (the majority, e.g. Title 21): ``Title -> Section``, with
  citations like ``21-701.7``. A single synthetic chapter whose identifier
  equals the title number is exposed.
* CHAPTERED titles (e.g. Title 2): ``Title -> Chapter -> Section``, with
  citations like ``2-1-1``. Real chapters are exposed.

``SectionRef.identifier`` is always the full Oklahoma citation.

**REAL trimmed fixtures**: the ``ok_*`` fixtures are page-range subsets of
the official per-title PDFs (captured live Aug 23 2026; see
``docs/research/oklahoma.md``), re-saved with pypdf. ``ok_title_index.html``
is the official title index. They are NOT synthetic.

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

from state_statutes_mcp.adapters.oklahoma.adapter import OklahomaAdapter
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

# --- REAL live fixtures: page-range subsets of the official per-title PDFs
# --- and the official title index (fetched Aug 23 2026; see docs/research/oklahoma.md).
FIXTURES = Path(__file__).parent / "fixtures"

TITLE_INDEX_HTML = (FIXTURES / "ok_title_index.html").read_bytes()
T21_701_7_PDF = (FIXTURES / "ok_title21_section_701.7.pdf").read_bytes()
T21_REPEALED_PDF = (FIXTURES / "ok_title21_repealed.pdf").read_bytes()
T2_CH1_PDF = (FIXTURES / "ok_title2_ch1.pdf").read_bytes()
T2_CH2_PDF = (FIXTURES / "ok_title2_ch2_sections.pdf").read_bytes()
T3A_PDF = (FIXTURES / "ok_title3A_lettered.pdf").read_bytes()

BASE = "https://www.oklegislature.gov"
INDEX_URL = f"{BASE}/osStatuesTitle.html"
T21_URL = f"{BASE}/OK_Statutes/CompleteTitles/os21.pdf"
T2_URL = f"{BASE}/OK_Statutes/CompleteTitles/os2.pdf"
T3A_URL = f"{BASE}/OK_Statutes/CompleteTitles/os3A.pdf"


def _title_ref(identifier: str = "21") -> TitleRef:
    return TitleRef(state_code="OK", identifier=identifier)


def _chapter_ref(title: str = "21", chapter: str = "21") -> ChapterRef:
    return ChapterRef(title=_title_ref(title), identifier=chapter)


def _make_ref(chapter: str = "21", section: str = "21-701.7") -> SectionRef:
    return SectionRef(chapter=_chapter_ref(chapter=chapter), identifier=section)


def _serve_all() -> dict[str, bytes]:
    """Serve every fixture used by the discovery + retrieval tests."""
    return {
        INDEX_URL: TITLE_INDEX_HTML,
        T21_URL: T21_701_7_PDF,
        T2_URL: T2_CH1_PDF,
        T3A_URL: T3A_PDF,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert OklahomaAdapter.__abstractmethods__ == frozenset()
        adapter = OklahomaAdapter()
        assert adapter.state_code == "OK"
        assert adapter.state_name == "Oklahoma"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = OklahomaAdapter()

    def test_title_ref_url(self) -> None:
        assert self.adapter.build_url(_title_ref("21")) == T21_URL

    def test_chapter_ref_url(self) -> None:
        assert self.adapter.build_url(_chapter_ref()) == T21_URL

    def test_section_ref_url(self) -> None:
        assert self.adapter.build_url(_make_ref()) == T21_URL

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestListTitles:
    def test_discovers_all_titles_with_lettered_and_gaps(self) -> None:
        adapter = OklahomaAdapter()
        with mock_urlopen_serving_bytes({INDEX_URL: TITLE_INDEX_HTML}):
            titles = adapter.list_titles()

        identifiers = [t.identifier for t in titles]
        assert "1" in identifiers and "2" in identifiers and "21" in identifiers
        assert "3A" in identifiers and "74E" in identifiers and "85A" in identifiers
        assert "35" not in identifiers and "48" not in identifiers  # gaps
        assert all(t.level == HierarchyLevel.TITLE for t in titles)
        assert all(t.ref.state_code == "OK" for t in titles)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = OklahomaAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_titles()

    def test_empty_index_raises_adapter_unavailable(self) -> None:
        adapter = OklahomaAdapter()
        with mock_urlopen_serving_bytes({INDEX_URL: b"<html></html>"}):
            with pytest.raises(AdapterUnavailableError, match="no usable"):
                adapter.list_titles()


class TestListChapters:
    def test_flat_title_returns_synthetic_chapter_equal_to_title(self) -> None:
        adapter = OklahomaAdapter()
        served = {T21_URL: T21_701_7_PDF}
        with mock_urlopen_serving_bytes(served):
            chapters = adapter.list_chapters(_title_ref("21"))

        assert len(chapters) == 1
        assert chapters[0].identifier == "21"
        assert chapters[0].name == "Title 21 sections"
        assert chapters[0].level == HierarchyLevel.CHAPTER

    def test_chaptered_title_returns_real_chapters(self) -> None:
        adapter = OklahomaAdapter()
        served = {T2_URL: T2_CH2_PDF}
        with mock_urlopen_serving_bytes(served):
            chapters = adapter.list_chapters(_title_ref("2"))

        identifiers = [c.identifier for c in chapters]
        assert "2" in identifiers
        assert all(c.level == HierarchyLevel.CHAPTER for c in chapters)

    def test_lettered_title_returns_synthetic_chapter(self) -> None:
        adapter = OklahomaAdapter()
        served = {T3A_URL: T3A_PDF}
        with mock_urlopen_serving_bytes(served):
            chapters = adapter.list_chapters(_title_ref("3A"))

        assert len(chapters) == 1
        assert chapters[0].identifier == "3A"

    def test_missing_title_pdf_404_raises_ref_not_found(self) -> None:
        adapter = OklahomaAdapter()
        error = urllib.error.HTTPError(
            "https://www.oklegislature.gov/OK_Statutes/CompleteTitles/os999.pdf",
            404, "Not Found", {}, io.BytesIO(b""),
        )

        from unittest import mock

        class _Fake:
            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

            def read(self):
                raise error

        with mock.patch(
            "state_statutes_mcp.adapters._fetch.urllib.request.urlopen",
            side_effect=lambda url, timeout=None: _Fake(),
        ):
            with pytest.raises(RefNotFoundError, match="HTTP 404"):
                adapter.list_chapters(_title_ref("999"))


class TestListSections:
    def test_flat_title_lists_full_citation_sections(self) -> None:
        adapter = OklahomaAdapter()
        served = {T21_URL: T21_701_7_PDF}
        with mock_urlopen_serving_bytes(served):
            sections = adapter.list_sections(_chapter_ref("21", "21"))

        ids = [s.identifier for s in sections]
        assert "21-701.7" in ids
        assert all(s.level == HierarchyLevel.SECTION for s in sections)
        assert all(s.ref.chapter == _chapter_ref("21", "21") for s in sections)

    def test_chaptered_title_filters_to_requested_chapter(self) -> None:
        adapter = OklahomaAdapter()
        served = {T2_URL: T2_CH1_PDF}
        chapter = ChapterRef(title=_title_ref("2"), identifier="1")
        with mock_urlopen_serving_bytes(served):
            sections = adapter.list_sections(chapter)

        ids = [s.identifier for s in sections]
        assert "2-1-1" in ids
        assert all(s.identifier.startswith("2-1-") for s in sections)


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = OklahomaAdapter()

    def test_flat_title_normal_section(self) -> None:
        ref = _make_ref()
        served = {T21_URL: T21_701_7_PDF}
        with mock_urlopen_serving_bytes(served):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Okla. Stat. tit. 21, § 21-701.7"
        assert section.citation.state_code == "OK"
        assert section.ref == ref
        assert section.heading == "Murder in the first degree."
        assert section.text.startswith(
            "A.  A person commits murder in the first degree"
        )
        assert "Oklahoma Statutes - Title" not in section.text
        assert section.status.value == "unknown"
        assert section.amendment_notes is not None
        assert "Added by Laws 1976" in section.amendment_notes
        assert section.source_url == T21_URL
        assert section.retrieved_at is not None

    def test_flat_title_repealed_section(self) -> None:
        ref = _make_ref(section="21-12")
        served = {T21_URL: T21_REPEALED_PDF}
        with mock_urlopen_serving_bytes(served):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Okla. Stat. tit. 21, § 21-12"
        assert section.heading.startswith("Repealed by Laws 1999")
        assert section.text == ""
        assert section.status.value == "unknown"

    def test_chaptered_title_normal_section(self) -> None:
        ref = SectionRef(
            chapter=ChapterRef(title=_title_ref("2"), identifier="1"),
            identifier="2-1-1",
        )
        served = {T2_URL: T2_CH1_PDF}
        with mock_urlopen_serving_bytes(served):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Okla. Stat. tit. 2, § 2-1-1"
        assert section.heading == "Short title."
        assert section.text == (
            "This act shall be known as the Oklahoma Agricultural Code."
        )
        assert section.status.value == "unknown"

    def test_decimal_section(self) -> None:
        ref = SectionRef(
            chapter=ChapterRef(title=_title_ref("2"), identifier="2"),
            identifier="2-2-17.1",
        )
        served = {T2_URL: T2_CH2_PDF}
        with mock_urlopen_serving_bytes(served):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Okla. Stat. tit. 2, § 2-2-17.1"
        assert section.heading.startswith("False statements, etc.")
        assert section.text.startswith("In addition to other penalties")

    def test_lettered_section(self) -> None:
        ref = SectionRef(
            chapter=ChapterRef(title=_title_ref("2"), identifier="2"),
            identifier="2-2-17A",
        )
        served = {T2_URL: T2_CH2_PDF}
        with mock_urlopen_serving_bytes(served):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Okla. Stat. tit. 2, § 2-2-17A"
        assert section.heading.startswith("Repealed by Laws 2000")
        assert section.text == ""

    def test_repealed_section(self) -> None:
        ref = SectionRef(
            chapter=ChapterRef(title=_title_ref("2"), identifier="2"),
            identifier="2-2-17",
        )
        served = {T2_URL: T2_CH2_PDF}
        with mock_urlopen_serving_bytes(served):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Okla. Stat. tit. 2, § 2-2-17"
        assert section.heading.startswith("Repealed by Laws 2000")
        assert section.text == ""

    def test_renumbered_section(self) -> None:
        ref = SectionRef(
            chapter=ChapterRef(title=_title_ref("2"), identifier="2"),
            identifier="2-2-19",
        )
        served = {T2_URL: T2_CH2_PDF}
        with mock_urlopen_serving_bytes(served):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Okla. Stat. tit. 2, § 2-2-19"
        assert section.heading.startswith("Renumbered as § 14-81")
        assert section.text == ""

    def test_lettered_title_section(self) -> None:
        ref = SectionRef(
            chapter=ChapterRef(title=_title_ref("3A"), identifier="3A"),
            identifier="3A-201",
        )
        served = {T3A_URL: T3A_PDF}
        with mock_urlopen_serving_bytes(served):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Okla. Stat. tit. 3A, § 3A-201"
        assert section.heading.startswith("Oklahoma Horse Racing Commission")

    def test_missing_section_raises_ref_not_found(self) -> None:
        ref = _make_ref(section="21-9999")
        served = {T21_URL: T21_701_7_PDF}
        with mock_urlopen_serving_bytes(served):
            with pytest.raises(RefNotFoundError, match="not find section"):
                self.adapter.retrieve_section(ref)

    def test_title_404_maps_to_ref_not_found(self) -> None:
        ref = _make_ref()
        error = urllib.error.HTTPError(T21_URL, 404, "Not Found", {}, io.BytesIO(b""))

        from unittest import mock

        class _Fake:
            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

            def read(self):
                raise error

        with mock.patch(
            "state_statutes_mcp.adapters._fetch.urllib.request.urlopen",
            side_effect=lambda url, timeout=None: _Fake(),
        ):
            with pytest.raises(RefNotFoundError, match="HTTP 404"):
                self.adapter.retrieve_section(ref)

    def test_non_pdf_response_raises_ref_not_found(self) -> None:
        ref = _make_ref()
        served = {T21_URL: b"<html>not a pdf</html>"}
        with mock_urlopen_serving_bytes(served):
            with pytest.raises(RefNotFoundError, match="non-PDF"):
                self.adapter.retrieve_section(ref)

    def test_malformed_pdf_raises_adapter_unavailable(self) -> None:
        ref = _make_ref()
        served = {T21_URL: b"%PDF-1.4 garbage not a real pdf"}
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
        self.adapter = OklahomaAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref()
        parsed = ParsedDocument(
            raw_citation="Okla. Stat. tit. 21, § 21-701.7",
            heading="Murder in the first degree.",
            text="A.  A person commits murder in the first degree ...",
            amendment_notes="Added by Laws 1976 ...",
            source_url=T21_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "Okla. Stat. tit. 21, § 21-701.7"
        assert section.citation.state_code == "OK"
        assert section.heading == "Murder in the first degree."
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="NV", identifier="21"),
                identifier="21",
            ),
            identifier="21-701.7",
        )
        parsed = ParsedDocument(raw_citation="Okla. Stat. tit. 21, § 21-701.7", text="x")
        with pytest.raises(NormalizationError, match="expected 'OK'"):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref()
        parsed = ParsedDocument(raw_citation="Okla. Stat. tit. 21, § 21-9999", text="x")
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, ref)


class TestHierarchyMapping:
    def test_flat_title_synthetic_chapter_chain(self) -> None:
        adapter = OklahomaAdapter()
        served = {T21_URL: T21_701_7_PDF}
        with mock_urlopen_serving_bytes(served):
            chapters = adapter.list_chapters(_title_ref("21"))
            assert len(chapters) == 1
            chapter = chapters[0].ref
            assert isinstance(chapter, ChapterRef)
            sections = adapter.list_sections(chapter)
            assert all(s.ref.chapter == chapter for s in sections)
            assert any(s.identifier == "21-701.7" for s in sections)