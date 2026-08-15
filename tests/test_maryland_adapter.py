"""Tests for MarylandAdapter.

Maryland is a server-rendered HTML/JSON source (the official Maryland
General Assembly publication of the Annotated Code of Maryland at
mgaleg.maryland.gov). Three structural levels map onto the framework model,
with Maryland's article/subtitle/section structure flattened to
Title -> Chapter -> Section:

* ``TitleRef.identifier`` is the article code (e.g. ``"gtr"`` for
  Transportation); ``TitleRef.name`` is the article display name (e.g.
  ``"Transportation"``).
* ``ChapterRef.identifier`` is the subtitle number -- the leading segment
  of each section id (e.g. ``"1"`` in ``1-101``, ``"18.5"`` in
  ``18.5-101``). Subtitle groupings are derived from the article's flat
  ``GetSections`` listing, the same flattening pattern Arizona uses.
* ``SectionRef.identifier`` is the full section citation (e.g. ``"1-101"``,
  ``"2-103.1"``).

Discovery uses the ``GetSections`` JSON API
(``/mgawebsite/api/Laws/GetSections?articleCode={code}&enactments=false``),
which returns one record per section. Section retrieval uses the section
page (``/mgawebsite/Laws/StatuteText?article={code}&section={sec}``),
whose ``<div id="StatuteText">`` holds an embedded ``<html>`` fragment
with the section heading (``&sect;1&ndash;101.``) and body.

Section-retrieval and section-discovery tests exercise the adapter's real
fetch -> parse path against **REAL captured Maryland HTML/JSON**: verbatim
slices of the official mgaleg.maryland.gov pages, captured live on Aug 15,
2026 and stored under ``tests/fixtures/md_*``:

* ``md_statutes.html`` -- the statute browser page (the ``#Articles``
  select lists all 36 Annotated Code articles).
* ``md_sections_gtr.json`` -- the Transportation article's ``GetSections``
  response (1744 sections across 28 subtitles).
* ``md_section_1-101.html`` -- section 1-101 of Transportation (a long
  definitional body).
* ``md_section_2-103.1.html`` -- dotted section 2-103.1 (a long body).
* ``md_section_404.html`` -- a section that does not exist (the verified
  ``File Not Found`` page, HTTP 200).

All tests are fully offline: the real network boundary
(``urllib.request.urlopen`` as imported by the shared ``_fetch`` helper) is
mocked, never adapter internals.
"""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

from _mock_network import mock_urlopen, mock_urlopen_error, mock_urlopen_serving

from state_statutes_mcp.adapters.maryland.adapter import MarylandAdapter
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

# --- REAL fixtures: verbatim slices of the official Maryland General
# --- Assembly pages captured live on Aug 15, 2026. NOT synthetic.
FIXTURES = Path(__file__).parent / "fixtures"

REAL_STATUTES_HTML = (FIXTURES / "md_statutes.html").read_text(
    encoding="utf-8"
)
REAL_SECTIONS_GTR = (FIXTURES / "md_sections_gtr.json").read_text(
    encoding="utf-8"
)
REAL_SEC_1_101_HTML = (FIXTURES / "md_section_1-101.html").read_text(
    encoding="utf-8"
)
REAL_SEC_2_103_1_HTML = (FIXTURES / "md_section_2-103.1.html").read_text(
    encoding="utf-8"
)
REAL_SEC_404_HTML = (FIXTURES / "md_section_404.html").read_text(
    encoding="utf-8"
)

BASE = "https://mgaleg.maryland.gov"

STATUTES_URL = f"{BASE}/mgawebsite/Laws/Statutes"
SECTIONS_GTR_URL = (
    f"{BASE}/mgawebsite/api/Laws/GetSections"
    "?articleCode=gtr&enactments=false"
)
SECTIONS_GAG_URL = (
    f"{BASE}/mgawebsite/api/Laws/GetSections"
    "?articleCode=gag&enactments=false"
)
SEC_1_101_URL = (
    f"{BASE}/mgawebsite/Laws/StatuteText?article=gtr&section=1-101"
)
SEC_2_103_1_URL = (
    f"{BASE}/mgawebsite/Laws/StatuteText?article=gtr&section=2-103.1"
)
SEC_1_102_URL = (
    f"{BASE}/mgawebsite/Laws/StatuteText?article=gtr&section=1-102"
)


