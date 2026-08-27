"""Tests for MichiganAdapter.

The Michigan Compiled Laws (legislature.mi.gov) are served as
server-rendered HTML. The live host is protected by a bot-challenge wall
(HTTP 403 to this environment), so the fixtures used here are REAL archived
official captures of the official host (retrieved via the Wayback Machine,
Aug 2026; see docs/research/michigan.md) -- NOT live captures.

Hierarchy mapping: TitleRef = synthetic "MCL"; ChapterRef = MCL chapter
(e.g. "701", "712A"); SectionRef.identifier = the full citation (e.g.
"712A.2d"). Section retrieval is direct via
`/Laws/MCL?objectName=mcl-{chapter}-{section}`.

Network tests mock the real network boundary
(``urllib.request.urlopen`` as imported by the shared ``_fetch`` helper),
never adapter internals.
"""

from __future__ import annotations

import io
import urllib.error
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pytest

from _mock_network import mock_urlopen_error, mock_urlopen_serving

from state_statutes_mcp.adapters.michigan.adapter import MichiganAdapter
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

# --- REAL archived official fixtures (Wayback captures, Aug 2026) ---
FIXTURES = Path(__file__).parent / "fixtures"

INDEX_HTML = (FIXTURES / "mi_chapter_index.html").read_text(encoding="utf-8")
CHAP6_HTML = (FIXTURES / "mi_chapter_6.html").read_text(encoding="utf-8")
ACT62_HTML = (FIXTURES / "mi_act_62_of_1872.html").read_text(encoding="utf-8")
CHAP5_HTML = (FIXTURES / "mi_chapter_5.html").read_text(encoding="utf-8")
ACT120_HTML = (FIXTURES / "mi_act_120_of_1937.html").read_text(encoding="utf-8")
ACT288_HTML = (FIXTURES / "mi_act_288_of_1939.html").read_text(encoding="utf-8")
DIV_XIIA_HTML = (FIXTURES / "mi_division_288_1939_XIIA.html").read_text(
    encoding="utf-8"
)
SEC_750_82 = (FIXTURES / "mi_section_750_82.html").read_text(encoding="utf-8")
SEC_257_1 = (FIXTURES / "mi_section_257_1.html").read_text(encoding="utf-8")
SEC_712A_2A = (FIXTURES / "mi_section_712A_2a.html").read_text(encoding="utf-8")
SEC_712A_2D = (FIXTURES / "mi_section_712A_2d.html").read_text(encoding="utf-8")
SEC_INVALID = (FIXTURES / "mi_section_invalid.html").read_text(encoding="utf-8")

BASE = "https://www.legislature.mi.gov"
INDEX_URL = f"{BASE}/Laws/ChapterIndex"


def _sec_url(chapter: str, section: str) -> str:
    return f"{BASE}/Laws/MCL?objectName=mcl-{chapter}-{section}"


def _chap_url(chapter: str) -> str:
    return f"{BASE}/Laws/MCL?objectName=mcl-chap{chapter}"


def _obj_url(object_name: str) -> str:
    return f"{BASE}/Laws/MCL?objectName={object_name}"


def _make_ref(chapter: str = "750", citation: str = "750.82") -> SectionRef:
    return SectionRef(
        chapter=ChapterRef(
            title=TitleRef(state_code="MI", identifier="MCL"),
            identifier=chapter,
        ),
        identifier=citation,
    )


class _FakeResponse(io.BytesIO):
    """A bytes-backed response that behaves as a context manager."""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


