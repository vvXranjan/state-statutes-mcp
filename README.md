# state-statutes-mcp

An MCP (Model Context Protocol) server that retrieves U.S. state statutes
from the official state sources via state-specific adapters.

## Status

**32 / 50 states implemented** on the `feature/framework` branch.

| Code | State | Code | State |
|------|-------|------|-------|
| AZ | Arizona | MN | Minnesota |
| CT | Connecticut | MO | Missouri |
| DE | Delaware | MT | Montana |
| FL | Florida | NC | North Carolina |
| HI | Hawaii | ND | North Dakota |
| IA | Iowa | NE | Nebraska |
| ID | Idaho | NH | New Hampshire |
| IL | Illinois | NV | Nevada |
| KS | Kansas | OH | Ohio |
| KY | Kentucky | OR | Oregon |
| MA | Massachusetts | RI | Rhode Island |
| MD | Maryland | SC | South Carolina |
| ME | Maine | VA | Virginia |
| SD | South Dakota | VT | Vermont |
| TX | Texas | WI | Wisconsin |
| WA | Washington | WV | West Virginia |

Each state is served by its own adapter under
`src/state_statutes_mcp/adapters/{state}/adapter.py`, registered explicitly
in `server.py`. Adapters are grouped by retrieval family (one-file-per-section
HTML, chapter-document HTML, and JSON API); see `docs/research/` for the
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

Shared helpers: `adapters/_fetch.py` (network), `adapters/_htmltext.py`
(tag stripping). Models: `TitleRef → ChapterRef → SectionRef` refs,
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

- 20 states remain. The next realistic candidates are the PDF-family states
  (Kentucky, Iowa, New Mexico, Oklahoma) and Michigan (pending re-verification
  of its host). Ten states (GA, AR, CO, TN, MS, IN, AL, CA, NY, PA) are
  currently stopped behind auth walls / API keys / JS-only interfaces.
- See `docs/ROADMAP.md` (empty) and `docs/research/` for planning notes.