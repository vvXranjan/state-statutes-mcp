"""Tests for IowaAdapter.

The Iowa Code (legis.iowa.gov) is the framework's second PDF-family
source: discovery is server-rendered HTML (a root page listing all 16
titles, per-title chapter listings, and per-chapter section listings),
while each section is a real PDF document retrieved through the shared
``fetch_bytes`` + ``extract_pdf_text`` infrastructure.

``TitleRef.identifier`` is the Roman-numeral title (``"I"``),
``ChapterRef.identifier`` is the chapter number (``"1"``, ``"6A"``), and
``SectionRef.identifier`` is the full citation (``"1.1"``, ``"1.15A"``).
The current Code year is resolved dynamically from the root page (the
official URLs all embed ``year=YYYY``).

**Repealed behavior (VERIFIED live)**: a repealed section is simply absent
-- omitted from the section listing and its PDF URL returns a genuine HTTP
404 (VERIFIED: ``§4.16`` and ``§4.17``). Repealed/absent sections map to
``RefNotFoundError``; no special stub handling is needed.

**Reserved behavior (VERIFIED live)**: a RESERVED chapter (e.g. Chapter 6)
exists in the chapter listing but its section listing is EMPTY (an empty
table body). ``list_sections`` returns an empty sequence for it.

**HTTP errors (VERIFIED live)**: a nonexistent section PDF returns HTTP
404; a nonexistent chapter's section listing returns HTTP 200 with an
empty table body; the root page determines the year.

**REAL live fixtures**: the ``ia_*`` fixtures are verbatim captures of the
official host fetched live on Aug 23 2026 (see ``docs/research/iowa.md``);
they are NOT synthetic. The HTML pages are captures; the section fixtures
are real PDF documents.

The shared ``extract_pdf_text`` was enhanced to fall back to pypdf layout
mode for per-word-positioned PDFs (VERIFIED for the Iowa Code); see
``_pdftext.py``'s module docstring.

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

from state_statutes_mcp.adapters.iowa.adapter import IowaAdapter
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
# --- (legis.iowa.gov, fetched Aug 23 2026; see docs/research/iowa.md).
FIXTURES = Path(__file__).parent / "fixtures"

ROOT_HTML = (FIXTURES / "ia_root.html").read_bytes()
CH_I_HTML = (FIXTURES / "ia_chapters_titleI.html").read_bytes()
CH_XV_HTML = (FIXTURES / "ia_chapters_titleXV.html").read_bytes()
SEC1_HTML = (FIXTURES / "ia_sections_ch1.html").read_bytes()
SEC633_HTML = (FIXTURES / "ia_sections_ch633.html").read_bytes()
INVALID_CHAPTER_HTML = (FIXTURES / "ia_sections_invalid_chapter.html").read_bytes()
SEC1_1_PDF = (FIXTURES / "ia_section_1.1.pdf").read_bytes()
SEC1_15A_PDF = (FIXTURES / "ia_section_1.15A.pdf").read_bytes()
SEC656_2_PDF = (FIXTURES / "ia_section_656.2.pdf").read_bytes()
CH6_RESERVED_PDF = (FIXTURES / "ia_chapter6_reserved.pdf").read_bytes()

BASE = "https://www.legis.iowa.gov"
ROOT_URL = f"{BASE}/law/iowaCode"
CH_I_URL = f"{BASE}/law/iowaCode/chapters?title=I&year=2026"
CH_XV_URL = f"{BASE}/law/iowaCode/chapters?title=XV&year=2026"
SEC1_URL = f"{BASE}/law/iowaCode/sections?codeChapter=1&year=2026"
SEC633_URL = f"{BASE}/law/iowaCode/sections?codeChapter=633&year=2026"
SEC1_1_URL = f"{BASE}/docs/code/2026/1.1.pdf"
SEC1_15A_URL = f"{BASE}/docs/code/2026/1.15A.pdf"
SEC656_2_URL = f"{BASE}/docs/code/2026/656.2.pdf"


def _title_ref(identifier: str = "I") -> TitleRef:
    return TitleRef(state_code="IA", identifier=identifier)


def _chapter_ref(title: str = "I", chapter: str = "1") -> ChapterRef:
    return ChapterRef(title=_title_ref(title), identifier=chapter)


def _make_ref(chapter: str = "1", section: str = "1.1") -> SectionRef:
    return SectionRef(chapter=_chapter_ref(chapter=chapter), identifier=section)


def _serve_all() -> dict[str, bytes]:
    """Serve every fixture used by the discovery + retrieval tests."""
    return {
        ROOT_URL: ROOT_HTML,
        CH_I_URL: CH_I_HTML,
        CH_XV_URL: CH_XV_HTML,
        SEC1_URL: SEC1_HTML,
        SEC633_URL: SEC633_HTML,
        SEC1_1_URL: SEC1_1_PDF,
        SEC1_15A_URL: SEC1_15A_PDF,
        SEC656_2_URL: SEC656_2_PDF,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert IowaAdapter.__abstractmethods__ == frozenset()
        adapter = IowaAdapter()
        assert adapter.state_code == "IA"
        assert adapter.state_name == "Iowa"


class TestCurrentYear:
    def test_dynamic_year_from_root_page(self) -> None:
        adapter = IowaAdapter()
        with mock_urlopen_serving_bytes({ROOT_URL: ROOT_HTML}):
            assert adapter._current_year() == "2026"

    def test_year_missing_raises_adapter_unavailable(self) -> None:
        adapter = IowaAdapter()
        with mock_urlopen_serving_bytes({ROOT_URL: b"<html>no year here</html>"}):
            with pytest.raises(AdapterUnavailableError, match="no year=YYYY"):
                adapter._current_year()


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = IowaAdapter()

    def test_title_ref_url_is_root(self) -> None:
        assert self.adapter.build_url(_title_ref()) == ROOT_URL

    def test_chapter_ref_url_uses_dynamic_year(self) -> None:
        with mock_urlopen_serving_bytes({ROOT_URL: ROOT_HTML}):
            assert self.adapter.build_url(_chapter_ref()) == SEC1_URL

    def test_section_ref_url_uses_dynamic_year(self) -> None:
        with mock_urlopen_serving_bytes({ROOT_URL: ROOT_HTML}):
            assert self.adapter.build_url(_make_ref()) == SEC1_1_URL

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestListTitles:
    def test_returns_all_16_titles(self) -> None:
        adapter = IowaAdapter()
        with mock_urlopen_serving_bytes({ROOT_URL: ROOT_HTML}):
            titles = adapter.list_titles()

        assert len(titles) == 16
        assert all(t.level == HierarchyLevel.TITLE for t in titles)
        assert all(t.ref.state_code == "IA" for t in titles)
        assert titles[0].identifier == "I"
        assert titles[0].name == "STATE SOVEREIGNTY AND MANAGEMENT"
        assert titles[-1].identifier == "XVI"
        assert titles[-1].name == "CRIMINAL LAW AND PROCEDURE"

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = IowaAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_titles()

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = IowaAdapter()
        with mock_urlopen_serving_bytes({ROOT_URL: b"<html></html>"}):
            with pytest.raises(AdapterUnavailableError, match="no usable title"):
                adapter.list_titles()


class TestListChapters:
    def test_returns_chapters_including_lettered_and_reserved(self) -> None:
        adapter = IowaAdapter()
        served = {ROOT_URL: ROOT_HTML, CH_I_URL: CH_I_HTML}
        with mock_urlopen_serving_bytes(served):
            chapters = adapter.list_chapters(_title_ref("I"))

        assert len(chapters) == 151
        ch1 = next(c for c in chapters if c.identifier == "1")
        assert ch1.name == "SOVEREIGNTY AND JURISDICTION OF THE STATE"
        ch1a = next(c for c in chapters if c.identifier == "1A")
        assert ch1a.name == "GREAT SEAL OF IOWA"
        ch6 = next(c for c in chapters if c.identifier == "6")
        assert ch6.name == "RESERVED"
        assert all(c.level == HierarchyLevel.CHAPTER for c in chapters)
        assert all(c.ref.title == _title_ref("I") for c in chapters)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = IowaAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_chapters(_title_ref("I"))

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = IowaAdapter()
        served = {ROOT_URL: ROOT_HTML, CH_I_URL: b"<html></html>"}
        with mock_urlopen_serving_bytes(served):
            with pytest.raises(AdapterUnavailableError, match="no usable chapter"):
                adapter.list_chapters(_title_ref("I"))


class TestListSections:
    def test_returns_sections_including_lettered(self) -> None:
        adapter = IowaAdapter()
        served = {ROOT_URL: ROOT_HTML, SEC1_URL: SEC1_HTML}
        with mock_urlopen_serving_bytes(served):
            sections = adapter.list_sections(_chapter_ref())

        ids = [s.identifier for s in sections]
        assert "1.1" in ids and "1.15A" in ids
        s115a = next(s for s in sections if s.identifier == "1.15A")
        assert s115a.name == "Criminal jurisdiction — Sac and Fox Indian settlement."
        assert all(s.level == HierarchyLevel.SECTION for s in sections)
        assert all(s.ref.chapter == _chapter_ref() for s in sections)

    def test_reserved_chapter_returns_empty(self) -> None:
        # VERIFIED: a RESERVED chapter exists but has an empty section
        # listing. The adapter returns an empty sequence (not an error).
        adapter = IowaAdapter()
        chapter = _chapter_ref(chapter="6")
        served = {ROOT_URL: ROOT_HTML, f"{BASE}/law/iowaCode/sections?codeChapter=6&year=2026": SEC1_HTML.replace(b"1.1", b"x.1")}
        # Serve a listing with no section rows (empty tbody) for ch 6:
        served = {ROOT_URL: ROOT_HTML, f"{BASE}/law/iowaCode/sections?codeChapter=6&year=2026": b"<html><tbody>   </tbody></html>"}
        with mock_urlopen_serving_bytes(served):
            sections = adapter.list_sections(chapter)
        assert sections == ()

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = IowaAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_sections(_chapter_ref())


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = IowaAdapter()

    def test_full_retrieval_normal_section(self) -> None:
        ref = _make_ref()
        with mock_urlopen_serving_bytes(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Iowa Code § 1.1"
        assert section.citation.state_code == "IA"
        assert section.ref == ref
        assert section.heading == "State boundaries."
        assert section.text == (
            "The boundaries of the state are as defined in the preamble of "
            "the Constitution of the State\nof Iowa."
        )
        assert section.status.value == "unknown"
        assert section.amendment_notes.startswith("[C51, §1; R60, §1;")
        assert "2009 Acts, ch 41, §1" in section.amendment_notes
        assert "Referredtoin§1.2" in section.amendment_notes
        # The generated footer must be dropped, not present in notes.
        assert "Iowa Code 2026, Section" not in section.amendment_notes
        assert section.source_url == SEC1_1_URL
        assert section.retrieved_at is not None

    def test_lettered_section_retrieval(self) -> None:
        ref = _make_ref(section="1.15A")
        with mock_urlopen_serving_bytes(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Iowa Code § 1.15A"
        assert section.heading == "Criminal jurisdiction — Sac and Fox Indian settlement."
        assert section.text.startswith(
            "Notwithstanding any other provision of law to the contrary"
        )
        assert section.amendment_notes == "2016 Acts, ch 1050, §1"

    def test_multi_page_section_retrieval(self) -> None:
        # §656.2 spans two pages; the whole body must be present in order
        # and the codification history from the last page must be captured.
        ref = _make_ref(chapter="656", section="656.2")
        served = {
            ROOT_URL: ROOT_HTML,
            f"{BASE}/docs/code/2026/656.2.pdf": SEC656_2_PDF,
        }
        with mock_urlopen_serving_bytes(served):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Iowa Code § 656.2"
        assert section.heading == "Notice."
        assert section.text.startswith("1. The forfeiture shall be initiated")
        assert section.text.rstrip().endswith(
            "vendee’s interest in the real estate."
        )
        assert "[C97, §4299; S13, §4299;" in section.amendment_notes
        assert "Referredtoin§656.3,656.8" in section.amendment_notes
        assert "Iowa Code 2026, Section" not in section.amendment_notes

    def test_repealed_section_404_maps_to_ref_not_found(self) -> None:
        # VERIFIED: a repealed section (e.g. §4.16) returns a genuine HTTP
        # 404. Map it to RefNotFoundError.
        ref = _make_ref(section="1.999")
        url = f"{BASE}/docs/code/2026/1.999.pdf"
        served = {ROOT_URL: ROOT_HTML}
        error = urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))

        from unittest import mock

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

            def read(self):
                raise error

        def fake_urlopen(requested_url, timeout=None):
            if requested_url == ROOT_URL:
                return _FakeResponseFor(ROOT_HTML)
            raise error

        class _FakeResponseFor(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

        with mock.patch(
            "state_statutes_mcp.adapters._fetch.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            with pytest.raises(RefNotFoundError, match="HTTP 404"):
                self.adapter.retrieve_section(ref)

    def test_section_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        # Request 1.1 but serve the 1.15A PDF (whose citation is 1.15A);
        # the extracted citation disagrees with the requested section.
        ref = _make_ref(section="1.1")
        served = {ROOT_URL: ROOT_HTML, SEC1_1_URL: SEC1_15A_PDF}
        with mock_urlopen_serving_bytes(served):
            with pytest.raises(RefMismatchError, match="does not match"):
                self.adapter.retrieve_section(ref)

    def test_malformed_pdf_raises_adapter_unavailable(self) -> None:
        ref = _make_ref()
        served = {
            ROOT_URL: ROOT_HTML,
            SEC1_1_URL: b"%PDF-1.4 garbage not a real pdf",
        }
        with mock_urlopen_serving_bytes(served):
            with pytest.raises(AdapterUnavailableError, match="Could not extract"):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        ref = _make_ref()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)


class TestParseSectionText:
    def test_parses_citation_catchline_body_and_drops_footer(self) -> None:
        text = (
            "1 SOVEREIGNTY AND JURISDICTION OF THE STATE, §1.1\n"
            "1.1  State  boundaries.\n"
            "The boundaries of the state are as defined in the preamble.\n"
            "[C51, §1; R60, §1]\n"
            "2009 Acts, ch 41, §1\n"
            "Referredtoin§1.2\n"
            "Wed Dec 10 21:39:07 2025 Iowa Code 2026, Section 1.1 (17, 0)\n"
        )
        citation, catchline, body, notes = IowaAdapter._parse_section_text(text)
        assert citation == "1.1"
        assert catchline == "State boundaries."
        assert body == "The boundaries of the state are as defined in the preamble."
        assert notes == "[C51, §1; R60, §1]\n2009 Acts, ch 41, §1\nReferredtoin§1.2"

    def test_malformed_text_raises_normalization_error(self) -> None:
        with pytest.raises(NormalizationError, match="no citation"):
            IowaAdapter._parse_section_text("just some text")


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = IowaAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref()
        parsed = ParsedDocument(
            raw_citation="Iowa Code § 1.1",
            heading="State boundaries.",
            text="The boundaries of the state ...",
            amendment_notes="[C51, §1]",
            source_url=SEC1_1_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "Iowa Code § 1.1"
        assert section.citation.state_code == "IA"
        assert section.heading == "State boundaries."
        assert section.status.value == "unknown"
        assert section.amendment_notes == "[C51, §1]"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="NV", identifier="I"),
                identifier="1",
            ),
            identifier="1.1",
        )
        parsed = ParsedDocument(raw_citation="Iowa Code § 1.1", text="Some text.")
        with pytest.raises(NormalizationError, match="expected 'IA'"):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref()
        parsed = ParsedDocument(raw_citation="Iowa Code § 1.999", text="Some text.")
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, ref)


class TestHierarchyMapping:
    def test_title_chapter_section_chain_descends(self) -> None:
        adapter = IowaAdapter()
        with mock_urlopen_serving_bytes(_serve_all()):
            titles = adapter.list_titles()
            title = next(t.ref for t in titles if t.identifier == "I")
            assert isinstance(title, TitleRef)
            assert title.state_code == "IA"

            chapters = adapter.list_chapters(title)
            assert all(c.ref.title == title for c in chapters)
            chapter = next(c.ref for c in chapters if c.identifier == "1")
            assert isinstance(chapter, ChapterRef)
            assert chapter.title == title

            sections = adapter.list_sections(chapter)
            assert all(s.ref.chapter.title == title for s in sections)
            assert all(s.ref.chapter == chapter for s in sections)

            section = next(s.ref for s in sections if s.identifier == "1.1")
            retrieved = adapter.retrieve_section(section)
            assert retrieved.citation.raw == "Iowa Code § 1.1"
            assert retrieved.heading == "State boundaries."