"""Tests for MissouriAdapter.

Missouri is a server-rendered HTML source (the official Revisor of
Missouri publication of the Revised Statutes of Missouri at
revisor.mo.gov). Three structural levels (Title -> Chapter -> Section)
map 1:1 onto the framework model; title identifiers are Roman numerals
(``XXXVI``), chapter identifiers are chapter numbers (``536``), and
section identifiers are the dotted section numbers (``536.050``).

Section-retrieval and section-discovery tests exercise the adapter's real
fetch -> parse path against **REAL captured Missouri HTML**: verbatim
slices of the official revisor.mo.gov pages, captured via the Wayback
Machine on Aug 14-15, 2026 and stored under ``tests/fixtures/missouri_*``:

* ``missouri_home_titles.html`` -- the home page's "Chapters in Title"
  region (all 41 title blocks, 468 chapter links).
* ``missouri_chapter536.html`` -- the Chapter 536 TOC page's section
  listing table (54 sections, 536.010 -> 536.320).
* ``missouri_section536050.html`` -- section 536.050
  "Declaratory judgments respecting the validity of rules ...".
* ``missouri_section536303.html`` -- section 536.303, a repealed section
  whose body is entirely replaced by a ``(Repealed ...)`` marker.

All tests are fully offline: the real network boundary
(``urllib.request.urlopen`` as imported by the shared ``_fetch`` helper) is
mocked, never adapter internals.
"""

from __future__ import annotations

import io
import urllib.error
from pathlib import Path

import pytest

from _mock_network import mock_urlopen, mock_urlopen_error, mock_urlopen_serving

from state_statutes_mcp.adapters.missouri.adapter import MissouriAdapter
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

# --- REAL fixtures: verbatim slices of the official Revisor of Missouri
# --- pages captured via the Wayback Machine on Aug 14-15, 2026. NOT synthetic.
FIXTURES = Path(__file__).parent / "fixtures"

REAL_HOME_HTML = (FIXTURES / "missouri_home_titles.html").read_text(
    encoding="utf-8"
)
REAL_CH536_HTML = (FIXTURES / "missouri_chapter536.html").read_text(
    encoding="utf-8"
)
REAL_SEC536050_HTML = (FIXTURES / "missouri_section536050.html").read_text(
    encoding="utf-8"
)
REAL_SEC536303_HTML = (FIXTURES / "missouri_section536303.html").read_text(
    encoding="utf-8"
)

BASE = "https://revisor.mo.gov/main"

HOME_URL = f"{BASE}/Home.aspx"
CH536_URL = f"{BASE}/PageSelect.aspx?chapter=536"
SEC536050_URL = f"{BASE}/OneSection.aspx?section=536.050"
SEC536303_URL = f"{BASE}/OneSection.aspx?section=536.303"


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the shared fetch helper will
    wrap into ``AdapterUnavailableError`` with ``__cause__`` set to it."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


def _title_ref() -> TitleRef:
    return TitleRef(state_code="MO", identifier="XXXVI")


def _chapter_ref() -> ChapterRef:
    return ChapterRef(title=_title_ref(), identifier="536")


def _make_ref(section: str) -> SectionRef:
    return SectionRef(chapter=_chapter_ref(), identifier=section)


