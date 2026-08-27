"""Tests for ColoradoAdapter.

The Colorado Revised Statutes (content.leg.colorado.gov/sites/default/files/
images/olls/crs2024-title-{NN}.pdf) are the framework's sixth PDF-family
source, following the Oklahoma/Wyoming per-title PDF pattern. The live host
returns an AWS WAF HTTP 403 to this environment for both valid and invalid
title URLs, so the fixtures used here are REAL archived official captures
(via the Wayback Machine, Aug 24 2026; see docs/research/colorado.md) --
NOT live captures.

Hierarchy: Title -> Article -> Part -> Section. Article is exposed as
ChapterRef (decimal articles preserved, e.g. "1.5"); Part is folded away;
SectionRef.identifier is the full "T-A-S" citation.

**REAL archived fixtures**: the ``co_*`` fixtures are page-range subsets of
the official per-title PDFs captured via the Wayback Machine. They are NOT
synthetic.

Network tests mock the real network boundary
(``urllib.request.urlopen`` as imported by the shared ``_fetch`` helper),
never adapter internals.
"""

from __future__ import annotations

import io
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pytest

from _mock_network import PATCH_TARGET, mock_urlopen_error

from state_statutes_mcp.adapters.colorado.adapter import ColoradoAdapter
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

# --- REAL archived official fixtures (Wayback captures, Aug 24 2026) ---
FIXTURES = Path(__file__).parent / "fixtures"

T1_P1_PDF = (FIXTURES / "co_title01_p1.pdf").read_bytes()
T1_CH1_PDF = (FIXTURES / "co_title01_ch1.pdf").read_bytes()
T1_DECIMAL_PDF = (FIXTURES / "co_title01_decimal.pdf").read_bytes()
T1_REPEALED_PDF = (FIXTURES / "co_title01_repealed.pdf").read_bytes()
T1_RANGE_PDF = (FIXTURES / "co_title01_range.pdf").read_bytes()
T42_CH1_PDF = (FIXTURES / "co_title42_ch1.pdf").read_bytes()
T42_DECIMAL_PDF = (FIXTURES / "co_title42_decimal.pdf").read_bytes()
INVALID_TITLE_HTML = (FIXTURES / "co_invalid_title.html").read_bytes()

BASE = "https://content.leg.colorado.gov/sites/default/files/images/olls"
T1_URL = f"{BASE}/crs2024-title-01.pdf"
T42_URL = f"{BASE}/crs2024-title-42.pdf"
T86_URL = f"{BASE}/crs2024-title-86.pdf"


class _FakeResponse(io.BytesIO):
    """A bytes-backed response that also behaves as a context manager and
    exposes ``.headers`` (with ``Content-Type``) and ``.status``."""

    def __init__(self, data: bytes, content_type: str = "application/pdf"):
        super().__init__(data)
        self.status = 200
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


@contextmanager
def _serve(url_to_bytes: dict[str, bytes]):
    """Serve specific URLs from ``url_to_bytes`` for GET requests and
    report ``application/pdf`` vs ``text/html`` for HEAD requests.

    The Colorado adapter probes title existence with HEAD requests (checking
    ``Content-Type``) and fetches title PDFs with GET requests.
    """
    with mock.patch(PATCH_TARGET) as mock_urlopen:

        def fake_urlopen(request, timeout=None):
            if isinstance(request, urllib.request.Request):
                url = request.full_url
                method = request.get_method()
            else:
                url = request
                method = "GET"
            if method == "HEAD":
                if url in url_to_bytes:
                    return _FakeResponse(b"", content_type="application/pdf")
                return _FakeResponse(b"", content_type="text/html")
            if url in url_to_bytes:
                return _FakeResponse(url_to_bytes[url])
            return _FakeResponse(INVALID_TITLE_HTML, content_type="text/html")

        mock_urlopen.side_effect = fake_urlopen
        yield


def _title_ref(identifier: str = "42") -> TitleRef:
    return TitleRef(state_code="CO", identifier=identifier)


