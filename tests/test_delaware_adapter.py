"""Tests for DelawareAdapter.

Delaware is the framework's first anchor-based adapter: sections are not
individually addressable by URL but live as ``SectionHead`` anchors inside a
containing document (a chapter page when the chapter has no subchapters, or
the subchapter pages when it does). These tests exercise both chapter shapes
(inline vs subchapter-based), the reserved/range ``[Reserved.]`` handling,
lettered chapter identifiers (``84a``, ``87a``), the padded URL scheme, and
the end-to-end section retrieval. All retrieval tests are fully offline: the
real network boundary (``urllib.request.urlopen`` as imported by the shared
``_fetch`` helper) is mocked, so the adapter's real fetch -> parse path runs
against the HTML below.

All HTML below is **synthetic** -- hand-written to match the confirmed markup
structure documented in ``DelawareAdapter``'s module docstring and in
``docs/research/delaware.md`` (home page ``title{N}/index.html`` links; title
page ``cNNN.../index.html`` chapter links; ``<div class="Section">`` blocks
with ``<div class="SectionHead" id="N">`` anchors, ``<p class="subsection">``
body paragraphs, and a trailing inline amendment-history chain). It is NOT a
saved real government fixture.
"""

from __future__ import annotations

import io
import urllib.error

import pytest

from _mock_network import mock_urlopen, mock_urlopen_error, mock_urlopen_serving

from state_statutes_mcp.adapters.delaware.adapter import DelawareAdapter
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

# --- SYNTHETIC mock pages -- NOT real government fixtures. ---

# Home page: title links in a deliberately scrambled order, plus a
# constitution link the adapter must ignore.
SYNTHETIC_HOME_HTML = """
<html><body>
  <div class="title-links"><a href="&#xA; title11/index.html&#xA; ">
                        Title 11 - Crimes and Criminal Procedure</a></div>
  <div class="title-links"><a href="&#xA; title1/index.html&#xA; ">
                        Title 1 - General Provisions</a></div>
  <div class="title-links"><a href="&#xA; title2/index.html&#xA; ">
                        Title 2 - Transportation</a></div>
  <div class="title-links"><a href="constitution/index.html">The Delaware Constitution</a></div>
</body></html>
"""

# Title 11 page: chapter links (scrambled order, lettered chapters included,
# plus a PDF link the adapter must ignore).
SYNTHETIC_TITLE_HTML = """
<html><body>
  <h3>Part I</h3><h3>Delaware Criminal Code</h3>
  <div class="title-links"><a href="../title11/c005/index.html">
                          Chapter 5. SPECIFIC OFFENSES</a></div>
  <div class="title-links"><a href="../title11/c001/index.html">
                          Chapter 1. INTRODUCTORY PROVISIONS</a></div>
  <div class="title-links"><a href="../title11/c087a/index.html">
                          Chapter 87A. Reporting and Review of Deaths of Individuals in Custody of Law Enforcement Agencies</a></div>
  <div class="title-links"><a href="../title11/c084a/index.html">
                          Chapter 84A. Body-Worn Cameras for Law-Enforcement Officers</a></div>
  <span class="breadcrumb"><a href="../Title11.pdf">Authenticated PDF</a></span>
</body></html>
"""

# Inline chapter (c001): no subchapters; sections rendered directly on the
# chapter page.
SYNTHETIC_INLINE_CHAPTER_HTML = """
<html><body>
  <div id="TitleHead"><h1>TITLE 11</h1><h4>Crimes and Criminal Procedure</h4>
    <h2>Delaware Criminal Code</h2><h3>CHAPTER 1. Introductory Provisions</h3></div>
  <div id="CodeBody">
    <div class="Section">
      <div class="SectionHead" id="101">
          \u00a7
        101. Short title.</div>
      <p class="subsection">Part I of this title shall be known as the "Delaware Criminal Code."</p>11 Del. C. 1953,
                \u00a7
               101;
      <a href="https://legis.delaware.gov/SessionLaws?volume=58&amp;chapter=497">58 Del. Laws, c. 497,
                \u00a7
               1</a>;
      </div><br><div class="Section">
      <div class="SectionHead" id="102">
          \u00a7
        102. Applicability to offenses committed prior to July 1, 1973.</div>
      <p class="subsection">Except as provided in subsections (b) and (c) of this section, this Criminal Code does not apply to offenses committed prior to July 1, 1973.</p>11 Del. C. 1953,
                \u00a7
               102;
      <a href="https://legis.delaware.gov/SessionLaws?volume=58&amp;chapter=497">58 Del. Laws, c. 497,
                \u00a7
               1</a>;
      </div><br>
  </div>
</body></html>
"""

