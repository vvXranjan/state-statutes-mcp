B12 Replacement Research — Post-Kentucky (29/50)

Research only. No source touched, no adapters written, no commits, no pushes.

Correction to the candidate list before starting

Per the standing rule not to trust the matrix (or, here, the candidate list itself) without direct verification:

Vermont is already implemented. It shipped in the very first batch (Maine + Missouri + Vermont + West Virginia). It is not a valid B12 candidate and I did not research it as one.

New Jersey was already ruled out at the B11 stage — its primary interface (lis.njleg.state.nj.us) is a Folio/NXT keyword-search database with no deterministic per-section URL, which is precisely what this brief's own "avoid: search-only interfaces with no deterministic retrieval" rules out. I did not re-research it as a candidate; see the note at the end on the bulk-ZIP fallback, which is a separate, still-open question.

That left one candidate already in progress (Massachusetts) and the requirement to find at least one genuinely new one. I live-tested two new candidates this session: Oklahoma (rejected — see below) and New York (viable but doesn't cleanly meet the "avoid authentication" criterion). Massachusetts is the only candidate that clears every criterion in the brief.

Candidate 1: Massachusetts — VERIFIED, READY (with one caveat)

This state has been through three prior deep-research sessions (a 27-point pass, then two follow-up sessions specifically targeting the error-boundary gap). I re-verified live this session rather than trusting that history at face value.

Official source: malegislature.gov/Laws/GeneralLaws — VERIFIED (re-fetched this session: Part I index page, Chapter 4 TOC, and five individual section pages including a repealed-range entry and a lettered section)

Live accessibility: VERIFIED — every URL tried returned real content on the first request, no JS shell, no bot-block, no CAPTCHA

Title discovery: VERIFIED — Laws/GeneralLaws lists all 5 Parts; each Part page lists its Chapter ranges

Candidate 2: Kentucky — REJECTED for this batch (PDF family)

Live verification this session confirmed that `statute.aspx?id=N` returns
real PDF binaries (per-section PDFs), not HTML. Kentucky is therefore not a
Family A/B/D/E candidate: it requires the codebase's first binary-content
retrieval path (raw-bytes fetch + PDF text extraction). No PDF dependency
or binary-safe fetch exists in the project yet (`adapters/_fetch.py` always
decodes UTF-8), so Kentucky — along with Iowa, New Mexico, and Oklahoma —
belongs in a dedicated PDF-family batch, not B12. Kentucky remains the
recommended first PDF-family state once that capability is introduced (its
per-section PDFs are small and single-page).

Decision

B12 = Massachusetts (solo). It clears every criterion in the brief:
directly live-verified (via the r.jina.ai proxy), a proven Family A
retrieval mechanism requiring no framework change, no bot/auth/JS risk,
and a single well-precedented adapter-local design decision (the 4-level
Part → Title → Chapter → Section hierarchy folded into the 3-level ref
model inside the adapter). Implementation is complete as of Aug 20, 2026:
adapter, 18 real proxy-captured fixtures, dedicated adapter tests, MCP
integration test, and registration in `server.py` (see
`docs/research/massachusetts.md` for the full verified structure).