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

import pytest

from _mock_network import mock_urlopen, mock_urlopen_error, mock_urlopen_serving

from state_statutes_mcp.adapters.delaware.adapter import DelawareAdapter
from state_statutes_mcp.adapters.illinois.adapter import IllinoisAdapter
from state_statutes_mcp.adapters.texas.adapter import TexasAdapter
from state_statutes_mcp.adapters.virginia.adapter import VirginiaAdapter
from state_statutes_mcp.adapters.washington.adapter import WashingtonAdapter
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
    return registry


class TestListStates:
    def test_returns_all_registered_states(self) -> None:
        result = list_states(_registry())

        assert result == [
            {"state_code": "DE", "state_name": "Delaware"},
            {"state_code": "IL", "state_name": "Illinois"},
            {"state_code": "TX", "state_name": "Texas"},
            {"state_code": "VA", "state_name": "Virginia"},
            {"state_code": "WA", "state_name": "Washington"},
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