"""Tests for the pure MCP tool layer (``server_tools``).

These exercise the adapter-facing logic behind the MCP tools with the
real adapters but with the network boundary mocked, so nothing touches
the network. The MCP SDK is deliberately not involved here — the whole
point of ``server_tools`` is to be testable with pydantic + pytest.

The synthetic HTML below is hand-written to match the markup structure
the Washington adapter documents; it is NOT a saved real government
fixture.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pytest

from _mock_network import (
    PATCH_TARGET,
    mock_urlopen,
    mock_urlopen_error,
    mock_urlopen_graphql,
    mock_urlopen_serving,
    mock_urlopen_serving_bytes,
)

from state_statutes_mcp.adapters.alabama.adapter import AlabamaAdapter
from state_statutes_mcp.adapters.arizona.adapter import ArizonaAdapter
from state_statutes_mcp.adapters.california.adapter import CaliforniaAdapter
from state_statutes_mcp.adapters.colorado.adapter import ColoradoAdapter
from state_statutes_mcp.adapters.connecticut.adapter import ConnecticutAdapter
from state_statutes_mcp.adapters.delaware.adapter import DelawareAdapter
from state_statutes_mcp.adapters.florida.adapter import FloridaAdapter
from state_statutes_mcp.adapters.hawaii.adapter import HawaiiAdapter
from state_statutes_mcp.adapters.idaho.adapter import IdahoAdapter
from state_statutes_mcp.adapters.illinois.adapter import IllinoisAdapter
from state_statutes_mcp.adapters.iowa.adapter import IowaAdapter
from state_statutes_mcp.adapters.kansas.adapter import KansasAdapter
from state_statutes_mcp.adapters.kentucky.adapter import KentuckyAdapter
from state_statutes_mcp.adapters.maine.adapter import MaineAdapter
from state_statutes_mcp.adapters.maryland.adapter import MarylandAdapter
from state_statutes_mcp.adapters.massachusetts.adapter import MassachusettsAdapter
from state_statutes_mcp.adapters.michigan.adapter import MichiganAdapter
from state_statutes_mcp.adapters.minnesota.adapter import MinnesotaAdapter
from state_statutes_mcp.adapters.missouri.adapter import MissouriAdapter
from state_statutes_mcp.adapters.montana.adapter import MontanaAdapter
from state_statutes_mcp.adapters.nebraska.adapter import NebraskaAdapter
from state_statutes_mcp.adapters.nevada.adapter import NevadaAdapter
from state_statutes_mcp.adapters.new_hampshire.adapter import NewHampshireAdapter
from state_statutes_mcp.adapters.new_mexico.adapter import NewMexicoAdapter
from state_statutes_mcp.adapters.north_carolina.adapter import NorthCarolinaAdapter
from state_statutes_mcp.adapters.north_dakota.adapter import NorthDakotaAdapter
from state_statutes_mcp.adapters.ohio.adapter import OhioAdapter
from state_statutes_mcp.adapters.oklahoma.adapter import OklahomaAdapter
from state_statutes_mcp.adapters.oregon.adapter import OregonAdapter
from state_statutes_mcp.adapters.rhode_island.adapter import RhodeIslandAdapter
from state_statutes_mcp.adapters.south_carolina.adapter import SouthCarolinaAdapter
from state_statutes_mcp.adapters.south_dakota.adapter import SouthDakotaAdapter
from state_statutes_mcp.adapters.texas.adapter import TexasAdapter
from state_statutes_mcp.adapters.vermont.adapter import VermontAdapter
from state_statutes_mcp.adapters.virginia.adapter import VirginiaAdapter
from state_statutes_mcp.adapters.washington.adapter import WashingtonAdapter
from state_statutes_mcp.adapters.west_virginia.adapter import WestVirginiaAdapter
from state_statutes_mcp.adapters.wisconsin.adapter import WisconsinAdapter
from state_statutes_mcp.adapters.wyoming.adapter import WyomingAdapter
from state_statutes_mcp.core.exceptions import AdapterUnavailableError, RefMismatchError
from state_statutes_mcp.core.registry import AdapterRegistry
from state_statutes_mcp.server_tools import (
    get_section,
    list_chapters,
    list_sections,
    list_states,
    list_titles,
)

# --- SYNTHETIC mock pages -- NOT real government fixtures. ---

SYNTHETIC_TITLES_HTML = """
<html><body><table>
<tr><td><a href="default.aspx?Cite=49">Title 49</a></td><td>LABOR REGULATIONS</td></tr>
<tr><td><a href="default.aspx?Cite=9A">Title 9A</a></td><td>CRIMINAL LAW</td></tr>
</table></body></html>
"""

SYNTHETIC_CHAPTERS_HTML = """
<html><body><table>
<tr><td><a href="default.aspx?cite=49.60">49.60</a></td><td>Apprenticeship.</td></tr>
<tr><td><a href="default.aspx?cite=49.61">49.61</a></td><td>Employment counseling.</td></tr>
</table></body></html>
"""

SYNTHETIC_SECTIONS_HTML = """
<html><body><table>
<tr><td><a href="default.aspx?cite=49.60.010">HTML</a></td><td>&nbsp;</td></tr>
<tr><td><a href="default.aspx?cite=49.60.010">49.60.010</a></td><td>Purpose.</td></tr>
<tr><td><a href="default.aspx?cite=49.60.2235">49.60.2235</a></td><td>Definitions.</td></tr>
<tr><td><a href="default.aspx?cite=90.16.010">90.16.010</a></td><td>Water.</td></tr>
</table></body></html>
"""

SYNTHETIC_SECTION_HTML = """
<html><body>
<h1><!-- field: Citations -->RCW 49.60.010<!-- field: --></h1>
<h2><!-- field: CaptionsTitles -->Purpose of chapter.<!-- field: --></h2>
<div style="text-indent:0.5in;">It is the policy of the state of Washington to protect the health of all residents.</div>
<div style="text-indent:0.5in;">The legislature finds that this chapter furthers that policy.</div>
<div style="margin-top:15pt;margin-bottom:0pt;">[2006 c 66 &sect; 1.]</div>
<h2 class="text-warning">Legislative questions or comments</h2>
</body></html>
"""

# SYNTHETIC mock payload -- NOT a real government fixture. Matches the
# verified Code of Virginia section-detail shape documented in
# VirginiaAdapter's module docstring.
SYNTHETIC_VA_SECTION_JSON = {
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
            ),
        }
    ],
}


# SYNTHETIC mock pages -- NOT real government fixtures. Matches the verified
# Delaware structure documented in DelawareAdapter's module docstring: a
# subchapter-based chapter page linking sc01, and a subchapter page holding
# section 501 as a <div class="Section"> block.
SYNTHETIC_DE_CHAPTER_HTML = """
<html><body>
  <div class="title-links"><a href="../../title11/c005/sc01/index.html">
                        Subchapter I. Inchoate Crimes</a></div>
</body></html>
"""

SYNTHETIC_DE_SECTION_HTML = """
<html><body>
  <div id="CodeBody">
    <div class="Section">
      <div class="SectionHead" id="501">
          \u00a7
        501. Criminal solicitation in the third degree; class A misdemeanor.</div>
      <p class="subsection">A person is guilty of criminal solicitation in the third degree when, intending that another person engage in conduct constituting a misdemeanor, the person solicits or otherwise attempts to cause the other person to engage in such conduct.</p>
      <p class="subsection">Criminal solicitation in the third degree is a class A misdemeanor.</p>11 Del. C. 1953,
                \u00a7
               501;
      <a href="https://legis.delaware.gov/SessionLaws?volume=58&amp;chapter=497">58 Del. Laws, c. 497,
                \u00a7
               1</a>;
      </div><br>
  </div>