def _chapter_ref(title: str = "42", article: str = "1") -> ChapterRef:
    return ChapterRef(title=_title_ref(title), identifier=article)


def _make_ref(
    title: str = "42", article: str = "1", section: str = "42-1-101"
) -> SectionRef:
    return SectionRef(chapter=_chapter_ref(title, article), identifier=section)


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert ColoradoAdapter.__abstractmethods__ == frozenset()
        adapter = ColoradoAdapter()
        assert adapter.state_code == "CO"
        assert adapter.state_name == "Colorado"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = ColoradoAdapter()

    def test_title_ref_url(self) -> None:
        assert self.adapter.build_url(_title_ref("1")) == T1_URL

    def test_title_42_zero_padded(self) -> None:
        assert self.adapter.build_url(_title_ref("42")) == T42_URL

    def test_chapter_ref_url(self) -> None:
        assert self.adapter.build_url(_chapter_ref()) == T42_URL

    def test_section_ref_url(self) -> None:
        assert self.adapter.build_url(_make_ref()) == T42_URL

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestListTitles:
    def test_discovers_valid_titles_from_bounded_probe(self) -> None:
        adapter = ColoradoAdapter()
        served = {T1_URL: T1_P1_PDF, T42_URL: T42_CH1_PDF}
        with _serve(served):
            titles = adapter.list_titles()

        identifiers = [t.identifier for t in titles]
        assert "1" in identifiers
        assert "42" in identifiers
        assert "86" not in identifiers
        assert all(t.level == HierarchyLevel.TITLE for t in titles)
        assert all(t.ref.state_code == "CO" for t in titles)
        assert next(t.name for t in titles if t.identifier == "1") == "ELECTIONS"
        assert next(t.name for t in titles if t.identifier == "42") == "VEHICLES AND TRAFFIC"

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = ColoradoAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_titles()

    def test_no_valid_titles_raises_adapter_unavailable(self) -> None:
        adapter = ColoradoAdapter()
        with _serve({}):  # all titles return the HTML shell
            with pytest.raises(AdapterUnavailableError, match="no valid"):
                adapter.list_titles()


class TestListChapters:
    def test_lists_articles_under_title(self) -> None:
        adapter = ColoradoAdapter()
        with _serve({T42_URL: T42_CH1_PDF}):
            chapters = adapter.list_chapters(_title_ref("42"))

        identifiers = [c.identifier for c in chapters]
        assert "1" in identifiers
        assert all(c.level == HierarchyLevel.CHAPTER for c in chapters)

    def test_missing_title_pdf_html_raises_ref_not_found(self) -> None:
        adapter = ColoradoAdapter()
        with _serve({}):  # title not served -> HTML shell
            with pytest.raises(RefNotFoundError, match="non-PDF"):
                adapter.list_chapters(_title_ref("86"))


