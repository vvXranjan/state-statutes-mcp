"""Tests for AlabamaAdapter.

The official Alabama Code (alison.legislature.state.al.us/graphql) is the
framework's first GraphQL/JSON-POST source: discovery uses
``{ codeOfAlabamaTitles }`` (a single delimited TOC string) and retrieval
uses ``{ codesOfAlabama(where: { codeId: { eq: N } }) }``. The Code of
Alabama is a uniform Title -> Chapter -> Section hierarchy (46 titles
including lettered ``10A``/``13A``; 1,529 chapters including lettered
``2A``/``2B``; 49,271 sections). Title 7 (the Uniform Commercial Code) has
no Chapter level, so it exposes one synthetic chapter equal to the title
number (the same flat-title precedent Oklahoma uses).

**REAL official fixtures**: the ``al_*`` fixtures are verbatim captures of
the official ALISON GraphQL API (fetched live Aug 24 2026; see
``docs/research/alabama.md``). ``al_toc_trimmed.json`` is a real subset of
the official TOC string (kept small for the test suite; the full TOC is
~4.2 MB). The section fixtures are complete real API responses. They are
NOT synthetic.

Network tests mock the real network boundary
(``urllib.request.urlopen`` as imported by the shared ``_fetch`` helper),
never adapter internals, via ``mock_urlopen_graphql`` (which dispatches on
the GraphQL query string in the POST body).
"""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from _mock_network import (
    mock_urlopen_error,
    mock_urlopen_graphql,
)

from state_statutes_mcp.adapters.alabama.adapter import AlabamaAdapter
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

# --- REAL live fixtures: verbatim captures of the official ALISON GraphQL
# --- API (fetched Aug 24 2026; see docs/research/alabama.md).
FIXTURES = Path(__file__).parent / "fixtures"

TOC_JSON = json.loads(
    (FIXTURES / "al_toc_trimmed.json").read_text(encoding="utf-8")
)
S1_1_1_JSON = json.loads(
    (FIXTURES / "al_section_1-1-1.json").read_text(encoding="utf-8")
)
S1_1_1_1_JSON = json.loads(
    (FIXTURES / "al_section_1-1-1.1.json").read_text(encoding="utf-8")
)
S2_1_1_JSON = json.loads(
    (FIXTURES / "al_section_2-1-1.json").read_text(encoding="utf-8")
)
S4_2_77_JSON = json.loads(
    (FIXTURES / "al_section_4-2-77.json").read_text(encoding="utf-8")
)
S1_2A_1_JSON = json.loads(
    (FIXTURES / "al_section_1-2A-1.json").read_text(encoding="utf-8")
)
S7_1_101_JSON = json.loads(
    (FIXTURES / "al_section_7-1-101.json").read_text(encoding="utf-8")
)
S_INVALID_JSON = json.loads(
    (FIXTURES / "al_section_invalid.json").read_text(encoding="utf-8")
)

GRAPHQL_URL = "https://alison.legislature.state.al.us/graphql"

# Query keys used to dispatch the mock on the GraphQL query body.
TOC_KEY = "codeOfAlabamaTitles"
RETRIEVE_KEY = "codesOfAlabama"


def _retrieve_key(code_id: str) -> str:
    return f"codeId: {{ eq: {code_id} }}"


def _title_ref(identifier: str = "1") -> TitleRef:
    return TitleRef(state_code="AL", identifier=identifier)


def _chapter_ref(title: str = "1", chapter: str = "1") -> ChapterRef:
    return ChapterRef(title=_title_ref(title), identifier=chapter)


def _make_ref(title: str = "1", chapter: str = "1", section: str = "1-1-1") -> SectionRef:
    return SectionRef(chapter=_chapter_ref(title, chapter), identifier=section)


