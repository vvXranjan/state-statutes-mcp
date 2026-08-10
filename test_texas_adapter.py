"""Local tests for TexasAdapter.retrieve_section against the real
uploaded texas_current_pe19.html.

No network calls are made: urllib.request.urlopen is monkeypatched to
serve the local HTML file's bytes for the expected TCSS chapter URL,
so these tests exercise the actual parsing/boundary logic against real
markup while staying fully offline.

Run with:
    PYTHONPATH=. python3 -m pytest test_texas_adapter.py -v
or:
    PYTHONPATH=. python3 test_texas_adapter.py
"""

from __future__ import annotations

import io
import unittest
from contextlib import contextmanager
from unittest import mock

from state_statutes_mcp.adapters.texas.adapter import TexasAdapter
from state_statutes_mcp.core.exceptions import NormalizationError, RefMismatchError
from state_statutes_mcp.models.refs import ChapterRef, SectionRef, TitleRef

HTML_PATH = "texas_current_pe19.html"
EXPECTED_CHAPTER_URL = (
    "https://tcss.legis.texas.gov/resources/PE/htm/PE.19.htm"
)

with open(HTML_PATH, encoding="utf-8") as f:
    _PE19_HTML = f.read()


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


@contextmanager
def _mock_urlopen_serving(url_to_html: dict[str, str]):
    def fake_urlopen(url, timeout=None):
        if url not in url_to_html:
            raise AssertionError(f"Unexpected URL fetched in test: {url!r}")
        return _FakeResponse(url_to_html[url].encode("utf-8"))

    with mock.patch(
        "state_statutes_mcp.adapters.texas.adapter.urllib.request.urlopen",
        side_effect=fake_urlopen,
    ):
        yield


def _pe19_ref(identifier: str) -> SectionRef:
    return SectionRef(
        chapter=ChapterRef(
            title=TitleRef(state_code="TX", identifier="PE"),
            identifier="19",
        ),
        identifier=identifier,
    )


class TexasAdapterBuildUrlTest(unittest.TestCase):
    def test_chapter_url_uses_tcss_host(self):
        adapter = TexasAdapter()
        ref = _pe19_ref("19.01").chapter
        self.assertEqual(adapter.build_url(ref), EXPECTED_CHAPTER_URL)


class TexasAdapterRetrieveSectionTest(unittest.TestCase):
    def setUp(self):
        self.adapter = TexasAdapter()

    def test_retrieve_19_01(self):
        with _mock_urlopen_serving({EXPECTED_CHAPTER_URL: _PE19_HTML}):
            section = self.adapter.retrieve_section(_pe19_ref("19.01"))

        self.assertEqual(section.citation.raw, "Sec. 19.01. TYPES OF CRIMINAL HOMICIDE.")
        self.assertEqual(section.heading, "TYPES OF CRIMINAL HOMICIDE.")
        self.assertIn(
            "A person commits criminal homicide if he intentionally, "
            "knowingly, recklessly, or with criminal negligence causes "
            "the death of an individual.",
            section.text,
        )
        self.assertIn("Criminal homicide is murder, capital murder", section.text)
        self.assertIsNotNone(section.amendment_notes)
        self.assertTrue(section.amendment_notes.startswith("Acts 1973, 63rd Leg."))
        self.assertEqual(section.source_url, f"{EXPECTED_CHAPTER_URL}#19.01")
        self.assertIsNotNone(section.retrieved_at)

    def test_retrieve_19_02(self):
        with _mock_urlopen_serving({EXPECTED_CHAPTER_URL: _PE19_HTML}):
            section = self.adapter.retrieve_section(_pe19_ref("19.02"))

        self.assertEqual(section.citation.raw, "Sec. 19.02. MURDER.")
        self.assertEqual(section.heading, "MURDER.")
        self.assertIn("In this section:", section.text)
        self.assertIn("Adequate cause", section.text)
        self.assertIn(
            "It is a defense to prosecution under Subsection (b)(4)",
            section.text,
        )
        # The amendment_notes block legitimately contains later
        # "Amended by:" / bill-history paragraphs -- confirm those
        # made it in verbatim, not just the first Acts line.
        self.assertIn("Amended by:", section.amendment_notes)
        self.assertIn("Ch. 910 (H.B.", section.amendment_notes)

    def test_19_01_does_not_leak_into_19_02(self):
        """19.01's block must stop at the 19.02 anchor, not spill over
        into 19.02's body -- and must not be confused by 19.03's body
        text, which references "Section 19.02(b)(1)" inline."""
        with _mock_urlopen_serving({EXPECTED_CHAPTER_URL: _PE19_HTML}):
            section_01 = self.adapter.retrieve_section(_pe19_ref("19.01"))
            section_02 = self.adapter.retrieve_section(_pe19_ref("19.02"))
            section_03 = self.adapter.retrieve_section(_pe19_ref("19.03"))

        # 19.01 is short and self-contained; MURDER-specific content
        # must not appear in it.
        self.assertNotIn("MURDER", section_01.text)
        self.assertNotIn("Adequate cause", section_01.text)
        self.assertNotIn("In this section:", section_01.text)

        # 19.02's own block must not contain 19.03's CAPITAL MURDER
        # content.
        self.assertNotIn("CAPITAL MURDER", section_02.text)
        self.assertNotIn("peace officer or fireman", section_02.text)

        # 19.03's body legitimately *mentions* "Section 19.02(b)(1)" in
        # prose -- that inline mention must not have been mistaken for
        # a boundary, i.e. 19.03's own real content must still be
        # present in full.
        self.assertIn("murders a peace officer or fireman", section_03.text)
        self.assertIn("capital felony", section_03.text)

    def test_unknown_section_raises_normalization_error(self):
        with _mock_urlopen_serving({EXPECTED_CHAPTER_URL: _PE19_HTML}):
            with self.assertRaises(NormalizationError):
                self.adapter.retrieve_section(_pe19_ref("19.99"))

    def test_ref_mismatch_is_detected_via_normalize(self):
        """Directly exercise normalize()'s RefMismatchError path (the
        contract retrieve_section relies on) with a parsed document
        whose citation doesn't match the requested ref."""
        from state_statutes_mcp.models.documents import ParsedDocument

        mismatched_ref = _pe19_ref("19.05")
        parsed = ParsedDocument(
            raw_citation="Sec. 19.01. TYPES OF CRIMINAL HOMICIDE.",
            heading="TYPES OF CRIMINAL HOMICIDE.",
            text="(a) A person commits criminal homicide ...",
        )
        with self.assertRaises(RefMismatchError):
            self.adapter.normalize(parsed, mismatched_ref)


if __name__ == "__main__":
    unittest.main()
