"""New York adapter tests — fixture-based, offline."""

from __future__ import annotations

from pathlib import Path

import pytest

from state_statutes_mcp.adapters.new_york.adapter import NewYorkAdapter
from state_statutes_mcp.core.exceptions import (
    NormalizationError,
    RefMismatchError,
    RefNotFoundError,
)
from state_statutes_mcp.models.documents import ParsedDocument
from state_statutes_mcp.models.refs import ChapterRef, SectionRef, TitleRef
from _mock_network import mock_urlopen_serving

FIXTURES = Path(__file__).parent / "fixtures" / "new_york"


def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _url(law: str, sec: str) -> str:
    return f"https://www.nysenate.gov/legislation/laws/{law}/{sec}"


# 1. contract
def test_adapter_is_concrete():
    assert NewYorkAdapter.__abstractmethods__ == frozenset()


# 2. identity
def test_state_identity():
    a = NewYorkAdapter()
    assert a.state_code == "NY"
    assert a.state_name == "New York"


# 3. build_url
def test_build_url():
    a = NewYorkAdapter()
    assert a.build_url(SectionRef(chapter=ChapterRef(title=TitleRef(state_code="NY", identifier="STT"), identifier="57-A"), identifier="501")) == _url("STT", "501")
    assert a.build_url(SectionRef(chapter=ChapterRef(title=TitleRef(state_code="NY", identifier="VAT"), identifier="71"), identifier="1110")) == _url("VAT", "1110")
    assert a.build_url(TitleRef(state_code="NY", identifier="STT")) == "https://www.nysenate.gov/legislation/laws/STT"
    assert a.build_url(ChapterRef(title=TitleRef(state_code="NY", identifier="STT"), identifier="57-A")) == "https://www.nysenate.gov/legislation/laws/STT/57-A"


# 4. list_titles
def test_list_titles():
    titles = NewYorkAdapter().list_titles()
    ids = {n.identifier for n in titles}
    assert "STT" in ids
    assert "VAT" in ids


# 5. list_chapters
def test_list_chapters():
    a = NewYorkAdapter()
    stt_chaps = a.list_chapters(TitleRef(state_code="NY", identifier="STT"))
    assert any(n.identifier == "57-A" for n in stt_chaps)
    vat_chaps = a.list_chapters(TitleRef(state_code="NY", identifier="VAT"))
    assert any(n.identifier == "71" for n in vat_chaps)
    assert a.list_chapters(TitleRef(state_code="NY", identifier="ZZZ")) == ()


# 6. list_sections
def test_list_sections():
    a = NewYorkAdapter()
    stt_secs = a.list_sections(ChapterRef(title=TitleRef(state_code="NY", identifier="STT"), identifier="57-A"))
    assert {n.identifier for n in stt_secs} == {"501", "502"}
    vat_secs = a.list_sections(ChapterRef(title=TitleRef(state_code="NY", identifier="VAT"), identifier="71"))
    assert {n.identifier for n in vat_secs} == {"1110", "1111"}


# 7-8. STT retrieval
def test_retrieve_stt_501():
    html = _read_fixture("STT_501.html")
    ref = SectionRef(chapter=ChapterRef(title=TitleRef(state_code="NY", identifier="STT"), identifier="57-A"), identifier="501")
    with mock_urlopen_serving({_url("STT", "501"): html}):
        sec = NewYorkAdapter().retrieve_section(ref)
    assert sec.ref.identifier == "501"
    assert "Definitions" in (sec.heading or "")
    assert "Automated decision-making tool" in sec.text
    assert sec.citation.raw == "STT 501"
    assert sec.ref.state_code == "NY"
    assert sec.amendment_notes and "NB Repealed July 1, 2028" in sec.amendment_notes


def test_retrieve_stt_502():
    html = _read_fixture("STT_502.html")
    ref = SectionRef(chapter=ChapterRef(title=TitleRef(state_code="NY", identifier="STT"), identifier="57-A"), identifier="502")
    with mock_urlopen_serving({_url("STT", "502"): html}):
        sec = NewYorkAdapter().retrieve_section(ref)
    assert sec.citation.raw == "STT 502"
    assert "Disclosure" in (sec.heading or "")


# 9-10. VAT retrieval
def test_retrieve_vat_1110():
    html = _read_fixture("VAT_1110.html")
    ref = SectionRef(chapter=ChapterRef(title=TitleRef(state_code="NY", identifier="VAT"), identifier="71"), identifier="1110")
    with mock_urlopen_serving({_url("VAT", "1110"): html}):
        sec = NewYorkAdapter().retrieve_section(ref)
    assert sec.citation.raw == "VAT 1110"
    assert "Obedience to" in (sec.heading or "") or "Obedience" in sec.text


def test_retrieve_vat_1111():
    html = _read_fixture("VAT_1111.html")
    ref = SectionRef(chapter=ChapterRef(title=TitleRef(state_code="NY", identifier="VAT"), identifier="71"), identifier="1111")
    with mock_urlopen_serving({_url("VAT", "1111"): html}):
        sec = NewYorkAdapter().retrieve_section(ref)
    assert sec.citation.raw == "VAT 1111"
    assert "Traffic-control" in sec.text or "Traffic-control" in (sec.heading or "")