def _http_error(url: str, code: int = 404) -> urllib.error.HTTPError:
    """Build a real ``urllib.error.HTTPError`` the shared fetch helper will
    wrap into ``AdapterUnavailableError`` with ``__cause__`` set to it."""
    return urllib.error.HTTPError(url, code, "Not Found", {}, io.BytesIO(b""))


def _title_ref() -> TitleRef:
    return TitleRef(state_code="MD", identifier="gtr", name="Transportation")


def _chapter_ref() -> ChapterRef:
    return ChapterRef(title=_title_ref(), identifier="1")


def _chapter_18_5_ref() -> ChapterRef:
    return ChapterRef(title=_title_ref(), identifier="18.5")


def _make_ref(section: str) -> SectionRef:
    return SectionRef(chapter=_chapter_ref(), identifier=section)


def _sections_json(article_code: str) -> str:
    """Load the gtr sections fixture, rewritten for ``article_code`` (the
    JSON itself contains no article reference, so the same body serves any
    article in tests)."""
    del article_code
    return REAL_SECTIONS_GTR


def _serve_all() -> dict[str, str]:
    return {
        STATUTES_URL: REAL_STATUTES_HTML,
        SECTIONS_GTR_URL: REAL_SECTIONS_GTR,
        SEC_1_101_URL: REAL_SEC_1_101_HTML,
        SEC_2_103_1_URL: REAL_SEC_2_103_1_HTML,
    }


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert MarylandAdapter.__abstractmethods__ == frozenset()
        adapter = MarylandAdapter()
        assert adapter.state_code == "MD"
        assert adapter.state_name == "Maryland"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = MarylandAdapter()

    def test_title_ref_url_is_sections_api(self) -> None:
        # The article itself has no page; its full section list is the
        # closest real resource (mirrors Arizona's title detail page).
        assert (
            self.adapter.build_url(_title_ref())
            == f"{BASE}/mgawebsite/api/Laws/GetSections"
            "?articleCode=gtr&enactments=false"
        )

    def test_chapter_ref_url_is_sections_api(self) -> None:
        # Subtitle groupings carry no page of their own.
        assert (
            self.adapter.build_url(_chapter_ref())
            == f"{BASE}/mgawebsite/api/Laws/GetSections"
            "?articleCode=gtr&enactments=false"
        )

    def test_section_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_make_ref("1-101"))
            == f"{BASE}/mgawebsite/Laws/StatuteText?article=gtr&section=1-101"
        )

    def test_dotted_section_ref_url(self) -> None:
        assert (
            self.adapter.build_url(_make_ref("2-103.1"))
            == f"{BASE}/mgawebsite/Laws/StatuteText?article=gtr&section=2-103.1"
        )

    def test_unsupported_ref_raises(self) -> None:
        with pytest.raises(UnsupportedRefError, match="does not support"):
            self.adapter.build_url(object())  # type: ignore[arg-type]


class TestDecodeSectionNumber:
    def test_plain_number(self) -> None:
        assert MarylandAdapter._decode_section_number("1-101") == "1-101"

    def test_en_dash_number(self) -> None:
        # The site renders the dash as &ndash; (U+2013 after decoding).
        assert MarylandAdapter._decode_section_number("1\u2013101") == "1-101"

    def test_dotted_number(self) -> None:
        assert MarylandAdapter._decode_section_number("2-103.1") == "2-103.1"


class TestListTitles:
    def test_returns_annotated_code_articles(self) -> None:
        adapter = MarylandAdapter()
        with mock_urlopen_serving({STATUTES_URL: REAL_STATUTES_HTML}):
            titles = adapter.list_titles()

        assert len(titles) == 36
        first = titles[0]
        assert first.level == HierarchyLevel.TITLE
        assert first.identifier == "gag"
        assert first.name == "Agriculture"
        assert first.ref.state_code == "MD"
        identifiers = [node.identifier for node in titles]
        assert "gtr" in identifiers
        # Non-Annotated-Code options (Constitution c*, local codes l*,
        # charters) are excluded.
        assert not any(identifier.startswith("l") for identifier in identifiers)
        assert not any(identifier.startswith("c") for identifier in identifiers)
        assert "municc" not in identifiers
        assert "acts" not in identifiers
        assert "baltc" not in identifiers
        assert len(set(identifiers)) == 36

    def test_articles_select_missing_raises_adapter_unavailable(self) -> None:
        adapter = MarylandAdapter()
        with mock_urlopen("<html><body>no select here</body></html>"):
            with pytest.raises(AdapterUnavailableError, match="#Articles select"):
                adapter.list_titles()

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = MarylandAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_titles()


