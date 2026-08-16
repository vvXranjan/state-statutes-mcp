"""Tests for MontanaAdapter.

The Montana Code Annotated (mca.legmt.gov) is a per-section HTML source
(the Family A model). The MCA has a real Title -> Chapter -> Section
hierarchy; Montana's Part level is folded into the published three-number
citation and used only as URL routing (adapter-internal, derived
arithmetically: ``part = S // 100``, ``local = S % 100``).
``SectionRef.identifier`` is the full ``{T}-{C}-{S}`` citation (e.g.
``"1-11-103"``, ``"2-6-1001"``, ``"45-5-511"``). History is the page's
``History:`` block; repealed/reserved/renumbered sections are returned
with the note as the heading and empty text.

**REAL live fixtures**: the ``montana_*`` fixtures are verbatim live
captures of the official host (see ``docs/research/montana.md``); they
are NOT synthetic. The parts-index fixture is a trimmed capture preserving
the real page header plus a contiguous subset of the real rows (the two
parts used by the aggregation test), mirroring the Nebraska trimmed
pattern. All others are full real captures.

Section-retrieval and section-discovery tests exercise the adapter's real
fetch -> parse path against these fixtures. All tests are fully offline:
the real network boundary (``urllib.request.urlopen``) is mocked, never
adapter internals.
"""

from __future__ import annotations

import io
import urllib.error
from pathlib import Path
from unittest import mock

import pytest

from _mock_network import PATCH_TARGET, mock_urlopen_error, mock_urlopen_serving

from state_statutes_mcp.adapters.montana.adapter import MontanaAdapter
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
# --- (mca.legmt.gov/bills/mca, fetched Aug 16 2026; see docs/research/montana.md).
FIXTURES = Path(__file__).parent / "fixtures"

INDEX_HTML = (FIXTURES / "montana_title_0010_index.html").read_text(
    encoding="utf-8"
)
TITLE1_CHAPTERS_HTML = (
    FIXTURES / "montana_title_0010_chapters_index.html"
).read_text(encoding="utf-8")
TITLE45_CHAPTERS_HTML = (
    FIXTURES / "montana_title_0450_chapters_index.html"
).read_text(encoding="utf-8")
CH45_PARTS_HTML = (
    FIXTURES / "montana_title_0450_chapter_0050_parts_index.html"
).read_text(encoding="utf-8")
PART1_SECTIONS_HTML = (
    FIXTURES / "montana_title_0450_chapter_0050_part_0010_sections_index.html"
).read_text(encoding="utf-8")
PART5_SECTIONS_HTML = (
    FIXTURES / "montana_title_0450_chapter_0050_part_0050_sections_index.html"
).read_text(encoding="utf-8")

SEC1_11_103_HTML = (FIXTURES / "montana_title_1_11_103.html").read_text(
    encoding="utf-8"
)
SEC1_13_101_HTML = (FIXTURES / "montana_title_1_13_101.html").read_text(
    encoding="utf-8"
)
SEC1_13_104_HTML = (FIXTURES / "montana_title_1_13_104.html").read_text(
    encoding="utf-8"
)
SEC1_13_106_HTML = (FIXTURES / "montana_title_1_13_106.html").read_text(
    encoding="utf-8"
)
SEC2_6_1001_HTML = (FIXTURES / "montana_title_2_6_1001.html").read_text(
    encoding="utf-8"
)
SEC45_5_505_HTML = (FIXTURES / "montana_title_45_5_505.html").read_text(
    encoding="utf-8"
)
SEC45_5_509_HTML = (FIXTURES / "montana_title_45_5_509.html").read_text(
    encoding="utf-8"
)
SEC45_5_511_HTML = (FIXTURES / "montana_title_45_5_511.html").read_text(
    encoding="utf-8"
)
NOT_FOUND_HTML = (FIXTURES / "montana_missing_section_404.html").read_text(
    encoding="utf-8"
)

BASE = "https://mca.legmt.gov/bills/mca"