@contextmanager
def _serve_error(url: str, code: int):
    """Make urlopen raise an ``HTTPError`` with the given status for one URL."""
    def fake_urlopen(u, timeout=None):
        target = u if isinstance(u, str) else u.full_url
        if target != url:
            raise AssertionError(f"Unexpected URL fetched in test: {target!r}")
        raise urllib.error.HTTPError(
            url, code, "Error", {}, io.BytesIO(b"")
        )

    with mock.patch(
        "state_statutes_mcp.adapters._fetch.urllib.request.urlopen",
        side_effect=fake_urlopen,
    ):
        yield


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert MichiganAdapter.__abstractmethods__ == frozenset()
        adapter = MichiganAdapter()
        assert adapter.state_code == "MI"
        assert adapter.state_name == "Michigan"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = MichiganAdapter()

    def test_title_ref_url_is_chapter_index(self) -> None:
        ref = TitleRef(state_code="MI", identifier="MCL")
        assert self.adapter.build_url(ref) == INDEX_URL

    def test_chapter_ref_url(self) -> None:
        ref = ChapterRef(
            title=TitleRef(state_code="MI", identifier="MCL"), identifier="712A"
        )
        assert self.adapter.build_url(ref) == _chap_url("712A")

    def test_section_ref_url(self) -> None:
        assert self.adapter.build_url(_make_ref("712A", "712A.2d")) == _sec_url(
            "712A", "2d"
        )

    def test_section_ref_lettered_url(self) -> None:
        assert self.adapter.build_url(_make_ref("712A", "712A.2a")) == _sec_url(
            "712A", "2a"
        )

    def test_section_ref_url_uses_citation_chapter(self) -> None:
        # The citation carries the chapter; the objectName is derived from it.
        assert self.adapter.build_url(_make_ref("750", "750.82")) == _sec_url(
            "750", "82"
        )

    def test_invalid_title_raises_ref_not_found(self) -> None:
        with pytest.raises(RefNotFoundError):
            self.adapter.build_url(TitleRef(state_code="MI", identifier="BAD"))

    def test_invalid_chapter_raises_ref_not_found(self) -> None:
        ref = ChapterRef(
            title=TitleRef(state_code="MI", identifier="MCL"), identifier="abc"
        )
        with pytest.raises(RefNotFoundError):
            self.adapter.build_url(ref)

    def test_invalid_citation_raises_ref_not_found(self) -> None:
        with pytest.raises(RefNotFoundError):
            self.adapter.build_url(_make_ref("750", "not-a-citation"))

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestListTitles:
    def test_returns_synthetic_title(self) -> None:
        adapter = MichiganAdapter()
        titles = adapter.list_titles()

        assert len(titles) == 1
        assert titles[0].identifier == "MCL"
        assert titles[0].level == HierarchyLevel.TITLE
        assert isinstance(titles[0].ref, TitleRef)
        assert titles[0].ref.state_code == "MI"


class TestListChapters:
    def setup_method(self) -> None:
        self.adapter = MichiganAdapter()

    def test_returns_chapters_from_index(self) -> None:
        mcl = TitleRef(state_code="MI", identifier="MCL")
        with mock_urlopen_serving({INDEX_URL: INDEX_HTML}):
            chapters = self.adapter.list_chapters(mcl)

        assert len(chapters) > 200
        by_id = {c.identifier: c for c in chapters}
        assert by_id["6"].name == "IMPEACHMENTS"
        assert by_id["750"].name == "MICHIGAN PENAL CODE"
        assert by_id["700"]  # a chapter present in this archived capture
        assert all(c.level == HierarchyLevel.CHAPTER for c in chapters)
        assert all(isinstance(c.ref, ChapterRef) for c in chapters)

    def test_wrong_title_raises_adapter_unavailable(self) -> None:
        with pytest.raises(AdapterUnavailableError):
            self.adapter.list_chapters(TitleRef(state_code="MI", identifier="NOPE"))

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_chapters(
                    TitleRef(state_code="MI", identifier="MCL")
                )

    def test_empty_result_raises_adapter_unavailable(self) -> None:
        with mock_urlopen_serving({INDEX_URL: "<html></html>"}):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_chapters(
                    TitleRef(state_code="MI", identifier="MCL")
                )