def _serve(
    toc: bool = True,
    *,
    code_ids: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """Build the query->JSON map for ``mock_urlopen_graphql``.

    Args:
        toc: Whether to serve the trimmed TOC (discovery).
        code_ids: Mapping of codeId string to the section JSON response to
            serve for it.
    """
    mapping: dict[str, dict] = {}
    if toc:
        mapping[TOC_KEY] = TOC_JSON
    for code_id, payload in (code_ids or {}).items():
        mapping[_retrieve_key(code_id)] = payload
    return mapping


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert AlabamaAdapter.__abstractmethods__ == frozenset()
        adapter = AlabamaAdapter()
        assert adapter.state_code == "AL"
        assert adapter.state_name == "Alabama"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = AlabamaAdapter()

    def test_title_ref_url(self) -> None:
        assert self.adapter.build_url(_title_ref("1")) == GRAPHQL_URL

    def test_chapter_ref_url(self) -> None:
        assert self.adapter.build_url(_chapter_ref()) == GRAPHQL_URL

    def test_section_ref_url(self) -> None:
        assert self.adapter.build_url(_make_ref()) == GRAPHQL_URL

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestListTitles:
    def test_discovers_titles_from_trimmed_toc(self) -> None:
        adapter = AlabamaAdapter()
        with mock_urlopen_graphql(_serve()):
            titles = adapter.list_titles()

        identifiers = [t.identifier for t in titles]
        assert identifiers == ["1", "4", "7", "10A", "45"]
        assert all(t.level == HierarchyLevel.TITLE for t in titles)
        assert all(t.ref.state_code == "AL" for t in titles)
        assert [t.name for t in titles] == [
            "General Provisions",
            "Aviation",
            "Commercial Code",
            "Alabama Business and Nonprofit Entities Code",
            "Local Laws",
        ]

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = AlabamaAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_titles()

    def test_empty_toc_raises_adapter_unavailable(self) -> None:
        adapter = AlabamaAdapter()
        empty = {"data": {"codeOfAlabamaTitles": ""}}
        with mock_urlopen_graphql({TOC_KEY: empty}):
            with pytest.raises(AdapterUnavailableError, match="no usable"):
                adapter.list_titles()


class TestListChapters:
    def test_lists_chapters_under_title(self) -> None:
        adapter = AlabamaAdapter()
        with mock_urlopen_graphql(_serve()):
            chapters = adapter.list_chapters(_title_ref("1"))

        identifiers = [c.identifier for c in chapters]
        assert identifiers == ["1", "2A"]
        assert all(c.level == HierarchyLevel.CHAPTER for c in chapters)
        assert [c.name for c in chapters] == [
            "Construction of Code and Statutes",
            "The Alabama State Flag Act",
        ]
        assert all(c.ref.title.identifier == "1" for c in chapters)

    def test_title7_returns_synthetic_chapter_equal_to_title(self) -> None:
        adapter = AlabamaAdapter()
        with mock_urlopen_graphql(_serve()):
            chapters = adapter.list_chapters(_title_ref("7"))

        assert len(chapters) == 1
        assert chapters[0].identifier == "7"
        assert chapters[0].name == "Title 7 sections"
        assert chapters[0].level == HierarchyLevel.CHAPTER

    def test_lettered_title_has_real_chapters(self) -> None:
        adapter = AlabamaAdapter()
        with mock_urlopen_graphql(_serve()):
            chapters = adapter.list_chapters(_title_ref("10A"))

        assert [c.identifier for c in chapters] == ["20"]

    def test_unknown_title_raises_ref_not_found(self) -> None:
        adapter = AlabamaAdapter()
        with mock_urlopen_graphql(_serve()):
            with pytest.raises(RefNotFoundError, match="no title '999'"):
                adapter.list_chapters(_title_ref("999"))


class TestListSections:
    def test_lists_sections_under_chapter(self) -> None:
        adapter = AlabamaAdapter()
        with mock_urlopen_graphql(_serve()):
            sections = adapter.list_sections(_chapter_ref("1", "1"))

        ids = [s.identifier for s in sections]
        assert "1-1-1" in ids
        assert "1-1-1.1" in ids  # decimal preserved
        assert "1-1-16" in ids
        assert all(s.level == HierarchyLevel.SECTION for s in sections)
        assert all(s.ref.chapter == _chapter_ref("1", "1") for s in sections)

    def test_lettered_chapter_sections(self) -> None:
        adapter = AlabamaAdapter()
        with mock_urlopen_graphql(_serve()):
            sections = adapter.list_sections(_chapter_ref("1", "2A"))

        ids = [s.identifier for s in sections]
        assert "1-2A-1" in ids and "1-2A-8" in ids

    def test_synthetic_chapter_sections(self) -> None:
        adapter = AlabamaAdapter()
        with mock_urlopen_graphql(_serve()):
            sections = adapter.list_sections(_chapter_ref("7", "7"))

        ids = [s.identifier for s in sections]
        assert "7-1-101" in ids and "7-1-102" in ids

    def test_unknown_chapter_raises_ref_not_found(self) -> None:
        adapter = AlabamaAdapter()
        with mock_urlopen_graphql(_serve()):
            with pytest.raises(RefNotFoundError, match="no chapter '99'"):
                adapter.list_sections(_chapter_ref("1", "99"))


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = AlabamaAdapter()

    def test_normal_section(self) -> None:
        ref = _make_ref()
        served = _serve(code_ids={"14515": S1_1_1_JSON})
        with mock_urlopen_graphql(served):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Ala. Code § 1-1-1"
        assert section.citation.state_code == "AL"
        assert section.ref == ref
        assert section.heading == "Meaning of Certain Words and Terms."
        assert section.text.startswith(
            "The following words, whenever they appear in this code"
        )
        assert section.status.value == "unknown"
        assert section.amendment_notes is None
        assert section.source_url == GRAPHQL_URL
        assert section.retrieved_at is not None

    def test_decimal_section(self) -> None:
        ref = _make_ref(section="1-1-1.1")
        served = _serve(code_ids={"60323": S1_1_1_1_JSON})
        with mock_urlopen_graphql(served):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Ala. Code § 1-1-1.1"
        assert section.heading == (
            "Sex-Based Terminology; Legislative Findings and Intent."
        )
        assert section.text.startswith("(a)(1) The purpose of Act 2025-3")

    def test_lettered_chapter_section(self) -> None:
        ref = SectionRef(
            chapter=_chapter_ref("1", "2A"), identifier="1-2A-1"
        )
        served = _serve(code_ids={"30249": S1_2A_1_JSON})
        with mock_urlopen_graphql(served):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Ala. Code § 1-2A-1"
        assert section.heading == "Short Title."
        assert "This chapter shall be known" in section.text

    def test_synthetic_chapter_section(self) -> None:
        ref = SectionRef(
            chapter=_chapter_ref("7", "7"), identifier="7-1-101"
        )
        served = _serve(code_ids={"15738": S7_1_101_JSON})
        with mock_urlopen_graphql(served):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "Ala. Code § 7-1-101"
        assert section.heading == "Short Titles."
        assert "may be cited as the Uniform Commercial Code" in section.text

    def test_repealed_section(self) -> None:
        ref = SectionRef(
            chapter=_chapter_ref("4", "2"), identifier="4-2-77"
        )
        served = _serve(code_ids={"29009": S4_2_77_JSON})
        with mock_urlopen_graphql(served):
            section = self.adapter.retrieve_section(ref)

        # Documented deviation (same as Nebraska/North Carolina): the repeal
        # note becomes the heading and the body is empty.
        assert section.citation.raw == "Ala. Code § 4-2-77"
        assert section.heading == (
            "Repealed by Act 2000-220, § 48, effective May 13, 2000."
        )
        assert section.text == ""
        assert section.status.value == "unknown"

    def test_invalid_citation_absent_from_toc_raises_ref_not_found(self) -> None:
        ref = _make_ref(section="1-99-999")
        served = _serve()  # no matching codeId -> citation absent from TOC
        with mock_urlopen_graphql(served):
            with pytest.raises(RefNotFoundError, match="no section '1-99-999'"):
                self.adapter.retrieve_section(ref)

    def test_invalid_code_id_empty_data_raises_ref_not_found(self) -> None:
        # A codeId that IS in the TOC (1-1-1 -> 14515) but whose retrieval
        # query returns an empty data list.
        ref = _make_ref()
        served = _serve(code_ids={"14515": S_INVALID_JSON})
        with mock_urlopen_graphql(served):
            with pytest.raises(RefNotFoundError, match="returned no record"):
                self.adapter.retrieve_section(ref)

    def test_wrong_but_valid_code_id_raises_ref_mismatch(self) -> None:
        # Request 1-1-1 (codeId 14515) but the API returns the record for a
        # DIFFERENT valid codeId (e.g. 29009 / section 4-2-77). The adapter
        # must detect the mismatch rather than return the wrong section.
        ref = _make_ref()
        served = _serve(code_ids={"14515": S4_2_77_JSON})
        with mock_urlopen_graphql(served):
            with pytest.raises(RefMismatchError, match="codeId"):
                self.adapter.retrieve_section(ref)

    def test_citation_mismatch_raises_ref_mismatch(self) -> None:
        # Same codeId but a record whose embedded citation disagrees with the
        # request (simulated by serving a record whose title cites 1-1-3).
        ref = _make_ref(section="1-1-1")
        wrong = {
            "data": {
                "codesOfAlabama": {
                    "data": [
                        {
                            "id": "5",
                            "codeId": "14515",
                            "title": "Section 1-1-3 Blind Person Defined; How "
                            "Blindness Proved.",
                            "content": "<p>body</p>",
                        }
                    ]
                }
            }
        }
        served = _serve(code_ids={"14515": wrong})
        with mock_urlopen_graphql(served):
            with pytest.raises(RefMismatchError, match="does not match the "
                             "citation"):
                self.adapter.retrieve_section(ref)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        ref = _make_ref()
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(ref)

    def test_malformed_response_raises_normalization_error(self) -> None:
        ref = _make_ref()
        malformed = {"data": {"unexpected": "shape"}}
        served = _serve(code_ids={"14515": malformed})
        with mock_urlopen_graphql(served):
            with pytest.raises(NormalizationError, match="codesOfAlabama"):
                self.adapter.retrieve_section(ref)

    def test_non_json_response_raises_adapter_unavailable(self) -> None:
        ref = _make_ref()

        def fake_urlopen(url, timeout=None):
            from _mock_network import _FakeResponse

            return _FakeResponse(b"<html>not json</html>")

        from unittest import mock

        from _mock_network import PATCH_TARGET

        with mock.patch(PATCH_TARGET, side_effect=fake_urlopen):
            with pytest.raises(AdapterUnavailableError, match="not valid JSON"):
                self.adapter.retrieve_section(ref)


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = AlabamaAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref()
        parsed = ParsedDocument(
            raw_citation="Ala. Code § 1-1-1",
            heading="Meaning of Certain Words and Terms.",
            text="The following words ...",
            source_url=GRAPHQL_URL,
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "Ala. Code § 1-1-1"
        assert section.citation.state_code == "AL"
        assert section.heading == "Meaning of Certain Words and Terms."
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        foreign_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="NV", identifier="1"),
                identifier="1",
            ),
            identifier="1-1-1",
        )
        parsed = ParsedDocument(raw_citation="Ala. Code § 1-1-1", text="x")
        with pytest.raises(NormalizationError, match="expected 'AL'"):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref()
        parsed = ParsedDocument(raw_citation="Ala. Code § 1-1-3", text="x")
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, ref)


class TestGraphQLFetchHelpers:
    def test_split_section_heading(self) -> None:
        assert AlabamaAdapter._split_section_heading(
            "Section 1-1-1 Meaning of Certain Words and Terms."
        ) == ("1-1-1", "Meaning of Certain Words and Terms.")
        # No catchline
        assert AlabamaAdapter._split_section_heading("Section 6-5-800") == (
            "6-5-800",
            None,
        )
        # Decimal with trailing sentence period
        assert AlabamaAdapter._split_section_heading(
            "Section 45-57-70.01. County Commissioner Blanket Bond, "
            "Contract, or Policy."
        ) == ("45-57-70.01", "County Commissioner Blanket Bond, Contract, or Policy.")
        # Not a section heading
        assert AlabamaAdapter._split_section_heading("Chapter 1 Foo.") == (None, None)

    def test_numeric_sort_key(self) -> None:
        assert AlabamaAdapter._numeric_sort_key("10A") == (10, "10A")
        assert AlabamaAdapter._numeric_sort_key("2") == (2, "2")
        assert AlabamaAdapter._numeric_sort_key("zzz") == (0, "zzz")