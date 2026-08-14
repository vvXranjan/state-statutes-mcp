"""Tests for IllinoisAdapter.

Two tiers of section-retrieval test, deliberately kept separate and
separately labeled:

1. ``test_retrieve_section_synthetic_mock`` and friends, using
   ``SYNTHETIC_MOCK_SECTION_TEXT`` below -- a **hand-written string
   documented as synthetic**, not a saved real fixture, used only to
   exercise the parsing logic's mechanics (regex boundaries, group
   extraction, error paths). Its *content* (the citation/heading/body
   /history text) matches what was independently verified via two real
   fetches of https://www.ilga.gov/ftp/ILCS/Ch%200720/Act%200005/072000050K9-2.html
   during design/research -- see IllinoisAdapter's module docstring --
   but the surrounding whitespace/formatting here is written by hand
   for the test, not copied from a saved response.

2. ``test_retrieve_section_real_fixture``, which reads from
   ``tests/fixtures/illinois_720_ilcs_5_9-2.html`` and is skipped
   entirely if that file does not exist. No such fixture exists in
   this environment as of writing (ilga.gov is unreachable from this
   sandbox's network egress allowlist) -- this test exists so that
   dropping the real file in later immediately activates real
   end-to-end verification, without anyone needing to touch this test
   file again.
"""

from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest

from _mock_network import mock_urlopen as _mock_urlopen
from _mock_network import mock_urlopen_error

from state_statutes_mcp.adapters.illinois.adapter import IllinoisAdapter
from state_statutes_mcp.core.exceptions import (
    AdapterUnavailableError,
    NormalizationError,
    RefMismatchError,
)
from state_statutes_mcp.models.refs import ChapterRef, SectionRef, TitleRef

FIXTURES_DIR = Path(__file__).parent / "fixtures"
REAL_FIXTURE_PATH = FIXTURES_DIR / "illinois_720_ilcs_5_9-2.html"

# --- SYNTHETIC, hand-written mock -- NOT a saved real HTML response. ---
# Content matches the independently-verified real text for 720 ILCS
# 5/9-2 (see module docstring); markup/whitespace below is invented
# for this test only, deliberately including some tags with no
# specific names/classes/attributes, to prove the parser doesn't
# depend on any particular tag shape.
SYNTHETIC_MOCK_SECTION_TEXT = """
<html><body>
<p>(720 ILCS 5/9-2) (from Ch. 38, par. 9-2)</p>
<p>Sec. 9-2. Second degree murder.
(a) A person commits the offense of second degree murder when he or
she commits the offense of first degree murder as defined in
paragraph (1) or (2) of subsection (a) of Section 9-1 of this Code
and either of the following mitigating factors are present:
(b) Serious provocation is conduct sufficient to excite an intense
passion in a reasonable person.
(c) When evidence of either of the mitigating factors defined in
subsection (a) of this Section has been presented, the burden of
proof is on the defendant.
(d) Sentence. Second degree murder is a Class 1 felony.</p>
<p>(Source: P.A. 100-460, eff. 1-1-18.)</p>
</body></html>
"""

# A second synthetic mock without the optional "(from Ch. ...)" clause
# -- requirement 8.
SYNTHETIC_MOCK_NO_LEGACY_CITATION = """
<div>(720 ILCS 5/9-1)</div>
<div>Sec. 9-1. First degree murder.
(a) A person who kills an individual without lawful justification
commits first degree murder.</div>
<div>(Source: P.A. 89-203, eff. 7-21-95.)</div>
"""


def _make_ref(chapter: str, act: str, section: str) -> SectionRef:
    return SectionRef(
        chapter=ChapterRef(
            title=TitleRef(state_code="IL", identifier=chapter),
            identifier=act,
        ),
        identifier=section,
    )


class TestConcreteness:
    def test_adapter_is_concrete(self) -> None:
        assert IllinoisAdapter.__abstractmethods__ == frozenset()
        adapter = IllinoisAdapter()
        assert adapter.state_code == "IL"
        assert adapter.state_name == "Illinois"


