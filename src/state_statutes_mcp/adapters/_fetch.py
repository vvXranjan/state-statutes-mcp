"""Shared minimal HTTP fetch helpers.

Centralizes the genuinely duplicated pieces of networking
infrastructure shared by every adapter so far: a single
``urllib.request.urlopen`` call with a timeout, whose content is returned
as decoded text (:func:`fetch_url`, for HTML sources) or as raw bytes
(:func:`fetch_bytes`, for binary sources such as PDFs), and whose network
failures are wrapped into
:class:`~state_statutes_mcp.core.exceptions.AdapterUnavailableError`.

Deliberately minimal and NOT a general-purpose HTTP client: no retries,
no caching, no sessions, no rate limiting, no connection pooling. Those
are future decisions, gated on the framework's later
fetcher/parser-collaborator milestone (see ``BaseStateAdapter``'s module
docstring).

State-specific behavior stays in each adapter: these helpers only fetch
raw bytes (and decode them, for :func:`fetch_url`); any
cleaning/stripping/parsing of the result is the adapter's concern via
:func:`state_statutes_mcp.adapters._htmltext.strip_tags` or the PDF
extraction helper :func:`state_statutes_mcp.adapters._pdftext.extract_pdf_text`.
"""

from __future__ import annotations

import urllib.error
import urllib.request

from state_statutes_mcp.core.exceptions import AdapterUnavailableError


def fetch_url(url: str, *, what: str, timeout: float = 30) -> str:
    """Fetch ``url`` and return its content as decoded text.

    Args:
        url: The URL to fetch.
        what: A short human-readable description of what is being
            fetched, used only to build a clear error message (e.g.
            "RCW section page").
        timeout: Socket timeout in seconds.

    Returns:
        The fetched content, decoded as UTF-8 with undecodable bytes
        replaced, un-cleaned (raw text, not tag-stripped).

    Raises:
        AdapterUnavailableError: If ``url`` cannot be reached (network
            failure or non-2xx HTTP response).
    """
    try:
        with urllib.request.urlopen(  # noqa: S310
            url,
            timeout=timeout,
        ) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AdapterUnavailableError(
            f"Could not reach the {what} at {url!r}: {exc}"
        ) from exc


def fetch_bytes(url: str, *, what: str, timeout: float = 30) -> bytes:
    """Fetch ``url`` and return its content as raw bytes, undecoded.

    This is the binary counterpart of :func:`fetch_url`: it performs the
    exact same single ``urllib.request.urlopen`` call with the same
    timeout and the same error mapping, but returns
    ``response.read()`` as-is instead of UTF-8-decoding it. It exists for
    sources whose content is not text — most notably PDF documents —
    where decoding to text (or worse, decoding with ``errors="replace"``)
    would silently corrupt the payload before the caller ever sees it.

    Deliberately minimal, matching :func:`fetch_url`: no retries, no
    sessions, no caching, no Content-Type detection, no size limits. The
    caller decides what the bytes mean and how to parse them.

    Args:
        url: The URL to fetch.
        what: A short human-readable description of what is being
            fetched, used only to build a clear error message (e.g.
            "Kentucky statute PDF").
        timeout: Socket timeout in seconds.

    Returns:
        The fetched content as raw bytes, un-decoded and unmodified.

    Raises:
        AdapterUnavailableError: If ``url`` cannot be reached (network
            failure or non-2xx HTTP response).
    """
    try:
        with urllib.request.urlopen(  # noqa: S310
            url,
            timeout=timeout,
        ) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AdapterUnavailableError(
            f"Could not reach the {what} at {url!r}: {exc}"
        ) from exc