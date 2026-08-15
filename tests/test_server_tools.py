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

import json
import urllib.error
from pathlib import Path

import pytest

from _mock_network import mock_urlopen, mock_urlopen_error, mock_urlopen_serving

from state_statutes_mcp.adapters.arizona.adapter import ArizonaAdapter
from state_statutes_mcp.adapters.delaware.adapter import DelawareAdapter
from state_statutes_mcp.adapters.florida.adapter import FloridaAdapter
from state_statutes_mcp.adapters.illinois.adapter import IllinoisAdapter
from state_statutes_mcp.adapters.kansas.adapter import KansasAdapter
from state_statutes_mcp.adapters.maine.adapter import MaineAdapter
from state_statutes_mcp.adapters.minnesota.adapter import MinnesotaAdapter
from state_statutes_mcp.adapters.missouri.adapter import MissouriAdapter
from state_statutes_mcp.adapters.north_dakota.adapter import NorthDakotaAdapter
from state_statutes_mcp.adapters.south_dakota.adapter import SouthDakotaAdapter
from state_statutes_mcp.adapters.texas.adapter import TexasAdapter
from state_statutes_mcp.adapters.vermont.adapter import VermontAdapter
from state_statutes_mcp.adapters.virginia.adapter import VirginiaAdapter
from state_statutes_mcp.adapters.washington.adapter import WashingtonAdapter
from state_statutes_mcp.adapters.west_virginia.adapter import WestVirginiaAdapter
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


def _registry() -> AdapterRegistry:
    """Build the same registry the real server would use."""
    registry = AdapterRegistry()
    registry.register(WashingtonAdapter())
    registry.register(TexasAdapter())
    registry.register(IllinoisAdapter())
    registry.register(VirginiaAdapter())
    registry.register(DelawareAdapter())
    registry.register(FloridaAdapter())
    registry.register(SouthDakotaAdapter())
    registry.register(ArizonaAdapter())
    registry.register(KansasAdapter())
    registry.register(MaineAdapter())
    registry.register(MinnesotaAdapter())
    registry.register(MissouriAdapter())
    registry.register(NorthDakotaAdapter())
    registry.register(VermontAdapter())
    registry.register(WestVirginiaAdapter())
    return registry


class TestListStates:
    def test_returns_all_registered_states(self) -> None:
        result = list_states(_registry())

        assert result == [
            {"state_code": "AZ", "state_name": "Arizona"},
            {"state_code": "DE", "state_name": "Delaware"},
            {"state_code": "FL", "state_name": "Florida"},
            {"state_code": "IL", "state_name": "Illinois"},
            {"state_code": "KS", "state_name": "Kansas"},
            {"state_code": "ME", "state_name": "Maine"},
            {"state_code": "MN", "state_name": "Minnesota"},
            {"state_code": "MO", "state_name": "Missouri"},
            {"state_code": "ND", "state_name": "North Dakota"},
            {"state_code": "SD", "state_name": "South Dakota"},
            {"state_code": "TX", "state_name": "Texas"},
            {"state_code": "VA", "state_name": "Virginia"},
            {"state_code": "VT", "state_name": "Vermont"},
            {"state_code": "WA", "state_name": "Washington"},
            {"state_code": "WV", "state_name": "West Virginia"},
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