class TestBuildUrl:
    def setup_method(self) -> None:
        self.adapter = IllinoisAdapter()

    def test_title_ref_url(self) -> None:
        ref = TitleRef(state_code="IL", identifier="720")
        assert (
            self.adapter.build_url(ref)
            == "https://www.ilga.gov/ftp/ILCS/Ch%200720/"
        )

    def test_chapter_ref_url(self) -> None:
        ref = ChapterRef(
            title=TitleRef(state_code="IL", identifier="720"), identifier="5"
        )
        assert (
            self.adapter.build_url(ref)
            == "https://www.ilga.gov/ftp/ILCS/Ch%200720/Act%200005/"
        )

    def test_section_ref_url(self) -> None:
        ref = _make_ref("720", "5", "9-2")
        assert (
            self.adapter.build_url(ref)
            == "https://www.ilga.gov/ftp/ILCS/Ch%200720/Act%200005/"
            "072000050K9-2.html"
        )


class TestRetrieveSectionSyntheticMock:
    """Parsing-mechanics tests against the hand-written synthetic mock
    documented at the top of this file. NOT a real-fixture test."""

    def setup_method(self) -> None:
        self.adapter = IllinoisAdapter()
        self.ref = _make_ref("720", "5", "9-2")

    def test_citation_heading_body_history(self) -> None:
        with _mock_urlopen(SYNTHETIC_MOCK_SECTION_TEXT):
            section = self.adapter.retrieve_section(self.ref)

        assert section.citation.raw == "(720 ILCS 5/9-2) (from Ch. 38, par. 9-2)"
        assert section.heading == "Second degree murder"
        assert "second degree murder" in section.text
        assert "Class 1 felony" in section.text
        assert section.amendment_notes == "(Source: P.A. 100-460, eff. 1-1-18.)"
        # No paragraph fidelity is claimed -- confirm the text really
        # is whitespace-normalized to single spaces, per the adapter's
        # documented trade-off, not accidentally preserving newlines.
        assert "\n" not in section.text

    def test_optional_legacy_citation_absent(self) -> None:
        ref = _make_ref("720", "5", "9-1")
        with _mock_urlopen(SYNTHETIC_MOCK_NO_LEGACY_CITATION):
            section = self.adapter.retrieve_section(ref)

        assert section.citation.raw == "(720 ILCS 5/9-1)"
        assert section.heading == "First degree murder"
        assert "without lawful justification" in section.text

    def test_citation_mismatch_raises_ref_mismatch_error(self) -> None:
        wrong_ref = _make_ref("720", "5", "9-99")
        with _mock_urlopen(SYNTHETIC_MOCK_SECTION_TEXT):
            with pytest.raises(RefMismatchError):
                self.adapter.retrieve_section(wrong_ref)

    def test_no_citation_found_raises_normalization_error(self) -> None:
        with _mock_urlopen("<p>nothing useful here</p>"):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(self.ref)

    def test_empty_body_raises_normalization_error(self) -> None:
        malformed = "(720 ILCS 5/9-2) Sec. 9-2. Second degree murder. (Source: P.A. 100-460, eff. 1-1-18.)"
        with _mock_urlopen(malformed):
            with pytest.raises(NormalizationError):
                self.adapter.retrieve_section(self.ref)

    def test_network_failure_raises_adapter_unavailable_error(self) -> None:
        adapter = IllinoisAdapter()
        ref = _make_ref("720", "5", "9-2")

        with mock_urlopen_error(
            urllib.error.URLError("simulated network failure")
        ):
            with pytest.raises(AdapterUnavailableError):
                adapter.retrieve_section(ref)


@pytest.mark.skipif(
    not REAL_FIXTURE_PATH.exists(),
    reason=(
        "Real fixture not available in this environment "
        "(ilga.gov unreachable from this sandbox's network egress "
        "allowlist). Drop the real saved HTML response at "
        f"{REAL_FIXTURE_PATH} to activate this test."
    ),
)
class TestRetrieveSectionRealFixture:
    """End-to-end test against a REAL saved response, once available.
    Currently skipped -- see class-level skip reason."""

    def test_real_fixture_parses(self) -> None:
        adapter = IllinoisAdapter()
        ref = _make_ref("720", "5", "9-2")
        real_html = REAL_FIXTURE_PATH.read_text(encoding="utf-8")
        with _mock_urlopen(real_html):
            section = adapter.retrieve_section(ref)
        assert section.heading == "Second degree murder"
        assert section.amendment_notes is not None