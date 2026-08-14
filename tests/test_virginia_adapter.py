"""Tests for VirginiaAdapter.

Virginia is the framework's first JSON-consuming adapter, so these tests
exercise both the JSON shape handling (listings, dedup, sorting,
flattening) and the end-to-end section retrieval. All retrieval tests are
fully offline: the real network boundary (``urllib.request.urlopen`` as
imported by the shared ``_fetch`` helper) is mocked, so the adapter's real
fetch -> parse path runs against the JSON below.

All JSON below is **synthetic** -- hand-written to match the confirmed
response shapes documented in ``VirginiaAdapter``'s module docstring and
in ``docs/research/virginia.md`` (titles as a JSON array of
``{"TitleNumber","TitleName","ChapterList":null}``; chapters as
``{"TitleNumber","TitleName","ChapterList":[...]}``; section listings as
the nested ``ArticleList -> SubPartList -> SectionList`` structure; section
detail as one section inside ``{"TitleNumber",...,"ChapterList":[...]}``
with an HTML ``Body``). It is NOT a saved real government fixture.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from _mock_network import mock_urlopen, mock_urlopen_error, mock_urlopen_serving

from state_statutes_mcp.adapters.virginia.adapter import VirginiaAdapter
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

# --- SYNTHETIC mock JSON payloads -- NOT real government fixtures. ---

# Titles: a JSON array. The API is verified to sometimes list the same
# TitleNumber twice (with cosmetically different names), so 8.2 appears
# twice here; the adapter must keep the first occurrence.
SYNTHETIC_TITLES_JSON = [
    {"TitleNumber": "1", "TitleName": "General Provisions", "ChapterList": None},
    {"TitleNumber": "18.2", "TitleName": "Crimes Against Property", "ChapterList": None},
    {"TitleNumber": "8.2", "TitleName": "Civil Remedies and Procedure", "ChapterList": None},
    {"TitleNumber": "8.2", "TitleName": "Civil Remedies (renamed)", "ChapterList": None},
    {"TitleNumber": "54.1", "TitleName": "Professions and Occupations", "ChapterList": None},
]

# Chapters: lexicographic order on purpose (1, 10, 11, 2, 2.1, 3) -- the
# adapter must re-sort numerically, and must preserve dotted chapter
# numbers like "2.1".
SYNTHETIC_CHAPTERS_JSON = {
    "TitleNumber": "18.2",
    "TitleName": "Crimes Against Property",
    "ChapterList": [
        {"ChapterNum": "1", "ChapterName": "In General"},
        {"ChapterNum": "10", "ChapterName": "Arson"},
        {"ChapterNum": "11", "ChapterName": "Burglary and Housebreaking"},
        {"ChapterNum": "2", "ChapterName": "Assault and Bodily Wounding"},
        {"ChapterNum": "2.1", "ChapterName": "Strangulation"},
        {"ChapterNum": "3", "ChapterName": "Homicide"},
    ],
}

# Sections: the verified nested ArticleList -> SubPartList -> SectionList
# structure, given in a deliberately scrambled order so the adapter's
# deterministic sort is what establishes the result order. Includes a
# decimal-section identifier (18.2-76.2) and a section repeated under a
# second SubPart to exercise the keep-first dedup.
SYNTHETIC_SECTIONS_JSON = {
    "TitleNumber": "18.2",
    "TitleName": "Crimes Against Property",
    "ChapterNum": "4",
    "ChapterName": "Crimes Against the Person",
    "ArticleList": [
        {
            "SubPartList": [
                {
                    "SectionList": [
                        {
                            "SectionRange": "§ 18.2-76.2",
                            "SectionNumber": "18.2-76.2",
                            "SectionTitle": "Strangulation.",
                        },
                        {
                            "SectionRange": "§ 18.2-51",
                            "SectionNumber": "18.2-51",
                            "SectionTitle": "Shooting, stabbing, etc., with intent to maim, kill, or disable.",
                        },
                    ]
                },
                {
                    "SubPartName": "Second grouping (presentation only)",
                    "SectionList": [
                        {
                            "SectionRange": "§ 18.2-51",
                            "SectionNumber": "18.2-51",
                            "SectionTitle": "Shooting, stabbing, etc. (duplicate listing)",
                        },
                        {
                            "SectionRange": "§ 18.2-30",
                            "SectionNumber": "18.2-30",
                            "SectionTitle": "Murder or manslaughter; penalty.",
                        },
                    ],
                },
            ]
        }
    ],
}

# Section detail: the verified shape -- one section inside the top-level
# ChapterList, keyed by the flat SectionNumber. SectionText is null
# (verified); Body is HTML with one <p> per paragraph, a trailing history
# paragraph, and the verified recurring sidenote paragraph.
SYNTHETIC_SECTION_JSON = {
    "TitleNumber": "18.2",
    "TitleName": "Crimes Against Property",
    "ChapterList": [
        {
            "ChapterNum": "4",
            "ChapterName": "Crimes Against the Person",
            "SectionRange": "§ 18.2-51",
            "SectionNumber": "18.2-51",
            "SectionTitle": "Shooting, stabbing, etc., with intent to maim, kill, or disable.",
            "SectionText": None,
            "Body": (
                "<p>If any person maliciously shoot, stab, cut or wound any "
                "person by any means with intent to maim, kill or disable "
                "such person, he shall be guilty of a Class 2 felony.</p>"
                "<p>Code 1950, § 18.1-65; 1960, c. 358; 1975, cc. 14, 15.</p>"
                "<p class='sidenote'>§ 18.2-51</p>"
            ),
        }
    ],
}

SYNTHETIC_SECTION_WITH_HISTORY = {
    "TitleNumber": "18.2",
    "TitleName": "Crimes Against Property",
    "ChapterList": [
        {
            "ChapterNum": "4",
            "ChapterName": "Crimes Against the Person",
            "SectionRange": "§ 18.2-51",
            "SectionNumber": "18.2-51",
            "SectionTitle": "Shooting, stabbing, etc., with intent to maim, kill, or disable.",
            "SectionText": None,
            "Body": (
                "<p>Code 1919 amendments apply retroactively to this section.</p>"
                "<p>The body of the statute continues here.</p>"
                "<p>Code 1919, § 1; R. P. 1948, § 1-1.</p>"
            ),
        }
    ],
}

SYNTHETIC_SECTION_NO_HISTORY = {
    "TitleNumber": "1",
    "TitleName": "General Provisions",
    "ChapterList": [
        {
            "ChapterNum": "1",
            "ChapterName": "In General",
            "SectionRange": "§ 1-1",
            "SectionNumber": "1-1",
            "SectionTitle": "Contents and designation of Code.",
            "SectionText": None,
            "Body": "<p>The Code of Virginia shall consist of the titles set out in this act.</p>",
        }
    ],
}


def _make_ref(section: str) -> SectionRef:
    return SectionRef(
        chapter=ChapterRef(
            title=TitleRef(state_code="VA", identifier="18.2"),
            identifier="4",
        ),
        identifier=section,
    )


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert VirginiaAdapter.__abstractmethods__ == frozenset()
        adapter = VirginiaAdapter()
        assert adapter.state_code == "VA"
        assert adapter.state_name == "Virginia"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = VirginiaAdapter()

    def test_title_ref_url(self) -> None:
        ref = TitleRef(state_code="VA", identifier="18.2")
        assert (
            self.adapter.build_url(ref)
            == "https://law.lis.virginia.gov/api/CoVChaptersGetListOfJson/18.2/"
        )

    def test_chapter_ref_url(self) -> None:
        ref = ChapterRef(
            title=TitleRef(state_code="VA", identifier="18.2"), identifier="4"
        )
        assert (
            self.adapter.build_url(ref)
            == "https://law.lis.virginia.gov/api/CoVSectionsGetListOfJson/18.2/4/"
        )

    def test_section_ref_url(self) -> None:
        ref = _make_ref("18.2-51")
        assert (
            self.adapter.build_url(ref)
            == "https://law.lis.virginia.gov/api/CoVSectionsGetSectionDetailsJson/18.2-51/"
        )

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestDiscovery:
    def setup_method(self) -> None:
        self.adapter = VirginiaAdapter()

    def test_list_titles(self) -> None:
        with mock_urlopen(json.dumps(SYNTHETIC_TITLES_JSON)):
            titles = self.adapter.list_titles()

        assert [n.identifier for n in titles] == ["1", "18.2", "8.2", "54.1"]
        assert [n.name for n in titles] == [
            "General Provisions",
            "Crimes Against Property",
            "Civil Remedies and Procedure",
            "Professions and Occupations",
        ]
        assert all(n.level == HierarchyLevel.TITLE for n in titles)
        assert all(n.ref.state_code == "VA" for n in titles)

    def test_list_titles_empty_array_raises(self) -> None:
        with mock_urlopen("[]"):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_titles_non_array_raises(self) -> None:
        with mock_urlopen(json.dumps({"TitleNumber": "1"})):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_list_chapters_sorts_numerically(self) -> None:
        title_ref = TitleRef(state_code="VA", identifier="18.2")
        with mock_urlopen(json.dumps(SYNTHETIC_CHAPTERS_JSON)):
            chapters = self.adapter.list_chapters(title_ref)

        assert [n.identifier for n in chapters] == ["1", "2", "2.1", "3", "10", "11"]
        assert [n.name for n in chapters] == [
            "In General",
            "Assault and Bodily Wounding",
            "Strangulation",
            "Homicide",
            "Arson",
            "Burglary and Housebreaking",
        ]
        assert all(n.level == HierarchyLevel.CHAPTER for n in chapters)
        assert all(n.ref.title == title_ref for n in chapters)

    def test_list_chapters_empty_chapter_list_raises(self) -> None:
        title_ref = TitleRef(state_code="VA", identifier="18.2")
        payload = {"TitleNumber": "18.2", "TitleName": "X", "ChapterList": []}
        with mock_urlopen(json.dumps(payload)):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_chapters(title_ref)

    def test_list_chapters_missing_chapter_list_raises(self) -> None:
        title_ref = TitleRef(state_code="VA", identifier="18.2")
        with mock_urlopen(json.dumps({"TitleNumber": "18.2"})):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_chapters(title_ref)

    def test_list_sections_flattens_and_sorts(self) -> None:
        chapter_ref = ChapterRef(
            title=TitleRef(state_code="VA", identifier="18.2"), identifier="4"
        )
        with mock_urlopen(json.dumps(SYNTHETIC_SECTIONS_JSON)):
            sections = self.adapter.list_sections(chapter_ref)

        assert [n.identifier for n in sections] == ["18.2-30", "18.2-51", "18.2-76.2"]
        assert [n.name for n in sections] == [
            "Murder or manslaughter; penalty.",
            "Shooting, stabbing, etc., with intent to maim, kill, or disable.",
            "Strangulation.",
        ]
        assert all(n.level == HierarchyLevel.SECTION for n in sections)
        assert all(n.ref.chapter == chapter_ref for n in sections)

    def test_list_sections_empty_article_list_raises(self) -> None:
        chapter_ref = ChapterRef(
            title=TitleRef(state_code="VA", identifier="18.2"), identifier="4"
        )
        payload = {"ArticleList": []}
        with mock_urlopen(json.dumps(payload)):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_sections(chapter_ref)

    def test_list_sections_missing_article_list_raises(self) -> None:
        chapter_ref = ChapterRef(
            title=TitleRef(state_code="VA", identifier="18.2"), identifier="4"
        )
        with mock_urlopen(json.dumps({"TitleNumber": "18.2"})):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_sections(chapter_ref)


class TestRetrieveSection:
    """Retrieval tests against synthetic JSON that matches the verified
    shapes documented in the adapter's module docstring."""

    def setup_method(self) -> None:
        self.adapter = VirginiaAdapter()
        self.ref = _make_ref("18.2-51")

    def test_full_retrieval_citation_heading_body_history(self) -> None:
        with mock_urlopen(json.dumps(SYNTHETIC_SECTION_JSON)):
            section = self.adapter.retrieve_section(self.ref)

        assert section.citation.raw == "§ 18.2-51"
        assert section.citation.state_code == "VA"
        assert section.ref == self.ref
        assert (
            section.heading
            == "Shooting, stabbing, etc., with intent to maim, kill, or disable."
        )
        assert (
            section.text
            == "If any person maliciously shoot, stab, cut or wound any person by "
            "any means with intent to maim, kill or disable such person, he shall "
            "be guilty of a Class 2 felony."
        )
        assert section.amendment_notes == (
            "Code 1950, § 18.1-65; 1960, c. 358; 1975, cc. 14, 15.\n\n"
            "§ 18.2-51"
        )
        assert section.status.value == "unknown"
        assert section.source_url == (
            "https://law.lis.virginia.gov/api/"
            "CoVSectionsGetSectionDetailsJson/18.2-51/"
        )
        assert section.retrieved_at is not None

    def test_history_split_takes_last_history_paragraph(self) -> None:
        with mock_urlopen(json.dumps(SYNTHETIC_SECTION_WITH_HISTORY)):
            section = self.adapter.retrieve_section(self.ref)

        assert (
            section.text
            == "Code 1919 amendments apply retroactively to this section.\n\n"
            "The body of the statute continues here."
        )
        assert section.amendment_notes == "Code 1919, § 1; R. P. 1948, § 1-1."

    def test_no_history_paragraph_leaves_amendment_notes_none(self) -> None:
        ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="VA", identifier="1"),
                identifier="1",
            ),
            identifier="1-1",
        )
        with mock_urlopen(json.dumps(SYNTHETIC_SECTION_NO_HISTORY)):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "§ 1-1"
        assert section.heading == "Contents and designation of Code."
        assert section.text == (
            "The Code of Virginia shall consist of the titles set out in this act."
        )
        assert section.amendment_notes is None

    def test_empty_chapter_list_raises_ref_not_found(self) -> None:
        payload = {
            "TitleNumber": None,
            "TitleName": None,
            "ChapterList": [],
        }
        with mock_urlopen(json.dumps(payload)):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(self.ref)

    def test_title_mismatch_raises_ref_mismatch_error(self) -> None:
        payload = json.loads(json.dumps(SYNTHETIC_SECTION_JSON))
        payload["TitleNumber"] = "1"
        with mock_urlopen(json.dumps(payload)):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(self.ref)

    def test_chapter_mismatch_raises_ref_mismatch_error(self) -> None:
        payload = json.loads(json.dumps(SYNTHETIC_SECTION_JSON))
        payload["ChapterList"][0]["ChapterNum"] = "3"
        with mock_urlopen(json.dumps(payload)):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(self.ref)

    def test_section_mismatch_raises_ref_mismatch_error(self) -> None:
        payload = json.loads(json.dumps(SYNTHETIC_SECTION_JSON))
        payload["ChapterList"][0]["SectionNumber"] = "18.2-99"
        with mock_urlopen(json.dumps(payload)):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(self.ref)

    def test_missing_section_range_raises_normalization_error(self) -> None:
        payload = json.loads(json.dumps(SYNTHETIC_SECTION_JSON))
        del payload["ChapterList"][0]["SectionRange"]
        with mock_urlopen(json.dumps(payload)):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(self.ref)

    def test_missing_body_raises_normalization_error(self) -> None:
        payload = json.loads(json.dumps(SYNTHETIC_SECTION_JSON))
        payload["ChapterList"][0]["Body"] = None
        with mock_urlopen(json.dumps(payload)):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(self.ref)

    def test_empty_body_after_cleaning_raises_normalization_error(self) -> None:
        payload = json.loads(json.dumps(SYNTHETIC_SECTION_JSON))
        payload["ChapterList"][0]["Body"] = "<p>   </p>"
        with mock_urlopen(json.dumps(payload)):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(self.ref)

    def test_malformed_json_raises_adapter_unavailable_error(self) -> None:
        with mock_urlopen("this is not json"):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(self.ref)

    def test_network_failure_raises_adapter_unavailable_error(self) -> None:
        with mock_urlopen_error(
            urllib.error.URLError("simulated network failure")
        ):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(self.ref)

    def test_uses_section_detail_endpoint(self) -> None:
        url = "https://law.lis.virginia.gov/api/CoVSectionsGetSectionDetailsJson/18.2-51/"
        with mock_urlopen_serving({url: json.dumps(SYNTHETIC_SECTION_JSON)}):
            section = self.adapter.retrieve_section(self.ref)

        assert section.citation.raw == "§ 18.2-51"


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = VirginiaAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("18.2-51")
        parsed = ParsedDocument(
            raw_citation="§ 18.2-51",
            heading="Shooting, stabbing, etc.",
            text="If any person maliciously shoot, stab, cut or wound any person...",
            amendment_notes="Code 1950, § 18.1-65; 1960, c. 358; 1975, cc. 14, 15.",
            source_url="https://law.lis.virginia.gov/api/CoVSectionsGetSectionDetailsJson/18.2-51/",
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref == ref
        assert section.citation.raw == "§ 18.2-51"
        assert section.citation.state_code == "VA"
        assert section.heading == "Shooting, stabbing, etc."
        assert section.text == "If any person maliciously shoot, stab, cut or wound any person..."
        assert section.amendment_notes == "Code 1950, § 18.1-65; 1960, c. 358; 1975, cc. 14, 15."
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
            raw_citation="§ 18.2-51",
            text="The Code of Virginia...",
        )
        with pytest.raises(NormalizationError):
            self.adapter.normalize(parsed, foreign_ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("18.2-51")
        parsed = ParsedDocument(
            raw_citation="§ 18.2-99",
            text="Some other section's text.",
        )
        with pytest.raises(RefMismatchError):
            self.adapter.normalize(parsed, ref)