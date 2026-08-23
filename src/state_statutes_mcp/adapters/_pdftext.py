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
        return "".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise AdapterUnavailableError(
            f"Could not extract text from PDF data: {exc}"
        ) from exc