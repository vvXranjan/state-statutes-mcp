"""Shared HTML text-cleaning helpers.

Only genuinely shared, mechanical HTML text-cleaning behavior lives here:
HTML comment removal, tag stripping, HTML entity decoding, and whitespace
normalization. State-specific parsing patterns (regexes anchored to a
particular state's confirmed markup) deliberately do NOT live here -- see
each state adapter's module docstring for those.

The one behavioral switch this module exposes is ``preserve_block_breaks``:

* ``False`` (default): all whitespace collapses to single spaces. Used by
  ``WashingtonAdapter`` (which cleans small, already-isolated fragments)
  and ``IllinoisAdapter`` (whose raw HTML tag structure has not been
  verified, so no paragraph fidelity is claimed -- see its module
  docstring).
* ``True``: block-level tag boundaries are preserved as newlines, so
  blank-line paragraph breaks survive tag-stripping. Used by
  ``TexasAdapter``, whose chapter-document parsing depends on preserving
  those boundaries.

Removed tags are replaced with a single space -- never the empty string --
so that two words separated by a removed tag are not jammed together.
"""

from __future__ import annotations

import html
import re

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")

# Block-level tags whose open tag is replaced with a newline when
# ``preserve_block_breaks`` is True, so that tag-stripping does not run
# separate lines/cells together into one unbroken string.
_BLOCK_TAG_OPEN = re.compile(r"<(?:p|div|tr|li|br|h[1-6])\b[^>]*>", re.IGNORECASE)


def strip_tags(text: str, preserve_block_breaks: bool = False) -> str:
    """Strip HTML comments and tags from ``text``, decode HTML entities,
    and normalize whitespace.

    Args:
        text: The HTML fragment or page to clean.
        preserve_block_breaks: If True, block-level tag boundaries are
            preserved as newlines (blank-line paragraph breaks survive).
            If False (default), all whitespace, including any original
            newlines, collapses to single spaces.

    Returns:
        The cleaned plain text.
    """
    without_comments = _COMMENT.sub(" ", text)
    if preserve_block_breaks:
        without_comments = _BLOCK_TAG_OPEN.sub("\n", without_comments)
    without_tags = _TAG.sub(" ", without_comments)
    decoded = html.unescape(without_tags)
    if preserve_block_breaks:
        lines = (" ".join(line.split()) for line in decoded.splitlines())
        return "\n".join(line for line in lines if line)
    return " ".join(decoded.split())