class TestListSections:
    def test_lists_sections_under_article(self) -> None:
        adapter = ColoradoAdapter()
        with _serve({T42_URL: T42_CH1_PDF}):
            sections = adapter.list_sections(_chapter_ref("42", "1"))

        ids = [s.identifier for s in sections]
        assert "42-1-101" in ids
        assert "42-1-102" in ids
        assert all(s.level == HierarchyLevel.SECTION for s in sections)
        assert all(s.ref.chapter == _chapter_ref("42", "1") for s in sections)

    def test_range_repeal_not_exposed_as_section(self) -> None:
        # co_title01_range.pdf contains the structural range-repeal line
        # '1-1-401 to 1-1-403. (Repealed)' but no other article-1 sections.
        # A range-repeal line is NOT an ordinary retrievable section, so it
        # must not be exposed: listing article 1 yields no sections (rather
        # than a bogus '1-1-401' entry), while article 1.5's real sections
        # are still listed.
        adapter = ColoradoAdapter()
        with _serve({T1_URL: T1_RANGE_PDF}):
            with pytest.raises(AdapterUnavailableError, match="no usable"):
                adapter.list_sections(_chapter_ref("1", "1"))

            sections_15 = adapter.list_sections(
                ChapterRef(
                    title=TitleRef(state_code="CO", identifier="1"),
                    identifier="1.5",
                )
            )

        ids_15 = [s.identifier for s in sections_15]
        assert "1-1.5-101" in ids_15
        assert "1-1.5-104" in ids_15
        assert "1-1-401" not in ids_15


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = ColoradoAdapter()

    def test_normal_section(self) -> None:
        ref = _make_ref()
        with _serve({T42_URL: T42_CH1_PDF}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Colo. Rev. Stat. 42-1-101"
        assert section.citation.state_code == "CO"
        assert section.ref == ref
        assert section.heading.strip() == "Short title."
        assert "Articles 1 to 4 of this title shall be known" in section.text
        assert section.status.value == "unknown"
        assert section.amendment_notes is not None
        assert section.source_url == T42_URL
        assert section.retrieved_at is not None

    def test_normal_section_title1(self) -> None:
        ref = SectionRef(
            chapter=_chapter_ref("1", "1"), identifier="1-1-101"
        )
        with _serve({T1_URL: T1_CH1_PDF}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Colo. Rev. Stat. 1-1-101"
        assert section.heading.strip() == "Short title."
        assert "Uniform Election Code of 1992" in section.text
        assert section.status.value == "unknown"
        assert section.amendment_notes is not None

    def test_decimal_section(self) -> None:
        ref = _make_ref(section="42-1-218.5")
        with _serve({T42_URL: T42_DECIMAL_PDF}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Colo. Rev. Stat. 42-1-218.5"
        assert section.heading.strip() == "Electronic hearings."
        assert "(1)  Notwithstanding any other provision" in section.text
        assert section.amendment_notes is not None

    def test_decimal_section_title1(self) -> None:
        ref = SectionRef(
            chapter=_chapter_ref("1", "1"), identifier="1-1-105.5"
        )
        with _serve({T1_URL: T1_DECIMAL_PDF}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Colo. Rev. Stat. 1-1-105.5"
        assert "District elections conducted on or prior" in section.heading
        assert section.amendment_notes is not None

    def test_decimal_article_section(self) -> None:
        # Article 1.5 is encoded as '1-1.5-101'.
        ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="CO", identifier="1"),
                identifier="1.5",
            ),
            identifier="1-1.5-101",
        )
        with _serve({T1_URL: T1_RANGE_PDF}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Colo. Rev. Stat. 1-1.5-101"
        assert section.heading.strip() == "Legislative declaration."
        assert "Help America Vote Act" in section.text

    def test_repealed_section(self) -> None:
        ref = SectionRef(
            chapter=_chapter_ref("1", "1"), identifier="1-1-112"
        )
        with _serve({T1_URL: T1_REPEALED_PDF}):
            section = self.adapter.retrieve_section(ref)

        # Repealed sections keep '(Repealed)' in the heading; body is empty.
        assert section.citation.raw == "Colo. Rev. Stat. 1-1-112"
        assert section.heading == "Powers and duties of election commission. (Repealed)"
        assert section.text == ""
        assert section.status.value == "unknown"
        assert section.amendment_notes is not None

    def test_repealed_section_wrapped_catchline(self) -> None:
        # 42-1-223's catchline wraps: the line ends with '... repeal.' and a
        # bare '(Repealed)' marker is on the FOLLOWING line. The marker must
        # be folded into the heading and the body must be empty.
        ref = SectionRef(
            chapter=_chapter_ref("42", "1"), identifier="42-1-223"
        )
        with _serve({T42_URL: T42_DECIMAL_PDF}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Colo. Rev. Stat. 42-1-223"
        assert section.heading == (
            "Monitoring driving improvement schools - fund - rules - "
            "repeal. (Repealed)"
        )
        assert section.text == ""
        assert section.status.value == "unknown"
        assert section.amendment_notes is not None

    def test_invalid_section_raises_ref_not_found(self) -> None:
        ref = _make_ref(section="42-1-999999")
        with _serve({T42_URL: T42_CH1_PDF}):
            with pytest.raises(RefNotFoundError, match="not find section"):
                self.adapter.retrieve_section(ref)

    def test_invalid_title_html_raises_ref_not_found(self) -> None:
        # Title 86 does not exist: the source returns a non-PDF page.
        ref = SectionRef(
            chapter=_chapter_ref("86", "1"), identifier="86-1-101"
        )
        with _serve({}):  # title 86 not served -> HTML shell
            with pytest.raises(RefNotFoundError, match="non-PDF"):
                self.adapter.retrieve_section(ref)

    def test_wrong_title_pdf_raises_ref_mismatch(self) -> None:
        # Request title 42 but serve title 1's PDF (which self-identifies as
        # TITLE 1). The adapter must reject it.
        ref = _make_ref()
        with _serve({T42_URL: T1_P1_PDF}):
            with pytest.raises(RefMismatchError, match="self-identifies"):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        ref = _make_ref()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)

    def test_malformed_pdf_raises_adapter_unavailable(self) -> None:
        ref = _make_ref()
        with _serve({T42_URL: b"%PDF-1.4 garbage not a real pdf"}):
            with pytest.raises(AdapterUnavailableError, match="Could not extract"):
                self.adapter.retrieve_section(ref)

    def test_non_pdf_response_raises_ref_not_found(self) -> None:
        ref = _make_ref()
        with _serve({T42_URL: b"<html>not a pdf</html>"}):
            with pytest.raises(RefNotFoundError, match="non-PDF"):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = ColoradoAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref()
        parsed = ParsedDocument(
            raw_citation="Colo. Rev. Stat. 42-1-101",
            heading="Short title.",
            text="Articles 1 to 4 of this title ...",
            source_url=T42_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "Colo. Rev. Stat. 42-1-101"
        assert section.citation.state_code == "CO"
        assert section.heading == "Short title."
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="NV", identifier="42"),
                identifier="1",
            ),
            identifier="42-1-101",
        )
        parsed = ParsedDocument(raw_citation="Colo. Rev. Stat. 42-1-101", text="x")
        with pytest.raises(NormalizationError, match="expected 'CO'"):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref()
        parsed = ParsedDocument(raw_citation="Colo. Rev. Stat. 42-1-999", text="x")
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, ref)