# Subchapter-based chapter (c005): the chapter page lists only subchapters.
SYNTHETIC_SUBCHAPTER_CHAPTER_HTML = """
<html><body>
  <div class="title-links"><a href="../../title11/c005/sc01/index.html">
                        Subchapter I. Inchoate Crimes</a></div>
  <div class="title-links"><a href="../../title11/c005/sc02/index.html">
                        Subchapter II. Offenses Against the Person</a></div>
</body></html>
"""

# Subchapter I page: sections 501/502 (with history), a reserved range block
# 504-510, and 542.
SYNTHETIC_SUBCHAPTER_HTML = """
<html><body>
  <div id="TitleHead"><h1>TITLE 11</h1><h4>Crimes and Criminal Procedure</h4>
    <h2>Delaware Criminal Code</h2><h3>CHAPTER 5. Specific Offenses</h3>
    <h4>Subchapter I. Inchoate Crimes</h4></div>
  <div id="CodeBody">
    <div class="Section">
      <div class="SectionHead" id="501">
          \u00a7
        501. Criminal solicitation in the third degree; class A misdemeanor.</div>
      <p class="subsection">A person is guilty of criminal solicitation in the third degree when, intending that another person engage in conduct constituting a misdemeanor, the person solicits, requests, commands, importunes or otherwise attempts to cause the other person to engage in conduct that would constitute the misdemeanor.</p>
      <p class="subsection">Criminal solicitation in the third degree is a class A misdemeanor.</p>11 Del. C. 1953,
                \u00a7
               501;
      <a href="https://legis.delaware.gov/SessionLaws?volume=58&amp;chapter=497">58 Del. Laws, c. 497,
                \u00a7
               1</a>;
      <a href="https://legis.delaware.gov/SessionLaws?volume=67&amp;chapter=130">67 Del. Laws, c. 130,
                \u00a7
               8</a>;
      <a href="https://legis.delaware.gov/SessionLaws?volume=70&amp;chapter=186">70 Del. Laws, c. 186,
                \u00a7
               1</a>;
      </div><br><div class="Section">
      <div class="SectionHead" id="502">
          \u00a7
        502. Criminal solicitation in the second degree; class F felony.</div>
      <p class="subsection">A person is guilty of criminal solicitation in the second degree when, intending that another person engage in conduct constituting a felony, the person solicits or otherwise attempts to cause the other person to engage in such conduct.</p>11 Del. C. 1953,
                \u00a7
               502;
      <a href="https://legis.delaware.gov/SessionLaws?volume=58&amp;chapter=497">58 Del. Laws, c. 497,
                \u00a7
               1</a>;
      </div><br><div class="Section">
      <div class="SectionHead" id="504-510">
          \u00a7\u00a7
        504-510. [Reserved.]</div>
      </div><br><div class="Section">
      <div class="SectionHead" id="542">
          \u00a7
        542. Exemption of law-enforcement officers.</div>
      <p class="subsection">Nothing in this subchapter shall apply to any law-enforcement officer or the officer's agent while acting in the lawful performance of duty.</p>11 Del. C. 1953,
                \u00a7
               542;
      <a href="https://legis.delaware.gov/SessionLaws?volume=58&amp;chapter=497">58 Del. Laws, c. 497,
                \u00a7
               1</a>;
      </div><br>
  </div>
</body></html>
"""

