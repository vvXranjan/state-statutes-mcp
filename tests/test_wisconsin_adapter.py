"""Tests for WisconsinAdapter.

Wisconsin is a server-rendered HTML source (the official Wisconsin
Legislature publication of the Wisconsin Statutes at docs.legis.wisconsin.gov).
The site has NO formal title level: chapters are listed flatly on the
statutes index page. To fit the framework's three-level ref model, the
adapter maps the entire code onto a single synthetic ``TitleRef`` whose
identifier is ``"Wisconsin Statutes"`` -- an adapter-internal mapping, not
a framework change. Chapter identifiers are numeric (``13``);
``SectionRef.identifier`` is the full dotted ``{chapter}.{section}`` form
(e.g. ``"13.92"``, ``"13.035"``).

A Wisconsin section page renders a RANGE of sections (the requested
section plus preceding siblings in the same subchapter); the adapter
isolates the requested section's ``qsatxt_1sect level3`` block by its
``data-section`` attribute. History is present only for sections whose
history has been rendered on the page (13.90 has one; 13.92, the last
rendered section, does not), so ``amendment_notes`` is optional.

Section-retrieval and section-discovery tests exercise the adapter's real
fetch -> parse path against **REAL captured Wisconsin HTML**: verbatim
slices of the official docs.legis.wisconsin.gov pages, captured through a
Wayback Machine snapshot of the official host (timestamp 20260722161219,
the live host being unreachable from this environment) and stored under
``tests/fixtures/wi_*``:

* ``wi_statutes_index.html`` -- the statutes index page (flat list of all
  470 chapters).
* ``wi_chapter13.html`` -- the Chapter 13 page (55 sections).
* ``wi_section_13.92.html`` -- the section page for 13.92 (renders the
  13.905-13.92 range; no history block for 13.92).
* ``wi_section_13.90.html`` -- the section page for 13.90 (renders the
  13.90-13.92 range; 13.90 carries a history block).

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

from state_statutes_mcp.adapters.wisconsin.adapter import WisconsinAdapter
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

# --- REAL fixtures: verbatim slices of the official Wisconsin Legislature
# --- statutes pages captured through a Wayback Machine snapshot of
# --- docs.legis.wisconsin.gov (timestamp 20260722161219). NOT synthetic.
FIXTURES = Path(__file__).parent / "fixtures"

REAL_INDEX_HTML = (FIXTURES / "wi_statutes_index.html").read_text(
    encoding="utf-8"
)
REAL_CH13_HTML = (FIXTURES / "wi_chapter13.html").read_text(encoding="utf-8")
REAL_SEC13_92_HTML = (FIXTURES / "wi_section_13.92.html").read_text(
    encoding="utf-8"
)
REAL_SEC13_90_HTML = (FIXTURES / "wi_section_13.90.html").read_text(
    encoding="utf-8"
)

BASE = "https://docs.legis.wisconsin.gov"

INDEX_URL = f"{BASE}/statutes/statutes"
CH13_URL = f"{BASE}/statutes/statutes/13"
SEC13_92_URL = f"{BASE}/document/statutes/13.92"
SEC13_90_URL = f"{BASE}/document/statutes/13.90"


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the shared fetch helper will
    wrap into ``AdapterUnavailableError`` with ``__cause__`` set to it."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


def _title_ref() -> TitleRef:
    return TitleRef(state_code="WI", identifier="Wisconsin Statutes")


def _chapter_ref() -> ChapterRef:
    return ChapterRef(title=_title_ref(), identifier="13")


def _make_ref(section: str) -> SectionRef:
    return SectionRef(chapter=_chapter_ref(), identifier=section)


def _serve_all() -> dict[str, str]:
    return {
        INDEX_URL: REAL_INDEX_HTML,
        CH13_URL: REAL_CH13_HTML,
        SEC13_92_URL: REAL_SEC13_92_HTML,
        SEC13_90_URL: REAL_SEC13_90_HTML,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert WisconsinAdapter.__abstractmethods__ == frozenset()
        adapter = WisconsinAdapter()
        assert adapter.state_code == "WI"
        assert adapter.state_name == "Wisconsin"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = WisconsinAdapter()

    def test_title_ref_url_is_index_page(self) -> None:
        assert (
            self.adapter.build_url(_title_ref())
            == "https://docs.legis.wisconsin.gov/statutes/statutes"
        )

    def test_chapter_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_chapter_ref())
            == "https://docs.legis.wisconsin.gov/statutes/statutes/13"
        )

    def test_section_ref_url_uses_document_redirect(self) -> None:
        assert (
            self.adapter.build_url(_make_ref("13.92"))
            == "https://docs.legis.wisconsin.gov/document/statutes/13.92"
        )

    def test_section_ref_url_decimal_local(self) -> None:
        assert (
            self.adapter.build_url(_make_ref("13.035"))
            == "https://docs.legis.wisconsin.gov/document/statutes/13.035"
        )

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestListTitles:
    def test_returns_single_synthetic_title(self) -> None:
        adapter = WisconsinAdapter()
        titles = adapter.list_titles()

        assert len(titles) == 1
        node = titles[0]
        assert node.level == HierarchyLevel.TITLE
        assert node.identifier == "Wisconsin Statutes"
        assert node.name == "Wisconsin Statutes"
        assert node.ref.state_code == "WI"


class TestListChapters:
    def test_returns_all_470_chapters_from_index(self) -> None:
        adapter = WisconsinAdapter()
        with mock_urlopen_serving({INDEX_URL: REAL_INDEX_HTML}):
            chapters = adapter.list_chapters(_title_ref())

        assert len(chapters) == 470
        assert [n.identifier for n in chapters][:3] == ["1", "2", "3"]
        assert [n.identifier for n in chapters][-1] == "995"
        assert chapters[0].name == "Sovereignty And Jurisdiction Of The State"
        assert all(n.level == HierarchyLevel.CHAPTER for n in chapters)
        assert all(n.ref.title == _title_ref() for n in chapters)

    def test_chapter_13_name(self) -> None:
        adapter = WisconsinAdapter()
        with mock_urlopen_serving({INDEX_URL: REAL_INDEX_HTML}):
            chapters = adapter.list_chapters(_title_ref())
        by_id = {n.identifier: n.name for n in chapters}
        assert by_id["13"] == "Legislative Branch"

    def test_nameless_chapter_falls_back_to_identifier(self) -> None:
        adapter = WisconsinAdapter()
        with mock_urlopen_serving({INDEX_URL: REAL_INDEX_HTML}):
            chapters = adapter.list_chapters(_title_ref())
        by_id = {n.identifier: n.name for n in chapters}
        # Chapter 164 is listed on the index page without a name.
        assert by_id["164"] == "164"

    def test_numeric_order(self) -> None:
        adapter = WisconsinAdapter()
        with mock_urlopen_serving({INDEX_URL: REAL_INDEX_HTML}):
            chapters = adapter.list_chapters(_title_ref())
        identifiers = [n.identifier for n in chapters]
        assert identifiers == sorted(identifiers, key=int)

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = WisconsinAdapter()
        # The synthetic title never 404s; force the error path via the
        # fetch boundary directly to confirm the mapping.
        with mock_urlopen_error(_http_error(INDEX_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_chapters(_title_ref())

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = WisconsinAdapter()
        with mock_urlopen("<html><body>no chapters</body></html>"):
            with pytest.raises(AdapterUnavailableError, match="no usable chapter"):
                adapter.list_chapters(_title_ref())

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = WisconsinAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_chapters(_title_ref())


class TestListSections:
    def test_returns_sections_from_chapter_13(self) -> None:
        adapter = WisconsinAdapter()
        with mock_urlopen_serving({CH13_URL: REAL_CH13_HTML}):
            sections = adapter.list_sections(_chapter_ref())

        assert len(sections) == 55
        assert sections[0].identifier == "13.01"
        assert [n.identifier for n in sections][1:3] == ["13.02", "13.03"]
        assert sections[-1].identifier == "13.31"
        assert all(n.level == HierarchyLevel.SECTION for n in sections)
        assert all(n.ref.chapter == _chapter_ref() for n in sections)

    def test_section_names_present(self) -> None:
        adapter = WisconsinAdapter()
        with mock_urlopen_serving({CH13_URL: REAL_CH13_HTML}):
            sections = adapter.list_sections(_chapter_ref())
        by_id = {n.identifier: n.name for n in sections}
        assert by_id["13.01"] == "Number of legislators."
        assert by_id["13.02"] == "Regular sessions."
        assert by_id["13.31"] == "Witnesses; how subpoenaed."

    def test_decimal_local_identifier(self) -> None:
        adapter = WisconsinAdapter()
        with mock_urlopen_serving({CH13_URL: REAL_CH13_HTML}):
            sections = adapter.list_sections(_chapter_ref())
        identifiers = [n.identifier for n in sections]
        # A leading-zero local extension sorts between 13.02 and 13.03.
        assert "13.035" in identifiers

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = WisconsinAdapter()
        with mock_urlopen_error(_http_error(CH13_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_sections(_chapter_ref())

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = WisconsinAdapter()
        with mock_urlopen_serving({CH13_URL: "<html><body>none</body></html>"}):
            with pytest.raises(AdapterUnavailableError, match="no usable section"):
                adapter.list_sections(_chapter_ref())


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = WisconsinAdapter()

    def test_last_rendered_section_full_retrieval(self) -> None:
        ref = _make_ref("13.92")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Wis. Stat. § 13.92"
        assert section.citation.state_code == "WI"
        assert section.ref == ref
        assert section.heading == "Legislative reference bureau."
        assert "There is created a bureau to be known as" in section.text
        assert "(1) Duties of the bureau." in section.text
        # 13.92 is the last section rendered on its page; its history block
        # falls on the next scroll chunk and is absent here.
        assert section.amendment_notes is None
        assert section.status.value == "unknown"
        assert section.source_url == SEC13_92_URL
        assert section.retrieved_at is not None

    def test_history_carrying_section(self) -> None:
        ref = _make_ref("13.90")
        with mock_urlopen_serving(_serve_all()):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Wis. Stat. § 13.90"
        assert section.heading == (
            "Duties and powers of the joint committee on legislative "
            "organization."
        )
        assert "(1) The joint committee on legislative organization" in section.text
        assert section.amendment_notes is not None
        assert section.amendment_notes.startswith("1971 c. 215 ;")
        assert "2023 a. 19 ." in section.amendment_notes
        assert section.status.value == "unknown"
        assert section.source_url == SEC13_90_URL

    def test_missing_section_404_raises_ref_not_found(self) -> None:
        ref = _make_ref("13.999")
        url = "https://docs.legis.wisconsin.gov/document/statutes/13.999"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable_error(self) -> None:
        ref = _make_ref("13.92")
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)


class TestParseEdgeCases:
    def setup_method(self) -> None:
        self.adapter = WisconsinAdapter()

    def test_section_not_rendered_in_range_raises_normalization_error(self) -> None:
        # Serve the 13.90 range page under 13.50's URL, but request 13.50,
        # which is not in that rendered range.
        ref = _make_ref("13.50")
        url = "https://docs.legis.wisconsin.gov/document/statutes/13.50"
        with mock_urlopen_serving({url: REAL_SEC13_90_HTML}):
            with pytest.raises(NormalizationError, match="did not render section"):
                self.adapter.retrieve_section(ref)

    def test_missing_heading_raises_normalization_error(self) -> None:
        ref = _make_ref("13.92")
        html = (
            '<div class="qsatxt_1sect  level3" data-section="13.92">'
            "<p>body</p></div>"
        )
        with mock_urlopen_serving({SEC13_92_URL: html}):
            with pytest.raises(NormalizationError, match="no heading element"):
                self.adapter.retrieve_section(ref)

    def test_empty_body_raises_normalization_error(self) -> None:
        ref = _make_ref("13.92")
        html = (
            '<div class="qsatxt_1sect  level3" data-section="13.92">'
            '<span class="qstitle_sect">Heading.</span></div>'
        )
        with mock_urlopen_serving({SEC13_92_URL: html}):
            with pytest.raises(NormalizationError, match="body text was empty"):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = WisconsinAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("13.92")
        parsed = ParsedDocument(
            raw_citation="Wis. Stat. § 13.92",
            heading="Legislative reference bureau.",
            text="There is created a bureau ...",
            amendment_notes=None,
            source_url=SEC13_92_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "Wis. Stat. § 13.92"
        assert section.citation.state_code == "WI"
        assert section.heading == "Legislative reference bureau."
        assert section.text == "There is created a bureau ..."
        assert section.amendment_notes is None
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="MN", identifier="x"), identifier="1"
            ),
            identifier="13.92",
        )
        parsed = ParsedDocument(
            raw_citation="Wis. Stat. § 13.92",
            text="Some text.",
        )
        with pytest.raises(NormalizationError, match="expected 'WI'"):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("13.92")
        parsed = ParsedDocument(
            raw_citation="Wis. Stat. § 13.90",
            text="Some other section's text.",
        )
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, ref)
