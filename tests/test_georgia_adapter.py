"""Tests for GeorgiaAdapter (OCGA bulk via Archive.org)."""

from __future__ import annotations

from pathlib import Path

import pytest

from state_statutes_mcp.adapters.georgia.adapter import GeorgiaAdapter
from state_statutes_mcp.core.exceptions import (
    AdapterUnavailableError,
    NormalizationError,
    RefMismatchError,
    RefNotFoundError,
)
from state_statutes_mcp.models.refs import ChapterRef, SectionRef, TitleRef

_FIXTURE = Path(__file__).parent / "fixtures" / "georgia" / "ga_T50_slice.txt"


def _adapter() -> GeorgiaAdapter:
    return GeorgiaAdapter(data_path=_FIXTURE)


def _ref(identifier: str, title: str = "50", chapter: str = "3") -> SectionRef:
    return SectionRef(
        chapter=ChapterRef(title=TitleRef(state_code="GA", identifier=title), identifier=chapter),
        identifier=identifier,
    )


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_state_identity() -> None:
    a = _adapter()
    assert a.state_code == "GA"
    assert a.state_name == "Georgia"


def test_is_concrete() -> None:
    a = _adapter()
    assert isinstance(a, GeorgiaAdapter)
    assert not getattr(a.__class__, "__abstractmethods__", set())


def test_build_url_section() -> None:
    a = _adapter()
    ref = _ref("50-3-1")
    assert a.build_url(ref) == "local-ga-ocga://GA/50/3/50-3-1"


def test_build_url_chapter() -> None:
    a = _adapter()
    cref = ChapterRef(title=TitleRef(state_code="GA", identifier="50"), identifier="3")
    assert a.build_url(cref) == "local-ga-ocga://GA/50/3"


def test_build_url_title() -> None:
    a = _adapter()
    tref = TitleRef(state_code="GA", identifier="50")
    assert a.build_url(tref) == "local-ga-ocga://GA/50"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_list_titles() -> None:
    a = _adapter()
    ids = {n.identifier for n in a.list_titles()}
    assert "50" in ids
    assert "49" in ids


def test_list_chapters_50() -> None:
    a = _adapter()
    chaps = {n.identifier for n in a.list_chapters(TitleRef(state_code="GA", identifier="50"))}
    assert "3" in chaps
    assert "1" in chaps


def test_list_chapters_unknown() -> None:
    a = _adapter()
    assert a.list_chapters(TitleRef(state_code="GA", identifier="999")) == ()


def test_list_sections_50_3() -> None:
    a = _adapter()
    secs = {n.identifier for n in a.list_sections(ChapterRef(title=TitleRef(state_code="GA", identifier="50"), identifier="3"))}
    assert "50-3-1" in secs
    assert "50-3-2" in secs
    assert "50-3-3" in secs
    assert "50-3-4.1" in secs
    assert "50-3-10" in secs


def test_list_sections_sorted() -> None:
    a = _adapter()
    secs = [n.identifier for n in a.list_sections(ChapterRef(title=TitleRef(state_code="GA", identifier="50"), identifier="3"))]
    # Numeric order: 1,2,3,4,4.1,5...10,11... not lexicographic 1,10,11...
    assert secs.index("50-3-1") < secs.index("50-3-2") < secs.index("50-3-10")
    assert secs.index("50-3-9") < secs.index("50-3-10")


# ---------------------------------------------------------------------------
# Valid retrieval
# ---------------------------------------------------------------------------


def test_retrieve_50_3_1() -> None:
    a = _adapter()
    sec = a.retrieve_section(_ref("50-3-1"))
    assert sec.ref.identifier == "50-3-1"
    assert sec.citation.raw == "50-3-1"
    assert sec.heading is not None and "Description of state flag" in sec.heading
    assert "The flag of the State of Georgia shall consist" in sec.text
    assert sec.source_url is not None
    assert sec.retrieved_at is not None


def test_retrieve_50_3_2() -> None:
    a = _adapter()
    sec = a.retrieve_section(_ref("50-3-2"))
    assert sec.citation.raw == "50-3-2"
    assert "Pledge of allegiance" in (sec.heading or "")
    assert "I pledge allegiance" in sec.text or "pledge of allegiance" in sec.text.lower()