# Subchapter II page: sections 601 and 613.
SYNTHETIC_SUBCHAPTER2_HTML = """
<html><body>
  <div id="CodeBody">
    <div class="Section">
      <div class="SectionHead" id="601">
          \u00a7
        601. Kidnapping in the first degree; class A felony.</div>
      <p class="subsection">A person is guilty of kidnapping in the first degree when the person unlawfully confines another person with intent to compel a third person to pay a ransom.</p>11 Del. C. 1953,
                \u00a7
               601;
      </div><br><div class="Section">
      <div class="SectionHead" id="613">
          \u00a7
        613. Definitions.</div>
      <p class="subsection">As used in this subchapter, the following words have the following meanings.</p>11 Del. C. 1953,
                \u00a7
               613;
      </div><br>
  </div>
</body></html>
"""

HOME_URL = "https://delcode.delaware.gov/"
TITLE11_URL = "https://delcode.delaware.gov/title11/index.html"
C001_URL = "https://delcode.delaware.gov/title11/c001/index.html"
C005_URL = "https://delcode.delaware.gov/title11/c005/index.html"
SC01_URL = "https://delcode.delaware.gov/title11/c005/sc01/index.html"
SC02_URL = "https://delcode.delaware.gov/title11/c005/sc02/index.html"


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the shared fetch helper will
    wrap into ``AdapterUnavailableError`` with ``__cause__`` set to it."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


def _make_ref(section: str) -> SectionRef:
    return SectionRef(
        chapter=ChapterRef(
            title=TitleRef(state_code="DE", identifier="11"),
            identifier="5",
        ),
        identifier=section,
    )


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert DelawareAdapter.__abstractmethods__ == frozenset()
        adapter = DelawareAdapter()
        assert adapter.state_code == "DE"
        assert adapter.state_name == "Delaware"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = DelawareAdapter()

    def test_title_ref_url(self) -> None:
        ref = TitleRef(state_code="DE", identifier="11")
        assert (
            self.adapter.build_url(ref)
            == "https://delcode.delaware.gov/title11/index.html"
        )

    def test_chapter_ref_url(self) -> None:
        ref = ChapterRef(
            title=TitleRef(state_code="DE", identifier="11"), identifier="5"
        )
        assert (
            self.adapter.build_url(ref)
            == "https://delcode.delaware.gov/title11/c005/index.html"
        )

    def test_chapter_ref_url_pads_and_keeps_letter_suffix(self) -> None:
        ref = ChapterRef(
            title=TitleRef(state_code="DE", identifier="11"), identifier="84a"
        )
        assert (
            self.adapter.build_url(ref)
            == "https://delcode.delaware.gov/title11/c084a/index.html"
        )

    def test_section_ref_url_is_parent_chapter_page(self) -> None:
        ref = _make_ref("501")
        assert (
            self.adapter.build_url(ref)
            == "https://delcode.delaware.gov/title11/c005/index.html"
        )

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestChapterIdentifierConversion:
    def setup_method(self) -> None:
        self.adapter = DelawareAdapter()

    @pytest.mark.parametrize(
        ("identifier", "url_id"),
        [
            ("5", "005"),
            ("1", "001"),
            ("100", "100"),
            ("84a", "084a"),
            ("87a", "087a"),
        ],
    )
    def test_chapter_to_url(self, identifier: str, url_id: str) -> None:
        assert self.adapter._chapter_to_url(identifier) == url_id

    @pytest.mark.parametrize(
        ("url_id", "identifier"),
        [
            ("005", "5"),
            ("001", "1"),
            ("100", "100"),
            ("084a", "84a"),
            ("087a", "87a"),
        ],
    )
    def test_chapter_to_identifier(self, url_id: str, identifier: str) -> None:
        assert self.adapter._chapter_to_identifier(url_id) == identifier


