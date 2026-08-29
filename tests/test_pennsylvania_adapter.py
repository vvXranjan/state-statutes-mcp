"""Tests for PennsylvaniaAdapter.

The Pennsylvania consolidated statutes
(www.legis.state.pa.us/WU01/LI/LI/CT/HTM/{TT}/00.{chapter}.{local}.{decimal}.
.HTM) are served as server-rendered HTML. The live hosts are TCP-blocked
from this environment, so the fixtures used here are REAL archived official
captures of the official host (retrieved via the Wayback Machine, Aug 2026;
see docs/research/pennsylvania.md) -- NOT live captures.

Hierarchy mapping: TitleRef = title number (0-87; 0 is the Constitution);
ChapterRef = chapter number (e.g. "27"); SectionRef.identifier = the full
section citation (e.g. "2707", "2702.1", "2109.1"). The chapter is encoded
by the citation (chapter = int(section) // 100).

Network tests mock the real network boundary
(``urllib.request.urlopen``), never adapter internals.
"""

from __future__ import annotations

import io
import urllib.error
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pytest

from _mock_network import mock_urlopen_serving, mock_urlopen_error

from state_statutes_mcp.adapters.pennsylvania.adapter import PennsylvaniaAdapter
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
from state_statutes_mcp.models.statute_section import StatuteStatus

# --- REAL archived official fixtures (Wayback captures, Aug 2026) ---
FIXTURES = Path(__file__).parent / "fixtures"

TITLE_00 = (FIXTURES / "pa_title_00.html").read_text()
TITLE_18 = (FIXTURES / "pa_title_18.html").read_text()
CHAPTER_INDEX = (FIXTURES / "pa_chapter_index.html").read_text()
SEC_2707 = (FIXTURES / "pa_section_2707.html").read_text()
SEC_1102_1 = (FIXTURES / "pa_section_1102_1.html").read_text()
SEC_4321 = (FIXTURES / "pa_section_4321.html").read_text()
NOT_FOUND = (FIXTURES / "pa_404.html").read_text()

BASE = "https://www.legis.state.pa.us/WU01/LI/LI/CT/HTM"
TITLE_URL = lambda t: f"{BASE}/{int(t):02d}/00.001..HTM"
CHAPTER_URL = lambda t, c: f"{BASE}/{int(t):02d}/00.{int(c):03d}.001.000..HTM"
SECTION_URL = lambda t, c, l, d: (
    f"{BASE}/{int(t):02d}/00.{int(c):03d}.{int(l):03d}.{int(d):03d}..HTM"
)


def _make_ref(title: str, chapter: str, section: str) -> SectionRef:
    return SectionRef(
        chapter=ChapterRef(
            title=TitleRef(state_code="PA", identifier=title),
            identifier=chapter,
        ),
        identifier=section,
    )


def _serve_not_found_for(url: str, content: str = NOT_FOUND):
    """Serve ``content`` (default: the official 'Page Not Found' page) for
    exactly one URL."""
    return mock_urlopen_serving({url: content})


@contextmanager
def _serve_http_error(url: str, code: int):
    """Make urlopen raise an ``HTTPError`` with the given status for one URL."""
    def fake_urlopen(u, timeout=None):
        target = u if isinstance(u, str) else u.full_url
        if target != url:
            raise AssertionError(f"Unexpected URL fetched in test: {target!r}")
        raise urllib.error.HTTPError(url, code, "Error", {}, io.BytesIO(b""))

    with mock.patch(
        "state_statutes_mcp.adapters._fetch.urllib.request.urlopen",
        side_effect=fake_urlopen,
    ):
        yield


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert PennsylvaniaAdapter.__abstractmethods__ == frozenset()
        adapter = PennsylvaniaAdapter()
        assert adapter.state_code == "PA"
        assert adapter.state_name == "Pennsylvania"


