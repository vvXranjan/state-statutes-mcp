"""Tests for WashingtonAdapter.

Washington is the most markup-sensitive adapter in the framework (its
section parsing is anchored to specific tag/style combinations), so this
suite exercises it thoroughly. All retrieval tests are fully offline:
the real network boundary (``urllib.request.urlopen`` as imported by the
shared ``_fetch`` helper) is mocked, so the adapter's real fetch -> parse
path runs against the HTML below.

All HTML below is **synthetic** -- hand-written to match the confirmed
markup structure documented in ``WashingtonAdapter.retrieve_section``'s
docstring (bare ``<h1>`` citation, bare ``<h2>`` catchline,
``<div style="text-indent:0.5in;">`` body paragraphs, a
``margin-top:15pt`` history div, and the ``class="text-warning"`` footer
heading). It is NOT a saved real government fixture.
"""

from __future__ import annotations

import urllib.error

import pytest

from _mock_network import mock_urlopen, mock_urlopen_error

from state_statutes_mcp.adapters.washington.adapter import WashingtonAdapter
from state_statutes_mcp.core.exceptions import (
    AdapterUnavailableError,
    NormalizationError,
    RefMismatchError,
    UnsupportedRefError,
)
from state_statutes_mcp.models.documents import ParsedDocument
from state_statutes_mcp.models.hierarchy import HierarchyLevel
from state_statutes_mcp.models.refs import ChapterRef, SectionRef, TitleRef

# --- SYNTHETIC mock pages -- NOT real government fixtures. ---

# A complete section page: citation h1, catchline h2, two body
# paragraphs, a history div, and the site-wide footer heading.
SYNTHETIC_SECTION_HTML = """
<html><body>
<h1><!-- field: Citations -->RCW 49.60.010<!-- field: --></h1>
<h2><!-- field: CaptionsTitles -->Purpose of chapter.<!-- field: --></h2>
<div style="text-indent:0.5in;">It is the policy of the state of Washington to protect the health of all residents.</div>
<div style="text-indent:0.5in;">The legislature finds that this chapter furthers that policy.</div>
<div style="margin-top:15pt;margin-bottom:0pt;">[2006 c 66 &sect; 1; 1993 c 93 &sect; 1; 1979 c 19 &sect; 1.]</div>
<h2 class="text-warning">Legislative questions or comments</h2>
</body></html>
"""

# Title listing page: one "RCWs by Title" table row per title.
SYNTHETIC_TITLES_HTML = """
<html><body><table>
<tr><td><a href="default.aspx?Cite=49">Title 49</a></td><td>LABOR REGULATIONS</td></tr>
<tr><td><a href="default.aspx?Cite=9A">Title 9A</a></td><td>CRIMINAL LAW</td></tr>
</table></body></html>
"""

# Chapter listing page for title 49.
SYNTHETIC_CHAPTERS_HTML = """
<html><body><table>
<tr><td><a href="default.aspx?cite=49.60">49.60</a></td><td>Apprenticeship.</td></tr>
<tr><td><a href="default.aspx?cite=49.61">49.61</a></td><td>Employment counseling.</td></tr>
</table></body></html>
"""

# Section listing page for chapter 49.60, including an "HTML" format
# link (link text does not echo the citation, so it must be excluded),
# and a cross-chapter mention (different cite prefix, must be excluded).
SYNTHETIC_SECTIONS_HTML = """
<html><body><table>
<tr><td><a href="default.aspx?cite=49.60.010">HTML</a></td><td>&nbsp;</td></tr>
<tr><td><a href="default.aspx?cite=49.60.010">49.60.010</a></td><td>Purpose.</td></tr>
<tr><td><a href="default.aspx?cite=49.60.2235">49.60.2235</a></td><td>Definitions.</td></tr>
<tr><td><a href="default.aspx?cite=90.16.010">90.16.010</a></td><td>Water.</td></tr>
</table></body></html>
"""


