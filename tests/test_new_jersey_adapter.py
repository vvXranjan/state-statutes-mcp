"""New Jersey adapter tests.

Offline tests use a small representative STATUTES.TXT fixture extracted
from the official STATUTES-TEXT.zip. The fixture is not the full dataset.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from state_statutes_mcp.adapters.new_jersey.adapter import NewJerseyAdapter
from state_statutes_mcp.core.exceptions import (
    AdapterUnavailableError,
    NormalizationError,
    RefMismatchError,
    RefNotFoundError,
)
from state_statutes_mcp.core.registry import AdapterRegistry
from state_statutes_mcp.models.documents import ParsedDocument
from state_statutes_mcp.models.refs import ChapterRef, SectionRef, TitleRef
from state_statutes_mcp.models.statute_section import StatuteSection
from state_statutes_mcp.server_tools import get_section, list_states

FIXTURE = Path(__file__).parent / "fixtures" / "new_jersey" / "statutes.txt"


def _adapter() -> NewJerseyAdapter:
    return NewJerseyAdapter(data_path=FIXTURE)


def _section_ref(identifier: str, title: str = "39", chapter: str = "4") -> SectionRef:
    return SectionRef(
        chapter=ChapterRef(
            title=TitleRef(state_code="NJ", identifier=title),
            identifier=chapter,
        ),
        identifier=identifier,
    )


def test_adapter_is_concrete() -> None:
    assert NewJerseyAdapter.__abstractmethods__ == frozenset()


def test_state_identity() -> None:
    adapter = _adapter()
    assert adapter.state_code == "NJ"
    assert adapter.state_name == "New Jersey"


def test_missing_dataset_raises_unavailable() -> None:
    adapter = NewJerseyAdapter(data_path=Path("/no/such/statutes.txt"))
    with pytest.raises(AdapterUnavailableError):
        adapter.list_titles()


def test_list_titles() -> None:
    titles = _adapter().list_titles()
    ids = [node.identifier for node in titles]
    assert "1" in ids
    assert "2A" in ids
    assert "39" in ids
    assert ids == sorted(ids, key=lambda value: (int("".join(c for c in value if c.isdigit()) or "0"), value))


def test_list_chapters() -> None:
    adapter = _adapter()
    chapters = adapter.list_chapters(TitleRef(state_code="NJ", identifier="39"))
    assert [node.identifier for node in chapters] == ["4"]
    assert adapter.list_chapters(TitleRef(state_code="NJ", identifier="999")) == ()


def test_list_sections_uses_full_citation() -> None:
    adapter = _adapter()
    sections = adapter.list_sections(
        ChapterRef(title=TitleRef(state_code="NJ", identifier="39"), identifier="4")
    )
    ids = [node.identifier for node in sections]
    assert "39:4-97" in ids
    assert "39:4-98" in ids
    assert "39:4-99" in ids
    assert "39:4-97a" in ids
    assert "39:4-98.1" in ids
    for node in sections:
        retrieved = adapter.retrieve_section(node.ref)  # type: ignore[arg-type]
        assert retrieved.ref.identifier == node.identifier


def test_retrieve_neighboring_sections() -> None:
    adapter = _adapter()
    s97 = adapter.retrieve_section(_section_ref("39:4-97"))
    s98 = adapter.retrieve_section(_section_ref("39:4-98"))
    s99 = adapter.retrieve_section(_section_ref("39:4-99"))
    assert isinstance(s97, StatuteSection)
    assert s97.citation.raw == "39:4-97"
    assert s98.citation.raw == "39:4-98"
    assert s99.citation.raw == "39:4-99"
    assert "careless" in s97.text.lower()
    assert "rates of speed" in s98.heading.lower()
    assert s97.text != s98.text
    assert s98.text != s99.text


def test_decimal_and_lettered_citations() -> None:
    adapter = _adapter()
    decimal = adapter.retrieve_section(_section_ref("39:4-98.1"))
    lettered = adapter.retrieve_section(_section_ref("39:4-97a"))
    assert decimal.citation.raw == "39:4-98.1"
    assert lettered.citation.raw == "39:4-97a"
    assert decimal.text
    assert lettered.text


def test_lettered_title() -> None:
    section = _adapter().retrieve_section(_section_ref("2A:3-14", title="2A", chapter="3"))
    assert section.citation.raw == "2A:3-14"
    assert section.ref.state_code == "NJ"


@pytest.mark.parametrize(
    "identifier",
    ["39:4-098", "39:4-98X", "39:4-98.999", "39:4-9999", "99:99-99", "not-a-citation"],
)
def test_invalid_citations_do_not_fallback(identifier: str) -> None:
    with pytest.raises(RefNotFoundError):
        _adapter().retrieve_section(_section_ref(identifier))


def test_normalize_mismatch_raises() -> None:
    adapter = _adapter()
    parsed = ParsedDocument(raw_citation="39:4-97", text="unrelated body")
    with pytest.raises(RefMismatchError):
        adapter.normalize(parsed, _section_ref("39:4-98"))


def test_normalize_wrong_state_raises() -> None:
    adapter = _adapter()
    parsed = ParsedDocument(raw_citation="1-1-1", text="x")
    wrong = SectionRef(
        chapter=ChapterRef(
            title=TitleRef(state_code="AL", identifier="1"),
            identifier="1",
        ),
        identifier="1-1-1",
    )
    with pytest.raises(NormalizationError):
        adapter.normalize(parsed, wrong)


def test_normalize_matching_citation() -> None:
    adapter = _adapter()
    parsed = ParsedDocument(
        raw_citation="39:4-98",
        heading="Rates of speed",
        text="body text",
    )
    result = adapter.normalize(parsed, _section_ref("39:4-98"))
    assert result.ref.state_code == "NJ"
    assert result.text == "body text"


def test_status_unknown_by_default() -> None:
    section = _adapter().retrieve_section(_section_ref("39:4-98"))
    assert section.status.name == "UNKNOWN"


def test_adapter_registers_once() -> None:
    registry = AdapterRegistry()
    adapter = _adapter()
    registry.register(adapter)
    assert registry.is_registered("NJ")
    assert registry.get("NJ") is adapter


def test_list_states_and_get_section_use_server_tools() -> None:
    registry = AdapterRegistry()
    registry.register(_adapter())
    states = list_states(registry)
    assert states == [{"state_code": "NJ", "state_name": "New Jersey"}]
    result = get_section(registry, "NJ", "39", "4", "39:4-98")
    assert result["state"] == "NJ"
    assert result["citation"] == "39:4-98"
    assert result["text"]