class TestCitationParsing:
    def test_parses_integer(self) -> None:
        assert PennsylvaniaAdapter._parse_citation("2707") == (2707, 0)

    def test_parses_decimal(self) -> None:
        assert PennsylvaniaAdapter._parse_citation("2702.1") == (2702, 1)

    def test_parses_three_digit(self) -> None:
        assert PennsylvaniaAdapter._parse_citation("101") == (101, 0)

    def test_rejects_lettered(self) -> None:
        assert PennsylvaniaAdapter._parse_citation("2713a") is None

    def test_rejects_alpha(self) -> None:
        assert PennsylvaniaAdapter._parse_citation("abc") is None

    def test_rejects_two_digit(self) -> None:
        assert PennsylvaniaAdapter._parse_citation("99") is None

    def test_rejects_extra_component(self) -> None:
        assert PennsylvaniaAdapter._parse_citation("1.2.3") is None

    def test_rejects_blank(self) -> None:
        assert PennsylvaniaAdapter._parse_citation("") is None


class TestUrlConstruction:
    def test_integer_section_url(self) -> None:
        adapter = PennsylvaniaAdapter()
        ref = _make_ref("18", "27", "2707")
        assert adapter.build_url(ref) == SECTION_URL("18", "27", "7", 0)

    def test_decimal_section_url(self) -> None:
        adapter = PennsylvaniaAdapter()
        ref = _make_ref("18", "11", "1102.1")
        assert adapter.build_url(ref) == SECTION_URL("18", "11", "2", 1)

    def test_section_title_is_zero_padded(self) -> None:
        adapter = PennsylvaniaAdapter()
        ref = _make_ref("1", "1", "101")
        assert adapter.build_url(ref).startswith(f"{BASE}/01/00.001.001.000..HTM")

    def test_chapter_url(self) -> None:
        adapter = PennsylvaniaAdapter()
        ref = ChapterRef(
            title=TitleRef(state_code="PA", identifier="18"),
            identifier="27",
        )
        assert adapter.build_url(ref) == CHAPTER_URL("18", "27")

    def test_title_url(self) -> None:
        adapter = PennsylvaniaAdapter()
        ref = TitleRef(state_code="PA", identifier="18")
        assert adapter.build_url(ref) == TITLE_URL("18")

    def test_title_zero_is_zero_padded(self) -> None:
        adapter = PennsylvaniaAdapter()
        ref = TitleRef(state_code="PA", identifier="0")
        assert adapter.build_url(ref) == f"{BASE}/00/00.001..HTM"

    def test_invalid_section_raises(self) -> None:
        adapter = PennsylvaniaAdapter()
        ref = _make_ref("18", "27", "2707a")
        with pytest.raises(RefNotFoundError):
            adapter.build_url(ref)

    def test_invalid_chapter_raises(self) -> None:
        adapter = PennsylvaniaAdapter()
        ref = ChapterRef(
            title=TitleRef(state_code="PA", identifier="18"),
            identifier="0",
        )
        with pytest.raises(RefNotFoundError):
            adapter.build_url(ref)

    def test_invalid_title_raises(self) -> None:
        adapter = PennsylvaniaAdapter()
        ref = TitleRef(state_code="PA", identifier="abc")
        with pytest.raises(RefNotFoundError):
            adapter.build_url(ref)

    def test_unsupported_ref_raises(self) -> None:
        adapter = PennsylvaniaAdapter()
        with pytest.raises(UnsupportedRefError):
            adapter.build_url("not a ref")  # type: ignore[arg-type]