def _make_ref(section: str) -> SectionRef:
    return SectionRef(
        chapter=ChapterRef(
            title=TitleRef(state_code="WA", identifier="49"),
            identifier="60",
        ),
        identifier=section,
    )


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert WashingtonAdapter.__abstractmethods__ == frozenset()
        adapter = WashingtonAdapter()
        assert adapter.state_code == "WA"
        assert adapter.state_name == "Washington"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = WashingtonAdapter()

    def test_title_ref_url(self) -> None:
        ref = TitleRef(state_code="WA", identifier="49")
        assert (
            self.adapter.build_url(ref)
            == "https://app.leg.wa.gov/RCW/default.aspx?cite=49"
        )

    def test_chapter_ref_url(self) -> None:
        ref = ChapterRef(
            title=TitleRef(state_code="WA", identifier="49"), identifier="60"
        )
        assert (
            self.adapter.build_url(ref)
            == "https://app.leg.wa.gov/RCW/default.aspx?cite=49.60"
        )

    def test_section_ref_url(self) -> None:
        ref = _make_ref("49.60.010")
        assert (
            self.adapter.build_url(ref)
            == "https://app.leg.wa.gov/RCW/default.aspx?cite=49.60.010"
        )

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestDiscovery:
    def setup_method(self) -> None:
        self.adapter = WashingtonAdapter()

    def test_list_titles(self) -> None:
        with mock_urlopen(SYNTHETIC_TITLES_HTML):
            titles = self.adapter.list_titles()

        assert [n.identifier for n in titles] == ["49", "9A"]
        assert [n.name for n in titles] == ["LABOR REGULATIONS", "CRIMINAL LAW"]
        assert all(n.level == HierarchyLevel.TITLE for n in titles)
        assert all(n.ref.state_code == "WA" for n in titles)

    def test_list_chapters(self) -> None:
        title_ref = TitleRef(state_code="WA", identifier="49")
        with mock_urlopen(SYNTHETIC_CHAPTERS_HTML):
            chapters = self.adapter.list_chapters(title_ref)

        assert [n.identifier for n in chapters] == ["60", "61"]
        assert [n.name for n in chapters] == ["Apprenticeship.", "Employment counseling."]
        assert all(n.level == HierarchyLevel.CHAPTER for n in chapters)

    def test_list_sections_excludes_format_links_and_cross_refs(self) -> None:
        chapter_ref = ChapterRef(
            title=TitleRef(state_code="WA", identifier="49"), identifier="60"
        )
        with mock_urlopen(SYNTHETIC_SECTIONS_HTML):
            sections = self.adapter.list_sections(chapter_ref)

        assert [n.identifier for n in sections] == ["49.60.010", "49.60.2235"]
        assert [n.name for n in sections] == ["Purpose.", "Definitions."]
        assert all(n.level == HierarchyLevel.SECTION for n in sections)

    def test_list_titles_no_rows_raises(self) -> None:
        with mock_urlopen("<html><body>nothing here</body></html>"):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()


class TestRetrieveSection:
    """Retrieval tests against synthetic markup that matches the
    confirmed structure documented in the adapter."""

    def setup_method(self) -> None:
        self.adapter = WashingtonAdapter()
        self.ref = _make_ref("49.60.010")

    def test_full_retrieval_citation_catchline_body_history(self) -> None:
        with mock_urlopen(SYNTHETIC_SECTION_HTML):
            section = self.adapter.retrieve_section(self.ref)

        assert section.citation.raw == "RCW 49.60.010"
        assert section.heading == "Purpose of chapter."
        assert (
            "It is the policy of the state of Washington to protect "
            "the health of all residents."
            in section.text
        )
        assert "The legislature finds that this chapter furthers that policy." in section.text
        assert "\n\n" in section.text
        assert section.amendment_notes == "[2006 c 66 \u00a7 1; 1993 c 93 \u00a7 1; 1979 c 19 \u00a7 1.]"
        assert section.source_url == "https://app.leg.wa.gov/RCW/default.aspx?cite=49.60.010"
        assert section.retrieved_at is not None

    def test_no_citation_h1_raises_normalization_error(self) -> None:
        with mock_urlopen("<html><body><div>no heading here</div></body></html>"):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(self.ref)

    def test_no_body_paragraphs_raises_normalization_error(self) -> None:
        html = (
            "<h1>RCW 49.60.010</h1>"
            "<h2>Purpose of chapter.</h2>"
            "<h2 class=\"text-warning\">footer</h2>"
        )
        with mock_urlopen(html):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(self.ref)

    def test_empty_body_raises_normalization_error(self) -> None:
        html = (
            "<h1>RCW 49.60.010</h1>"
            "<h2>Purpose of chapter.</h2>"
            '<div style="text-indent:0.5in;">   </div>'
            '<h2 class="text-warning">footer</h2>'
        )
        with mock_urlopen(html):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(self.ref)

    def test_network_failure_raises_adapter_unavailable_error(self) -> None:
        with mock_urlopen_error(
            urllib.error.URLError("simulated network failure")
        ):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(self.ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = WashingtonAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("49.60.010")
        parsed = ParsedDocument(
            raw_citation="RCW 49.60.010",
            heading="Purpose of chapter.",
            text="It is the policy of the state of Washington...",
            amendment_notes="[2006 c 66 \u00a7 1.]",
            source_url="https://app.leg.wa.gov/RCW/default.aspx?cite=49.60.010",
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "RCW 49.60.010"
        assert section.heading == "Purpose of chapter."
        assert section.text == "It is the policy of the state of Washington..."
        assert section.amendment_notes == "[2006 c 66 \u00a7 1.]"
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="TX", identifier="PE"),
                identifier="19",
            ),
            identifier="19.01",
        )
        parsed = ParsedDocument(
            raw_citation="RCW 49.60.010",
            text="It is the policy of the state of Washington...",
        )
        with pytest.raises(NormalizationError):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("49.60.010")
        parsed = ParsedDocument(
            raw_citation="RCW 49.60.100",
            text="Some other section's text.",
        )
        with pytest.raises(RefMismatchError):
            self.adapter.normalize(parsed, ref)