def _serve_all() -> dict[str, str]:
    return {
        HOME_URL: REAL_HOME_HTML,
        CH536_URL: REAL_CH536_HTML,
        SEC536050_URL: REAL_SEC536050_HTML,
        SEC536303_URL: REAL_SEC536303_HTML,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert MissouriAdapter.__abstractmethods__ == frozenset()
        adapter = MissouriAdapter()
        assert adapter.state_code == "MO"
        assert adapter.state_name == "Missouri"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = MissouriAdapter()

    def test_title_ref_url(self) -> None:
        # Titles have no URL of their own; the home page is returned.
        assert (
            self.adapter.build_url(_title_ref())
            == "https://revisor.mo.gov/main/Home.aspx"
        )

    def test_chapter_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_chapter_ref())
            == "https://revisor.mo.gov/main/PageSelect.aspx?chapter=536"
        )

    def test_section_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_make_ref("536.050"))
            == "https://revisor.mo.gov/main/OneSection.aspx?section=536.050"
        )

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestDiscovery:
    def setup_method(self) -> None:
        self.adapter = MissouriAdapter()

    def test_list_titles_real_fixture(self) -> None:
        with mock_urlopen_serving({HOME_URL: REAL_HOME_HTML}):
            titles = self.adapter.list_titles()

        identifiers = [n.identifier for n in titles]
        assert len(identifiers) == 41
        assert identifiers[0] == "I"
        assert identifiers[-1] == "XLI"
        assert "XXXVI" in identifiers
        assert all(n.level == HierarchyLevel.TITLE for n in titles)
        assert all(n.ref.state_code == "MO" for n in titles)

    def test_list_titles_sorted_by_chapter_range(self) -> None:
        with mock_urlopen_serving({HOME_URL: REAL_HOME_HTML}):
            titles = self.adapter.list_titles()
        # Title I (Chs. 1-3) sorts before Title II (Chs. 7-14) before
        # Title XLI (Chs. 700-701), even though the Roman numerals don't
        # sort lexically.
        by_id = {n.identifier: n.name for n in titles}
        assert by_id["XXXVI"] == "STATUTORY ACTIONS AND TORTS"
        assert by_id["I"] == "LAWS AND STATUTES"

    def test_list_titles_no_title_blocks_raises(self) -> None:
        with mock_urlopen("<html><body>no titles here</body></html>"):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_titles_network_failure_raises(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_chapters_real_fixture(self) -> None:
        with mock_urlopen_serving({HOME_URL: REAL_HOME_HTML}):
            chapters = self.adapter.list_chapters(_title_ref())

        assert len(chapters) == 18
        assert [n.identifier for n in chapters][:3] == ["521", "522", "523"]
        assert [n.name for n in chapters][:3] == [
            "Attachments",
            "Actions on Bonds",
            "Condemnation Proceedings",
        ]
        assert all(n.level == HierarchyLevel.CHAPTER for n in chapters)
        assert all(n.ref.title == _title_ref() for n in chapters)
        assert "536" in [n.identifier for n in chapters]

    def test_list_chapters_unknown_title_raises_ref_not_found(self) -> None:
        title_ref = TitleRef(state_code="MO", identifier="XLII")
        with mock_urlopen_serving({HOME_URL: REAL_HOME_HTML}):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_chapters(title_ref)

    def test_list_chapters_network_failure_raises(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_chapters(_title_ref())

    def test_list_sections_real_fixture(self) -> None:
        with mock_urlopen_serving({CH536_URL: REAL_CH536_HTML}):
            sections = self.adapter.list_sections(_chapter_ref())

        assert len(sections) == 54
        assert [n.identifier for n in sections][:3] == [
            "536.010",
            "536.014",
            "536.015",
        ]
        assert sections[0].name == "Definitions. (8/28/2006)"
        assert [n.identifier for n in sections][-1] == "536.320"
        assert all(n.level == HierarchyLevel.SECTION for n in sections)
        assert all(n.ref.chapter == _chapter_ref() for n in sections)

    def test_list_sections_name_keeps_effective_date(self) -> None:
        with mock_urlopen_serving({CH536_URL: REAL_CH536_HTML}):
            sections = self.adapter.list_sections(_chapter_ref())
        by_id = {n.identifier: n.name for n in sections}
        assert by_id["536.014"] == "Rules invalid, when. (6/27/1997)"
        assert by_id["536.320"] == (
            "Waiver or reduction of administrative penalties, when — "
            "inapplicability, when. (8/28/2004)"
        )

    def test_list_sections_no_links_raises(self) -> None:
        with mock_urlopen_serving({CH536_URL: "<html><body>no sections</body></html>"}):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_sections(_chapter_ref())

    def test_list_sections_404_raises_ref_not_found(self) -> None:
        chapter_ref = ChapterRef(title=_title_ref(), identifier="999")
        url = f"{BASE}/PageSelect.aspx?chapter=999"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_sections(chapter_ref)


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = MissouriAdapter()

    def test_simple_section_full_retrieval(self) -> None:
        ref = _make_ref("536.050")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "RSMo § 536.050"
        assert section.citation.state_code == "MO"
        assert section.ref == ref
        assert section.heading == (
            "Declaratory judgments respecting the validity of rules — fees "
            "and expenses — standing, intervention by general assembly."
        )
        assert section.text.startswith("1. The power of the courts of this state")
        assert "remedy is otherwise inadequate" in section.text
        assert section.status.value == "unknown"
        assert section.amendment_notes.startswith("(L. 1945 p. 1504 § 5")
        assert "A.L. 2005 H.B. 576" in section.amendment_notes
        assert section.source_url == SEC536050_URL
        assert section.retrieved_at is not None

    def test_repealed_section_status_repealed(self) -> None:
        ref = _make_ref("536.303")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "RSMo § 536.303"
        assert section.heading == "(Repealed L. 2024 S.B. 894 & 825)"
        assert section.text == ""
        assert section.status.value == "repealed"
        assert section.amendment_notes is None

    def test_title_mismatch_raises_ref_mismatch_error(self) -> None:
        # Request title I but the section page belongs to title XXXVI.
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="MO", identifier="I"),
                identifier="536",
            ),
            identifier="536.050",
        )
        url = f"{BASE}/OneSection.aspx?section=536.050"
        with mock_urlopen_serving({url: REAL_SEC536050_HTML}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(foreign_ref)

    def test_chapter_mismatch_raises_ref_mismatch_error(self) -> None:
        # Request chapter 1 but the section page belongs to chapter 536.
        foreign_ref = SectionRef(
            chapter=ChapterRef(title=_title_ref(), identifier="1"),
            identifier="536.050",
        )
        with mock_urlopen_serving({SEC536050_URL: REAL_SEC536050_HTML}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(foreign_ref)

    def test_missing_section_404_raises_ref_not_found(self) -> None:
        ref = _make_ref("536.999")
        url = f"{BASE}/OneSection.aspx?section=536.999"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable_error(self) -> None:
        ref = _make_ref("536.050")
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)


class TestParseEdgeCases:
    def setup_method(self) -> None:
        self.adapter = MissouriAdapter()

    def test_empty_body_raises_normalization_error(self) -> None:
        ref = _make_ref("536.050")
        html = (
            '<p>Title XXXVI  STATUTORY ACTIONS AND TORTS</p>'
            '<a href="/main/PageSelect.aspx?chapter=536">Chapter 536</a>'
            '<span class="bold"> 536.050.<span> </span>Something.</span>'
            '<div class="norm" title="" style="background-color:#fffff7;">'
            "   \n </div>"
        )
        with mock_urlopen_serving({SEC536050_URL: html}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)

    def test_missing_heading_raises_normalization_error(self) -> None:
        ref = _make_ref("536.050")
        html = (
            '<p>Title XXXVI  STATUTORY ACTIONS AND TORTS</p>'
            '<a href="/main/PageSelect.aspx?chapter=536">Chapter 536</a>'
            '<div class="norm" title="" style="background-color:#fffff7;">body</div>'
        )
        with mock_urlopen_serving({SEC536050_URL: html}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)

    def test_missing_title_anchor_raises_normalization_error(self) -> None:
        ref = _make_ref("536.050")
        html = (
            '<a href="/main/PageSelect.aspx?chapter=536">Chapter 536</a>'
            '<span class="bold"> 536.050.<span> </span>Something.</span>'
            '<p class="norm">body</p>'
        )
        with mock_urlopen_serving({SEC536050_URL: html}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = MissouriAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("536.050")
        parsed = ParsedDocument(
            raw_citation="RSMo § 536.050",
            heading="Declaratory judgments respecting the validity of rules.",
            text="1. The power of the courts ...",
            amendment_notes="(L. 1945 p. 1504 § 5)",
            source_url=SEC536050_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "RSMo § 536.050"
        assert section.citation.state_code == "MO"
        assert section.heading == "Declaratory judgments respecting the validity of rules."
        assert section.text == "1. The power of the courts ..."
        assert section.amendment_notes == "(L. 1945 p. 1504 § 5)"
        assert section.status.value == "unknown"

    def test_normalize_repealed_heading_sets_status(self) -> None:
        ref = _make_ref("536.303")
        parsed = ParsedDocument(
            raw_citation="RSMo § 536.303",
            heading="(Repealed L. 2024 S.B. 894 & 825)",
            text="",
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.status.value == "repealed"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="WA", identifier="49"),
                identifier="60",
            ),
            identifier="49.60.010",
        )
        parsed = ParsedDocument(
            raw_citation="RSMo § 536.050",
            text="Some text.",
        )
        with pytest.raises(NormalizationError):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("536.050")
        parsed = ParsedDocument(
            raw_citation="RSMo § 536.100",
            text="Some other section's text.",
        )
        with pytest.raises(RefMismatchError):
            self.adapter.normalize(parsed, ref)
