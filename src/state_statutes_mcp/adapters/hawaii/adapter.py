"""HawaiiAdapter: the Hawaii-specific concrete state adapter.

Source: the official Hawaii Revised Statutes at
``https://data.capitol.hawaii.gov`` -- anonymous, server-rendered,
Microsoft-Word-exported HTML with no authentication or API key.
``data.capitol.hawaii.gov`` is the official statute host (NOT
``www.capitol.hawaii.gov``).

This adapter implements the two identity properties and all five abstract
methods declared by ``BaseStateAdapter`` (``build_url``, ``list_titles``,
``list_chapters``, ``list_sections``, ``normalize``), plus the
adapter-owned ``retrieve_section`` convenience method required by the MCP
``get_section`` tool (see ``BaseStateAdapter``'s module docstring for that
requirement).

**VERIFIED facts this adapter relies on** (from ``docs/research/hawaii.md``;
all structures verified against real captures of the official host, Aug 17
2026):

* Base URL ``https://data.capitol.hawaii.gov``.
* Discovery:
  * Titles: ``{BASE}/hrsall`` -- 14 volume rows, one per printed volume
    of the HRS. ``TitleRef.identifier`` is the volume number (``"1"`` ..
    ``"14"``). No synthetic hierarchy: Title = Volume.
  * Chapters: ``{BASE}/hrsall/ChaptersByVolume.aspx?id={vol}`` -- one row
    per chapter of that volume, e.g. ``377`` / ``346C``, with the chapter
    page link ``/hrscurrent/Vol07_Ch0346-0398/HRS0377/HRS_0377-.htm``.
    Repealed chapters (names carrying ``(REPEALED)``, e.g. chapter 2
    ``STATUTE REVISION AND PUBLICATION (REPEALED)``) are still listed but,
    per the B11 brief, are NOT treated as normal chapter links and are
    skipped. The page also links front-matter documents (``01-USCON``,
    ``02-HNP/``, ``03-ORG/``, ``04-ADM/``, ``05-CONST/``, ``06-HHCA/``)
    that never match the chapter-row pattern.
  * Sections: the chapter page ``{BASE}/hrscurrent/{folder}/HRS_{chapter}-.htm``
    is a plain-text TOC whose section rows read ``377-1 Definitions``,
    ``377-4.5 Religious exemption from labor organization membership``
    (leading ``&#160;`` spacers, no hyperlinks). ``SectionRef.identifier``
    is the full ``{chapter}-{section}`` citation (e.g. ``"377-4.5"``,
    ``"1B-1"``). For chapter 1 the chapter page is the printed title page
    (``HRS_0001-.htm``), which also lists the title's chapters; the
    section-row pattern plus a chapter-prefix filter keep chapter rows
    (``1 Common Law; Construction of Laws``) out.
* URL construction (all VERIFIED against real captures):
  * The volume -> folder map is a VERIFIED constant (all 14 volumes); it is
    NOT arithmetically derivable (volume 7 lists chapters ``346-398A`` but
    its folder is ``Vol07_Ch0346-0398``). ``build_url`` keys off the volume
    number via ``_VOLUME_FOLDERS``.
  * Chapter directory/file: the numeric part of the chapter is zero-padded
    to 4 digits and the letter suffix is kept verbatim (``377`` -> ``0377``,
    ``1B`` -> ``0001B``, ``346C`` -> ``0346C``).
  * Section filename: the integer part is zero-padded to 4 digits and an
    optional decimal part is appended as ``_{decimal:04d}`` -- VERIFIED
    ``377-4.5`` -> ``HRS_0377-0004_0005.htm``, ``1-4.5`` ->
    ``HRS_0001-0004_0005.htm``, ``1-13.5`` -> ``HRS_0001-0013_0005.htm``,
    ``1B-1`` -> ``HRS_0001B-0001.htm``, ``701-119`` -> ``HRS_0701-0119.htm``.
* Section page structure (Word-exported, class-driven):
  * The operative content lives in ``<div class="WordSection1">``.
  * The section heading is the first ``<p class="RegularParagraphs">``: the
    heading text is everything up to the LAST ``</b>`` (the heading may be
    split across bold runs -- ``<b>§1</b>-<b>2&#160; Certain laws ...</b>``
    -- or the citation may sit in its own bold run --
    ``<b>[§1B-1]</b>&#160; <b>Rural areas ...</b>``). The page's own
    citation is recovered from the cleaned heading with
    ``[§]{chapter}-{section}`` and cross-checked against ``ref.identifier``
    (whitespace-normalized, so the split-bold ``§1 - 2`` matches ``1-2``).
  * The body is the joined remaining paragraphs before the first
    ``class="XNotes"`` block, matching ``<p class="RegularParagraphs">`` or
    ``<p class="oneParagraph">`` (the latter holds lettered/list items such
    as ``(1)``, ``(2)``).
  * The bracketed history ``[L ...; HRS §{ch}-{sec}]`` is inline at the end
    of the operative text; it is extracted into ``amendment_notes`` and
    stripped from ``text``.
  * Annotations (``Attorney General Opinions``, ``Law Journals and
    Reviews``, ``Case Notes``, ``Cross References`` -- all
    ``XNotesHeading``/``XNotes`` blocks) are excluded from statute text by
    splitting at the first ``class="XNotes"``.
* Repealed sections (VERIFIED: 701-119) render ``<b>§701-119</b> <b>
  &#160;REPEALED.&#160; </b>L 1988, c 260, §§4, 7; L 1996, c 104, §6.`` -- a
  ``REPEALED.`` heading with the repeal citation as the following text.
  Per the framework rule (a structural ``Repealed`` marker in place of body
  text, same decision as MissouriAdapter/RhodeIslandAdapter), the section
  is returned with ``heading="REPEALED."``, ``text=""``, the repeal
  citation in ``amendment_notes``, and ``status=REPEALED``. Repealed
  chapters (e.g. chapter 2) render a ``REPEALED.`` chapter page with no
  section rows.
* Citation: ``Haw. Rev. Stat. Section {chapter}-{section}``.
* Encoding: UTF-8 on all section/chapter/list pages (``<meta charset="utf-8">``
  in the Word header), so the shared UTF-8 ``fetch_url`` helper is used
  directly.

**HTTP 404 / missing-document behavior (UNVERIFIED directly):** for a
deliberately nonexistent chapter ``HRS0031`` in Volume 1, the fetch proxy
reported upstream ``Target URL returned error 404: Not Found`` and the
body is the IIS ``404 - File or directory not found.`` page. The mapping
HTTP 404 -> ``RefNotFoundError`` is implemented (same as MontanaAdapter)
per project convention; because the environment's live access to
``data.capitol.hawaii.gov`` is Cloudflare-blocked (HTTP 403), the 404 was
NOT observed via a direct socket and is explicitly marked UNVERIFIED
directly. Documented honestly in ``docs/research/hawaii.md``.
"""