# 11. neighboring distinct
def test_neighboring_distinct():
    a = NewYorkAdapter()
    html501 = _read_fixture("STT_501.html")
    html502 = _read_fixture("STT_502.html")
    ref501 = SectionRef(chapter=ChapterRef(title=TitleRef(state_code="NY", identifier="STT"), identifier="57-A"), identifier="501")
    ref502 = SectionRef(chapter=ChapterRef(title=TitleRef(state_code="NY", identifier="STT"), identifier="57-A"), identifier="502")
    with mock_urlopen_serving({_url("STT", "501"): html501}):
        s501 = a.retrieve_section(ref501)
    with mock_urlopen_serving({_url("STT", "502"): html502}):
        s502 = a.retrieve_section(ref502)
    assert s501.text != s502.text
    assert s501.citation.raw != s502.citation.raw
    assert s501.heading != s502.heading


# 12-13. explicit not-equal checks
def test_501_not_502():
    assert _read_fixture("STT_501.html") != _read_fixture("STT_502.html")


def test_1110_not_1111():
    assert _read_fixture("VAT_1110.html") != _read_fixture("VAT_1111.html")


# 14. wrong lawId
def test_wrong_law_rejected():
    html = _read_fixture("VAT_1110.html")  # VAT 1110 content but request STT 1110
    ref = SectionRef(chapter=ChapterRef(title=TitleRef(state_code="NY", identifier="STT"), identifier="57-A"), identifier="1110")
    with mock_urlopen_serving({_url("STT", "1110"): html}):
        with pytest.raises(RefMismatchError):
            NewYorkAdapter().retrieve_section(ref)


# 15. invalid section
def test_invalid_section_rejected():
    html = _read_fixture("STT_INVALID.html")
    ref = SectionRef(chapter=ChapterRef(title=TitleRef(state_code="NY", identifier="STT"), identifier="57-A"), identifier="999999")
    with mock_urlopen_serving({_url("STT", "999999"): html}):
        with pytest.raises(RefNotFoundError):
            NewYorkAdapter().retrieve_section(ref)


# 16. invalid HTTP-200 page (500 is also not-found)
def test_invalid_http200_page_rejected():
    html = _read_fixture("STT_500.html")
    ref = SectionRef(chapter=ChapterRef(title=TitleRef(state_code="NY", identifier="STT"), identifier="57-A"), identifier="500")
    with mock_urlopen_serving({_url("STT", "500"): html}):
        with pytest.raises(RefNotFoundError):
            NewYorkAdapter().retrieve_section(ref)


# 17. normalize matching
def test_normalize_matching():
    a = NewYorkAdapter()
    parsed = ParsedDocument(raw_citation="STT 501", heading="Definitions", text="body", source_url=_url("STT", "501"))
    ref = SectionRef(chapter=ChapterRef(title=TitleRef(state_code="NY", identifier="STT"), identifier="57-A"), identifier="501")
    sec = a.normalize(parsed, ref)
    assert sec.citation.raw == "STT 501"


# 18. normalize mismatch
def test_normalize_mismatch():
    a = NewYorkAdapter()
    parsed = ParsedDocument(raw_citation="STT 502", heading="x", text="body")
    ref = SectionRef(chapter=ChapterRef(title=TitleRef(state_code="NY", identifier="STT"), identifier="57-A"), identifier="501")
    with pytest.raises(RefMismatchError):
        a.normalize(parsed, ref)


# 19. history/NB extraction
def test_history_extraction():
    html = _read_fixture("STT_501.html")
    ref = SectionRef(chapter=ChapterRef(title=TitleRef(state_code="NY", identifier="STT"), identifier="57-A"), identifier="501")
    with mock_urlopen_serving({_url("STT", "501"): html}):
        sec = NewYorkAdapter().retrieve_section(ref)
    assert sec.amendment_notes is not None
    assert "NB Repealed July 1, 2028" in sec.amendment_notes
    assert "NB Repealed" in sec.text  # also preserved in text


# 20. missing history does not fail (VAT 1110 has no NB)
def test_missing_history_does_not_fail():
    html = _read_fixture("VAT_1110.html")
    ref = SectionRef(chapter=ChapterRef(title=TitleRef(state_code="NY", identifier="VAT"), identifier="71"), identifier="1110")
    with mock_urlopen_serving({_url("VAT", "1110"): html}):
        sec = NewYorkAdapter().retrieve_section(ref)
    assert sec.text
    # VAT has no NB, amendment_notes should be None
    assert sec.amendment_notes is None


# 21. malformed citation
def test_malformed_citation_rejected():
    html = _read_fixture("STT_INVALID.html")
    ref = SectionRef(chapter=ChapterRef(title=TitleRef(state_code="NY", identifier="STT"), identifier="57-A"), identifier="501A+BAD")
    with mock_urlopen_serving({_url("STT", "501A+BAD"): html}):
        with pytest.raises((RefNotFoundError, RefMismatchError)):
            NewYorkAdapter().retrieve_section(ref)


# 22. registry
def test_registry_integration():
    from state_statutes_mcp.core.registry import AdapterRegistry

    r = AdapterRegistry()
    r.register(NewYorkAdapter())
    assert r.is_registered("NY")
    assert r.get("NY").state_code == "NY"


# 23. server_tools
def test_server_tools_integration():
    from state_statutes_mcp.core.registry import AdapterRegistry
    from state_statutes_mcp.server_tools import get_section, list_states

    reg = AdapterRegistry()
    reg.register(NewYorkAdapter())
    assert any(s["state_code"] == "NY" for s in list_states(reg))
    html = _read_fixture("STT_501.html")
    with mock_urlopen_serving({_url("STT", "501"): html}):
        result = get_section(reg, "NY", "STT", "57-A", "501")
    assert result["state"] == "NY"
    assert result["citation"] == "STT 501"


# 24. no network dependency — all above use fixtures via mock