class TestHelpers:
    def test_title_identity(self) -> None:
        assert ColoradoAdapter._title_identity("Colorado Revised Statutes 2024\nTITLE 42\nVEHICLES") == "42"
        assert ColoradoAdapter._title_identity("no header here") is None

    def test_title_name(self) -> None:
        assert ColoradoAdapter._title_name("TITLE 42\nVEHICLES AND TRAFFIC\n", "42") == "VEHICLES AND TRAFFIC"
        assert ColoradoAdapter._title_name("no header", "7") == "Title 7"

    def test_strip_footer(self) -> None:
        assert ColoradoAdapter._strip_footer(
            "Colorado Revised Statutes 2024 Page 29 of  834 Uncertified Printoutcontent"
        ) == "content"
        assert ColoradoAdapter._strip_footer("plain line") == "plain line"

    def test_catchline_ends(self) -> None:
        assert ColoradoAdapter._catchline_ends("Short title.")
        assert ColoradoAdapter._catchline_ends("Powers. (Repealed)")
        assert ColoradoAdapter._catchline_ends("(Repealed)")
        assert ColoradoAdapter._catchline_ends("(Renumbered)")
        assert not ColoradoAdapter._catchline_ends("Articles 1 to 4 of this title")

    def test_num_key(self) -> None:
        assert ColoradoAdapter._num_key("1.5") == (1.5, "1.5")
        assert ColoradoAdapter._num_key("10") == (10.0, "10")
        assert ColoradoAdapter._num_key("2") == (2.0, "2")