class TestDiscovery:
    def setup_method(self) -> None:
        self.adapter = DelawareAdapter()

    def test_list_titles(self) -> None:
        with mock_urlopen(SYNTHETIC_HOME_HTML):
            titles = self.adapter.list_titles()

        assert [n.identifier for n in titles] == ["1", "2", "11"]
        assert [n.name for n in titles] == [
            "General Provisions",
            "Transportation",
            "Crimes and Criminal Procedure",
        ]
        assert all(n.level == HierarchyLevel.TITLE for n in titles)
        assert all(n.ref.state_code == "DE" for n in titles)

    def test_list_titles_no_title_links_raises(self) -> None:
        with mock_urlopen("<html><body>no titles here</body></html>"):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_titles_network_failure_raises(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_chapters(self) -> None:
        title_ref = TitleRef(state_code="DE", identifier="11")
        with mock_urlopen_serving({TITLE11_URL: SYNTHETIC_TITLE_HTML}):
            chapters = self.adapter.list_chapters(title_ref)

        assert [n.identifier for n in chapters] == ["1", "5", "84a", "87a"]
        assert [n.name for n in chapters] == [
            "INTRODUCTORY PROVISIONS",
            "SPECIFIC OFFENSES",
            "Body-Worn Cameras for Law-Enforcement Officers",
            "Reporting and Review of Deaths of Individuals in Custody of Law Enforcement Agencies",
        ]
        assert all(n.level == HierarchyLevel.CHAPTER for n in chapters)
        assert all(n.ref.title == title_ref for n in chapters)

    def test_list_chapters_404_raises_ref_not_found(self) -> None:
        title_ref = TitleRef(state_code="DE", identifier="11")
        with mock_urlopen_error(_http_error(TITLE11_URL)):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_chapters(title_ref)

    def test_list_chapters_network_failure_raises(self) -> None:
        title_ref = TitleRef(state_code="DE", identifier="11")
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_chapters(title_ref)

    def test_list_sections_inline_chapter(self) -> None:
        chapter_ref = ChapterRef(
            title=TitleRef(state_code="DE", identifier="11"), identifier="1"
        )
        with mock_urlopen_serving({C001_URL: SYNTHETIC_INLINE_CHAPTER_HTML}):
            sections = self.adapter.list_sections(chapter_ref)

        assert [n.identifier for n in sections] == ["101", "102"]
        assert [n.name for n in sections] == [
            "Short title.",
            "Applicability to offenses committed prior to July 1, 1973.",
        ]
        assert all(n.level == HierarchyLevel.SECTION for n in sections)
        assert all(n.ref.chapter == chapter_ref for n in sections)

    def test_list_sections_subchapter_chapter_walks_subchapters(self) -> None:
        chapter_ref = ChapterRef(
            title=TitleRef(state_code="DE", identifier="11"), identifier="5"
        )
        served = {
            C005_URL: SYNTHETIC_SUBCHAPTER_CHAPTER_HTML,
            SC01_URL: SYNTHETIC_SUBCHAPTER_HTML,
            SC02_URL: SYNTHETIC_SUBCHAPTER2_HTML,
        }
        with mock_urlopen_serving(served):
            sections = self.adapter.list_sections(chapter_ref)

        assert [n.identifier for n in sections] == [
            "501",
            "502",
            "504-510",
            "542",
            "601",
            "613",
        ]
        assert [n.name for n in sections] == [
            "Criminal solicitation in the third degree; class A misdemeanor.",
            "Criminal solicitation in the second degree; class F felony.",
            "[Reserved.]",
            "Exemption of law-enforcement officers.",
            "Kidnapping in the first degree; class A felony.",
            "Definitions.",
        ]
        assert all(n.level == HierarchyLevel.SECTION for n in sections)
        assert all(n.ref.chapter == chapter_ref for n in sections)

    def test_list_sections_404_raises_ref_not_found(self) -> None:
        chapter_ref = ChapterRef(
            title=TitleRef(state_code="DE", identifier="11"), identifier="999"
        )
        url = "https://delcode.delaware.gov/title11/c999/index.html"
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.list_sections(chapter_ref)

    def test_list_sections_no_anchors_raises(self) -> None:
        chapter_ref = ChapterRef(
            title=TitleRef(state_code="DE", identifier="11"), identifier="5"
        )
        with mock_urlopen_serving({C005_URL: "<html><body>no sections</body></html>"}):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_sections(chapter_ref)


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = DelawareAdapter()

    def test_section_in_subchapter_full_retrieval(self) -> None:
        ref = _make_ref("501")
        # Only the chapter page and sc01 are served: 501 is found in sc01,
        # so the walk must stop there and never fetch sc02.
        served = {
            C005_URL: SYNTHETIC_SUBCHAPTER_CHAPTER_HTML,
            SC01_URL: SYNTHETIC_SUBCHAPTER_HTML,
        }
        with mock_urlopen_serving(served):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "11 Del. C. § 501"
        assert section.citation.state_code == "DE"
        assert section.ref == ref
        assert section.heading == (
            "Criminal solicitation in the third degree; class A misdemeanor."
        )
        assert section.text == (
            "A person is guilty of criminal solicitation in the third degree when, "
            "intending that another person engage in conduct constituting a "
            "misdemeanor, the person solicits, requests, commands, importunes or "
            "otherwise attempts to cause the other person to engage in conduct that "
            "would constitute the misdemeanor.\n\n"
            "Criminal solicitation in the third degree is a class A misdemeanor."
        )
        assert section.amendment_notes == (
            "11 Del. C. 1953, § 501; 58 Del. Laws, c. 497, § 1 ; "
            "67 Del. Laws, c. 130, § 8 ; 70 Del. Laws, c. 186, § 1 ;"
        )
        assert section.status.value == "unknown"
        assert section.source_url == C005_URL
        assert section.retrieved_at is not None

    def test_section_in_inline_chapter(self) -> None:
        ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="DE", identifier="11"),
                identifier="1",
            ),
            identifier="101",
        )
        with mock_urlopen_serving({C001_URL: SYNTHETIC_INLINE_CHAPTER_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "11 Del. C. § 101"
        assert section.heading == "Short title."
        assert section.text == (
            'Part I of this title shall be known as the "Delaware Criminal Code."'
        )
        assert section.amendment_notes == (
            "11 Del. C. 1953, § 101; 58 Del. Laws, c. 497, § 1 ;"
        )
        assert section.status.value == "unknown"

    def test_missing_anchor_raises_ref_not_found(self) -> None:
        ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="DE", identifier="11"),
                identifier="1",
            ),
            identifier="999",
        )
        with mock_urlopen_serving({C001_URL: SYNTHETIC_INLINE_CHAPTER_HTML}):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(ref)

    def test_chapter_404_raises_ref_not_found(self) -> None:
        ref = _make_ref("501")
        url = "https://delcode.delaware.gov/title11/c999/index.html"
        bad_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="DE", identifier="11"),
                identifier="999",
            ),
            identifier="501",
        )
        with mock_urlopen_error(_http_error(url)):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(bad_ref)

    def test_reserved_range_section_raises_normalization_error(self) -> None:
        ref = _make_ref("504-510")
        served = {
            C005_URL: SYNTHETIC_SUBCHAPTER_CHAPTER_HTML,
            SC01_URL: SYNTHETIC_SUBCHAPTER_HTML,
        }
        with mock_urlopen_serving(served):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable_error(self) -> None:
        ref = _make_ref("501")
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = DelawareAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("501")
        parsed = ParsedDocument(
            raw_citation="11 Del. C. § 501",
            heading="Criminal solicitation in the third degree; class A misdemeanor.",
            text="A person is guilty of criminal solicitation in the third degree...",
            amendment_notes=(
                "11 Del. C. 1953, § 501; 58 Del. Laws, c. 497, § 1;"
            ),
            source_url=C005_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "11 Del. C. § 501"
        assert section.citation.state_code == "DE"
        assert section.heading == (
            "Criminal solicitation in the third degree; class A misdemeanor."
        )
        assert section.text == "A person is guilty of criminal solicitation in the third degree..."
        assert section.amendment_notes == "11 Del. C. 1953, § 501; 58 Del. Laws, c. 497, § 1;"
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="WA", identifier="49"),
                identifier="60",
            ),
            identifier="49.60.010",
        )
        parsed = ParsedDocument(
            raw_citation="11 Del. C. § 501",
            text="Criminal solicitation...",
        )
        with pytest.raises(NormalizationError):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("501")
        parsed = ParsedDocument(
            raw_citation="11 Del. C. § 999",
            text="Some other section's text.",
        )
        with pytest.raises(RefMismatchError):
            self.adapter.normalize(parsed, ref)