class TestListChapters:
    def test_returns_subtitle_groupings(self) -> None:
        adapter = MarylandAdapter()
        with mock_urlopen_serving({SECTIONS_GTR_URL: REAL_SECTIONS_GTR}):
            chapters = adapter.list_chapters(_title_ref())

        assert len(chapters) == 28
        first = chapters[0]
        assert first.level == HierarchyLevel.CHAPTER
        assert first.identifier == "1"
        assert first.ref.title.identifier == "gtr"
        assert first.ref.state_code == "MD"
        identifiers = [node.identifier for node in chapters]
        assert "18.5" in identifiers
        assert len(set(identifiers)) == 28

    def test_invalid_article_maps_to_ref_not_found(self) -> None:
        adapter = MarylandAdapter()
        bad = TitleRef(state_code="MD", identifier="zzz")
        bad_url = (
            f"{BASE}/mgawebsite/api/Laws/GetSections"
            "?articleCode=zzz&enactments=false"
        )
        not_found_body = json.dumps(
            {
                "message": "No HTTP resource was found that matches the request "
                "URI 'https://mgaleg.maryland.gov/mgawebsite/api/Laws/"
                "GetSections?articleCode=zzz'."
            }
        )
        with mock_urlopen_serving({bad_url: not_found_body}):
            with pytest.raises(RefNotFoundError, match="resolve article"):
                adapter.list_chapters(bad)

    def test_non_list_response_raises_adapter_unavailable(self) -> None:
        adapter = MarylandAdapter()
        with mock_urlopen_serving({SECTIONS_GTR_URL: '{"message": "boom"}'}):
            with pytest.raises(AdapterUnavailableError, match="not a JSON array"):
                adapter.list_chapters(_title_ref())

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = MarylandAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_chapters(_title_ref())


class TestListSections:
    def test_returns_sections_for_chapter(self) -> None:
        adapter = MarylandAdapter()
        with mock_urlopen_serving({SECTIONS_GTR_URL: REAL_SECTIONS_GTR}):
            sections = adapter.list_sections(_chapter_ref())

        identifiers = [node.identifier for node in sections]
        assert identifiers == ["1-101", "1-102", "1-103"]
        first = sections[0]
        assert first.level == HierarchyLevel.SECTION
        assert first.name == "1-101"
        assert first.ref.chapter.identifier == "1"
        assert first.ref.state_code == "MD"

    def test_dotted_subtitle_chapter(self) -> None:
        adapter = MarylandAdapter()
        with mock_urlopen_serving({SECTIONS_GTR_URL: REAL_SECTIONS_GTR}):
            sections = adapter.list_sections(_chapter_18_5_ref())

        identifiers = [node.identifier for node in sections]
        assert identifiers[0] == "18.5-101"
        assert len(identifiers) == 10

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = MarylandAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.list_sections(_chapter_ref())


class TestNormalize:
    def setup_method(self) -> None:
        self.adapter = MarylandAdapter()

    def test_happy_path(self) -> None:
        parsed = ParsedDocument(
            raw_citation="Md. Code, Transportation § 1-101",
            heading=None,
            text='(a) In this article the following words have the meanings indicated.',
            amendment_notes=None,
            source_url=SEC_1_101_URL,
            retrieved_at=None,
        )
        section = self.adapter.normalize(parsed, _make_ref("1-101"))

        assert section.citation.raw == "Md. Code, Transportation § 1-101"
        assert section.citation.state_code == "MD"
        assert section.heading is None
        assert section.text.startswith("(a) In this article")
        assert section.amendment_notes is None
        assert section.status.value == "unknown"

    def test_wrong_state_raises_normalization_error(self) -> None:
        parsed = ParsedDocument(
            raw_citation="Md. Code, Transportation § 1-101",
            heading=None,
            text="body",
            amendment_notes=None,
            source_url=None,
            retrieved_at=None,
        )
        other_ref = SectionRef(
            chapter=ChapterRef(
                title=TitleRef(state_code="DE", identifier="gtr"), identifier="1"
            ),
            identifier="1-101",
        )
        with pytest.raises(NormalizationError, match="expected 'MD'"):
            self.adapter.normalize(parsed, other_ref)

    def test_ref_mismatch_raises(self) -> None:
        parsed = ParsedDocument(
            raw_citation="Md. Code, Transportation § 1-102",
            heading=None,
            text="body",
            amendment_notes=None,
            source_url=None,
            retrieved_at=None,
        )
        with pytest.raises(RefMismatchError, match="does not match"):
            self.adapter.normalize(parsed, _make_ref("1-101"))


