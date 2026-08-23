"""Shared minimal PDF text-extraction helper.

Decodes a PDF document's bytes into plain text, page by page, in order.
This is the generic, state-agnostic bottom half of the PDF retrieval
path: it exists solely so a future PDF-based state adapter can turn a
binary response body into text without caring about the PDF format.

Deliberately narrow:

* Only PDF decoding/extraction lives here — no citation parsing, no
  heading parsing, no history parsing, no statute normalization, and no
  state-specific regexes. All of that belongs in the concrete adapter
  that consumes the extracted text.
* ``extract_pdf_text`` returns the concatenation of every page's text in
  page order. Callers that need per-page structure (unlikely for statute
  sources) can use ``pypdf`` directly; this helper exists for the common
  "whole document as one string" case.

Text reconstruction: most PDFs extract cleanly with pypdf's default
mode. A class of documents (VERIFIED for the Iowa Code's section PDFs)
position every word as its own separately-placed text operation, which
makes default extraction collapse to one word per line. For those, this
helper detects the fragmentation (a page whose non-empty lines are
overwhelmingly single words) and re-extracts that page in pypdf's layout
mode, which recovers the visual line structure; the layout-mode output is
emitted bottom-up, so the lines are reversed back into reading order.
PDFs that extract cleanly in default mode (e.g. the Kentucky Code's) are
never re-extracted, so their output is unchanged.

Errors follow the existing framework convention: if the bytes cannot be
parsed as a PDF, the underlying failure is wrapped into
:class:`~state_statutes_mcp.core.exceptions.AdapterUnavailableError` —
the same "the source could not be consumed" mapping the fetch helpers use
for unreachable sources. A document that parses but yields no usable text
is NOT an error for this utility: whether empty extraction is a
legitimate stub (repealed sections) or a ``NormalizationError`` is a
per-state decision that belongs in the consuming adapter.
"""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from state_statutes_mcp.core.exceptions import AdapterUnavailableError

# A page whose non-empty lines are mostly single words is the signature of
# a per-word-positioned PDF (see module docstring). Above this fraction we
# treat the default extraction as fragmented and re-extract in layout mode.
_FRAGMENTATION_THRESHOLD = 0.6


def _page_text(page) -> str:
    """Extract one page's text, falling back to layout mode if the default
    extraction is pathologically fragmented (per-word-positioned PDFs)."""
    text = page.extract_text() or ""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return text
    single_word = sum(1 for line in lines if len(line.split()) == 1)
    if single_word / len(lines) <= _FRAGMENTATION_THRESHOLD:
        return text
    layout = page.extract_text(extraction_mode="layout") or ""
    layout_lines = [line for line in layout.splitlines() if line.strip()]
    return "\n".join(reversed(layout_lines))


def extract_pdf_text(data: bytes) -> str:
    """Extract the text of ``data`` (a PDF document) as one string.

    All pages are read in document order and their extracted text is
    concatenated; the pages are not otherwise processed or cleaned.

    Args:
        data: The raw bytes of a PDF document.

    Returns:
        The concatenated text of every page, in page order. May be empty
        if the document is valid but has no extractable text.

    Raises:
        AdapterUnavailableError: If ``data`` cannot be parsed as a PDF
            (corrupt, truncated, or not a PDF at all).
    """
    try:
        reader = PdfReader(BytesIO(data))
        return "".join(_page_text(page) for page in reader.pages)
    except Exception as exc:
        raise AdapterUnavailableError(
            f"Could not extract text from PDF data: {exc}"
        ) from exc