class TestListSections:
    def setup_method(self) -> None:
        self.adapter = MichiganAdapter()

    def test_direct_sections_from_act_page(self) -> None:
        chapter = ChapterRef(
            title=TitleRef(state_code="MI", identifier="MCL"), identifier="6"
        )
        served = {
            _chap_url("6"): CHAP6_HTML,
            _obj_url("mcl-Act-62-of-1872"): ACT62_HTML,
        }
        with mock_urlopen_serving(served):
            sections = self.adapter.list_sections(chapter)

        identifiers = [s.identifier for s in sections]
        assert "6.1" in identifiers
        assert "6.16" in identifiers
        assert len(sections) == 16
        assert all(s.level == HierarchyLevel.SECTION for s in sections)

    def test_repealed_chapter_returns_empty(self) -> None:
        chapter = ChapterRef(
            title=TitleRef(state_code="MI", identifier="MCL"), identifier="5"
        )
        served = {
            _chap_url("5"): CHAP5_HTML,
            _obj_url("mcl-Act-120-of-1937"): ACT120_HTML,
        }
        with mock_urlopen_serving(served):
            sections = self.adapter.list_sections(chapter)

        assert sections == ()

    def test_division_walk(self) -> None:
        # The chapter page (real) lists an Act; the Act page (real) lists
        # Divisions; each Division page (real) lists the sections of one
        # chapter. The walk follows Act -> Divisions -> sections.
        chapter = ChapterRef(
            title=TitleRef(state_code="MI", identifier="MCL"), identifier="712A"
        )
        served = {
            _chap_url("712A"): CHAP6_HTML,
            _obj_url("mcl-Act-62-of-1872"): ACT288_HTML,
        }
        roman = [
            "I", "II", "III", "IV", "V", "VI", "VII", "VIII",
            "IX", "X", "XI", "XII", "XIIA", "XIIB", "XIII",
        ]
        for r in roman:
            served[_obj_url(f"mcl-288-1939-{r}")] = DIV_XIIA_HTML
        with mock_urlopen_serving(served):
            sections = self.adapter.list_sections(chapter)

        assert sections
        assert all(s.identifier.startswith("712A.") for s in sections)
        assert "712A.1" in [s.identifier for s in sections]

    def test_sections_filtered_to_requested_chapter(self) -> None:
        # A Division page listing other chapters' sections must not leak in.
        chapter = ChapterRef(
            title=TitleRef(state_code="MI", identifier="MCL"), identifier="712A"
        )
        served = {
            _chap_url("712A"): CHAP6_HTML,
            _obj_url("mcl-Act-62-of-1872"): ACT288_HTML,
        }
        roman = [
            "I", "II", "III", "IV", "V", "VI", "VII", "VIII",
            "IX", "X", "XI", "XII", "XIIA", "XIIB", "XIII",
        ]
        for r in roman:
            served[_obj_url(f"mcl-288-1939-{r}")] = DIV_XIIA_HTML
        with mock_urlopen_serving(served):
            sections = self.adapter.list_sections(chapter)

        assert sections
        assert all(s.identifier.startswith("712A.") for s in sections)

    def test_invalid_chapter_identifier_raises_ref_not_found(self) -> None:
        chapter = ChapterRef(
            title=TitleRef(state_code="MI", identifier="MCL"), identifier="abc"
        )
        with pytest.raises(RefNotFoundError):
            self.adapter.list_sections(chapter)

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        chapter = ChapterRef(
            title=TitleRef(state_code="MI", identifier="MCL"), identifier="6"
        )
        with mock_urlopen_error(urllib.error.URLError("simulated")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_sections(chapter)


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = MichiganAdapter()

    def test_full_retrieval_normal_section(self) -> None:
        with mock_urlopen_serving({_sec_url("750", "82"): SEC_750_82}):
            section = self.adapter.retrieve_section(_make_ref("750", "750.82"))

        assert section.ref.state_code == "MI"
        assert section.ref.identifier == "750.82"
        assert section.citation.raw == "MCL § 750.82"
        assert section.heading.startswith(
            "Felonious assault; violation of subsection (1)"
        )
        assert section.text.startswith("(1) Except as otherwise provided")
        assert section.status.value == "unknown"
        assert "1931, Act 328" in section.amendment_notes
        assert section.source_url == _sec_url("750", "82")
        assert section.retrieved_at is not None

    def test_vehicle_code_section(self) -> None:
        with mock_urlopen_serving({_sec_url("257", "1"): SEC_257_1}):
            section = self.adapter.retrieve_section(_make_ref("257", "257.1"))

        assert section.citation.raw == "MCL § 257.1"
        assert section.heading == (
            "Michigan vehicle code; words and phrases defined."
        )
        assert section.text

    def test_lettered_section(self) -> None:
        with mock_urlopen_serving({_sec_url("712A", "2a"): SEC_712A_2A}):
            section = self.adapter.retrieve_section(_make_ref("712A", "712A.2a"))

        assert section.citation.raw == "MCL § 712A.2a"
        assert section.heading.startswith("Continuing jurisdiction beyond")
        assert section.text

    def test_subsection_heavy_section(self) -> None:
        with mock_urlopen_serving({_sec_url("712A", "2d"): SEC_712A_2D}):
            section = self.adapter.retrieve_section(_make_ref("712A", "712A.2d"))

        assert section.citation.raw == "MCL § 712A.2d"
        assert len(section.text) > 1000
        assert section.amendment_notes is not None

    def test_invalid_section_200_error_page_raises_ref_not_found(self) -> None:
        # The archived HTTP-400 "Error" page served as a 200 body: the
        # content check must reject it.
        with mock_urlopen_serving({_sec_url("999", "999"): SEC_INVALID}):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(_make_ref("999", "999.999"))

    def test_invalid_section_http_400_raises_ref_not_found(self) -> None:
        with _serve_error(_sec_url("10", "31"), 400):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(_make_ref("10", "10.31"))

    def test_invalid_section_http_404_raises_ref_not_found(self) -> None:
        with _serve_error(_sec_url("999", "1"), 404):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(_make_ref("999", "999.1"))

    def test_wrong_citation_raises_ref_mismatch(self) -> None:
        # Serve the 750.82 page at the 750.83 URL: the declared section must
        # not be silently accepted.
        with mock_urlopen_serving({_sec_url("750", "83"): SEC_750_82}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(_make_ref("750", "750.83"))

    def test_wrong_chapter_content_raises_ref_mismatch(self) -> None:
        with mock_urlopen_serving({_sec_url("700", "82"): SEC_750_82}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(_make_ref("700", "700.82"))

    def test_ref_chapter_mismatch_raises_ref_mismatch(self) -> None:
        # The ref's chapter disagrees with the citation's own chapter.
        with pytest.raises(RefMismatchError):
            self.adapter.retrieve_section(_make_ref("701", "750.82"))

    def test_invalid_citation_format_raises_ref_not_found(self) -> None:
        with pytest.raises(RefNotFoundError):
            self.adapter.retrieve_section(_make_ref("750", "abc"))

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated")):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(_make_ref())

    def test_malformed_html_raises_normalization_error(self) -> None:
        malformed = (
            "<html><head><title>MCL - Section 750.82 - Michigan "
            "Legislature</title></head><body></body></html>"
        )
        with mock_urlopen_serving({_sec_url("750", "82"): malformed}):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(_make_ref())


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = MichiganAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref()
        parsed = ParsedDocument(
            raw_citation="MCL § 750.82",
            heading="Felonious assault; ...",
            text="(1) Body text.",
            source_url=_sec_url("750", "82"),
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref is ref
        assert section.citation.raw == "MCL § 750.82"
        assert section.heading == "Felonious assault; ..."
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="WA", identifier="49"),
                identifier="60",
            ),
            identifier="49.60.010",
        )
        parsed = ParsedDocument(raw_citation="MCL § 750.82", text="x")
        with pytest.raises(NormalizationError):
            self.adapter.normalize(parsed, ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("750", "750.83")
        parsed = ParsedDocument(raw_citation="MCL § 750.82", text="x")
        with pytest.raises(RefMismatchError):
            self.adapter.normalize(parsed, ref)


class TestHierarchyMapping:
    def test_title_chapter_section_chain_descends(self) -> None:
        title = TitleRef(state_code="MI", identifier="MCL")
        chapter = ChapterRef(title=title, identifier="712A")
        section = SectionRef(chapter=chapter, identifier="712A.2d")

        assert chapter.state_code == "MI"
        assert section.state_code == "MI"
        assert chapter.title is title
        assert section.chapter is chapter


class TestInputValidation:
    def setup_method(self) -> None:
        self.adapter = MichiganAdapter()

    def test_citation_parsing(self) -> None:
        m = self.adapter._CITATION.fullmatch("712A.2d")
        assert m is not None and m.group(1) == "712A" and m.group(2) == "2d"
        m = self.adapter._CITATION.fullmatch("750.82")
        assert m is not None and m.group(1) == "750" and m.group(2) == "82"
        m = self.adapter._CITATION.fullmatch("257.1")
        assert m is not None and m.group(1) == "257" and m.group(2) == "1"
        assert self.adapter._CITATION.fullmatch("abc") is None
        assert self.adapter._CITATION.fullmatch("750") is None

    def test_citation_from_row(self) -> None:
        assert (
            self.adapter._citation_from_row("mcl-712A-2d", "Section 712A.2d")
            == "712A.2d"
        )
        assert (
            self.adapter._citation_from_row("mcl-6-1", "Section 6.1") == "6.1"
        )
        assert self.adapter._citation_from_row("mcl-Act-62-of-1872", "Act 62 of 1872") is None

    def test_object_name_uses_only_validated_citation(self) -> None:
        # The citation is fully validated before any URL is built; no user
        # input reaches the host or a non-objectName path.
        url = self.adapter.build_url(_make_ref("712A", "712A.2d"))
        assert "objectName=mcl-712A-2d" in url
        assert url.startswith("https://www.legislature.mi.gov/Laws/MCL?")