def test_retrieve_50_3_3() -> None:
    a = _adapter()
    sec = a.retrieve_section(_ref("50-3-3"))
    assert sec.citation.raw == "50-3-3"
    assert sec.text.strip() != ""


def test_retrieve_50_3_4_1_dot() -> None:
    a = _adapter()
    sec = a.retrieve_section(_ref("50-3-4.1"))
    assert sec.citation.raw == "50-3-4.1"
    assert "Schools" in (sec.heading or "")


def test_neighbor_distinct() -> None:
    a = _adapter()
    s1 = a.retrieve_section(_ref("50-3-1"))
    s2 = a.retrieve_section(_ref("50-3-2"))
    s3 = a.retrieve_section(_ref("50-3-3"))
    assert s1.text != s2.text != s3.text
    assert s1.heading != s2.heading


def test_prefix_collision() -> None:
    a = _adapter()
    s1 = a.retrieve_section(_ref("50-3-1"))
    s10 = a.retrieve_section(_ref("50-3-10"))
    # Exact matching: 50-3-1 must not return 50-3-10 content
    assert s1.citation.raw == "50-3-1"
    assert s10.citation.raw == "50-3-10"
    assert s1.text != s10.text
    # Also 50-3-100 if present via secondary slice
    try:
        s100 = a.retrieve_section(_ref("50-3-100"))
        assert s100.citation.raw == "50-3-100"
        assert s1.text != s100.text
        assert s10.text != s100.text
    except RefNotFoundError:
        pass  # acceptable if fixture slice missing 100


# ---------------------------------------------------------------------------
# Invalid / error handling
# ---------------------------------------------------------------------------


def test_invalid_not_found() -> None:
    a = _adapter()
    with pytest.raises(RefNotFoundError):
        a.retrieve_section(_ref("50-3-999"))


@pytest.mark.parametrize("identifier", ["", "0", "-1", "999999", "50-3-", "abc", "50-3-1.1.1.1"])
def test_malformed_invalid(identifier: str) -> None:
    a = _adapter()
    # Empty identifier raises at model validation before adapter
    if identifier == "":
        with pytest.raises(Exception):  # ValidationError from pydantic
            _ref(identifier)
        return
    with pytest.raises((RefNotFoundError, RefMismatchError, NormalizationError)):
        a.retrieve_section(_ref(identifier))


def test_wrong_title_mismatch() -> None:
    a = _adapter()
    # Valid section number but wrong title
    with pytest.raises(RefMismatchError):
        a.retrieve_section(_ref("50-3-1", title="49", chapter="1"))


def test_wrong_chapter_mismatch() -> None:
    a = _adapter()
    with pytest.raises(RefMismatchError):
        a.retrieve_section(_ref("50-3-1", title="50", chapter="999"))


def test_cross_title_distinct() -> None:
    a = _adapter()
    sec_ga_50 = a.retrieve_section(_ref("50-3-1"))
    sec_49 = a.retrieve_section(_ref("49-1-1", title="49", chapter="1"))
    assert sec_ga_50.text != sec_49.text
    assert sec_ga_50.citation.raw != sec_49.citation.raw


def test_normalize_wrong_state() -> None:
    a = _adapter()
    from state_statutes_mcp.models.documents import ParsedDocument

    parsed = ParsedDocument(raw_citation="50-3-1", heading="h", text="body")
    bad_ref = SectionRef(
        chapter=ChapterRef(title=TitleRef(state_code="NY", identifier="STT"), identifier="57-A"),
        identifier="501",
    )
    with pytest.raises(NormalizationError):
        a.normalize(parsed, bad_ref)


def test_normalize_mismatch() -> None:
    a = _adapter()
    from state_statutes_mcp.models.documents import ParsedDocument

    parsed = ParsedDocument(raw_citation="50-3-2", heading="h", text="body")
    ref = _ref("50-3-1")
    with pytest.raises(RefMismatchError):
        a.normalize(parsed, ref)


def test_missing_data_path() -> None:
    bad = GeorgiaAdapter(data_path=Path("/nonexistent/path.txt"))
    with pytest.raises(AdapterUnavailableError):
        bad.list_titles()


def test_build_url_unsupported() -> None:
    from state_statutes_mcp.core.exceptions import UnsupportedRefError

    a = _adapter()

    class Dummy:
        pass

    with pytest.raises(UnsupportedRefError):
        a.build_url(Dummy())  # type: ignore[arg-type]
