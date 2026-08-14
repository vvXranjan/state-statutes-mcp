"""Shared minimal HTTP fetch helper.

Centralizes the one genuinely duplicated piece of networking
infrastructure shared by every adapter so far: a single
``urllib.request.urlopen`` call with a timeout, whose content is decoded
and returned, and whose network failures are wrapped into
:class:`~state_statutes_mcp.core.exceptions.AdapterUnavailableError`.

Deliberately minimal and NOT a general-purpose HTTP client: no retries,
no caching, no sessions, no rate limiting, no connection pooling. Those
are future decisions, gated on the framework's later
fetcher/parser-collaborator milestone (see ``BaseStateAdapter``'s module
docstring).

State-specific behavior stays in each adapter: this helper only fetches
raw bytes and decodes them; any cleaning/stripping of the result is the
adapter's concern via :func:`state_statutes_mcp.adapters._htmltext.strip_tags`.
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