class TestListTitles:
    def test_returns_titles(self) -> None:
        served = {
            TITLE_URL("0"): TITLE_00,
            TITLE_URL("18"): TITLE_18,
        }
        # Every other probed title number returns the official 'Page Not
        # Found' page and is skipped by the identity check.
        for t in range(0, 88):
            served.setdefault(TITLE_URL(str(t)), NOT_FOUND)
        with mock_urlopen_serving(served):
            result = PennsylvaniaAdapter().list_titles()

        identifiers = [(node.identifier, node.name) for node in result]
        assert ("0", "CONSTITUTION OF PENNSYLVANIA") in identifiers
        assert ("18", "CRIMES AND OFFENSES") in identifiers
        assert all(node.level == HierarchyLevel.TITLE for node in result)
        assert all(node.ref.state_code == "PA" for node in result)

    def test_skips_invalid_titles(self) -> None:
        # Every title probe returns the official 'Page Not Found' page,
        # which carries no title identity and must be skipped.
        served = {TITLE_URL(str(t)): NOT_FOUND for t in range(0, 88)}
        with mock_urlopen_serving(served):
            with pytest.raises(AdapterUnavailableError):
                PennsylvaniaAdapter().list_titles()

    def test_caches_per_instance(self) -> None:
        served = {
            TITLE_URL("0"): TITLE_00,
            TITLE_URL("18"): TITLE_18,
        }
        for t in range(0, 88):
            served.setdefault(TITLE_URL(str(t)), NOT_FOUND)
        with mock_urlopen_serving(served):
            adapter = PennsylvaniaAdapter()
            first = adapter.list_titles()
            second = adapter.list_titles()
        assert first is second

    def test_network_failure_raises(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                PennsylvaniaAdapter().list_titles()


class TestListChapters:
    def test_returns_chapters(self) -> None:
        served = {CHAPTER_URL("18", "27"): CHAPTER_INDEX}
        for c in range(1, 100):
            served.setdefault(CHAPTER_URL("18", str(c)), NOT_FOUND)
        with mock_urlopen_serving(served):
            result = PennsylvaniaAdapter().list_chapters(
                TitleRef(state_code="PA", identifier="18")
            )

        assert len(result) == 1
        assert result[0].identifier == "27"
        assert result[0].name == "ASSAULT"
        assert result[0].level == HierarchyLevel.CHAPTER
        assert result[0].ref.state_code == "PA"

    def test_caches_per_title(self) -> None:
        served = {CHAPTER_URL("18", "27"): CHAPTER_INDEX}
        for c in range(1, 100):
            served.setdefault(CHAPTER_URL("18", str(c)), NOT_FOUND)
        with mock_urlopen_serving(served):
            adapter = PennsylvaniaAdapter()
            title = TitleRef(state_code="PA", identifier="18")
            first = adapter.list_chapters(title)
            second = adapter.list_chapters(title)
        assert first is second

    def test_invalid_title_raises(self) -> None:
        with pytest.raises(RefNotFoundError):
            PennsylvaniaAdapter().list_chapters(
                TitleRef(state_code="PA", identifier="abc")
            )

    def test_network_failure_raises(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                PennsylvaniaAdapter().list_chapters(
                    TitleRef(state_code="PA", identifier="18")
                )


class TestListSections:
    def test_returns_sections(self) -> None:
        served = {CHAPTER_URL("18", "27"): CHAPTER_INDEX}
        with mock_urlopen_serving(served):
            result = PennsylvaniaAdapter().list_sections(
                ChapterRef(
                    title=TitleRef(state_code="PA", identifier="18"),
                    identifier="27",
                )
            )

        assert len(result) == 25
        assert result[0].identifier == "2701"
        assert result[0].name == "Simple assault."
        assert result[-1].identifier == "2719"
        assert result[-1].name == "Endangerment of public safety official."
        decimals = [n.identifier for n in result if "." in n.identifier]
        assert "2702.1" in decimals
        assert "2707.1" in decimals
        assert "2709.1" in decimals
        assert all(n.level == HierarchyLevel.SECTION for n in result)
        assert all(n.ref.state_code == "PA" for n in result)

    def test_invalid_chapter_raises(self) -> None:
        with pytest.raises(RefNotFoundError):
            PennsylvaniaAdapter().list_sections(
                ChapterRef(
                    title=TitleRef(state_code="PA", identifier="18"),
                    identifier="0",
                )
            )

    def test_not_found_page_raises(self) -> None:
        served = {CHAPTER_URL("18", "50"): NOT_FOUND}
        with mock_urlopen_serving(served):
            with pytest.raises(RefNotFoundError):
                PennsylvaniaAdapter().list_sections(
                    ChapterRef(
                        title=TitleRef(state_code="PA", identifier="18"),
                        identifier="50",
                    )
                )

    def test_http_404_raises(self) -> None:
        with _serve_http_error(CHAPTER_URL("18", "50"), 404):
            with pytest.raises(RefNotFoundError):
                PennsylvaniaAdapter().list_sections(
                    ChapterRef(
                        title=TitleRef(state_code="PA", identifier="18"),
                        identifier="50",
                    )
                )

    def test_network_failure_raises(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                PennsylvaniaAdapter().list_sections(
                    ChapterRef(
                        title=TitleRef(state_code="PA", identifier="27"),
                        identifier="27",
                    )
                )


class TestRetrieveSection:
    def test_returns_normalized_section(self) -> None:
        served = {SECTION_URL("18", "27", "7", 0): SEC_2707}
        with mock_urlopen_serving(served):
            result = PennsylvaniaAdapter().retrieve_section(
                _make_ref("18", "27", "2707")
            )

        assert result.ref.identifier == "2707"
        assert result.citation.raw == "18 Pa.C.S. § 2707"
        assert result.heading == (
            "Propulsion of missiles into an occupied vehicle or onto a "
            "roadway."
        )
        assert result.text.startswith(
            "(a) Occupied vehicles.-- Whoever intentionally throws"
        )
        assert "misdemeanor of the second degree" in result.text
        assert result.status == StatuteStatus.UNKNOWN
        assert result.amendment_notes is not None
        assert "P.L.62" in result.amendment_notes
        assert result.source_url == SECTION_URL("18", "27", "7", 0)
        assert result.retrieved_at is not None

    def test_decimal_section(self) -> None:
        served = {SECTION_URL("18", "11", "2", 1): SEC_1102_1}
        with mock_urlopen_serving(served):
            result = PennsylvaniaAdapter().retrieve_section(
                _make_ref("18", "11", "1102.1")
            )

        assert result.citation.raw == "18 Pa.C.S. § 1102.1"
        assert result.heading.startswith(
            "Sentence of persons under the age of 18"
        )
        assert result.status == StatuteStatus.UNKNOWN

    def test_repealed_section(self) -> None:
        served = {SECTION_URL("18", "43", "21", 0): SEC_4321}
        with mock_urlopen_serving(served):
            result = PennsylvaniaAdapter().retrieve_section(
                _make_ref("18", "43", "4321")
            )

        assert result.citation.raw == "18 Pa.C.S. § 4321"
        assert result.heading is None
        assert "1985 Repeal Note" in result.text
        assert result.status == StatuteStatus.REPEALED

    def test_invalid_identifier_raises(self) -> None:
        with pytest.raises(RefNotFoundError):
            PennsylvaniaAdapter().retrieve_section(
                _make_ref("18", "27", "2707a")
            )

    def test_chapter_mismatch_raises(self) -> None:
        served = {SECTION_URL("18", "27", "7", 0): SEC_2707}
        with mock_urlopen_serving(served):
            with pytest.raises(RefMismatchError):
                PennsylvaniaAdapter().retrieve_section(
                    _make_ref("18", "99", "2707")
                )


class TestInvalidSection:
    def test_not_found_page_raises(self) -> None:
        served = {SECTION_URL("18", "50", "3", 0): NOT_FOUND}
        with mock_urlopen_serving(served):
            with pytest.raises(RefNotFoundError):
                PennsylvaniaAdapter().retrieve_section(
                    _make_ref("18", "50", "5003")
                )

    def test_http_404_raises(self) -> None:
        with _serve_http_error(SECTION_URL("18", "50", "3", 0), 404):
            with pytest.raises(RefNotFoundError):
                PennsylvaniaAdapter().retrieve_section(
                    _make_ref("18", "50", "5003")
                )

    def test_network_failure_raises(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated failure")):
            with pytest.raises(AdapterUnavailableError):
                PennsylvaniaAdapter().retrieve_section(
                    _make_ref("18", "27", "2707")
                )


class TestSilentFallbackProtection:
    def test_wrong_section_identity_raises_mismatch(self) -> None:
        # Serve the §2707 page (identity 'Section 2707.0') in response to a
        # request for §2706: the identity must not be silently accepted.
        served = {SECTION_URL("18", "27", "6", 0): SEC_2707}
        with mock_urlopen_serving(served):
            with pytest.raises(RefMismatchError):
                PennsylvaniaAdapter().retrieve_section(
                    _make_ref("18", "27", "2706")
                )

    def test_wrong_title_identity_raises_mismatch(self) -> None:
        # Serve the Title 18 §2707 page in response to a Title 20 request:
        # the identity's 'Title 18' must not be silently accepted.
        served = {SECTION_URL("20", "27", "7", 0): SEC_2707}
        with mock_urlopen_serving(served):
            with pytest.raises(RefMismatchError):
                PennsylvaniaAdapter().retrieve_section(
                    _make_ref("20", "27", "2707")
                )

    def test_no_identity_raises_not_found(self) -> None:
        # A page with no 'Section {n}' identity (e.g. the 404 page) maps to
        # RefNotFoundError, never a silent section.
        served = {SECTION_URL("18", "27", "7", 0): NOT_FOUND}
        with mock_urlopen_serving(served):
            with pytest.raises(RefNotFoundError):
                PennsylvaniaAdapter().retrieve_section(
                    _make_ref("18", "27", "2707")
                )


class TestNormalize:
    def test_normalizes(self) -> None:
        adapter = PennsylvaniaAdapter()
        ref = _make_ref("18", "27", "2707")
        parsed = ParsedDocument(
            raw_citation="18 Pa.C.S. § 2707",
            heading="Simple assault.",
            text="(a) A person is guilty of simple assault if he attempts.",
        )
        result = adapter.normalize(parsed, ref)
        assert result.ref is ref
        assert result.citation.raw == "18 Pa.C.S. § 2707"
        assert result.status == StatuteStatus.UNKNOWN

    def test_repealed_marker_sets_status(self) -> None:
        adapter = PennsylvaniaAdapter()
        ref = _make_ref("18", "43", "4321")
        parsed = ParsedDocument(
            raw_citation="18 Pa.C.S. § 4321",
            heading=None,
            text="SUBCHAPTER B NONSUPPORT (Repealed). 1985 Repeal Note. ...",
        )
        result = adapter.normalize(parsed, ref)
        assert result.status == StatuteStatus.REPEALED

    def test_cross_check_mismatch_raises(self) -> None:
        adapter = PennsylvaniaAdapter()
        ref = _make_ref("18", "27", "2707")
        parsed = ParsedDocument(
            raw_citation="18 Pa.C.S. § 2706",
            text="body",
        )
        with pytest.raises(RefMismatchError):
            adapter.normalize(parsed, ref)

    def test_wrong_state_raises(self) -> None:
        adapter = PennsylvaniaAdapter()
        ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="AK", identifier="18"),
                identifier="27",
            ),
            identifier="2707",
        )
        parsed = ParsedDocument(
            raw_citation="18 Pa.C.S. § 2707",
            text="body",
        )
        with pytest.raises(NormalizationError):
            adapter.normalize(parsed, ref)


class TestMalformedStructure:
    def test_identity_without_heading_raises(self) -> None:
        # A page that declares the section identity but carries neither a
        # '§ {n}.' heading nor a repeal marker (a structural regression).
        malformed = """<html><head><title>Section 2707.0 - Title 18 -
        CRIMES AND OFFENSES</title></head><body>
        <p>Some unexpected content.</p></body></html>"""
        served = {SECTION_URL("18", "27", "7", 0): malformed}
        with mock_urlopen_serving(served):
            with pytest.raises(NormalizationError):
                PennsylvaniaAdapter().retrieve_section(
                    _make_ref("18", "27", "2707")
                )