def _section_url(section: str) -> str:
    """Build the exact official URL for a ``T-C-S`` citation."""
    title, chapter, number = (int(part) for part in section.split("-"))
    part, local = MontanaAdapter._split_section_number(number)
    return (
        f"{BASE}/title_{MontanaAdapter._code(title)}/"
        f"chapter_{MontanaAdapter._code(chapter)}/"
        f"part_{MontanaAdapter._code(part)}/section_{MontanaAdapter._code(local)}/"
        f"{MontanaAdapter._code(title)}-{MontanaAdapter._code(chapter)}-"
        f"{MontanaAdapter._code(part)}-{MontanaAdapter._code(local)}.html"
    )


INDEX_URL = f"{BASE}/index.html"
TITLE1_CHAPTERS_URL = f"{BASE}/title_0010/chapters_index.html"
TITLE45_CHAPTERS_URL = f"{BASE}/title_0450/chapters_index.html"
CH45_PARTS_URL = f"{BASE}/title_0450/chapter_0050/parts_index.html"
PART1_SECTIONS_URL = f"{BASE}/title_0450/chapter_0050/part_0010/sections_index.html"
PART5_SECTIONS_URL = f"{BASE}/title_0450/chapter_0050/part_0050/sections_index.html"

SEC1_11_103_URL = _section_url("1-11-103")
SEC1_13_101_URL = _section_url("1-13-101")
SEC1_13_104_URL = _section_url("1-13-104")
SEC1_13_106_URL = _section_url("1-13-106")
SEC2_6_1001_URL = _section_url("2-6-1001")
SEC45_5_505_URL = _section_url("45-5-505")
SEC45_5_509_URL = _section_url("45-5-509")
SEC45_5_511_URL = _section_url("45-5-511")
SEC1_11_199_URL = _section_url("1-11-199")


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the adapter's fetch wrapper
    will map to ``RefNotFoundError`` (404)."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


def _title_ref(identifier: str = "1") -> TitleRef:
    return TitleRef(state_code="MT", identifier=identifier)


def _chapter_ref(title: str = "1", chapter: str = "11") -> ChapterRef:
    return ChapterRef(title=_title_ref(title), identifier=chapter)


def _make_ref(section: str) -> SectionRef:
    title, chapter, _number = section.split("-")
    return SectionRef(
        chapter=_chapter_ref(title=title, chapter=chapter),
        identifier=section,
    )