from __future__ import annotations

import re
import urllib.error
from datetime import datetime, timezone
from typing import Sequence

from state_statutes_mcp.adapters._fetch import fetch_url
from state_statutes_mcp.adapters._htmltext import strip_tags
from state_statutes_mcp.adapters.base import BaseStateAdapter
from state_statutes_mcp.core.exceptions import (
    AdapterUnavailableError,
    NormalizationError,
    RefMismatchError,
    RefNotFoundError,
    UnsupportedRefError,
)
from state_statutes_mcp.models.citation import Citation
from state_statutes_mcp.models.documents import ParsedDocument
from state_statutes_mcp.models.hierarchy import HierarchyLevel, TocNode
from state_statutes_mcp.models.refs import ChapterRef, SectionRef, TitleRef
from state_statutes_mcp.models.statute_section import StatuteSection, StatuteStatus


class HawaiiAdapter(BaseStateAdapter):
    """Concrete state adapter for the official Hawaii Revised Statutes at
    data.capitol.hawaii.gov.

    Identity and all five of ``BaseStateAdapter``'s abstract methods are
    implemented, plus an adapter-owned ``retrieve_section`` convenience
    method (not part of the abstract contract). The HRS maps directly onto
    the framework's three-level ref model as Volume -> Chapter -> Section,
    with no synthetic hierarchy. See the module docstring.
    """

    BASE_URL = "https://data.capitol.hawaii.gov"
    DEFAULT_TIMEOUT_SECONDS = 30

    # Volume -> folder mapping, VERIFIED on all 14 volumes (Aug 17 2026).
    # The folder is a printed-range name and is NOT arithmetically derivable
    # from the volume id or the chapter numbers (e.g. volume 7 lists chapters
    # 346-398A but its folder is Vol07_Ch0346-0398).
    _VOLUME_FOLDERS: dict[str, str] = {
        "1": "Vol01_Ch0001-0042F",
        "2": "Vol02_Ch0046-0115",
        "3": "Vol03_Ch0121-0200D",
        "4": "Vol04_Ch0201-0257",
        "5": "Vol05_Ch0261-0319",
        "6": "Vol06_Ch0321-0344",
        "7": "Vol07_Ch0346-0398",
        "8": "Vol08_Ch0401-0429",
        "9": "Vol09_Ch0431-0435H",
        "10": "Vol10_Ch0436-0474",
        "11": "Vol11_Ch0476-0490",
        "12": "Vol12_Ch0501-0588",
        "13": "Vol13_Ch0601-0676",
        "14": "Vol14_Ch0701-0853",
    }

    # A volume row on /hrsall, e.g.
    # '<td class="text-left"><a href="ChaptersByVolume.aspx?id=1">VOLUME 1</a>
    #  </td><td class="text-right"><a href="ChaptersByVolume.aspx?id=1">1-42F</a></td>'.
    # Only the "VOLUME n" anchor text matches; the second cell's range text
    # (e.g. "1-42F") does not, so each row yields exactly one node.
    _TITLE_ROW = re.compile(
        r'ChaptersByVolume\.aspx\?id=(\d+)"[^>]*>(VOLUME \d+)</a>',
        re.DOTALL,
    )

    # A chapter row on ChaptersByVolume.aspx?id={vol}, e.g.
    # '<td class="text-left col-sm-1"><a href="/hrscurrent/Vol07_Ch0346-0398/
    #  HRS0377/HRS_0377-.htm">377</a></td><td class="text-left"><a href="...">
    #  HAWAII EMPLOYMENT RELATIONS ACT</a></td>'. The identifier is the
    # anchor text ("377", "346C"). Front-matter rows (01-USCON, 02-HNP/, ...)
    # use a different cell layout and never match.
    _CHAPTER_ROW = re.compile(
        r'<td class="text-left col-sm-1">\s*<a href="[^"]+"[^>]*>([^<]+)</a>'
        r"\s*</td>\s*<td class=\"text-left\">\s*<a href=\"[^\"]+\"[^>]*>(.*?)</a>",
        re.DOTALL,
    )

    # The operative content region of a section or chapter page.
    _WORD_SECTION = re.compile(
        r'<div class="WordSection1">(.*?)</div>', re.DOTALL
    )

    # A body paragraph on a section page (class RegularParagraphs for normal
    # paragraphs, oneParagraph for lettered/list items such as (1), (2)).
    _BODY_PARAGRAPH = re.compile(
        r'<p class="(?:RegularParagraphs|oneParagraph)">(.*?)</p>', re.DOTALL
    )

    # The page's own citation inside the cleaned heading, e.g. "§377-4.5 ...",
    # "[§1B-1] ...", or the split-bold "§1 - 2 ...". The optional bracket
    # wraps an optional § symbol. The inner group is whitespace-normalized
    # before comparison against ref.identifier.
    _CITATION = re.compile(r"[\[§]\s*§?\s*(\d+[A-Z]?\s*-\s*\d+(?:\.\d+)?)")

    # The inline, bracketed history citation at the end of the operative
    # text, e.g. "[L 1982, c 102, §2; am L 1983, c 124, §9]".
    _HISTORY_BRACKET = re.compile(r"(\[[^\[\]]*\])\s*$")

    # A structural repeal marker (heading exactly "REPEALED.").
    _REPEALED_MARKER = re.compile(r"^REPEALED\.?$", re.IGNORECASE)

    # A section row on a chapter TOC page after cleaning, e.g. "377-1
    # Definitions", "377-4.5 Religious exemption from labor organization
    # membership".
    _SECTION_ROW = re.compile(r"^(\d+[A-Z]?-\d+(?:\.\d+)?)\s+(.*)$")

    @property
    def state_code(self) -> str:
        """Two-letter USPS state code for Hawaii."""
        return "HI"

    @property
    def state_name(self) -> str:
        """Human-facing display name for Hawaii."""
        return "Hawaii"

    # ------------------------------------------------------------
    # URL construction helpers
    # ------------------------------------------------------------

    @staticmethod
    def _padded_chapter(chapter: str) -> str:
        """Zero-pad the numeric part of a chapter identifier to 4 digits and
        keep any letter suffix verbatim: ``"377"`` -> ``"0377"``, ``"1B"`` ->
        ``"0001B"``, ``"346C"`` -> ``"0346C"``.

        Raises:
            UnsupportedRefError: If ``chapter`` is not the ``{digits}{letters}``
                form this adapter addresses.
        """
        match = re.fullmatch(r"(\d+)([A-Z]*)", chapter)
        if match is None:
            raise UnsupportedRefError(
                f"HawaiiAdapter cannot address chapter {chapter!r}: HRS chapter "
                "identifiers are a digit string with an optional letter suffix "
                "(e.g. '377', '1B', '346C')."
            )
        digits, letters = match.groups()
        return f"{int(digits):04d}{letters}"

    @staticmethod
    def _section_filename(section: str) -> str:
        """Encode a section number into its 4-digit (plus optional decimal)
        filename component: ``"119"`` -> ``"0119"``, ``"4.5"`` ->
        ``"0004_0005"``, ``"13.5"`` -> ``"0013_0005"``.

        Raises:
            UnsupportedRefError: If ``section`` is not a positive integer or
                ``{integer}.{integer}`` decimal form.
        """
        if "." in section:
            whole, fraction = section.split(".", 1)
        else:
            whole, fraction = section, None
        if not whole.isdigit() or (fraction is not None and not fraction.isdigit()):
            raise UnsupportedRefError(
                f"HawaiiAdapter cannot address section {section!r}: HRS section "
                "identifiers are a positive integer with an optional decimal "
                "(e.g. '119', '4.5')."
            )
        filename = f"{int(whole):04d}"
        if fraction is not None:
            filename += f"_{int(fraction):04d}"
        return filename

    @staticmethod
    def _split_section_identifier(identifier: str) -> tuple[str, str]:
        """Split a full section identifier like ``"377-4.5"`` into its
        ``(chapter, section)`` parts: ``"377-4.5"`` -> ``("377", "4.5")``,
        ``"1B-1"`` -> ``("1B", "1")``.

        Raises:
            UnsupportedRefError: If ``identifier`` is not the
                ``{chapter}-{section}`` form this adapter addresses.
        """
        if "-" not in identifier:
            raise UnsupportedRefError(
                f"HawaiiAdapter cannot address section {identifier!r}: HRS "
                "section identifiers are the '{chapter}-{section}' citation "
                "form (e.g. '377-4.5', '1B-1')."
            )
        chapter, section = identifier.split("-", 1)
        return chapter, section

    def _folder_for_title(self, title_ref: TitleRef, *, what: str) -> str:
        """Resolve the ``VolXX_Ch...`` folder name for ``title_ref`` (the
        volume number), or raise ``UnsupportedRefError`` for an unknown one."""
        folder = self._VOLUME_FOLDERS.get(title_ref.identifier)
        if folder is None:
            raise UnsupportedRefError(
                f"HawaiiAdapter cannot address {what}: unknown HRS volume "
                f"{title_ref.identifier!r}; expected a volume number 1-14."
            )
        return folder

    # ------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------

    def build_url(self, ref: TitleRef | ChapterRef | SectionRef) -> str:
        """Construct the official Hawaii Revised Statutes URL for ``ref``.

        VERIFIED endpoint shapes (see docs/research/hawaii.md):

        * Section: ``{BASE}/hrscurrent/{folder}/HRS{padded}/
          HRS_{padded}-{section_filename}.htm`` where ``{folder}`` is the
          volume's VERIFIED folder constant, ``{padded}`` is the chapter
          number zero-padded to 4 digits with its letter suffix, and
          ``{section_filename}`` is the section's 4-digit (plus optional
          decimal) filename component.
        * Chapter: ``{BASE}/hrscurrent/{folder}/HRS{padded}/HRS_{padded}-.htm``
          -- the chapter's plain-text section-listing page.
        * Title: ``{BASE}/hrsall/ChaptersByVolume.aspx?id={vol}``.

        Args:
            ref: The title, chapter, or section to address.

        Returns:
            A URL string ready to be fetched.

        Raises:
            UnsupportedRefError: If ``ref``'s title is not an HRS volume
                (1-14), or if a section identifier is not the
                ``{chapter}-{section}`` form this adapter addresses, or the
                chapter part disagrees with ``ref.chapter``.
        """
        if isinstance(ref, SectionRef):
            chapter, section = self._split_section_identifier(ref.identifier)
            if chapter != ref.chapter.identifier:
                raise UnsupportedRefError(
                    f"HawaiiAdapter cannot address section {ref.identifier!r}: "
                    f"its chapter part {chapter!r} does not match the ref's "
                    f"chapter {ref.chapter.identifier!r}."
                )
            folder = self._folder_for_title(
                ref.chapter.title, what=f"section {ref.identifier!r}"
            )
            padded = self._padded_chapter(chapter)
            return (
                f"{self.BASE_URL}/hrscurrent/{folder}/HRS{padded}/"
                f"HRS_{padded}-{self._section_filename(section)}.htm"
            )
        elif isinstance(ref, ChapterRef):
            folder = self._folder_for_title(
                ref.title, what=f"chapter {ref.identifier!r}"
            )
            padded = self._padded_chapter(ref.identifier)
            return (
                f"{self.BASE_URL}/hrscurrent/{folder}/HRS{padded}/"
                f"HRS_{padded}-.htm"
            )
        elif isinstance(ref, TitleRef):
            self._folder_for_title(ref, what=f"title {ref.identifier!r}")
            return (
                f"{self.BASE_URL}/hrsall/ChaptersByVolume.aspx?id={ref.identifier}"
            )
        else:
            raise UnsupportedRefError(
                f"HawaiiAdapter.build_url does not support refs of type "
                f"{type(ref).__name__!r}."
            )

    # ------------------------------------------------------------
    # Shared fetch/HTML helpers
    # ------------------------------------------------------------

    def _fetch_html(self, url: str, *, what: str) -> str:
        """Fetch ``url`` and return its decoded HTML.

        Delegates the actual HTTP fetch to the shared
        :func:`~state_statutes_mcp.adapters._fetch.fetch_url` helper, so
        network failures are already wrapped into
        ``AdapterUnavailableError`` there. This method additionally maps an
        HTTP 404 into :class:`RefNotFoundError` -- the source was reached,
        but the addressed document does not resolve. Hawaii's real-HTTP-404
        behavior was observed only via the proxy's reported upstream status
        (UNVERIFIED directly; see the module docstring), so the mapping is
        kept per project convention; other network failures map to
        ``AdapterUnavailableError`` by project convention.

        Args:
            url: The URL to fetch.
            what: A short human-readable description of what is being
                fetched, used only to build a clear error message.

        Returns:
            The fetched HTML text.

        Raises:
            AdapterUnavailableError: If ``url`` cannot be reached for any
                reason other than an HTTP 404.
            RefNotFoundError: If ``url`` returns HTTP 404 (the document
                does not resolve on the Hawaii Revised Statutes site).
        """
        try:
            return fetch_url(url, what=what, timeout=self.DEFAULT_TIMEOUT_SECONDS)
        except AdapterUnavailableError as exc:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
                raise RefNotFoundError(
                    f"Could not fetch the {what} at {url!r}: it returned HTTP "
                    "404 and does not resolve on the Hawaii Revised Statutes "
                    "site."
                ) from exc
            raise

    @classmethod
    def _clean(cls, html_fragment: str) -> str:
        """Strip tags from ``html_fragment`` and collapse whitespace."""
        return " ".join(strip_tags(html_fragment).split())

    @classmethod
    def _clean_row_name(cls, html_fragment: str) -> str:
        """Clean a row's name cell: strip tags and collapse whitespace."""
        return cls._clean(html_fragment)

    # ------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------

    def list_titles(self) -> Sequence[TocNode]:
        """Enumerate every volume of the Hawaii Revised Statutes from the
        ``/hrsall`` index page.

        Each of the 14 printed HRS volumes is one title node. ``identifier``
        is the volume number; the name is the site's own ``VOLUME n`` label.

        Returns:
            A sequence of :class:`TocNode`, one per volume, in document
            order. Each node's ``ref`` is a :class:`TitleRef` whose
            ``identifier`` is the volume number.

        Raises:
            AdapterUnavailableError: If the index page cannot be fetched,
                or if no usable volume rows could be parsed from it.
        """
        url = f"{self.BASE_URL}/hrsall"
        html = self._fetch_html(url, what="Hawaii volume listing")

        titles = []
        seen: set[str] = set()
        for identifier, raw_name in self._TITLE_ROW.findall(html):
            if identifier in seen:
                continue
            seen.add(identifier)
            name = self._clean_row_name(raw_name)
            titles.append(
                TocNode(
                    level=HierarchyLevel.TITLE,
                    identifier=identifier,
                    name=name,
                    ref=TitleRef(state_code=self.state_code, identifier=identifier),
                )
            )

        if not titles:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable volume rows in it; the "
                "site's structure may have changed."
            )

        return tuple(titles)

    def list_chapters(self, title_ref: TitleRef) -> Sequence[TocNode]:
        """Enumerate every chapter under ``title_ref`` (an HRS volume) from
        ``ChaptersByVolume.aspx``.

        Each active chapter row is ``<td class="text-left col-sm-1">``
        carrying the chapter number anchor followed by the chapter-name
        anchor; the identifier is the anchor text (e.g. ``"377"``,
        ``"346C"``). Chapters whose names carry the ``(REPEALED)`` marker
        are still listed on the page but are NOT treated as normal chapter
        links (B11 brief) and are skipped. Front-matter rows (``01-USCON``,
        ``02-HNP/``, ``03-ORG/``, ``04-ADM/``, ``05-CONST/``, ``06-HHCA/``)
        use a different cell layout and never match.

        Args:
            title_ref: The parent volume to enumerate chapters under.

        Returns:
            A sequence of :class:`TocNode`, one per chapter, in document
            order. Each node's ``ref`` is a :class:`ChapterRef` whose
            ``identifier`` is the chapter number.

        Raises:
            UnsupportedRefError: If ``title_ref`` is not an HRS volume.
            RefNotFoundError: If the volume page returns HTTP 404.
            AdapterUnavailableError: If the volume page cannot be fetched
                for any other reason, or if no usable chapter rows could be
                parsed from it.
        """
        url = self.build_url(title_ref)
        html = self._fetch_html(url, what="Hawaii chapter listing")

        chapters = []
        seen: set[str] = set()
        for identifier, raw_name in self._CHAPTER_ROW.findall(html):
            if identifier in seen:
                continue
            name = self._clean_row_name(raw_name)
            if "(REPEALED)" in name.upper():
                continue
            seen.add(identifier)
            chapters.append(
                TocNode(
                    level=HierarchyLevel.CHAPTER,
                    identifier=identifier,
                    name=name,
                    ref=ChapterRef(title=title_ref, identifier=identifier),
                )
            )

        if not chapters:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable chapter rows in it; "
                "the site's structure may have changed."
            )

        return tuple(chapters)

    def list_sections(self, chapter_ref: ChapterRef) -> Sequence[TocNode]:
        """Enumerate every section under ``chapter_ref`` from the chapter's
        plain-text TOC page.

        The chapter page's section rows read ``377-1 Definitions`` /
        ``377-4.5 Religious exemption from labor organization membership``
        as plain text. Each section's identifier is the full
        ``{chapter}-{section}`` citation (e.g. ``"377-4.5"``); rows are
        filtered to the requested chapter. For chapter 1 the page is the
        printed title page and also lists the title's chapters -- those rows
        (``1 Common Law; Construction of Laws``) never match the section-row
        pattern. A repealed chapter (e.g. chapter 2) renders a ``REPEALED.``
        page with no section rows and is therefore reported as unresolvable.

        Args:
            chapter_ref: The parent chapter to enumerate sections under.

        Returns:
            A sequence of :class:`TocNode`, one per section, in document
            order. Each node's ``ref`` is a :class:`SectionRef` whose
            ``identifier`` is the full citation.

        Raises:
            UnsupportedRefError: If ``chapter_ref``'s title is not an HRS
                volume.
            RefNotFoundError: If the chapter page returns HTTP 404.
            AdapterUnavailableError: If the chapter page cannot be fetched
                for any other reason, or if no usable section rows could be
                parsed from it.
        """
        url = self.build_url(chapter_ref)
        html = self._fetch_html(url, what="Hawaii section listing")

        ws = self._WORD_SECTION.search(html)
        region = ws.group(1) if ws is not None else ""

        prefix = f"{chapter_ref.identifier}-"
        sections = []
        seen: set[str] = set()
        for raw in self._BODY_PARAGRAPH.findall(region):
            cleaned = self._clean(raw)
            match = self._SECTION_ROW.match(cleaned)
            if match is None:
                continue
            identifier, name = match.groups()
            if not identifier.startswith(prefix) or identifier in seen:
                continue
            seen.add(identifier)
            sections.append(
                TocNode(
                    level=HierarchyLevel.SECTION,
                    identifier=identifier,
                    name=name.strip(),
                    ref=SectionRef(chapter=chapter_ref, identifier=identifier),
                )
            )

        if not sections:
            raise AdapterUnavailableError(
                f"Fetched {url!r} but found no usable section rows in it; "
                f"chapter {chapter_ref.identifier!r} either does not resolve "
                "or the site's structure has changed."
            )

        return tuple(sections)

    # ------------------------------------------------------------
    # normalize
    # ------------------------------------------------------------

    def normalize(self, parsed: ParsedDocument, ref: SectionRef) -> StatuteSection:
        """Map ``parsed`` into a fully populated ``StatuteSection`` for
        Hawaii.

        Cross-checks ``parsed.raw_citation`` against ``ref`` before
        constructing anything: ``ref.identifier`` (the full
        ``{chapter}-{section}`` citation, e.g. ``"377-4.5"``) must appear
        verbatim within ``parsed.raw_citation`` (the ``Haw. Rev. Stat.
        Section 377-4.5`` citation). The stronger cross-check against the
        source page's own heading citation happens in
        :meth:`retrieve_section`.

        ``status`` is set to ``REPEALED`` only when the heading is a
        structural repeal marker (``REPEALED.`` in place of body text, e.g.
        section 701-119) -- the framework's own rule for a structural
        signal, same decision as MissouriAdapter/RhodeIslandAdapter. All
        other sections stay ``UNKNOWN``.

        Args:
            parsed: The intermediate document to normalize.
            ref: The section reference that was originally requested.

        Returns:
            A fully populated ``StatuteSection``.

        Raises:
            NormalizationError: If ``ref`` is not a Hawaii ref
                (``ref.state_code != "HI"``).
            RefMismatchError: If ``ref.identifier`` does not appear in
                ``parsed.raw_citation``.
        """
        if ref.state_code != self.state_code:
            raise NormalizationError(
                f"HawaiiAdapter.normalize cannot normalize a ref for state "
                f"{ref.state_code!r}; expected {self.state_code!r}."
            )

        if ref.identifier not in parsed.raw_citation:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"citation found in the parsed document: "
                f"{parsed.raw_citation!r}."
            )

        status = StatuteStatus.UNKNOWN
        if parsed.heading and self._REPEALED_MARKER.match(parsed.heading):
            status = StatuteStatus.REPEALED

        citation = Citation(
            state_code=self.state_code,
            raw=parsed.raw_citation,
        )

        return StatuteSection(
            ref=ref,
            citation=citation,
            heading=parsed.heading,
            text=parsed.text,
            status=status,
            amendment_notes=parsed.amendment_notes,
            source_url=parsed.source_url,
            retrieved_at=parsed.retrieved_at,
        )

    # ------------------------------------------------------------
    # End-to-end section retrieval (not part of BaseStateAdapter's
    # abstract contract -- mirrors the other adapters' retrieve_section)
    # ------------------------------------------------------------

    def retrieve_section(self, ref: SectionRef) -> StatuteSection:
        """Retrieve and normalize one Hawaii Revised Statutes section, end
        to end: :meth:`build_url` -> fetch the section page -> cross-check
        the page's own heading citation against ``ref`` -> parse the section
        into a :class:`ParsedDocument` -> :meth:`normalize` ->
        :class:`StatuteSection`.

        VERIFIED page structure (docs/research/hawaii.md): the operative
        content is ``<div class="WordSection1">``; the heading is the first
        body paragraph's text up to its last ``</b>`` (the heading may span
        multiple bold runs); the body is the remaining text plus the
        following ``RegularParagraphs``/``oneParagraph`` paragraphs up to
        the first annotation (``XNotes``) block; the inline bracketed
        history is extracted into ``amendment_notes``. A repealed section
        (e.g. 701-119) renders a ``REPEALED.`` heading with the repeal
        citation as the following text and no operative body -- it is
        returned with ``text=""`` and the repeal citation in
        ``amendment_notes`` (status ``REPEALED``).

        Args:
            ref: The section to retrieve. Must be a Hawaii ref
                (``ref.state_code == "HI"``); enforced by :meth:`normalize`,
                not this method directly.

        Returns:
            The fully normalized :class:`StatuteSection` for ``ref``.

        Raises:
            AdapterUnavailableError: If the section page cannot be fetched
                for any reason other than HTTP 404.
            RefNotFoundError: If the section page returns HTTP 404 (the
                section does not resolve).
            RefMismatchError: If the page's own heading citation disagrees
                with ``ref``. Also raised by :meth:`normalize` on citation
                disagreement.
            NormalizationError: If the section was located but the page is
                genuinely malformed (missing the WordSection1 region, the
                heading bold runs, or the page's citation line), or the body
                is empty after cleaning for a section that is not a
                legitimate repealed stub.
        """
        url = self.build_url(ref)
        html = self._fetch_html(url, what="Hawaii section page")

        ws = self._WORD_SECTION.search(html)
        if ws is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no "
                "WordSection1 region; the site's structure may have changed."
            )
        region = ws.group(1)

        # Annotations (Attorney General Opinions, Law Journals and Reviews,
        # Case Notes, Cross References) all live in XNotesHeading/XNotes
        # blocks after the operative text; everything at or after the first
        # "class=\"XNotes\"" is excluded from statute text.
        body_region = region.split('class="XNotes"', 1)[0]

        paragraphs = self._BODY_PARAGRAPH.findall(body_region)
        if not paragraphs:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no body "
                "paragraphs; the site's structure may have changed."
            )

        first = paragraphs[0]
        last_bold = first.rfind("</b>")
        if last_bold == -1:
            raise NormalizationError(
                f"Fetched {url!r} but the first body paragraph contained no "
                "heading element; the site's structure may have changed."
            )
        heading_html = first[: last_bold + 4]
        first_body_html = first[last_bold + 4 :]

        heading_text = self._clean(heading_html)
        citation_match = self._CITATION.search(heading_text)
        if citation_match is None:
            raise NormalizationError(
                f"Fetched {url!r} but the section page contained no numbered "
                "citation in its heading; the site's structure may have "
                "changed."
            )
        page_citation = re.sub(r"\s+", "", citation_match.group(1))
        if page_citation != ref.identifier:
            raise RefMismatchError(
                f"Requested section {ref.identifier!r} does not match the "
                f"citation found on the fetched page: {page_citation!r}."
            )

        heading = (
            heading_text[: citation_match.start()]
            + heading_text[citation_match.end() :]
        ).strip()
        # A bracket-wrapped citation ("[§1B-1]") leaves its closing bracket
        # behind after the citation match is removed.
        if heading.startswith("]"):
            heading = heading[1:].strip()

        body_parts = [first_body_html] + list(paragraphs[1:])
        text = "\n\n".join(
            part for part in (self._clean(p) for p in body_parts) if part
        ).strip()

        amendment_notes = None
        history = self._HISTORY_BRACKET.search(text)
        if history is not None:
            amendment_notes = history.group(1)
            text = text[: history.start()].rstrip()

        is_stub = (heading or "").lower().startswith("repealed")
        if is_stub:
            amendment_notes = amendment_notes or (text or None)
            text = ""
        elif not text:
            raise NormalizationError(
                f"Fetched {url!r} and resolved section {ref.identifier!r}, "
                "but its body text was empty after cleaning and its heading "
                "is not a legitimate repealed stub; the section is likely "
                "empty or the site's structure has changed."
            )

        raw_citation = f"Haw. Rev. Stat. Section {ref.identifier}"
        parsed = ParsedDocument(
            raw_citation=raw_citation,
            heading=heading,
            text=text,
            amendment_notes=amendment_notes,
            source_url=url,
            retrieved_at=datetime.now(timezone.utc),
        )

        return self.normalize(parsed, ref)
