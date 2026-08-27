# state-statutes-mcp

An MCP (Model Context Protocol) server that retrieves U.S. state statutes
from the official state sources via state-specific adapters.

## Status

**40 / 50 states implemented** on the `feature/framework` branch.

| Code | State | Code | State |
|------|-------|------|-------|
| AK | Alaska | MN | Minnesota |
| AL | Alabama | MO | Missouri |
| AZ | Arizona | MT | Montana |
| CA | California | NC | North Carolina |
| CO | Colorado | ND | North Dakota |
| CT | Connecticut | NE | Nebraska |
| DE | Delaware | NH | New Hampshire |
| FL | Florida | NM | New Mexico |
| HI | Hawaii | NV | Nevada |
| IA | Iowa | OH | Ohio |
| ID | Idaho | OK | Oklahoma |
| IL | Illinois | OR | Oregon |
| KS | Kansas | RI | Rhode Island |
| KY | Kentucky | SD | South Dakota |
| MA | Massachusetts | TX | Texas |
| MD | Maryland | VA | Virginia |
| ME | Maine | WA | Washington |
| MI | Michigan | WI | Wisconsin |
| SC | South Carolina | WV | West Virginia |
| VT | Vermont | WY | Wyoming |

Each state is served by its own adapter under
`src/state_statutes_mcp/adapters/{state}/adapter.py`, registered explicitly
in `server.py`. Adapters are grouped by retrieval family (one-file-per-section
HTML, chapter-document HTML, JSON API, and PDF); see `docs/research/` for the
per-state verification notes and `docs/research/state_family_matrix.md` for
the 50-state family plan.

## Architecture

```
MCP client
   ↓ (stdio)
server.py — MCP server, builds the AdapterRegistry
   ↓
server_tools.py — pure, state-agnostic tool functions
   ↓
core/registry.py — AdapterRegistry (explicit instance map, state code → adapter)
   ↓
adapters/base.py — BaseStateAdapter (build_url, list_titles, list_chapters,
                   list_sections, normalize + adapter-owned retrieve_section)
   ↓
per-state adapter → official state source → parse → normalize → StatuteSection
```

Shared helpers: `adapters/_fetch.py` (network, text + raw bytes + GraphQL
POST), `adapters/_htmltext.py` (tag stripping), `adapters/_pdftext.py` (PDF text
extraction). Models: `TitleRef → ChapterRef → SectionRef` refs,
`TocNode`, `StatuteSection`, `Citation`. Errors: framework exception
hierarchy rooted at `StateStatutesError`.

## Tools

- `list_states` — every supported state
- `list_titles(state_code)` — top-level titles
- `list_chapters(state_code, title)` — chapters under a title
- `list_sections(state_code, title, chapter)` — sections under a chapter
- `get_section(state_code, title, chapter, section)` — one normalized section

State-specific identifiers (from `list_titles`/`list_chapters`/
`list_sections`) are used verbatim by `get_section`; examples: WA
`title=49, chapter=60, section=49.60.010`, VA `title=18.2, chapter=4,
section=18.2-51`, MA `title="Part I Title I", chapter=4, section=7`.

## Usage

```bash
python -m state_statutes_mcp.server
```

Run from the project root with the package importable (e.g.
`PYTHONPATH=src` or an editable install).

## Development

```bash
.venv/bin/python -m pytest -q          # full suite
.venv/bin/python -m compileall -q src  # syntax check
git diff --check                       # whitespace check
```

Every adapter is tested offline against real captured fixtures in
`tests/fixtures/` (verbatim slices of the official sources) using the
shared network mock in `tests/_mock_network.py` — the real
`urllib.request.urlopen` boundary is mocked, never adapter internals.

## Roadmap

- **10 states remain**: AR, GA, IN, LA, MS, NJ, NY, PA, TN, UT.
- **Implemented adapter families**: Kentucky, Iowa, New Mexico, Oklahoma,
  Wyoming, and Colorado are the PDF-family adapters (shared binary-fetch +
  PDF-extraction infrastructure); Alabama is the framework's first
  GraphQL/JSON-POST adapter (the official ALISON Code API); California is
  the framework's first fully server-rendered-HTML adapter (leginfo
  per-section pages, no JS or bulk archive); Michigan is the framework's
  first archived-official-fixture HTML adapter with a synthetic title
  (legislature.mi.gov, verified through Wayback captures); Alaska is the
  framework's first ISO-8859-1 archived-fixture adapter with citation-driven
  TOC discovery and section retrieval (akleg.gov, verified through Wayback
  captures).
- **Blocked from this environment**: Arkansas, Utah, and New York
  (TCP/TLS unreachable or API-key gated); Pennsylvania, Indiana,
  Louisiana, and Tennessee (robots-blocked, JS-only, or LexisNexis-
  hosted); Mississippi and New Jersey (Lexis/Folio walls).
- See `docs/research/` for planning notes.