def _serve_all() -> dict[str, str]:
    return {
        INDEX_URL: INDEX_HTML,
        TITLE1_CHAPTERS_URL: TITLE1_CHAPTERS_HTML,
        TITLE45_CHAPTERS_URL: TITLE45_CHAPTERS_HTML,
        CH45_PARTS_URL: CH45_PARTS_HTML,
        PART1_SECTIONS_URL: PART1_SECTIONS_HTML,
        PART5_SECTIONS_URL: PART5_SECTIONS_HTML,
        SEC1_11_103_URL: SEC1_11_103_HTML,
        SEC1_13_101_URL: SEC1_13_101_HTML,
        SEC1_13_104_URL: SEC1_13_104_HTML,
        SEC1_13_106_URL: SEC1_13_106_HTML,
        SEC2_6_1001_URL: SEC2_6_1001_HTML,
        SEC45_5_505_URL: SEC45_5_505_HTML,
        SEC45_5_509_URL: SEC45_5_509_HTML,
        SEC45_5_511_URL: SEC45_5_511_HTML,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert MontanaAdapter.__abstractmethods__ == frozenset()
        adapter = MontanaAdapter()
        assert adapter.state_code == "MT"
        assert adapter.state_name == "Montana"


class TestPartArithmetic:
    """Focused unit tests for the code()/split arithmetic that drives every
    Montana URL -- the one genuinely novel piece of Montana-specific
    logic (research test matrix item 18)."""

    def test_code_encoding(self) -> None:
        assert MontanaAdapter._code(1) == "0010"
        assert MontanaAdapter._code(11) == "0110"
        assert MontanaAdapter._code(5) == "0050"
        assert MontanaAdapter._code(10) == "0100"
        assert MontanaAdapter._code(45) == "0450"

    def test_split_section_number(self) -> None:
        assert MontanaAdapter._split_section_number(103) == (1, 3)
        assert MontanaAdapter._split_section_number(511) == (5, 11)
        assert MontanaAdapter._split_section_number(1001) == (10, 1)

    def test_reproduces_all_sampled_url_codes(self) -> None:
        # Every cross-checked section from the research session must build
        # the exact URL this adapter produces.
        expected = {
            "1-11-103": (
                "/title_0010/chapter_0110/part_0010/section_0030/"
                "0010-0110-0010-0030.html"
            ),
            "1-13-101": (
                "/title_0010/chapter_0130/part_0010/section_0010/"
                "0010-0130-0010-0010.html"
            ),
            "1-13-106": (
                "/title_0010/chapter_0130/part_0010/section_0060/"
                "0010-0130-0010-0060.html"
            ),
            "2-6-1001": (
                "/title_0020/chapter_0060/part_0100/section_0010/"
                "0020-0060-0100-0010.html"
            ),
            "45-5-511": (
                "/title_0450/chapter_0050/part_0050/section_0110/"
                "0450-0050-0050-0110.html"
            ),
        }
        adapter = MontanaAdapter()
        for section, suffix in expected.items():
            assert adapter.build_url(_make_ref(section)) == BASE + suffix


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = MontanaAdapter()

    def test_section_ref_url(self) -> None:
        assert self.adapter.build_url(_make_ref("1-11-103")) == SEC1_11_103_URL

    def test_section_ref_url_double_digit_part(self) -> None:
        assert self.adapter.build_url(_make_ref("2-6-1001")) == SEC2_6_1001_URL

    def test_section_ref_url_percent_split(self) -> None:
        assert self.adapter.build_url(_make_ref("45-5-511")) == SEC45_5_511_URL

    def test_chapter_ref_url(self) -> None:
        assert self.adapter.build_url(_chapter_ref()) == (
            f"{BASE}/title_0010/chapter_0110/parts_index.html"
        )

    def test_chapter_ref_url_returns_parts_index(self) -> None:
        # A Montana chapter's build_url points at its parts_index.html --
        # the chapter has no direct section listing.
        assert self.adapter.build_url(
            ChapterRef(title=_title_ref("45"), identifier="5")
        ) == CH45_PARTS_URL

    def test_title_ref_url(self) -> None:
        assert self.adapter.build_url(_title_ref("1")) == TITLE1_CHAPTERS_URL

    def test_unsupported_ref_for_constitution_title(self) -> None:
        with pytest.raises(UnsupportedRefError, match="Constitution"):
            self.adapter.build_url(_title_ref("0"))

    def test_unsupported_ref_for_constitution_chapter(self) -> None:
        with pytest.raises(UnsupportedRefError, match="Constitution"):
            self.adapter.build_url(_chapter_ref(title="0", chapter="1"))

    def test_unsupported_ref_for_constitution_section(self) -> None:
        with pytest.raises(UnsupportedRefError, match="Constitution"):
            self.adapter.build_url(_make_ref("0-1-1"))

    def test_unsupported_ref_for_malformed_section(self) -> None:
        ref = SectionRef(chapter=_chapter_ref(title="45", chapter="5"), identifier="45-5")
        with pytest.raises(UnsupportedRefError, match="three-part"):
            self.adapter.build_url(ref)

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestListTitles:
    def test_returns_titles_skipping_reserved_and_constitution(self) -> None:
        adapter = MontanaAdapter()
        with mock_urlopen_serving({INDEX_URL: INDEX_HTML}):
            titles = adapter.list_titles()

        # The real index lists 53 active titles; the Constitution (title 0)
        # and every plain-text reserved row must be absent.
        assert len(titles) == 53
        assert all(t.level == HierarchyLevel.TITLE for t in titles)
        assert all(t.ref.state_code == "MT" for t in titles)
        assert all(t.identifier != "0" for t in titles)
        reserved = {"4", "6", "8", "9", "11", "12", "14"}
        assert not any(t.identifier in reserved for t in titles)
        assert titles[0].identifier == "1"
        assert titles[0].name == "TITLE 1. GENERAL LAWS AND DEFINITIONS"
        assert any(t.identifier == "45" for t in titles)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = MontanaAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_titles()

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = MontanaAdapter()
        with mock_urlopen_serving({INDEX_URL: "<html><body>none</body></html>"}):
            with pytest.raises(AdapterUnavailableError, match="no usable title"):
                adapter.list_titles()


class TestListChapters:
    def test_returns_chapters_skipping_reserved(self) -> None:
        adapter = MontanaAdapter()
        with mock_urlopen_serving({TITLE1_CHAPTERS_URL: TITLE1_CHAPTERS_HTML}):
            chapters = adapter.list_chapters(_title_ref("1"))

        # Title 1's chapters fixture includes a plain-text reserved range
        # ("CHAPTERS 7 THROUGH 10 RESERVED") that must be skipped.
        assert [c.identifier for c in chapters] == [
            "1", "2", "3", "4", "5", "6", "11", "12", "13",
        ]
        assert chapters[0].name == "CHAPTER 1. GENERAL PROVISIONS"
        assert all(c.level == HierarchyLevel.CHAPTER for c in chapters)
        assert all(c.ref.title == _title_ref("1") for c in chapters)

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = MontanaAdapter()
        with mock_urlopen_error(_http_error(TITLE1_CHAPTERS_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_chapters(_title_ref("1"))

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = MontanaAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_chapters(_title_ref("1"))

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = MontanaAdapter()
        with mock_urlopen_serving({TITLE1_CHAPTERS_URL: "<html></html>"}):
            with pytest.raises(AdapterUnavailableError, match="no usable chapter"):
                adapter.list_chapters(_title_ref("1"))


class TestListSections:
    def test_returns_sections_aggregated_across_parts(self) -> None:
        adapter = MontanaAdapter()
        chapter = _chapter_ref(title="45", chapter="5")
        with mock_urlopen_serving(
            {
                CH45_PARTS_URL: CH45_PARTS_HTML,
                PART1_SECTIONS_URL: PART1_SECTIONS_HTML,
                PART5_SECTIONS_URL: PART5_SECTIONS_HTML,
            }
        ):
            sections = adapter.list_sections(chapter)

        # The trimmed parts fixture lists Part 1 and Part 5; the aggregate
        # must contain every section of both parts, deduplicated.
        ids = [s.identifier for s in sections]
        assert len(ids) == len(set(ids))
        assert "45-5-101" in ids and "45-5-116" in ids  # Part 1
        assert "45-5-501" in ids and "45-5-513" in ids  # Part 5
        # Renumbered and reserved-range rows are real TOC rows.
        renumbered = next(s for s in sections if s.identifier == "45-5-505")
        assert renumbered.name == "Renumbered 45-8-218"
        reserved_pair = next(s for s in sections if s.identifier == "45-5-509")
        assert reserved_pair.name == "and 45-5-510 reserved"
        assert all(s.level == HierarchyLevel.SECTION for s in sections)
        assert all(s.ref.chapter == chapter for s in sections)

    def test_404_maps_to_ref_not_found(self) -> None:
        adapter = MontanaAdapter()
        chapter = _chapter_ref(title="45", chapter="5")
        with mock_urlopen_error(_http_error(CH45_PARTS_URL)):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                adapter.list_sections(chapter)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = MontanaAdapter()
        chapter = _chapter_ref(title="45", chapter="5")
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_sections(chapter)

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        adapter = MontanaAdapter()
        chapter = _chapter_ref(title="45", chapter="5")
        with mock_urlopen_serving({CH45_PARTS_URL: "<html></html>"}):
            with pytest.raises(AdapterUnavailableError, match="no usable section"):
                adapter.list_sections(chapter)


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = MontanaAdapter()

    def test_full_retrieval_normal_section(self) -> None:
        ref = _make_ref("1-11-103")
        with mock_urlopen_serving({SEC1_11_103_URL: SEC1_11_103_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Mont. Code Ann. § 1-11-103"
        assert section.citation.state_code == "MT"
        assert section.ref == ref
        assert section.heading == (
            "Effect of Montana Code Annotated -- official version."
        )
        assert section.text.startswith(
            "(1) The Montana Code Annotated is a reenactment of the Revised "
            "Codes of Montana, 1947, and the supplements thereto."
        )
        assert "(2) The enactment of the Montana Code Annotated may not:" in section.text
        assert section.amendment_notes == (
            "En. 12-506 by Sec. 6, Ch. 419, L. 1975; amd. Sec. 4, Ch. 1, "
            "L. 1977; R.C.M. 1947, 12-506; amd. Sec. 11, Ch. 119, L. 1979; "
            "amd. Sec. 2, Ch. 575, L. 1981; amd. Sec. 1, Ch. 100, L. 1993; "
            "amd. Sec. 12, Ch. 52, L. 2025."
        )
        assert section.status.value == "unknown"
        assert section.source_url == SEC1_11_103_URL
        assert section.retrieved_at is not None

    def test_repealed_section_empty_body_with_heading(self) -> None:
        # VERIFIED: a repealed section (1-13-101) renders a "Repealed."
        # catchline with no operative text but keeps its short History line.
        ref = _make_ref("1-13-101")
        with mock_urlopen_serving({SEC1_13_101_URL: SEC1_13_101_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Mont. Code Ann. § 1-13-101"
        assert section.heading == "Repealed."
        assert section.text == ""
        assert section.amendment_notes == "En. Sec. 1, Ch. 511, L. 1985."
        assert section.status.value == "unknown"

    def test_reserved_range_section_empty_body_no_history(self) -> None:
        # VERIFIED: a reserved-range section (1-13-106) has no body and no
        # History line.
        ref = _make_ref("1-13-106")
        with mock_urlopen_serving({SEC1_13_106_URL: SEC1_13_106_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Mont. Code Ann. § 1-13-106"
        assert "reserved" in section.heading
        assert section.text == ""
        assert section.amendment_notes is None
        assert section.status.value == "unknown"

    def test_renumbered_section_empty_body_no_history(self) -> None:
        # VERIFIED: a renumbered section (45-5-505) carries a
        # "Renumbered ..." catchline with no operative text and no History.
        ref = _make_ref("45-5-505")
        with mock_urlopen_serving({SEC45_5_505_URL: SEC45_5_505_HTML}):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Mont. Code Ann. § 45-5-505"
        assert section.heading == "Renumbered 45-8-218."
        assert section.text == ""
        assert section.amendment_notes is None
        assert section.status.value == "unknown"

    def test_section_number_mismatch_raises_ref_mismatch_error(self) -> None:
        # The page's own citation span must equal ref.identifier. Doctored
        # surgically: the section-content citation span is rewritten, while
        # the nav/breadcrumb occurrences are left alone.
        html = SEC1_11_103_HTML.replace(
            '<span class="citation">1-11-103</span>',
            '<span class="citation">1-11-199</span>',
            1,
        )
        with mock_urlopen_serving({SEC1_11_103_URL: html}):
            with pytest.raises(RefMismatchError, match="does not match"):
                self.adapter.retrieve_section(_make_ref("1-11-103"))

    def test_title_header_mismatch_raises_ref_mismatch_error(self) -> None:
        html = SEC1_11_103_HTML.replace(
            '<h4 class="section-title-title">\n      TITLE 1.',
            '<h4 class="section-title-title">\n      TITLE 2.',
            1,
        )
        with mock_urlopen_serving({SEC1_11_103_URL: html}):
            with pytest.raises(RefMismatchError, match="does not match"):
                self.adapter.retrieve_section(_make_ref("1-11-103"))

    def test_no_section_content_raises_normalization_error(self) -> None:
        html = "<html><body><p>nothing here</p></body></html>"
        with mock_urlopen_serving({SEC1_11_103_URL: html}):
            with pytest.raises(NormalizationError, match="section-content"):
                self.adapter.retrieve_section(_make_ref("1-11-103"))

    def test_no_citation_heading_raises_normalization_error(self) -> None:
        # A section-content region with no citation line is malformed.
        html = (
            "<html><body><div class=\"section-content\">"
            "<p class=\"line-indent\">Some text without a citation.</p>"
            "</div></body></html>"
        )
        with mock_urlopen_serving({SEC1_11_103_URL: html}):
            with pytest.raises(NormalizationError, match="no numbered citation"):
                self.adapter.retrieve_section(_make_ref("1-11-103"))

    def test_empty_body_normal_section_raises_normalization_error(self) -> None:
        # A section that is not a repealed/reserved/renumbered stub but has
        # no body text must not be silently returned with empty text.
        html = SEC1_11_103_HTML
        body_start = html.index('class="section-content">') + len(
            'class="section-content">'
        )
        body_end = html.index("</div>", body_start)
        stripped = (
            html[:body_start]
            + '<p class="line-indent"><span class="catchline">'
            + "<span class=\"citation\">1-11-103</span>. Heading only.</span>"
            + "</p>"
            + html[body_end:]
        )
        with mock_urlopen_serving({SEC1_11_103_URL: stripped}):
            with pytest.raises(NormalizationError, match="empty after cleaning"):
                self.adapter.retrieve_section(_make_ref("1-11-103"))

    def test_missing_section_404_maps_to_ref_not_found(self) -> None:
        # LIVE-VERIFIED: a nonexistent section number returns a plain HTTP
        # 404 with a real 404 error page.
        ref = _make_ref("1-11-199")
        error = urllib.error.HTTPError(
            SEC1_11_199_URL,
            404,
            "Not Found",
            {},
            io.BytesIO(NOT_FOUND_HTML.encode("utf-8")),
        )
        with mock_urlopen_error(error):
            with pytest.raises(RefNotFoundError, match="returned HTTP 404"):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        ref = _make_ref("1-11-103")
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = MontanaAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("1-11-103")
        parsed = ParsedDocument(
            raw_citation="Mont. Code Ann. § 1-11-103",
            heading="Effect of Montana Code Annotated -- official version.",
            text="The Montana Code Annotated is a reenactment ...",
            amendment_notes="En. 12-506 by Sec. 6, Ch. 419, L. 1975; ...",
            source_url=SEC1_11_103_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "Mont. Code Ann. § 1-11-103"
        assert section.citation.state_code == "MT"
        assert section.heading == (
            "Effect of Montana Code Annotated -- official version."
        )
        assert section.amendment_notes == "En. 12-506 by Sec. 6, Ch. 419, L. 1975; ..."
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="NV", identifier="1"),
                identifier="11",
            ),
            identifier="1-11-103",
        )
        parsed = ParsedDocument(
            raw_citation="Mont. Code Ann. § 1-11-103",
            text="Some text.",
        )
        with pytest.raises(NormalizationError, match="expected 'MT'"):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("1-11-103")
        parsed = ParsedDocument(
            raw_citation="Mont. Code Ann. § 1-11-104",
            text="Some text.",
        )
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, ref)


class TestHierarchyMapping:
    def test_real_three_level_hierarchy(self) -> None:
        # Montana has a real Title -> Chapter -> Section hierarchy (no
        # synthetic-title workaround), and discovery chains descend from the
        # real title.
        adapter = MontanaAdapter()
        with mock_urlopen_serving(_serve_all()):
            titles = adapter.list_titles()
            title = next(t.ref for t in titles if t.identifier == "45")
            assert isinstance(title, TitleRef)
            assert title.state_code == "MT"
            assert title.identifier == "45"

            chapters = adapter.list_chapters(title)
            assert all(c.ref.title == title for c in chapters)

            chapter = next(
                c.ref for c in chapters if c.identifier == "5"
            )
            sections = adapter.list_sections(chapter)
            assert all(s.ref.chapter.title == title for s in sections)
            assert all(s.ref.chapter == chapter for s in sections)