"""Tests for NevadaAdapter.

Nevada is a chapter-document HTML source (the official Nevada Legislature
publication of the Nevada Revised Statutes at leg.state.nv.us). Hierarchy
is Title -> Chapter -> Section. The root (``/nrs/``) lists the titles and
their chapter links. Chapter documents use the verified
``/nrs//NRS-{chapter}.html`` URL form (note the literal DOUBLE SLASH) and
contain the chapter's sections, each opened by an anchor of the form
``NRS{chapter}Sec{seq}`` (e.g. ``#NRS220Sec040``) and carrying its own
citation heading ``NRS {chapter}.{section}`` (e.g. ``NRS 220.170``) plus
caption, body, and bracketed session-law history. ``SectionRef.identifier``
is the full ``{chapter}.{section}`` number.

The anchor sequence number is distinct from the section's citation number
(in the 220 fixture: ``NRS220Sec039`` <-> ``NRS 220.160``,
``NRS220Sec040`` <-> ``NRS 220.170``, ``NRS220Sec041`` <-> ``NRS 220.180``),
so the adapter uses anchors ONLY as section-boundary markers and reads each
section's citation from its own heading.

**SYNTHETIC fixtures**: Wayback retrieval was unavailable from the
implementation environment for this batch, so the ``nv_*`` fixtures are
synthetic and representative -- they reproduce ONLY the structures verified
by the research source of truth for this adapter (see
``docs/research/nevada.md``). They are NOT official government captures.

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

from state_statutes_mcp.adapters.nevada.adapter import NevadaAdapter
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
# --- VERIFIED Nevada structures (see docs/research/nevada.md). NOT
# --- official government captures.
FIXTURES = Path(__file__).parent / "fixtures"

NV_INDEX_HTML = (FIXTURES / "nv_nrs_index.html").read_text(encoding="utf-8")
NV_CH220_HTML = (FIXTURES / "nv_chapter220.html").read_text(encoding="utf-8")
NV_CH220A_HTML = (FIXTURES / "nv_chapter220a.html").read_text(encoding="utf-8")

BASE = "https://www.leg.state.nv.us"

INDEX_URL = f"{BASE}/nrs/"
CH220_URL = f"{BASE}/nrs//NRS-220.html"
CH220A_URL = f"{BASE}/nrs//NRS-220A.html"


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the shared fetch helper will
    wrap into ``AdapterUnavailableError`` with ``__cause__`` set to it."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


def _title_ref() -> TitleRef:
    return TitleRef(state_code="NV", identifier="1")


def _chapter_ref() -> ChapterRef:
    return ChapterRef(title=_title_ref(), identifier="220")


def _chapter_ref_a() -> ChapterRef:
    return ChapterRef(title=_title_ref(), identifier="220A")


def _make_ref(section: str) -> SectionRef:
    return SectionRef(chapter=_chapter_ref(), identifier=section)


def _make_ref_a(section: str) -> SectionRef:
    return SectionRef(chapter=_chapter_ref_a(), identifier=section)


def _serve_all() -> dict[str, str]:
    return {
        INDEX_URL: NV_INDEX_HTML,
        CH220_URL: NV_CH220_HTML,
        CH220A_URL: NV_CH220A_HTML,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert NevadaAdapter.__abstractmethods__ == frozenset()
        adapter = NevadaAdapter()
        assert adapter.state_code == "NV"
        assert adapter.state_name == "Nevada"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = NevadaAdapter()

    def test_title_ref_url_is_root(self) -> None:
        assert (
            self.adapter.build_url(_title_ref())
            == "https://www.leg.state.nv.us/nrs/"
        )

    def test_chapter_ref_url_preserves_double_slash(self) -> None:
        # VERIFIED: chapter URL form is /nrs//NRS-{chapter}.html -- the
        # literal double slash after /nrs/ is part of the documented form.
        assert (
            self.adapter.build_url(_chapter_ref())
            == "https://www.leg.state.nv.us/nrs//NRS-220.html"
        )

    def test_lettered_chapter_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_chapter_ref_a())
            == "https://www.leg.state.nv.us/nrs//NRS-220A.html"
        )

    def test_section_ref_url_is_chapter_document(self) -> None:
        # Sections are embedded in their chapter document, so the chapter
        # document is the closest real resource.
        assert (
            self.adapter.build_url(_make_ref("220.170"))
            == "https://www.leg.state.nv.us/nrs//NRS-220.html"
        )

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestListTitles:
    def test_returns_titles_from_root(self) -> None:
        adapter = NevadaAdapter()
        with mock_urlopen_serving({INDEX_URL: NV_INDEX_HTML}):
            titles = adapter.list_titles()

        assert [n.identifier for n in titles] == ["1", "2"]
        assert titles[0].name == "State of Nevada"
        assert titles[1].name == "Local Government"
        assert all(n.level == HierarchyLevel.TITLE for n in titles)
        assert all(n.ref.state_code == "NV" for n in titles)

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = NevadaAdapter()
        with mock_urlopen("<html><body>no titles</body></html>"):
            with pytest.raises(AdapterUnavailableError, match="no usable title"):
                adapter.list_titles()

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = NevadaAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_titles()


class TestListChapters:
    def test_returns_chapters_under_title(self) -> None:
        adapter = NevadaAdapter()
        with mock_urlopen_serving({INDEX_URL: NV_INDEX_HTML}):
            chapters = adapter.list_chapters(_title_ref())

        assert [n.identifier for n in chapters] == ["220", "220A"]
        assert chapters[0].name == "State Highway System"
        assert chapters[1].name == "Transportation Alternative Programs"
        assert all(n.level == HierarchyLevel.CHAPTER for n in chapters)
        assert all(n.ref.title == _title_ref() for n in chapters)

    def test_lettered_chapter_identifier_preserved(self) -> None:
        adapter = NevadaAdapter()
        with mock_urlopen_serving({INDEX_URL: NV_INDEX_HTML}):
            chapters = adapter.list_chapters(_title_ref())
        by_id = {n.identifier: n for n in chapters}
        assert "220A" in by_id

    def test_unknown_title_raises_ref_not_found(self) -> None:
        adapter = NevadaAdapter()
        ref = TitleRef(state_code="NV", identifier="99")
        with mock_urlopen_serving({INDEX_URL: NV_INDEX_HTML}):
            with pytest.raises(RefNotFoundError, match="lists no title '99'"):
                adapter.list_chapters(ref)

    def test_title_with_no_chapters_raises_adapter_unavailable(self) -> None:
        adapter = NevadaAdapter()
        html = "<html><body><h2>Title 1 - Empty</h2></body></html>"
        with mock_urlopen_serving({INDEX_URL: html}):
            with pytest.raises(AdapterUnavailableError, match="no usable chapter"):
                adapter.list_chapters(_title_ref())

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = NevadaAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_chapters(_title_ref())


class TestListSections:
    def test_returns_sections_from_chapter_document(self) -> None:
        adapter = NevadaAdapter()
        with mock_urlopen_serving({CH220_URL: NV_CH220_HTML}):
            sections = adapter.list_sections(_chapter_ref())

        assert [n.identifier for n in sections] == ["220.160", "220.170", "220.180"]
        assert sections[0].name == "Administration of the highway system."
        assert sections[1].name == "Authority to acquire property."
        # 220.180 has no caption; the identifier falls back as the name.
        assert sections[2].name == "220.180"
        assert all(n.level == HierarchyLevel.SECTION for n in sections)
        assert all(n.ref.chapter == _chapter_ref() for n in sections)

    def test_lettered_chapter_sections(self) -> None:
        adapter = NevadaAdapter()
        with mock_urlopen_serving({CH220A_URL: NV_CH220A_HTML}):
            sections = adapter.list_sections(_chapter_ref_a())
        assert [n.identifier for n in sections] == ["220A.010"]
        assert sections[0].name == "Definitions."

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = NevadaAdapter()
        with mock_urlopen_error(_http_error(CH220_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_sections(_chapter_ref())

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = NevadaAdapter()
        with mock_urlopen_serving({CH220_URL: "<html><body>none</body></html>"}):
            with pytest.raises(AdapterUnavailableError, match="no usable section"):
                adapter.list_sections(_chapter_ref())


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = NevadaAdapter()

    def test_full_retrieval_with_bracketed_history(self) -> None:
        ref = _make_ref("220.170")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "NRS 220.170"
        assert section.citation.state_code == "NV"
        assert section.ref == ref
        assert section.heading == "Authority to acquire property."
        assert "The department may acquire, by purchase, condemnation" in section.text
        assert "Eminent domain may be exercised only as provided by law." in section.text
        # VERIFIED: history is bracketed session-law text after the body.
        assert section.amendment_notes == "[1:21:1955; 1965, 219]"
        assert section.status.value == "unknown"
        assert section.source_url == CH220_URL
        assert section.retrieved_at is not None

    def test_retrieval_with_simple_history(self) -> None:
        ref = _make_ref("220.160")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "NRS 220.160"
        assert section.heading == "Administration of the highway system."
        assert "administer the state highway system" in section.text
        assert section.amendment_notes == "[1:21:1955]"

    def test_retrieval_without_caption_or_history(self) -> None:
        ref = _make_ref("220.180")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "NRS 220.180"
        assert section.heading is None
        assert "All moneys received by the department" in section.text
        assert section.amendment_notes is None

    def test_missing_section_raises_ref_not_found(self) -> None:
        ref = _make_ref("220.999")
        with mock_urlopen_serving({CH220_URL: NV_CH220_HTML}):
            with pytest.raises(RefNotFoundError, match="contains no section"):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        ref = _make_ref("220.170")
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)


class TestParseEdgeCases:
    def setup_method(self) -> None:
        self.adapter = NevadaAdapter()

    def test_exact_section_boundaries(self) -> None:
        # Each section's body must stop at the next section's anchor --
        # no bleeding between neighbouring sections.
        with mock_urlopen_serving(_serve_all()):
            s160 = self.adapter.retrieve_section(_make_ref("220.160"))
            s170 = self.adapter.retrieve_section(_make_ref("220.170"))
            s180 = self.adapter.retrieve_section(_make_ref("220.180"))

        assert "charge of the maintenance and repair thereof" in s160.text
        assert "state highway fund" not in s160.text
        assert "maintenance and repair" not in s170.text
        assert "state highway fund" not in s170.text
        assert "Eminent domain" not in s180.text
        assert "acquire, by purchase" not in s180.text

    def test_citation_prefix_does_not_cross_match(self) -> None:
        # '220.16' is a prefix of '220.160' but is its own citation; the
        # adapter matches citations exactly, so the prefix must not resolve.
        ref = _make_ref("220.16")
        with mock_urlopen_serving({CH220_URL: NV_CH220_HTML}):
            with pytest.raises(RefNotFoundError, match="contains no section"):
                self.adapter.retrieve_section(ref)

    def test_empty_body_raises_normalization_error(self) -> None:
        ref = _make_ref("220.190")
        html = (
            '<a name="NRS220Sec050"></a>'
            "<p><b>NRS 220.190</b> Empty section.</p>"
        )
        with mock_urlopen_serving({CH220_URL: html}):
            with pytest.raises(NormalizationError, match="body text was empty"):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = NevadaAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("220.170")
        parsed = ParsedDocument(
            raw_citation="NRS 220.170",
            heading="Authority to acquire property.",
            text="The department may acquire real property ...",
            amendment_notes="[1:21:1955; 1965, 219]",
            source_url=CH220_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "NRS 220.170"
        assert section.citation.state_code == "NV"
        assert section.heading == "Authority to acquire property."
        assert section.amendment_notes == "[1:21:1955; 1965, 219]"
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="NH", identifier="x"), identifier="201"
            ),
            identifier="220.170",
        )
        parsed = ParsedDocument(
            raw_citation="NRS 220.170",
            text="Some text.",
        )
        with pytest.raises(NormalizationError, match="expected 'NV'"):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("220.170")
        parsed = ParsedDocument(
            raw_citation="NRS 220.160",
            text="Some other section's text.",
        )
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, ref)