class TestRetrieveSection:
    def test_simple_section(self) -> None:
        adapter = MarylandAdapter()
        with mock_urlopen_serving(_serve_all()):
            section = adapter.retrieve_section(_make_ref("1-101"))

        assert section.ref.identifier == "1-101"
        assert section.citation.raw == "Md. Code, Transportation § 1-101"
        assert section.heading is None
        assert section.text.startswith(
            "(a) In this article the following words have the meanings indicated."
        )
        assert '"(a)"' not in section.text
        assert "Consolidated Transportation Program" in section.text
        assert section.amendment_notes is None
        assert section.source_url == SEC_1_101_URL
        assert section.status.value == "unknown"
        assert section.retrieved_at is not None

    def test_dotted_section(self) -> None:
        adapter = MarylandAdapter()
        ref = SectionRef(
            chapter=ChapterRef(title=_title_ref(), identifier="2"),
            identifier="2-103.1",
        )
        with mock_urlopen_serving(_serve_all()):
            section = adapter.retrieve_section(ref)

        assert section.ref.identifier == "2-103.1"
        assert section.citation.raw == "Md. Code, Transportation § 2-103.1"
        assert section.text.startswith(
            "(a) (1) In this section the following words have the meanings indicated."
        )
        assert "Capital project" in section.text
        assert section.source_url == SEC_2_103_1_URL

    def test_file_not_found_maps_to_ref_not_found(self) -> None:
        adapter = MarylandAdapter()
        with mock_urlopen_serving({SEC_1_102_URL: REAL_SEC_404_HTML}):
            with pytest.raises(RefNotFoundError, match="File Not Found"):
                adapter.retrieve_section(_make_ref("1-102"))

    def test_network_failure_raises_adapter_unavailable(self) -> None:
        adapter = MarylandAdapter()
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                adapter.retrieve_section(_make_ref("1-101"))

    def test_citation_number_mismatch_raises(self) -> None:
        adapter = MarylandAdapter()
        # A section whose page names a different number than requested.
        wrong_ref = _make_ref("1-102")
        with mock_urlopen_serving({SEC_1_102_URL: REAL_SEC_1_101_HTML}):
            with pytest.raises(RefMismatchError, match="does not match the citation"):
                adapter.retrieve_section(wrong_ref)

    def test_missing_statute_text_div_raises_normalization_error(self) -> None:
        adapter = MarylandAdapter()
        with mock_urlopen("<html><body>no statute text here</body></html>"):
            with pytest.raises(NormalizationError, match="no StatuteText div"):
                adapter.retrieve_section(_make_ref("1-101"))

    def test_missing_heading_raises_normalization_error(self) -> None:
        adapter = MarylandAdapter()
        malformed = (
            '<div id="StatuteText">\n<html><div>Article - Transportation</div>'
            '<br><br>no section heading here</html>'
        )
        with mock_urlopen(malformed):
            with pytest.raises(NormalizationError, match="no section heading"):
                adapter.retrieve_section(_make_ref("1-101"))

    def test_empty_body_raises_normalization_error(self) -> None:
        adapter = MarylandAdapter()
        malformed = (
            '<div id="StatuteText">\n<html><div>Article - Transportation</div>'
            "<br><br>&sect;1&ndash;101.<br><br></html>"
        )
        with mock_urlopen(malformed):
            with pytest.raises(NormalizationError, match="body text was empty"):
                adapter.retrieve_section(_make_ref("1-101"))