</body></html>
"""


class _FakeResponse(io.BytesIO):
    """A raw-bytes-backed response that behaves as a context manager,
    matching how ``urllib.request.urlopen`` responses are used."""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


@contextmanager
def _serve_bytes(url_to_bytes: dict[str, bytes]):
    """Serve specific URLs from ``url_to_bytes`` (raw bytes); fail on any
    unexpected URL.

    Oregon pages are Windows-1252, so the mock serves raw bytes rather
    than the UTF-8-encoding helper. ``urlopen`` is patched on the shared
    ``urllib.request`` module object, so an adapter's own
    ``urllib.request.urlopen`` call is intercepted too.
    """

    def _target(url):
        return url.full_url if isinstance(url, urllib.request.Request) else url

    def fake_urlopen(url, timeout=None):
        target = _target(url)
        if target not in url_to_bytes:
            raise AssertionError(f"Unexpected URL fetched in test: {target!r}")
        return _FakeResponse(url_to_bytes[target])

    with mock.patch(PATCH_TARGET, side_effect=fake_urlopen):
        yield


def _registry() -> AdapterRegistry:
    """Build the same registry the real server would use."""
    registry = AdapterRegistry()
    registry.register(AlabamaAdapter())
    registry.register(WashingtonAdapter())
    registry.register(TexasAdapter())
    registry.register(IllinoisAdapter())
    registry.register(VirginiaAdapter())
    registry.register(DelawareAdapter())
    registry.register(FloridaAdapter())
    registry.register(ArizonaAdapter())
    registry.register(CaliforniaAdapter())
    registry.register(ColoradoAdapter())
    registry.register(ConnecticutAdapter())
    registry.register(HawaiiAdapter())
    registry.register(IdahoAdapter())
    registry.register(KansasAdapter())
    registry.register(KentuckyAdapter())
    registry.register(IowaAdapter())
    registry.register(MaineAdapter())
    registry.register(MarylandAdapter())
    registry.register(MassachusettsAdapter())
    registry.register(MichiganAdapter())
    registry.register(MinnesotaAdapter())
    registry.register(MissouriAdapter())
    registry.register(MontanaAdapter())
    registry.register(NebraskaAdapter())
    registry.register(NevadaAdapter())
    registry.register(NewHampshireAdapter())
    registry.register(NewMexicoAdapter())
    registry.register(NorthCarolinaAdapter())
    registry.register(NorthDakotaAdapter())
    registry.register(OhioAdapter())
    registry.register(OklahomaAdapter())
    registry.register(OregonAdapter())
    registry.register(RhodeIslandAdapter())
    registry.register(SouthCarolinaAdapter())
    registry.register(SouthDakotaAdapter())
    registry.register(VermontAdapter())
    registry.register(WestVirginiaAdapter())
    registry.register(WisconsinAdapter())
    registry.register(WyomingAdapter())
    return registry


class TestListStates:
    def test_returns_all_registered_states(self) -> None:
        result = list_states(_registry())

        assert result == [
            {"state_code": "AL", "state_name": "Alabama"},
            {"state_code": "AZ", "state_name": "Arizona"},
            {"state_code": "CA", "state_name": "California"},
            {"state_code": "CO", "state_name": "Colorado"},
            {"state_code": "CT", "state_name": "Connecticut"},
            {"state_code": "DE", "state_name": "Delaware"},
            {"state_code": "FL", "state_name": "Florida"},
            {"state_code": "HI", "state_name": "Hawaii"},
            {"state_code": "IA", "state_name": "Iowa"},
            {"state_code": "ID", "state_name": "Idaho"},
            {"state_code": "IL", "state_name": "Illinois"},
            {"state_code": "KS", "state_name": "Kansas"},
            {"state_code": "KY", "state_name": "Kentucky"},
            {"state_code": "MA", "state_name": "Massachusetts"},
            {"state_code": "MD", "state_name": "Maryland"},
            {"state_code": "ME", "state_name": "Maine"},
            {"state_code": "MI", "state_name": "Michigan"},
            {"state_code": "MN", "state_name": "Minnesota"},
            {"state_code": "MO", "state_name": "Missouri"},
            {"state_code": "MT", "state_name": "Montana"},
            {"state_code": "NC", "state_name": "North Carolina"},
            {"state_code": "ND", "state_name": "North Dakota"},
            {"state_code": "NE", "state_name": "Nebraska"},
            {"state_code": "NH", "state_name": "New Hampshire"},
            {"state_code": "NM", "state_name": "New Mexico"},
            {"state_code": "NV", "state_name": "Nevada"},
            {"state_code": "OH", "state_name": "Ohio"},
            {"state_code": "OK", "state_name": "Oklahoma"},
            {"state_code": "OR", "state_name": "Oregon"},
            {"state_code": "RI", "state_name": "Rhode Island"},
            {"state_code": "SC", "state_name": "South Carolina"},
            {"state_code": "SD", "state_name": "South Dakota"},
            {"state_code": "TX", "state_name": "Texas"},
            {"state_code": "VA", "state_name": "Virginia"},
            {"state_code": "VT", "state_name": "Vermont"},
            {"state_code": "WA", "state_name": "Washington"},
            {"state_code": "WI", "state_name": "Wisconsin"},
            {"state_code": "WV", "state_name": "West Virginia"},
            {"state_code": "WY", "state_name": "Wyoming"},
        ]

    def test_empty_registry_returns_empty_list(self) -> None:
        assert list_states(AdapterRegistry()) == []


class TestUnknownState:
    @pytest.mark.parametrize(
        "call",
        [
            lambda registry: list_titles(registry, "ZZ"),
            lambda registry: list_chapters(registry, "ZZ", "49"),
            lambda registry: list_sections(registry, "ZZ", "49", "60"),
            lambda registry: get_section(registry, "ZZ", "49", "60", "49.60.010"),
        ],
    )
    def test_unknown_state_raises_value_error(self, call) -> None:
        with pytest.raises(ValueError, match="Unknown or unsupported state: 'ZZ'"):
            call(_registry())


class TestListTitles:
    def test_returns_nodes(self) -> None:
        with mock_urlopen(SYNTHETIC_TITLES_HTML):
            result = list_titles(_registry(), "WA")

        assert result == [
            {"level": "title", "identifier": "49", "name": "LABOR REGULATIONS"},
            {"level": "title", "identifier": "9A", "name": "CRIMINAL LAW"},
        ]

    def test_lowercase_state_code_is_accepted(self) -> None:
        with mock_urlopen(SYNTHETIC_TITLES_HTML):
            result = list_titles(_registry(), "wa")

        assert result[0]["identifier"] == "49"

    def test_network_failure_propagates_adapter_unavailable_error(self) -> None:
        with mock_urlopen_error(urllib.error.URLError("simulated network failure")):
            with pytest.raises(AdapterUnavailableError):
                list_titles(_registry(), "WA")


class TestListChapters:
    def test_returns_nodes(self) -> None:
        with mock_urlopen(SYNTHETIC_CHAPTERS_HTML):
            result = list_chapters(_registry(), "WA", "49")

        assert result == [
            {"level": "chapter", "identifier": "60", "name": "Apprenticeship."},
            {"level": "chapter", "identifier": "61", "name": "Employment counseling."},
        ]


class TestListSections:
    def test_returns_nodes(self) -> None:
        with mock_urlopen(SYNTHETIC_SECTIONS_HTML):
            result = list_sections(_registry(), "WA", "49", "60")

        assert [r["identifier"] for r in result] == ["49.60.010", "49.60.2235"]
        assert all(r["level"] == "section" for r in result)


class TestGetSection:
    def test_returns_normalized_section(self) -> None:
        with mock_urlopen(SYNTHETIC_SECTION_HTML):
            result = get_section(_registry(), "WA", "49", "60", "49.60.010")

        assert result["state"] == "WA"
        assert result["section"] == "49.60.010"
        assert result["citation"] == "RCW 49.60.010"
        assert result["heading"] == "Purpose of chapter."
        assert "protect the health of all residents" in result["text"]
        assert result["status"] == "unknown"
        assert result["amendment_notes"] == "[2006 c 66 \u00a7 1.]"
        assert result["source_url"] == (
            "https://app.leg.wa.gov/RCW/default.aspx?cite=49.60.010"
        )
        assert result["retrieved_at"] is not None

    def test_citation_mismatch_propagates_ref_mismatch_error(self) -> None:
        html = (
            "<h1>RCW 49.60.100</h1>"
            "<h2>Some other section.</h2>"
            '<div style="text-indent:0.5in;">Its own text.</div>'
            '<h2 class="text-warning">footer</h2>'
        )
        with mock_urlopen(html):
            with pytest.raises(RefMismatchError):
                get_section(_registry(), "WA", "49", "60", "49.60.010")


class TestGetSectionVirginia:
    def test_returns_normalized_virginia_section(self) -> None:
        with mock_urlopen(json.dumps(SYNTHETIC_VA_SECTION_JSON)):
            result = get_section(_registry(), "VA", "18.2", "4", "18.2-51")

        assert result["state"] == "VA"
        assert result["section"] == "18.2-51"
        assert result["citation"] == "§ 18.2-51"
        assert (
            result["heading"]
            == "Shooting, stabbing, etc., with intent to maim, kill, or disable."
        )
        assert "maliciously shoot" in result["text"]
        assert result["status"] == "unknown"
        assert result["amendment_notes"] == "Code 1950, § 18.1-65; 1960, c. 358; 1975, cc. 14, 15."
        assert result["source_url"] == (
            "https://law.lis.virginia.gov/api/"
            "CoVSectionsGetSectionDetailsJson/18.2-51/"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionDelaware:
    def test_returns_normalized_delaware_section(self) -> None:
        served = {
            "https://delcode.delaware.gov/title11/c005/index.html": (
                SYNTHETIC_DE_CHAPTER_HTML
            ),
            "https://delcode.delaware.gov/title11/c005/sc01/index.html": (
                SYNTHETIC_DE_SECTION_HTML
            ),
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "DE", "11", "5", "501")

        assert result["state"] == "DE"
        assert result["section"] == "501"
        assert result["citation"] == "11 Del. C. § 501"
        assert (
            result["heading"]
            == "Criminal solicitation in the third degree; class A misdemeanor."
        )
        assert (
            "Criminal solicitation in the third degree is a class A misdemeanor."
            in result["text"]
        )
        assert result["status"] == "unknown"
        assert result["amendment_notes"] == (
            "11 Del. C. 1953, § 501; 58 Del. Laws, c. 497, § 1 ;"
        )
        assert result["source_url"] == (
            "https://delcode.delaware.gov/title11/c005/index.html"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionFlorida:
    def test_returns_normalized_florida_section(self) -> None:
        # The real trimmed fixture: a verbatim slice of the official
        # Chapter 775 "/All" document captured live on Aug 14, 2026.
        fixture = (
            Path(__file__).parent
            / "fixtures"
            / "florida_chapter775_all.html"
        ).read_text(encoding="utf-8")
        served = {
            "https://www.flsenate.gov/Laws/Statutes/2025/Chapter775/All": fixture
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "FL", "46", "775", "775.01")

        assert result["state"] == "FL"
        assert result["section"] == "775.01"
        assert result["citation"] == "s. 775.01, Fla. Stat."
        assert result["heading"] == "Common law of England."
        assert "The common law of England" in result["text"]
        assert result["status"] == "unknown"
        assert result["amendment_notes"] == (
            "s. 1, Nov. 6, 1829; s. 1, Feb. 10, 1832; RS 2369; GS 3194; "
            "RGS 5024; CGL 7126."
        )
        assert result["source_url"] == (
            "https://www.flsenate.gov/Laws/Statutes/2025/Chapter775/All"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionHawaii:
    def test_returns_normalized_hawaii_section(self) -> None:
        # The real trimmed fixture: a verbatim slice of the official Hawaii
        # Revised Statutes section page (data.capitol.hawaii.gov) captured
        # Aug 17, 2026 via the fetch proxy (see docs/research/hawaii.md).
        fixture = (
            Path(__file__).parent / "fixtures" / "hi_section_377-4.5.html"
        ).read_text(encoding="utf-8")
        served = {
            "https://data.capitol.hawaii.gov/hrscurrent/"
            "Vol07_Ch0346-0398/HRS0377/HRS_0377-0004_0005.htm": fixture
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "HI", "7", "377", "377-4.5")

        assert result["state"] == "HI"
        assert result["section"] == "377-4.5"
        assert result["citation"] == "Haw. Rev. Stat. Section 377-4.5"
        assert result["heading"] == (
            "Religious exemption from labor organization membership."
        )
        assert "Notwithstanding any other provision of law" in result["text"]
        assert "Attorney General Opinions" not in result["text"]
        assert result["status"] == "unknown"
        assert result["amendment_notes"] == "[L 1982, c 102, §2; am L 1983, c 124, §9]"
        assert result["source_url"] == (
            "https://data.capitol.hawaii.gov/hrscurrent/"
            "Vol07_Ch0346-0398/HRS0377/HRS_0377-0004_0005.htm"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionSouthDakota:
    def test_returns_normalized_south_dakota_section(self) -> None:
        # Synthetic JSON matching the verified South Dakota section-record
        # shape (embedded Html with a number+catchline line, body
        # paragraphs, and a trailing "Source:" amendment-history line).
        served = {
            "https://sdlegislature.gov/api/Statutes/Statute/22-3-1": json.dumps(
                {
                    "StatuteId": 2046938,
                    "Statute": "22-3-1",
                    "CatchLine": "Persons capable of committing crimes--Exceptions.",
                    "Type": "Section",
                    "Repealed": False,
                    "parents": [
                        {"StatuteId": 1, "Type": "Title", "Statute": "22"},
                        {"StatuteId": 2, "Type": "Chapter", "Statute": "3"},
                        {"StatuteId": 3, "Type": "Section", "Statute": "1"},
                    ],
                    "Html": (
                        "<html><head><style>span { white-space: pre-wrap; }</style></head><body>"
                        '<p dir="ltr" class="sSC"><a href="https://sdlegislature.gov/Statutes?Statute=22-3-1"><span>22-3-1</span></a><span>.</span> <span>Persons capable of committing crimes--Exceptions.</span></p>'
                        "<p dir=\"ltr\" class=\"sNormal\">Any person is capable of committing a crime, except the following.</p>"
                        '<p dir="ltr" class="sSCL"><span class="sSC">Source:</span><span class="sS"> SDC 1939, \u00a7 13.0201; SL 1968, ch 28, \u00a7\u00a7 1, 2.</span></p>'
                        "</body></html>"
                    ),
                }
            )
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "SD", "22", "3", "22-3-1")

        assert result["state"] == "SD"
        assert result["section"] == "22-3-1"
        assert result["citation"] == "SDCL § 22-3-1"
        assert (
            result["heading"]
            == "Persons capable of committing crimes--Exceptions."
        )
        assert "Any person is capable of committing a crime" in result["text"]
        assert result["status"] == "unknown"
        assert result["amendment_notes"] == (
            "Source: SDC 1939, § 13.0201; SL 1968, ch 28, §§ 1, 2."
        )
        assert result["source_url"] == (
            "https://sdlegislature.gov/api/Statutes/Statute/22-3-1"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionMaine:
    def test_returns_normalized_maine_section(self) -> None:
        # The real trimmed fixtures: verbatim slices of the official
        # legislature.maine.gov statutes pages captured live on Aug 15, 2026.
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://legislature.maine.gov/statutes/17-A/title17-Ach1sec0.html": (
                fixtures / "maine_title17a_ch1.html"
            ).read_text(encoding="utf-8"),
            "https://legislature.maine.gov/statutes/17-A/title17-Asec2.html": (
                fixtures / "maine_title17a_sec2.html"
            ).read_text(encoding="utf-8"),
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "ME", "17-A", "1", "2")

        assert result["state"] == "ME"
        assert result["section"] == "2"
        assert result["citation"] == "17-A M.R.S. § 2"
        assert result["heading"] == "Definitions"
        assert "As used in this code" in result["text"]
        assert result["status"] == "unknown"
        assert result["amendment_notes"].startswith("PL 1975, c. 499, §1 (NEW).")
        assert result["source_url"] == (
            "https://legislature.maine.gov/statutes/17-A/title17-Asec2.html"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionMissouri:
    def test_returns_normalized_missouri_section(self) -> None:
        # The real trimmed fixture: a verbatim slice of the official
        # revisor.mo.gov section page captured via the Wayback Machine
        # (the live host rejects automated clients).
        fixture = (
            Path(__file__).parent / "fixtures" / "missouri_section536050.html"
        ).read_text(encoding="utf-8")
        served = {
            "https://revisor.mo.gov/main/OneSection.aspx?section=536.050": fixture
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "MO", "XXXVI", "536", "536.050")

        assert result["state"] == "MO"
        assert result["section"] == "536.050"
        assert result["citation"] == "RSMo § 536.050"
        assert result["heading"] == (
            "Declaratory judgments respecting the validity of rules — fees and "
            "expenses — standing, intervention by general assembly."
        )
        assert "The power of the courts of this state to render declaratory" in (
            result["text"]
        )
        assert result["status"] == "unknown"
        assert result["amendment_notes"].startswith("(L. 1945 p. 1504 § 5")
        assert result["source_url"] == (
            "https://revisor.mo.gov/main/OneSection.aspx?section=536.050"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionVermont:
    def test_returns_normalized_vermont_section(self) -> None:
        # The real trimmed fixture: a verbatim slice of the official
        # legislature.vermont.gov section page captured via the Wayback
        # Machine (the live host rejects automated clients).
        fixture = (
            Path(__file__).parent / "fixtures" / "vermont_section01344.html"
        ).read_text(encoding="utf-8")
        served = {
            "https://legislature.vermont.gov/statutes/section/21/017/01344": fixture
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "VT", "21", "017", "01344")

        assert result["state"] == "VT"
        assert result["section"] == "01344"
        assert result["citation"] == "21 V.S.A. § 1344"
        assert result["heading"] == "Disqualifications"
        assert "An individual shall be disqualified for benefits" in result["text"]
        assert result["status"] == "unknown"
        assert result["amendment_notes"].startswith("(Amended 1959, No. 236;")
        assert result["source_url"] == (
            "https://legislature.vermont.gov/statutes/section/21/017/01344"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionWestVirginia:
    def test_returns_normalized_west_virginia_section(self) -> None:
        # The real trimmed fixture: a verbatim slice of the official
        # code.wvlegislature.gov section page captured via the Wayback
        # Machine (the live host rejects automated clients).
        fixture = (
            Path(__file__).parent / "fixtures" / "west_virginia_section112112.html"
        ).read_text(encoding="utf-8")
        served = {
            "https://code.wvlegislature.gov/11-21-12/": fixture
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "WV", "11", "21", "11-21-12")

        assert result["state"] == "WV"
        assert result["section"] == "11-21-12"
        assert result["citation"] == "W. Va. Code § 11-21-12"
        assert (
            result["heading"]
            == "West Virginia adjusted gross income of resident individual."
        )
        assert "The West Virginia adjusted gross income of a resident" in (
            result["text"]
        )
        assert result["status"] == "unknown"
        assert result["amendment_notes"] is None
        assert result["source_url"] == "https://code.wvlegislature.gov/11-21-12/"
        assert result["retrieved_at"] is not None


class TestGetSectionMinnesota:
    def test_returns_normalized_minnesota_section(self) -> None:
        # The real trimmed fixtures: verbatim slices of the official
        # revisor.mn.gov statutes pages captured live on Aug 15, 2026.
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://www.revisor.mn.gov/statutes/cite/3C.12": (
                fixtures / "mn_section_3C12.html"
            ).read_text(encoding="utf-8"),
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "MN", "LEGISLATURE", "3C", "3C.12")

        assert result["state"] == "MN"
        assert result["section"] == "3C.12"
        assert result["citation"] == "Minn. Stat. § 3C.12"
        assert result["heading"] == "SALE AND DISTRIBUTION OF STATUTES AND LAWS."
        assert "The revisor shall determine how many copies" in result["text"]
        assert result["status"] == "unknown"
        assert result["amendment_notes"].startswith("1984 c 480 s 12")
        assert result["source_url"] == (
            "https://www.revisor.mn.gov/statutes/cite/3C.12"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionMassachusetts:
    def test_returns_normalized_massachusetts_section(self) -> None:
        # The real trimmed fixtures: verbatim slices of the official
        # malegislature.gov General Laws pages captured on Aug 20 2026 via
        # the r.jina.ai proxy with X-Return-Format: html (see
        # docs/research/massachusetts.md).
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://malegislature.gov/Laws/GeneralLaws/PartI/TitleI/Chapter4/Section7": (
                fixtures / "ma_sec7.html"
            ).read_text(encoding="utf-8"),
        }
        with mock_urlopen_serving(served):
            result = get_section(
                _registry(), "MA", "Part I Title I", "4", "7"
            )

        assert result["state"] == "MA"
        assert result["section"] == "7"
        assert result["citation"] == "G.L. c. 4, § 7"
        assert result["heading"] == (
            "Definitions of statutory terms; statutory construction"
        )
        assert result["text"].startswith(
            "Section 7. In construing statutes the following words"
        )
        assert result["status"] == "unknown"
        assert result["amendment_notes"] is None
        assert result["source_url"] == (
            "https://malegislature.gov/Laws/GeneralLaws/PartI/TitleI/"
            "Chapter4/Section7"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionArizona:
    def test_returns_normalized_arizona_section(self) -> None:
        # The real trimmed fixtures: verbatim slices of the official
        # azleg.gov pages captured live on Aug 15, 2026.
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://www.azleg.gov/ars/28/00101.htm": (
                fixtures / "az_section_28-101.html"
            ).read_text(encoding="latin-1"),
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "AZ", "28", "1", "28-101")

        assert result["state"] == "AZ"
        assert result["section"] == "28-101"
        assert result["citation"] == "A.R.S. § 28-101"
        assert result["heading"] == "Definitions"
        assert 'In this title, unless the context' in result["text"]
        assert result["status"] == "unknown"
        assert result["amendment_notes"] is None
        assert result["source_url"] == "https://www.azleg.gov/ars/28/00101.htm"
        assert result["retrieved_at"] is not None


class TestGetSectionIllinois:
    def test_returns_normalized_illinois_section(self) -> None:
        # Illinois's section content is a hand-written synthetic mock (the
        # same one used by test_illinois_adapter.py): the ilga.gov host is
        # unreachable from this environment, so no real fixture can be
        # captured. Its citation/heading/body/history text matches what was
        # independently verified via two real fetches during design. The
        # adapter fetches the section file via the shared network boundary,
        # so mock_urlopen (any URL) serves the mock.
        synthetic_mock_section_text = """
        <html><body>
        <p>(720 ILCS 5/9-2) (from Ch. 38, par. 9-2)</p>
        <p>Sec. 9-2. Second degree murder.
        (a) A person commits the offense of second degree murder when he or
        she commits the offense of first degree murder as defined in
        paragraph (1) or (2) of subsection (a) of Section 9-1 of this Code
        and either of the following mitigating factors are present:
        (d) Sentence. Second degree murder is a Class 1 felony.</p>
        <p>(Source: P.A. 100-460, eff. 1-1-18.)</p>
        </body></html>
        """
        with mock_urlopen(synthetic_mock_section_text):
            result = get_section(_registry(), "IL", "720", "5", "9-2")

        assert result["state"] == "IL"
        assert result["section"] == "9-2"
        assert result["citation"] == "(720 ILCS 5/9-2) (from Ch. 38, par. 9-2)"
        assert result["heading"] == "Second degree murder"
        assert "second degree murder" in result["text"]
        assert "Class 1 felony" in result["text"]
        assert result["status"] == "unknown"
        assert result["amendment_notes"] == "(Source: P.A. 100-460, eff. 1-1-18.)"
        assert result["source_url"] == (
            "https://www.ilga.gov/ftp/ILCS/Ch%200720/Act%200005/"
            "072000050K9-2.html"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionTexas:
    def test_returns_normalized_texas_section(self) -> None:
        # The real fixture: a verbatim capture of the official Texas
        # Penal Code chapter page (tcss.legis.texas.gov/resources/PE/htm/
        # PE.19.htm). The adapter fetches the whole chapter document and
        # extracts the requested section by anchor, so the real fixture is
        # served for the chapter URL.
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://tcss.legis.texas.gov/resources/PE/htm/PE.19.htm": (
                fixtures / "texas_current_pe19.html"
            ).read_text(encoding="utf-8"),
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "TX", "PE", "19", "19.01")

        assert result["state"] == "TX"
        assert result["section"] == "19.01"
        assert result["citation"] == "Sec. 19.01. TYPES OF CRIMINAL HOMICIDE."
        assert result["heading"] == "TYPES OF CRIMINAL HOMICIDE."
        assert "criminal homicide" in result["text"]
        assert result["status"] == "unknown"
        assert result["amendment_notes"].startswith("Acts 1973, 63rd Leg.")
        assert result["source_url"] == (
            "https://tcss.legis.texas.gov/resources/PE/htm/PE.19.htm#19.01"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionKentucky:
    def test_returns_normalized_kentucky_section(self) -> None:
        # The real fixtures: verbatim captures of the official Kentucky
        # source (apps.legislature.ky.gov) taken live on Aug 23 2026 — the
        # index/chapter pages are HTML and the section is a real PDF (see
        # docs/research/kentucky.md). Kentucky section retrieval needs the
        # index (to resolve the opaque chapter ID) and the chapter page (to
        # resolve the opaque section ID) before fetching the PDF, so all
        # three are served.
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://apps.legislature.ky.gov/LAW/STATUTES/": (
                fixtures / "ky_index.html"
            ).read_bytes(),
            "https://apps.legislature.ky.gov/LAW/STATUTES/chapter.aspx?id=38124": (
                fixtures / "ky_chapter205.html"
            ).read_bytes(),
            "https://apps.legislature.ky.gov/LAW/STATUTES/statute.aspx?id=7624": (
                fixtures / "ky_section_205-010.pdf"
            ).read_bytes(),
        }
        with mock_urlopen_serving_bytes(served):
            result = get_section(_registry(), "KY", "XVII", "205", "205.010")

        assert result["state"] == "KY"
        assert result["section"] == "205.010"
        assert result["citation"] == "KRS 205.010"
        assert result["heading"] == "Definitions for chapter."
        assert result["text"].startswith(
            "As used in this chapter, unless the context requires otherwise"
        )
        assert result["status"] == "unknown"
        assert result["amendment_notes"].startswith(
            "Effective: June 20, 2005\nHistory: Amended 2005 Ky."
        )
        assert result["source_url"] == (
            "https://apps.legislature.ky.gov/LAW/STATUTES/"
            "statute.aspx?id=7624"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionIowa:
    def test_returns_normalized_iowa_section(self) -> None:
        # The real fixtures: verbatim captures of the official Iowa source
        # (legis.iowa.gov) taken live on Aug 23 2026 — the root page is
        # HTML (used to resolve the current Code year) and the section is a
        # real PDF (see docs/research/iowa.md). Iowa section retrieval
        # needs the root page to determine year=2026, then fetches the PDF.
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://www.legis.iowa.gov/law/iowaCode": (
                fixtures / "ia_root.html"
            ).read_bytes(),
            "https://www.legis.iowa.gov/docs/code/2026/1.1.pdf": (
                fixtures / "ia_section_1.1.pdf"
            ).read_bytes(),
        }
        with mock_urlopen_serving_bytes(served):
            result = get_section(_registry(), "IA", "I", "1", "1.1")

        assert result["state"] == "IA"
        assert result["section"] == "1.1"
        assert result["citation"] == "Iowa Code § 1.1"
        assert result["heading"] == "State boundaries."
        assert result["text"].startswith(
            "The boundaries of the state are as defined in the preamble"
        )
        assert result["status"] == "unknown"
        assert result["amendment_notes"].startswith("[C51, §1; R60, §1;")
        assert result["source_url"] == (
            "https://www.legis.iowa.gov/docs/code/2026/1.1.pdf"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionKansas:
    def test_returns_normalized_kansas_section(self) -> None:
        # The real trimmed fixture: a verbatim response of the official
        # kslegislature.gov JSON API captured live on Aug 15, 2026.
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://www.kslegislature.gov/api/v1/statutes/21-5903/": (
                fixtures / "ks_section_21-5903.json"
            ).read_text(encoding="utf-8"),
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "KS", "21", "59", "21-5903")

        assert result["state"] == "KS"
        assert result["section"] == "21-5903"
        assert result["citation"] == "Kan. Stat. Ann. § 21-5903"
        assert result["heading"] == "Perjury."
        assert "Perjury is intentionally and falsely" in result["text"]
        assert result["status"] == "unknown"
        assert result["amendment_notes"].startswith("History: L. 2010, ch. 136")
        assert result["source_url"] == (
            "https://www.kslegislature.gov/api/v1/statutes/21-5903/"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionNorthDakota:
    def test_returns_normalized_north_dakota_section(self) -> None:
        # The real trimmed fixture: a trimmed copy of the official
        # ndlegis.gov bulk JSON captured live on Aug 15, 2026.
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://ndlegis.gov/api/data/century_code.json": (
                fixtures / "nd_century_code_trimmed.json"
            ).read_text(encoding="utf-8"),
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "ND", "1", "01", "1-01-01")

        assert result["state"] == "ND"
        assert result["section"] == "1-01-01"
        assert result["citation"] == "N.D.C.C. § 1-01-01"
        assert result["heading"] == "This act - How referred to"
        assert "This revision, whenever cited" in result["text"]
        assert result["status"] == "unknown"
        assert result["amendment_notes"] is None
        assert result["source_url"] == (
            "https://ndlegis.gov/api/data/century_code.json"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionMaryland:
    def test_returns_normalized_maryland_section(self) -> None:
        # The real trimmed fixture: a verbatim response of the official
        # mgaleg.maryland.gov section page captured live on Aug 15, 2026.
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText"
            "?article=gtr&section=1-101": (
                fixtures / "md_section_1-101.html"
            ).read_text(encoding="utf-8"),
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "MD", "gtr", "1", "1-101")

        assert result["state"] == "MD"
        assert result["section"] == "1-101"
        assert result["citation"] == "Md. Code, Transportation § 1-101"
        assert result["heading"] is None
        assert "In this article the following words" in result["text"]
        assert result["status"] == "unknown"
        assert result["amendment_notes"] is None
        assert result["source_url"] == (
            "https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText"
            "?article=gtr&section=1-101"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionSouthCarolina:
    def test_returns_normalized_south_carolina_section(self) -> None:
        # The real trimmed fixture: a verbatim response of the official
        # scstatehouse.gov chapter page captured live on Aug 15, 2026.
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://www.scstatehouse.gov/code/t01c001.php": (
                fixtures / "sc_t01c001.php"
            ).read_text(encoding="latin-1"),
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "SC", "1", "1", "1-1-10")

        assert result["state"] == "SC"
        assert result["section"] == "1-1-10"
        assert result["citation"] == "S.C. Code § 1-1-10"
        assert result["heading"] == "Jurisdiction and boundaries of the State."
        assert "The sovereignty and jurisdiction of this State" in result["text"]
        assert result["status"] == "unknown"
        assert result["amendment_notes"].startswith("HISTORY: 1962 Code")
        assert result["source_url"] == "https://www.scstatehouse.gov/code/t01c001.php"
        assert result["retrieved_at"] is not None


class TestGetSectionOhio:
    def test_returns_normalized_ohio_section(self) -> None:
        # The real trimmed fixture: a verbatim slice of the official
        # codes.ohio.gov section page captured via the Wayback Machine
        # (the live host is unreachable from this environment).
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://codes.ohio.gov/ohio-revised-code/section-2901.01": (
                fixtures / "oh_section_2901.01.html"
            ).read_text(encoding="utf-8"),
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "OH", "29", "2901", "2901.01")

        assert result["state"] == "OH"
        assert result["section"] == "2901.01"
        assert result["citation"] == "Ohio Rev. Code § 2901.01"
        assert result["heading"] == "General provisions definitions."
        assert "(A) As used in the Revised Code:" in result["text"]
        assert result["status"] == "unknown"
        assert result["amendment_notes"].startswith("September 10, 2012")
        assert result["source_url"] == (
            "https://codes.ohio.gov/ohio-revised-code/section-2901.01"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionOklahoma:
    def test_returns_normalized_oklahoma_section(self) -> None:
        # The real trimmed fixtures: page-range subsets of the official
        # Oklahoma per-title PDFs captured live Aug 23 2026 (see
        # docs/research/oklahoma.md). Oklahoma section retrieval fetches the
        # title PDF (os21.pdf) and locates the requested section in its body.
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://www.oklegislature.gov/OK_Statutes/CompleteTitles/os21.pdf": (
                fixtures / "ok_title21_section_701.7.pdf"
            ).read_bytes(),
        }
        with mock_urlopen_serving_bytes(served):
            result = get_section(_registry(), "OK", "21", "21", "21-701.7")

        assert result["state"] == "OK"
        assert result["section"] == "21-701.7"
        assert result["citation"] == "Okla. Stat. tit. 21, § 21-701.7"
        assert result["heading"] == "Murder in the first degree."
        assert result["text"].startswith(
            "A.  A person commits murder in the first degree"
        )
        assert result["status"] == "unknown"
        assert result["amendment_notes"] is not None
        assert result["source_url"] == (
            "https://www.oklegislature.gov/OK_Statutes/"
            "CompleteTitles/os21.pdf"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionAlabama:
    def test_returns_normalized_alabama_section(self) -> None:
        # The real fixtures: verbatim captures of the official ALISON
        # GraphQL API (alison.legislature.state.al.us/graphql) captured live
        # Aug 24 2026 (see docs/research/alabama.md). Alabama section
        # retrieval first loads the TOC (codeOfAlabamaTitles) to resolve the
        # citation to its codeId, then POSTs a codesOfAlabama retrieval
        # query. The GraphQL mock dispatches on the query body.
        fixtures = Path(__file__).parent / "fixtures"
        toc = json.loads(
            (fixtures / "al_toc_trimmed.json").read_text(encoding="utf-8")
        )
        s1 = json.loads(
            (fixtures / "al_section_1-1-1.json").read_text(encoding="utf-8")
        )
        mapping = {
            "codeOfAlabamaTitles": toc,
            "codeId: { eq: 14515 }": s1,
        }
        with mock_urlopen_graphql(mapping):
            result = get_section(_registry(), "AL", "1", "1", "1-1-1")

        assert result["state"] == "AL"
        assert result["section"] == "1-1-1"
        assert result["citation"] == "Ala. Code § 1-1-1"
        assert result["heading"] == "Meaning of Certain Words and Terms."
        assert "The following words, whenever they appear in this code" in (
            result["text"]
        )
        assert result["status"] == "unknown"
        assert result["amendment_notes"] is None
        assert result["source_url"] == (
            "https://alison.legislature.state.al.us/graphql"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionWyoming:
    def test_returns_normalized_wyoming_section(self) -> None:
        # The real trimmed fixtures: page-range subsets of the official
        # per-title PDFs captured live Aug 24 2026 (see
        # docs/research/wyoming.md). Wyoming section retrieval fetches the
        # per-title PDF (title01.pdf) and locates the requested section in
        # its body. The network mock dispatches on HEAD (existence probe)
        # vs GET (PDF fetch).
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://wyoleg.gov/statutes/compress/title01.pdf": (
                fixtures / "wy_title01_ch1.pdf"
            ).read_bytes(),
        }

        import io
        import urllib.request
        from unittest import mock

        from _mock_network import PATCH_TARGET

        class _Resp(io.BytesIO):
            def __init__(self, data: bytes, content_type: str):
                super().__init__(data)
                self.status = 200
                self.headers = {"Content-Type": content_type}

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

        def fake_urlopen(request, timeout=None):
            if isinstance(request, urllib.request.Request):
                url = request.full_url
                method = request.get_method()
            else:
                url = request
                method = "GET"
            if method == "HEAD":
                if url in served:
                    return _Resp(b"", "application/pdf")
                return _Resp(b"", "text/html")
            if url in served:
                return _Resp(served[url], "application/pdf")
            return _Resp(b"<html></html>", "text/html")

        with mock.patch(PATCH_TARGET, side_effect=fake_urlopen):
            result = get_section(_registry(), "WY", "1", "1", "1-1-101")

        assert result["state"] == "WY"
        assert result["section"] == "1-1-101"
        assert result["citation"] == "Wyo. Stat. 1-1-101"
        assert result["heading"] == "Provisions to be liberally construed."
        assert "The Code of Civil Procedure and all proceedings under it" in (
            result["text"]
        )
        assert result["status"] == "unknown"
        assert result["amendment_notes"] is None
        assert result["source_url"] == (
            "https://wyoleg.gov/statutes/compress/title01.pdf"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionColorado:
    def test_returns_normalized_colorado_section(self) -> None:
        # The real archived fixtures: page-range subsets of the official
        # per-title PDFs captured via the Wayback Machine (the live host
        # returns an AWS WAF 403 to this environment). See
        # docs/research/colorado.md. Colorado section retrieval fetches the
        # per-title PDF (crs2024-title-42.pdf) and locates the requested
        # section in its body. The network mock dispatches on HEAD
        # (existence probe) vs GET (PDF fetch).
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://content.leg.colorado.gov/sites/default/files/images/"
            "olls/crs2024-title-42.pdf": (
                fixtures / "co_title42_ch1.pdf"
            ).read_bytes(),
        }

        import io
        import urllib.request
        from unittest import mock

        from _mock_network import PATCH_TARGET

        class _Resp(io.BytesIO):
            def __init__(self, data: bytes, content_type: str):
                super().__init__(data)
                self.status = 200
                self.headers = {"Content-Type": content_type}

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

        def fake_urlopen(request, timeout=None):
            if isinstance(request, urllib.request.Request):
                url = request.full_url
                method = request.get_method()
            else:
                url = request
                method = "GET"
            if method == "HEAD":
                if url in served:
                    return _Resp(b"", "application/pdf")
                return _Resp(b"", "text/html")
            if url in served:
                return _Resp(served[url], "application/pdf")
            return _Resp(b"<html></html>", "text/html")

        with mock.patch(PATCH_TARGET, side_effect=fake_urlopen):
            result = get_section(_registry(), "CO", "42", "1", "42-1-101")

        assert result["state"] == "CO"
        assert result["section"] == "42-1-101"
        assert result["citation"] == "Colo. Rev. Stat. 42-1-101"
        assert result["heading"] == "Short title."
        assert "Articles 1 to 4 of this title shall be known" in (
            result["text"]
        )
        assert result["status"] == "unknown"
        assert result["amendment_notes"] is not None
        assert result["source_url"] == (
            "https://content.leg.colorado.gov/sites/default/files/images/"
            "olls/crs2024-title-42.pdf"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionRhodeIsland:
    def test_returns_normalized_rhode_island_section(self) -> None:
        # The real trimmed fixture: a verbatim slice of the official
        # webserver.rilegislature.gov section page captured via the Wayback
        # Machine (the live host is unreachable from this environment).
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "http://webserver.rilegislature.gov/Statutes/TITLE43/43-3/43-3-2.htm": (
                fixtures / "ri_section_43-3-2.htm"
            ).read_text(encoding="utf-8"),
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "RI", "43", "43-3", "43-3-2")

        assert result["state"] == "RI"
        assert result["section"] == "43-3-2"
        assert result["citation"] == "R.I. Gen. Laws § 43-3-2"
        assert result["heading"] == "Application of rules of construction."
        assert "In the construction of statutes" in result["text"]
        assert result["status"] == "unknown"
        assert result["amendment_notes"].startswith("G.L. 1896, ch. 26, § 1;")
        assert result["source_url"] == (
            "http://webserver.rilegislature.gov/Statutes/TITLE43/43-3/43-3-2.htm"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionWisconsin:
    def test_returns_normalized_wisconsin_section(self) -> None:
        # The real trimmed fixtures: verbatim slices of the official
        # docs.legis.wisconsin.gov statutes pages captured via the Wayback
        # Machine (the live host is unreachable from this environment).
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://docs.legis.wisconsin.gov/document/statutes/13.90": (
                fixtures / "wi_section_13.90.html"
            ).read_text(encoding="utf-8"),
        }
        with mock_urlopen_serving(served):
            result = get_section(
                _registry(), "WI", "Wisconsin Statutes", "13", "13.90"
            )

        assert result["state"] == "WI"
        assert result["section"] == "13.90"
        assert result["citation"] == "Wis. Stat. § 13.90"
        assert result["heading"] == (
            "Duties and powers of the joint committee on legislative "
            "organization."
        )
        assert "(1) The joint committee on legislative organization" in (
            result["text"]
        )
        assert result["status"] == "unknown"
        assert result["amendment_notes"].startswith("1971 c. 215 ;")
        assert result["source_url"] == (
            "https://docs.legis.wisconsin.gov/document/statutes/13.90"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionIdaho:
    def test_returns_normalized_idaho_section(self) -> None:
        # The real trimmed fixtures: verbatim slices of the official
        # legislature.idaho.gov statutes pages captured via the Wayback
        # Machine (the live host is unreachable from this environment).
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://legislature.idaho.gov/statutesrules/idstat/"
            "Title18/T18CH40/SECT18-4001": (
                fixtures / "id_section_18-4001.html"
            ).read_text(encoding="utf-8"),
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "ID", "18", "40", "18-4001")

        assert result["state"] == "ID"
        assert result["section"] == "18-4001"
        assert result["citation"] == "Idaho Code § 18-4001"
        assert result["heading"] == "Murder defined."
        assert "Murder is the unlawful killing" in result["text"]
        assert result["status"] == "unknown"
        assert result["amendment_notes"].startswith(
            "[18-4001, added 1972, ch. 336, sec. 1, p. 928;"
        )
        assert result["source_url"] == (
            "https://legislature.idaho.gov/statutesrules/idstat/"
            "Title18/T18CH40/SECT18-4001"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionNevada:
    def test_returns_normalized_nevada_section(self) -> None:
        # SYNTHETIC fixtures: representative markup reproducing ONLY the
        # VERIFIED Nevada structures (Wayback retrieval was unavailable
        # from this environment). NOT official government captures.
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://www.leg.state.nv.us/nrs//NRS-220.html": (
                fixtures / "nv_chapter220.html"
            ).read_text(encoding="utf-8"),
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "NV", "1", "220", "220.170")

        assert result["state"] == "NV"
        assert result["section"] == "220.170"
        assert result["citation"] == "NRS 220.170"
        assert result["heading"] == "Authority to acquire property."
        assert "The department may acquire, by purchase, condemnation" in (
            result["text"]
        )
        assert result["status"] == "unknown"
        assert result["amendment_notes"] == "[1:21:1955; 1965, 219]"
        assert result["source_url"] == (
            "https://www.leg.state.nv.us/nrs//NRS-220.html"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionNewHampshire:
    def test_returns_normalized_new_hampshire_section(self) -> None:
        # SYNTHETIC fixtures: representative markup reproducing ONLY the
        # VERIFIED New Hampshire structures (Wayback retrieval was
        # unavailable from this environment). NOT official government
        # captures.
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://gc.nh.gov/rsa/html/xvi/201-a/201-a-mrg.htm": (
                fixtures / "nh_chapter201a.html"
            ).read_text(encoding="utf-8"),
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "NH", "16", "201-A", "201-A:1")

        assert result["state"] == "NH"
        assert result["section"] == "201-A:1"
        assert result["citation"] == "RSA 201-A:1"
        assert result["heading"] == "Definitions."
        assert '"trustee" means a member of a board of library trustees.' in (
            result["text"]
        )
        assert result["status"] == "unknown"
        assert result["amendment_notes"] == "Source. 1971, 224:1, eff. Aug. 22, 1971."
        assert result["source_url"] == (
            "https://gc.nh.gov/rsa/html/xvi/201-a/201-a-mrg.htm"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionNewMexico:
    def test_returns_normalized_new_mexico_section(self) -> None:
        # The real fixtures: verbatim captures of the official New Mexico
        # source (nmonesource.com) taken live on Aug 23 2026 — the
        # navigation pages are HTML (used to resolve the chapter's opaque
        # item ID) and the chapter is a real PDF (see
        # docs/research/new_mexico.md). New Mexico section retrieval needs
        # the navigation pages to resolve chapter 1 -> item 4351, then
        # fetches the chapter PDF and locates the section inside it.
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://nmonesource.com/nmos/nmsa/en/nav_date.do?iframe=true&page=1": (
                fixtures / "nm_nav_page1.html"
            ).read_bytes(),
            "https://nmonesource.com/nmos/nmsa/en/nav_date.do?iframe=true&page=2": (
                fixtures / "nm_nav_page2.html"
            ).read_bytes(),
            "https://nmonesource.com/nmos/nmsa/en/nav_date.do?iframe=true&page=3": (
                fixtures / "nm_nav_page3.html"
            ).read_bytes(),
            "https://nmonesource.com/nmos/nmsa/en/nav_date.do?iframe=true&page=4": (
                fixtures / "nm_nav_page4.html"
            ).read_bytes(),
            "https://nmonesource.com/nmos/nmsa/en/4351/1/document.do": (
                fixtures / "nm_ch1_sections.pdf"
            ).read_bytes(),
        }
        with mock_urlopen_serving_bytes(served):
            result = get_section(_registry(), "NM", "NMSA", "1", "1-1-1")

        assert result["state"] == "NM"
        assert result["section"] == "1-1-1"
        assert result["citation"] == "NM Stat. Ann. 1-1-1"
        assert result["heading"] == "Election Code."
        assert result["text"].startswith(
            'Chapter 1 NMSA 1978 may be cited as the "Election Code".'
        )
        assert result["status"] == "unknown"
        assert result["amendment_notes"].startswith("1953 Comp., § 3-1-1")
        assert result["source_url"] == (
            "https://nmonesource.com/nmos/nmsa/en/4351/1/document.do"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionConnecticut:
    def test_returns_normalized_connecticut_section(self) -> None:
        # The real trimmed fixtures: verbatim slices of the official
        # cga.ct.gov/current/pub pages captured via the Wayback Machine
        # (the live host is unreachable from this environment).
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://www.cga.ct.gov/current/pub/titles.htm": (
                fixtures / "ct_titles.html"
            ).read_text(encoding="utf-8"),
            "https://www.cga.ct.gov/current/pub/title_53a.htm": (
                fixtures / "ct_title53a.html"
            ).read_text(encoding="utf-8"),
            "https://www.cga.ct.gov/current/pub/title_42a.htm": (
                fixtures / "ct_title42a.html"
            ).read_text(encoding="utf-8"),
            "https://www.cga.ct.gov/current/pub/chap_952.htm": (
                fixtures / "ct_chap952_trimmed.html"
            ).read_text(encoding="utf-8"),
            "https://www.cga.ct.gov/current/pub/art_001.htm": (
                fixtures / "ct_art001_trimmed.html"
            ).read_text(encoding="utf-8"),
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "CT", "53a", "952", "53a-24")

        assert result["state"] == "CT"
        assert result["section"] == "53a-24"
        assert result["citation"] == "Sec. 53a-24"
        assert result["heading"] == (
            "Offense defined. Application of sentencing provisions to motor "
            "vehicle and drug selling violators."
        )
        assert result["text"].startswith(
            "(a) The term \u201coffense\u201d means any crime or violation"
        )
        assert result["status"] == "unknown"
        assert result["amendment_notes"].startswith("(1969, P.A. 828, S. 24;")
        assert result["source_url"] == (
            "https://www.cga.ct.gov/current/pub/chap_952.htm"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionOregon:
    def test_returns_normalized_oregon_section(self) -> None:
        # The real trimmed fixtures: verbatim slices of the official
        # oregonlegislature.gov ORS pages captured via the Wayback Machine
        # (the live host is unreachable from this environment). Raw
        # Windows-1252 bytes are served.
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://www.oregonlegislature.gov/bills_laws/ors/ors001.html": (
                fixtures / "or_ors001_trimmed.html"
            ).read_bytes(),
        }
        with _serve_bytes(served):
            result = get_section(_registry(), "OR", "1", "1", "1.001")

        assert result["state"] == "OR"
        assert result["section"] == "1.001"
        assert result["citation"] == "ORS 1.001"
        assert result["heading"] == "State policy for courts."
        assert result["text"].startswith("The Legislative Assembly hereby declares")
        assert result["status"] == "unknown"
        assert result["amendment_notes"] == "[1981 s.s. c.3 §1]"
        assert result["source_url"] == (
            "https://www.oregonlegislature.gov/bills_laws/ors/ors001.html"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionNorthCarolina:
    def test_returns_normalized_north_carolina_section(self) -> None:
        # The real trimmed fixtures: verbatim slices of the official
        # ncleg.gov pages captured via the Wayback Machine (the live host
        # rejects automated clients with HTTP 403). Raw bytes are served
        # because the section documents come in two encodings (UTF-8 and
        # Windows-1252).
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/"
            "Chapter_15/GS_15-1.html": (
                fixtures / "nc_section_15-1.html"
            ).read_bytes(),
        }
        with _serve_bytes(served):
            result = get_section(_registry(), "NC", "15", "15", "15-1")

        assert result["state"] == "NC"
        assert result["section"] == "15-1"
        assert result["citation"] == "G.S. 15-1"
        assert result["heading"] == "Statute of limitations for misdemeanors."
        assert result["text"].startswith("(a) The crimes of deceit")
        assert result["status"] == "unknown"
        assert result["amendment_notes"].startswith("(1826, c. 11;")
        assert result["source_url"] == (
            "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/"
            "Chapter_15/GS_15-1.html"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionNebraska:
    def test_returns_normalized_nebraska_section(self) -> None:
        # The real fixtures: verbatim slices of the official
        # nebraskalegislature.gov pages captured via the Wayback Machine
        # (the live host is unreachable from this environment). UTF-8, so
        # served through the shared UTF-8 mock.
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://nebraskalegislature.gov/laws/statutes.php?statute=77-1801": (
                fixtures / "ne_section_77-1801.html"
            ).read_text(encoding="utf-8"),
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "NE", "REVISED STATUTES", "77", "77-1801")

        assert result["state"] == "NE"
        assert result["section"] == "77-1801"
        assert result["citation"] == "Neb. Rev. Stat. § 77-1801"
        assert result["heading"] == "Real property taxes; collection by sale; when."
        assert result["text"].startswith("Except for delinquent taxes on mobile homes")
        assert result["status"] == "unknown"
        assert result["amendment_notes"].startswith("Laws 1903, c. 73, § 193")
        assert result["source_url"] == (
            "https://nebraskalegislature.gov/laws/statutes.php?statute=77-1801"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionMontana:
    def test_returns_normalized_montana_section(self) -> None:
        # The real fixture: a verbatim live capture of the official
        # mca.legmt.gov section page (fetched Aug 16 2026). UTF-8, so
        # served through the shared UTF-8 mock.
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://mca.legmt.gov/bills/mca/title_0010/chapter_0110/"
            "part_0010/section_0030/0010-0110-0010-0030.html": (
                fixtures / "montana_title_1_11_103.html"
            ).read_text(encoding="utf-8"),
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "MT", "1", "11", "1-11-103")

        assert result["state"] == "MT"
        assert result["section"] == "1-11-103"
        assert result["citation"] == "Mont. Code Ann. § 1-11-103"
        assert result["heading"] == (
            "Effect of Montana Code Annotated -- official version."
        )
        assert result["text"].startswith(
            "(1) The Montana Code Annotated is a reenactment of the Revised "
            "Codes of Montana, 1947, and the supplements thereto."
        )
        assert result["status"] == "unknown"
        assert result["amendment_notes"].startswith("En. 12-506 by Sec. 6")
        assert result["source_url"] == (
            "https://mca.legmt.gov/bills/mca/title_0010/chapter_0110/"
            "part_0010/section_0030/0010-0110-0010-0030.html"
        )
        assert result["retrieved_at"] is not None


class TestGetSectionCalifornia:
    def test_returns_normalized_california_section(self) -> None:
        # The real fixture: a verbatim live capture of the official
        # leginfo.legislature.ca.gov section page (fetched Aug 27 2026; the
        # JSF ViewState value is stubbed -- the statute HTML is verbatim).
        # California section retrieval is a single server-rendered GET.
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml"
            "?lawCode=BPC&sectionNum=5000": (
                fixtures / "ca_section_bpc_5000.html"
            ).read_text(encoding="utf-8"),
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "CA", "BPC", "3//1/1", "5000")

        assert result["state"] == "CA"
        assert result["section"] == "5000"
        assert result["citation"] == "Cal. BPC § 5000"
        assert result["heading"] is None
        assert result["text"].startswith(
            "(a) There is in the Department of Consumer Affairs"
        )
        assert result["status"] == "unknown"
        assert "Amended by Stats. 2024" in result["amendment_notes"]
        assert result["source_url"] == (
            "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml"
            "?lawCode=BPC&sectionNum=5000"
        )
        assert result["retrieved_at"] is not None

    def test_invalid_section_raises(self) -> None:
        from state_statutes_mcp.core.exceptions import RefNotFoundError

        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml"
            "?lawCode=BPC&sectionNum=999999": (
                fixtures / "ca_section_invalid.html"
            ).read_text(encoding="utf-8"),
        }
        with mock_urlopen_serving(served):
            with pytest.raises(RefNotFoundError):
                get_section(_registry(), "CA", "BPC", "3//1/1", "999999")


class TestGetSectionMichigan:
    def test_returns_normalized_michigan_section(self) -> None:
        # The real fixture: a verbatim archived official capture of the
        # legislature.mi.gov section page (retrieved via the Wayback
        # Machine, Aug 2026; the live host is bot-challenge-blocked from
        # this environment). Michigan section retrieval is a single direct
        # server-rendered GET.
        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://www.legislature.mi.gov/Laws/MCL"
            "?objectName=mcl-750-82": (
                fixtures / "mi_section_750_82.html"
            ).read_text(encoding="utf-8"),
        }
        with mock_urlopen_serving(served):
            result = get_section(_registry(), "MI", "MCL", "750", "750.82")

        assert result["state"] == "MI"
        assert result["section"] == "750.82"
        assert result["citation"] == "MCL § 750.82"
        assert result["heading"].startswith(
            "Felonious assault; violation of subsection (1)"
        )
        assert result["text"].startswith("(1) Except as otherwise provided")
        assert result["status"] == "unknown"
        assert "1931, Act 328" in result["amendment_notes"]
        assert result["source_url"] == (
            "https://www.legislature.mi.gov/Laws/MCL?objectName=mcl-750-82"
        )
        assert result["retrieved_at"] is not None

    def test_invalid_section_raises(self) -> None:
        from state_statutes_mcp.core.exceptions import RefNotFoundError

        fixtures = Path(__file__).parent / "fixtures"
        served = {
            "https://www.legislature.mi.gov/Laws/MCL"
            "?objectName=mcl-999-999": (
                fixtures / "mi_section_invalid.html"
            ).read_text(encoding="utf-8"),
        }
        with mock_urlopen_serving(served):
            with pytest.raises(RefNotFoundError):
                get_section(_registry(), "MI", "MCL", "999", "999.999")
