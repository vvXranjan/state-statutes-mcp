"""Tests for AlaskaAdapter.

The Alaska Statutes (www.akleg.gov/basis/statutes.asp) are served as
server-rendered HTML. The live host is protected by a bot-challenge wall
(HTTP 403 to this environment), so the fixtures used here are REAL archived
official captures of the official host (retrieved via the Wayback Machine,
Aug 2026; see docs/research/alaska.md) -- NOT live captures.

The official pages are ISO-8859-1 (verified via a literal ``§`` byte in a
repealed-note capture), so the adapter decodes ``windows-1252`` and the
fixtures are served as raw bytes.

Hierarchy mapping: TitleRef = title number (1-47); ChapterRef = the
zero-padded ``T.C`` citation (e.g. "11.41"); SectionRef.identifier = the
full zero-padded citation (e.g. "11.41.100").

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

from _mock_network import mock_urlopen_serving_bytes

from state_statutes_mcp.adapters.alaska.adapter import AlaskaAdapter
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

INDEX_HTML = (FIXTURES / "ak_index.html").read_bytes()
TOC_TITLE_HTML = (FIXTURES / "ak_toc_title.html").read_bytes()
TOC_CHAPTER_HTML = (FIXTURES / "ak_toc_chapter.html").read_bytes()
SEC_0110070 = (FIXTURES / "ak_section_0110070.html").read_bytes()
SEC_RENUMBERED = (FIXTURES / "ak_section_renumbered.html").read_bytes()
SEC_REPEALED = (FIXTURES / "ak_section_repealed.html").read_bytes()
INVALID_404 = (FIXTURES / "ak_invalid_404.html").read_bytes()

BASE = "https://www.akleg.gov/basis/statutes.asp"
INDEX_URL = BASE
TOC_URL = lambda t: f"{BASE}?media=js&type=TOC&title={t}"
SEC_URL = lambda c: f"{BASE}?media=print&secStart={c}&secEnd="


def _make_ref(citation: str, chapter: str | None = None) -> SectionRef:
    parts = citation.split(".")
    if len(parts) == 3:
        title, chap, _ = parts
        default_chapter = f"{int(title):02d}.{chap}"
    else:
        title = "1"
        default_chapter = "01.10"
    return SectionRef(
        chapter=ChapterRef(
            title=TitleRef(state_code="AK", identifier=str(int(title))),
            identifier=chapter or default_chapter,
        ),
        identifier=citation,
    )


@contextmanager
def _serve_error(url: str, code: int):
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
        assert AlaskaAdapter.__abstractmethods__ == frozenset()
        adapter = AlaskaAdapter()
        assert adapter.state_code == "AK"
        assert adapter.state_name == "Alaska"


class TestCitationNormalization:
    def test_zero_pads_title_chapter_section(self) -> None:
        assert AlaskaAdapter._canonical_citation("1.10.7") == "01.10.007"

    def test_preserves_already_canonical(self) -> None:
        assert AlaskaAdapter._canonical_citation("11.41.100") == "11.41.100"

    def test_zero_pads_partial(self) -> None:
        assert AlaskaAdapter._canonical_citation("1.5.10") == "01.05.010"

    def test_rejects_lettered(self) -> None:
        assert AlaskaAdapter._canonical_citation("01.10.070a") is None

    def test_rejects_decimal_extra_component(self) -> None:
        assert AlaskaAdapter._canonical_citation("1.2.3.4") is None

    def test_rejects_alpha(self) -> None:
        assert AlaskaAdapter._canonical_citation("abc") is None

    def test_canonical_chapter(self) -> None:
        assert AlaskaAdapter._canonical_chapter("1.5") == "01.05"
        assert AlaskaAdapter._canonical_chapter("11.41") == "11.41"
        assert AlaskaAdapter._canonical_chapter("abc") is None


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = AlaskaAdapter()

    def test_title_ref_url(self) -> None:
        ref = TitleRef(state_code="AK", identifier="11")
        assert self.adapter.build_url(ref) == TOC_URL("11")

    def test_chapter_ref_url(self) -> None:
        ref = ChapterRef(
            title=TitleRef(state_code="AK", identifier="11"), identifier="11.41"
        )
        assert self.adapter.build_url(ref) == TOC_URL("11.41")

    def test_chapter_ref_normalized(self) -> None:
        ref = ChapterRef(
            title=TitleRef(state_code="AK", identifier="1"), identifier="1.5"
        )
        assert self.adapter.build_url(ref) == TOC_URL("01.05")

    def test_section_ref_url(self) -> None:
        assert self.adapter.build_url(_make_ref("11.41.100")) == SEC_URL(
            "11.41.100"
        )

    def test_section_ref_normalized(self) -> None:
        assert self.adapter.build_url(_make_ref("1.10.7")) == SEC_URL("01.10.007")

    def test_invalid_title_raises(self) -> None:
        with pytest.raises(RefNotFoundError):
            self.adapter.build_url(TitleRef(state_code="AK", identifier="abc"))

    def test_invalid_chapter_raises(self) -> None:
        with pytest.raises(RefNotFoundError):
            self.adapter.build_url(
                ChapterRef(
                    title=TitleRef(state_code="AK", identifier="1"),
                    identifier="x.y",
                )
            )

    def test_invalid_citation_raises(self) -> None:
        with pytest.raises(RefNotFoundError):
            self.adapter.build_url(_make_ref("abc"))

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestListTitles:
    def setup_method(self) -> None:
        self.adapter = AlaskaAdapter()

    def test_returns_all_47_titles(self) -> None:
        with mock_urlopen_serving_bytes({INDEX_URL: INDEX_HTML}):
            titles = self.adapter.list_titles()

        assert len(titles) == 47
        assert titles[0].identifier == "1"
        assert titles[0].name == "GENERAL PROVISIONS"
        assert all(t.level == HierarchyLevel.TITLE for t in titles)
        assert all(isinstance(t.ref, TitleRef) for t in titles)

    def test_network_failure_raises(self) -> None:
        with _serve_error(INDEX_URL, 500):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()

    def test_empty_result_raises(self) -> None:
        with mock_urlopen_serving_bytes({INDEX_URL: b"<html></html>"}):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_titles()


class TestListChapters:
    def setup_method(self) -> None:
        self.adapter = AlaskaAdapter()

    def test_returns_chapters_from_title_toc(self) -> None:
        title = TitleRef(state_code="AK", identifier="11")
        with mock_urlopen_serving_bytes({TOC_URL("11"): TOC_TITLE_HTML}):
            chapters = self.adapter.list_chapters(title)

        assert len(chapters) == 30
        assert chapters[0].identifier == "11.05"
        assert chapters[0].name == "PUNISHMENT"
        assert "11.41" in [c.identifier for c in chapters]
        assert all(c.level == HierarchyLevel.CHAPTER for c in chapters)

    def test_invalid_title_raises(self) -> None:
        with pytest.raises(RefNotFoundError):
            self.adapter.list_chapters(TitleRef(state_code="AK", identifier="xx"))

    def test_network_failure_raises(self) -> None:
        with _serve_error(TOC_URL("11"), 500):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_chapters(TitleRef(state_code="AK", identifier="11"))

    def test_empty_result_raises(self) -> None:
        with mock_urlopen_serving_bytes({TOC_URL("11"): b"<html></html>"}):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_chapters(TitleRef(state_code="AK", identifier="11"))


class TestListSections:
    def setup_method(self) -> None:
        self.adapter = AlaskaAdapter()

    def test_returns_sections_from_chapter_toc(self) -> None:
        chapter = ChapterRef(
            title=TitleRef(state_code="AK", identifier="1"), identifier="01.10"
        )
        with mock_urlopen_serving_bytes({TOC_URL("01.10"): TOC_CHAPTER_HTML}):
            sections = self.adapter.list_sections(chapter)

        identifiers = [s.identifier for s in sections]
        assert "01.10.010" in identifiers
        assert "01.10.070" in identifiers
        assert len(sections) == 13
        assert all(s.level == HierarchyLevel.SECTION for s in sections)

    def test_invalid_chapter_raises(self) -> None:
        chapter = ChapterRef(
            title=TitleRef(state_code="AK", identifier="1"), identifier="xx"
        )
        with pytest.raises(RefNotFoundError):
            self.adapter.list_sections(chapter)

    def test_network_failure_raises(self) -> None:
        chapter = ChapterRef(
            title=TitleRef(state_code="AK", identifier="1"), identifier="01.10"
        )
        with _serve_error(TOC_URL("01.10"), 500):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.list_sections(chapter)


class TestRetrieveSection:
    def setup_method(self) -> None:
        self.adapter = AlaskaAdapter()

    def test_full_retrieval_normal_section(self) -> None:
        with mock_urlopen_serving_bytes({SEC_URL("01.10.070"): SEC_0110070}):
            section = self.adapter.retrieve_section(_make_ref("01.10.070"))

        assert section.ref.state_code == "AK"
        assert section.ref.identifier == "01.10.070"
        assert section.citation.raw == "AS 01.10.070"
        assert section.heading == "Time statutes become law and take effect."
        assert section.text.startswith(
            "(a) All bills passed by the legislature become law"
        )
        assert section.status.value == "unknown"
        assert section.source_url == SEC_URL("01.10.070")
        assert section.retrieved_at is not None

    def test_citation_normalized_retrieval(self) -> None:
        # '1.10.70' must be canonicalized to '01.10.070' before the fetch.
        with mock_urlopen_serving_bytes({SEC_URL("01.10.070"): SEC_0110070}):
            section = self.adapter.retrieve_section(_make_ref("1.10.70"))

        assert section.ref.identifier == "01.10.070"
        assert section.citation.raw == "AS 01.10.070"

    def test_renumbered_stub(self) -> None:
        with mock_urlopen_serving_bytes({SEC_URL("11.05.070"): SEC_RENUMBERED}):
            section = self.adapter.retrieve_section(_make_ref("11.05.070"))

        assert section.citation.raw == "AS 11.05.070"
        assert section.heading is not None
        assert "Renumbered as" in section.heading
        assert section.text == ""
        assert section.amendment_notes is not None

    def test_repealed_with_note_preserves_text(self) -> None:
        with mock_urlopen_serving_bytes({SEC_URL("18.65.010"): SEC_REPEALED}):
            section = self.adapter.retrieve_section(_make_ref("18.65.010"))

        assert section.citation.raw == "AS 18.65.010"
        assert section.text  # repealed-with-note sections render content
        assert "Repealed" not in section.text  # note moved to amendment_notes
        assert "Repealed, § 3 ch 6 SLA 1978." in section.amendment_notes
        assert section.status.value == "unknown"

    def test_invalid_citation_format_raises(self) -> None:
        with pytest.raises(RefNotFoundError):
            self.adapter.retrieve_section(_make_ref("abc"))

    def test_lettered_citation_rejected(self) -> None:
        with pytest.raises(RefNotFoundError):
            self.adapter.retrieve_section(_make_ref("01.10.070a"))

    def test_http_404_raises_ref_not_found(self) -> None:
        with _serve_error(SEC_URL("99.99.999"), 404):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(_make_ref("99.99.999"))

    def test_http_400_raises_adapter_unavailable(self) -> None:
        # Only 404 maps to RefNotFoundError; a 400 is a server-side error.
        with _serve_error(SEC_URL("01.10.070"), 400):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(_make_ref("01.10.070"))

    def test_http_500_raises_adapter_unavailable(self) -> None:
        with _serve_error(SEC_URL("01.10.070"), 500):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(_make_ref("01.10.070"))

    def test_silent_fallback_wrong_citation_raises(self) -> None:
        # Serve the 01.10.070 page at the 01.10.071 URL: the declared
        # citation must not be silently accepted.
        with mock_urlopen_serving_bytes({SEC_URL("01.10.071"): SEC_0110070}):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(_make_ref("01.10.071"))

    def test_ref_chapter_mismatch_raises(self) -> None:
        with pytest.raises(RefMismatchError):
            self.adapter.retrieve_section(
                SectionRef(
                    chapter=ChapterRef(
                        title=TitleRef(state_code="AK", identifier="1"),
                        identifier="01.20",
                    ),
                    identifier="01.10.070",
                )
            )

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        with _serve_error(SEC_URL("01.10.070"), 500):
            with pytest.raises(AdapterUnavailableError):
                self.adapter.retrieve_section(_make_ref("01.10.070"))

    def test_no_statute_content_raises_ref_not_found(self) -> None:
        with mock_urlopen_serving_bytes({SEC_URL("01.10.070"): b"<html></html>"}):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(_make_ref("01.10.070"))

    def test_missing_section_head_raises_ref_not_found(self) -> None:
        malformed = (
            '<p><div class="statute"><b><a name="01.10.070"></a>'
            "No Sec. here</b>body</div>"
        )
        with mock_urlopen_serving_bytes(
            {SEC_URL("01.10.070"): malformed.encode("latin-1")}
        ):
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(_make_ref("01.10.070"))

    def test_malformed_body_raises_normalization_error(self) -> None:
        # Head declares the section but the body is empty (not a stub).
        malformed = (
            '<p><div class="statute"><b><a name="01.10.070"></a>'
            "Sec. 01.10.070. Time statutes become law and take effect.</b>"
            "</div>"
        )
        with mock_urlopen_serving_bytes(
            {SEC_URL("01.10.070"): malformed.encode("latin-1")}
        ):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(_make_ref("01.10.070"))


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = AlaskaAdapter()

    def test_normalize_success(self) -> None:
        ref = _make_ref("01.10.070")
        parsed = ParsedDocument(
            raw_citation="AS 01.10.070",
            heading="Time statutes become law and take effect.",
            text="(a) Body.",
            source_url=SEC_URL("01.10.070"),
        )
        section = self.adapter.normalize(parsed, ref)

        assert section.ref is ref
        assert section.citation.raw == "AS 01.10.070"
        assert section.status.value == "unknown"

    def test_state_mismatch_raises_normalization_error(self) -> None:
        ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="WA", identifier="49"),
                identifier="60",
            ),
            identifier="49.60.010",
        )
        parsed = ParsedDocument(raw_citation="AS 01.10.070", text="x")
        with pytest.raises(NormalizationError):
            self.adapter.normalize(parsed, ref)

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        ref = _make_ref("01.10.071")
        parsed = ParsedDocument(raw_citation="AS 01.10.070", text="x")
        with pytest.raises(RefMismatchError):
            self.adapter.normalize(parsed, ref)


class TestHierarchyMapping:
    def test_title_chapter_section_chain_descends(self) -> None:
        title = TitleRef(state_code="AK", identifier="11")
        chapter = ChapterRef(title=title, identifier="11.41")
        section = SectionRef(chapter=chapter, identifier="11.41.100")

        assert chapter.state_code == "AK"
        assert section.state_code == "AK"
        assert chapter.title is title
        assert section.chapter is chapter


class TestInputValidation:
    def setup_method(self) -> None:
        self.adapter = AlaskaAdapter()

    def test_injection_inputs_rejected(self) -> None:
        for bad in [
            "../../etc/passwd",
            "https://evil.example",
            "1;rm -rf",
            "abc",
            "01.10.070;x",
            "1.2.3.4",
        ]:
            with pytest.raises(RefNotFoundError):
                self.adapter.retrieve_section(_make_ref(bad))

    def test_host_remains_constant(self) -> None:
        url = self.adapter.build_url(_make_ref("11.41.100"))
        assert url.startswith("https://www.akleg.gov/basis/statutes.asp?")
        assert "objectName" not in url  # no objectName-style injection surface