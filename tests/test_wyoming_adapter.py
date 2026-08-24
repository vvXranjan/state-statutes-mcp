"""Tests for WyomingAdapter.

The Wyoming Statutes (wyoleg.gov/statutes/compress/title{NN:02d}.pdf) are
the framework's fifth PDF-family source, following the Oklahoma per-title
PDF pattern. Each title's full text is one PDF; valid titles are 01-42,
97 (Constitution), and 99 (Noncodified Statutes); nonexistent titles
return an HTML SPA shell (HTTP 200, non-PDF).

Hierarchy: Title -> Chapter -> [Article] -> Section. Article is folded
away. ``SectionRef.identifier`` is always the full ``T-C-S`` citation.

**REAL trimmed fixtures**: the ``wy_*`` fixtures are page-range subsets of
the official per-title PDFs (captured live Aug 24 2026; see
``docs/research/wyoming.md``), re-saved with pypdf. ``wy_invalid_title.html``
is the real HTML SPA shell returned for a nonexistent title. They are NOT
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

from state_statutes_mcp.adapters.wyoming.adapter import WyomingAdapter
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
# --- and the real HTML shell for a nonexistent title (fetched Aug 24 2026;
# --- see docs/research/wyoming.md).
FIXTURES = Path(__file__).parent / "fixtures"

T1_CH1_PDF = (FIXTURES / "wy_title01_ch1.pdf").read_bytes()
T1_CH1_DECIMAL_PDF = (FIXTURES / "wy_title01_ch1_decimal.pdf").read_bytes()
T1_RENUMBERED_PDF = (FIXTURES / "wy_title01_renumbered.pdf").read_bytes()
T31_CH1_PDF = (FIXTURES / "wy_title31_ch1.pdf").read_bytes()
T99_P1_PDF = (FIXTURES / "wy_title99_p1.pdf").read_bytes()
INVALID_TITLE_HTML = (FIXTURES / "wy_invalid_title.html").read_bytes()

BASE = "https://wyoleg.gov/statutes/compress"
T1_URL = f"{BASE}/title01.pdf"
T31_URL = f"{BASE}/title31.pdf"
T43_URL = f"{BASE}/title43.pdf"
T99_URL = f"{BASE}/title99.pdf"


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

    The Wyoming adapter probes title existence with HEAD requests (checking
    ``Content-Type``) and fetches title PDFs with GET requests. This mock
    dispatches on the HTTP method and the request URL.

    Args:
        url_to_bytes: Mapping of exact URL string to the raw bytes to serve
            for GET requests. URLs not present are treated as nonexistent
            titles (serving the HTML shell).
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


def _title_ref(identifier: str = "1") -> TitleRef:
    return TitleRef(state_code="WY", identifier=identifier)


def _chapter_ref(title: str = "1", chapter: str = "1") -> ChapterRef:
    return ChapterRef(title=_title_ref(title), identifier=chapter)


def _make_ref(title: str = "1", chapter: str = "1", section: str = "1-1-101") -> SectionRef:
    return SectionRef(chapter=_chapter_ref(title, chapter), identifier=section)


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert WyomingAdapter.__abstractmethods__ == frozenset()
        adapter = WyomingAdapter()
        assert adapter.state_code == "WY"
        assert adapter.state_name == "Wyoming"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = WyomingAdapter()

    def test_title_ref_url(self) -> None:
        assert self.adapter.build_url(_title_ref("1")) == T1_URL

    def test_title_97_zero_padded(self) -> None:
        assert self.adapter.build_url(_title_ref("97")) == f"{BASE}/title97.pdf"

    def test_title_99_zero_padded(self) -> None:
        assert self.adapter.build_url(_title_ref("99")) == T99_URL

    def test_chapter_ref_url(self) -> None:
        assert self.adapter.build_url(_chapter_ref()) == T1_URL

    def test_section_ref_url(self) -> None:
        assert self.adapter.build_url(_make_ref()) == T1_URL

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestListTitles:
    def test_discovers_valid_titles_from_bounded_probe(self) -> None:
        # Serve titles 01 and 99 as valid PDFs; everything else as the HTML
        # shell. The adapter probes 01-99, keeping only real PDFs.
        adapter = WyomingAdapter()
        served = {T1_URL: T1_CH1_PDF, T99_URL: T99_P1_PDF}
        with _serve(served):
            titles = adapter.list_titles()

        identifiers = [t.identifier for t in titles]
        assert "1" in identifiers
        assert "99" in identifiers
        assert "43" not in identifiers
        assert all(t.level == HierarchyLevel.TITLE for t in titles)
        assert all(t.ref.state_code == "WY" for t in titles)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = WyomingAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_titles()

    def test_no_valid_titles_raises_adapter_unavailable(self) -> None:
        # All titles return the HTML shell -> no valid titles.
        adapter = WyomingAdapter()
        with _serve({}):
            with pytest.raises(AdapterUnavailableError, match="no valid"):
                adapter.list_titles()


class TestListChapters:
    def test_lists_chapters_under_title(self) -> None:
        adapter = WyomingAdapter()
        with _serve({T1_URL: T1_CH1_PDF}):
            chapters = adapter.list_chapters(_title_ref("1"))

        identifiers = [c.identifier for c in chapters]
        assert "1" in identifiers
        assert all(c.level == HierarchyLevel.CHAPTER for c in chapters)
        assert chapters[0].identifier == "1"
        assert chapters[0].name == "GENERAL PROVISIONS AS TO CIVIL ACTIONS"

    def test_missing_title_pdf_html_raises_ref_not_found(self) -> None:
        adapter = WyomingAdapter()
        with _serve({}):  # title 43 not served -> HTML shell
            with pytest.raises(RefNotFoundError, match="non-PDF"):
                adapter.list_chapters(_title_ref("43"))


class TestListSections:
    def test_lists_sections_under_chapter(self) -> None:
        adapter = WyomingAdapter()
        with _serve({T1_URL: T1_CH1_PDF}):
            sections = adapter.list_sections(_chapter_ref("1", "1"))

        ids = [s.identifier for s in sections]
        assert "1-1-101" in ids
        assert all(s.level == HierarchyLevel.SECTION for s in sections)
        assert all(s.ref.chapter == _chapter_ref("1", "1") for s in sections)

    def test_decimal_sections_listed(self) -> None:
        adapter = WyomingAdapter()
        with _serve({T1_URL: T1_CH1_DECIMAL_PDF}):
            sections = adapter.list_sections(_chapter_ref("1", "1"))

        ids = [s.identifier for s in sections]
        assert "1-1-123.1" in ids
        assert "1-1-123.5" in ids


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = WyomingAdapter()

    def test_normal_section(self) -> None:
        ref = _make_ref()
        with _serve({T1_URL: T1_CH1_PDF}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Wyo. Stat. 1-1-101"
        assert section.citation.state_code == "WY"
        assert section.ref == ref
        assert section.heading == "Provisions to be liberally construed."
        assert section.text.startswith(
            "The Code of Civil Procedure and all proceedings under it"
        )
        assert section.status.value == "unknown"
        assert section.amendment_notes is None
        assert section.source_url == T1_URL
        assert section.retrieved_at is not None

    def test_decimal_section(self) -> None:
        ref = _make_ref(section="1-1-123.1")
        with _serve({T1_URL: T1_CH1_DECIMAL_PDF}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Wyo. Stat. 1-1-123.1"
        assert section.heading == "Ski Safety Act; short title."
        assert 'known and may be cited as the "Ski Safety' in section.text

    def test_repealed_section(self) -> None:
        ref = _make_ref(section="1-1-110")
        with _serve({T1_URL: T1_CH1_PDF}):
            section = self.adapter.retrieve_section(ref)

        # Documented convention (Nebraska/North Carolina/Oklahoma): the
        # repeal note becomes the heading and the body is empty.
        assert section.citation.raw == "Wyo. Stat. 1-1-110"
        assert section.heading == "Repealed by Laws 1986, ch. 24, § 2."
        assert section.text == ""
        assert section.status.value == "unknown"

    def test_renumbered_section(self) -> None:
        ref = SectionRef(
            chapter=_chapter_ref("1", "12"), identifier="1-12-502"
        )
        with _serve({T1_URL: T1_RENUMBERED_PDF}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Wyo. Stat. 1-12-502"
        assert section.heading == "Renumbered by Laws 1979, ch. 142, § 3."
        assert section.text == ""
        assert section.status.value == "unknown"

    def test_invalid_section_raises_ref_not_found(self) -> None:
        ref = _make_ref(section="1-1-999")
        with _serve({T1_URL: T1_CH1_PDF}):
            with pytest.raises(RefNotFoundError, match="not find section"):
                self.adapter.retrieve_section(ref)

    def test_invalid_title_html_raises_ref_not_found(self) -> None:
        # Title 43 does not exist: the source returns the HTML shell.
        ref = SectionRef(
            chapter=_chapter_ref("43", "1"), identifier="43-1-101"
        )
        with _serve({}):  # title 43 not served -> HTML shell
            with pytest.raises(RefNotFoundError, match="non-PDF"):
                self.adapter.retrieve_section(ref)

    def test_wrong_title_pdf_raises_ref_mismatch(self) -> None:
        # Request title 1 but serve title 31's PDF (which self-identifies as
        # TITLE 31). The adapter must reject it.
        ref = _make_ref()
        with _serve({T1_URL: T31_CH1_PDF}):
            with pytest.raises(RefMismatchError, match="self-identifies"):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        ref = _make_ref()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)

    def test_malformed_pdf_raises_adapter_unavailable(self) -> None:
        ref = _make_ref()
        with _serve({T1_URL: b"%PDF-1.4 garbage not a real pdf"}):
            with pytest.raises(AdapterUnavailableError, match="Could not extract"):
                self.adapter.retrieve_section(ref)

    def test_non_pdf_response_raises_ref_not_found(self) -> None:
        ref = _make_ref()
        # Serve raw HTML bytes (not a PDF) for the title URL.
        with _serve({T1_URL: b"<html>not a pdf</html>"}):
            with pytest.raises(RefNotFoundError, match="non-PDF"):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = WyomingAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref()
        parsed = ParsedDocument(
            raw_citation="Wyo. Stat. 1-1-101",
            heading="Provisions to be liberally construed.",
            text="The Code of Civil Procedure and all proceedings ...",
            source_url=T1_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "Wyo. Stat. 1-1-101"
        assert section.citation.state_code == "WY"
        assert section.heading == "Provisions to be liberally construed."
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="NV", identifier="1"),
                identifier="1",
            ),
            identifier="1-1-101",
        )
        parsed = ParsedDocument(raw_citation="Wyo. Stat. 1-1-101", text="x")
        with pytest.raises(NormalizationError, match="expected 'WY'"):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref()
        parsed = ParsedDocument(raw_citation="Wyo. Stat. 1-1-999", text="x")
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, ref)


class TestHelpers:
    def test_title_identity(self) -> None:
        assert WyomingAdapter._title_identity(
            "TITLE 1 - CODE OF CIVIL PROCEDURE \nCHAPTER 1 ..."
        ) == "1"
        assert WyomingAdapter._title_identity("no header here") is None

    def test_title_name(self) -> None:
        assert WyomingAdapter._title_name(
            "TITLE 1 - CODE OF CIVIL PROCEDURE \nbody", "1"
        ) == "CODE OF CIVIL PROCEDURE"
        assert WyomingAdapter._title_name("no header", "7") == "Title 7"

    def test_num_key(self) -> None:
        assert WyomingAdapter._num_key("10") == (10, "10")
        assert WyomingAdapter._num_key("2") == (2, "2")