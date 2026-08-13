# Design Writeup

## Architecture and data model

Ingestion (offline, idempotent, `src/tracker/ingest/`) writes to Postgres; a single Flask process
serves both the JSON API and the dashboard off stored data only — no ingestion is ever triggered
by a request. `db/schema.sql` gives every table a natural unique key so re-ingestion is
`ON CONFLICT DO UPDATE`, not append-and-hope:

- `companies` — the configurable universe (CIKs resolved at runtime from `company_tickers.json`,
  never hardcoded; adding a ticker is a one-line change to `config.UNIVERSE`).
- `xbrl_facts` — raw EDGAR facts landing table, full audit trail, keyed on
  `(cik, concept, unit, fy, fp, form, accn)`.
- `fundamentals` — one row per `(ticker, fiscal_year)`, produced by `transform/normalize.py`
  walking an ordered tag-fallback chain per logical concept (`transform/concepts.py`) and
  recording which tag won.
- `prices`, `filings` / `filing_sections` / `filing_chunks` (with a generated `tsvector` + GIN
  index for full-text search), `macro_series`, `ingest_runs` (provenance/freshness).

`ingest/` only writes landing tables; `transform/` normalizes; `metrics/` is pure functions over
normalized data; `web/` and `ai/` only read. This separation is also why `transform/normalize.py`
exposes a pure `normalize_facts(list[dict]) -> list[dict]` function with no DB access — it's
unit-tested directly (`tests/test_concepts.py`) without a database.

## Integrating the three sources, and the messy-data problems that showed up building this

**Fiscal-year misalignment.** NVDA (Jan FYE), AAPL (Sep), MSFT (Jun), GOOGL/ETN (Dec) are keyed by
EDGAR's own `fy`/`fp='FY'` label, never by calendar year; every fiscal-year row carries its
`period_end` so the UI never implies a false apples-to-apples calendar alignment.

**Restatements.** EDGAR returns the same `(concept, fy)` from multiple filings; `normalize.py`
takes the latest-`filed` value per concept per year, keeping every prior version queryable in
`xbrl_facts`.

**Inconsistent tags, found by actually checking the numbers, not assuming they'd resolve.**
Cross-checking FY2024 figures against the real 10-Ks (the plan's explicit gate before building
anything downstream) surfaced real gaps: GOOGL and ETN report no `GrossProfit` line at all — their
income statements simply don't have that subtotal — so gross profit falls back to a derived
`revenue - cost_of_revenue` when the direct tag is absent, with the derivation recorded as the
"tag" (`derived:revenue-CostOfRevenue`) for provenance. NVDA has no standard-taxonomy capex tag at
all for FY2012–2023 (confirmed by exhaustively checking every `us-gaap` concept it reported those
years) — likely a company-specific XBRL extension outside the standard taxonomy. Rather than chase
that indefinitely, it's left as a documented gap: `capex_intensity` is `null` for those years, and
the dashboard's capex charts drop the gap years from the x-axis instead of drawing misleading
zero-height bars.

**A real correctness bug, not just a gap.** Apple's 10-Ks tag a same-year Q4-only disclosure
(e.g. a quarterly-breakdown footnote) with the *exact same* `(concept, fy, fp, form, accn)` as the
real annual figure — `xbrl_facts`' unique key doesn't distinguish them by period length, so
whichever fact landed last silently won, and AAPL's FY2019/2020 revenue was briefly showing
~$64B (one quarter) instead of ~$260B/$275B (the year). Fixed by rejecting any duration fact under
300 days at ingestion (`edgar_facts.py`) — this tracker is annual-only by design anyway, so that
filter is also just correct on its own terms, not a workaround.

**Stock splits aren't retroactively re-tagged.** NVDA's 10:1 split (Jun 2024), GOOGL's 20:1 split
(Jul 2022), and AAPL's 4:1 split (Aug 2020) each make diluted EPS look like it collapsed or
exploded YoY in the data, because EDGAR's own historical facts weren't uniformly restated across
every filing. Rather than trying to detect and re-adjust splits (out of scope for the time box),
the dashboard flags any YoY delta beyond a threshold (100% generally, 50% for EPS specifically)
with a hover-explained "⚠" instead of presenting it as an ordinary, comparable number.

**Section parsing.** 10-Ks aren't uniform. NVDA/AAPL/GOOGL directly attach body text to an
"Item 1A. Risk Factors" heading; a table-of-contents entry and inline self-references
("...as discussed in Item 1A. Risk Factors...") produce spurious regex matches for the same
pattern. Rather than trust "last match" (which breaks the moment a risk factor references itself),
every candidate start/end pairing is scored by resulting section length and the longest wins — a
real heading bounds a large span, a TOC line or cross-reference bounds a tiny one. MSFT renders
some headings as adjacent single-letter spans for kerning ("RIS" + "K" as separate text nodes),
which breaks a whitespace-tolerant regex; matching runs against a fully whitespace-stripped copy
of the text with a position index back to the original, so the artifact can't split a heading word
apart. ETN uses an "integrated" 10-K where Item 7 is a one-line pointer ("Information required by
this Item is presented in 'Management's Discussion and Analysis...' of this Form 10-K") to a
standalone, unnumbered heading elsewhere; the parser follows that pointer's quoted target when the
direct match comes up short instead of accepting the pointer sentence itself as "the section."

**The cross-source join.** `metrics/valuation.py` looks up the latest `prices` row and the latest
`fundamentals` row per ticker independently and joins them in Python — trailing P/E and P/S, with
both the price date and the EPS/revenue fiscal year returned alongside the ratio so staleness is
visible rather than implied.

## Where the LLM is — and isn't

The agent (`ai/agent.py`) is a Claude tool-use loop (`client.beta.messages.tool_runner`, 5
`@beta_tool`-decorated functions, max 10 iterations) over `get_fundamentals`, `compare_companies`,
`get_valuation`, `get_capex_context`, and `search_filings` (Postgres full-text search over Item
1A/7 chunks). Routing — which tool(s) a question needs — is the model's own choice, and it's
surfaced in the UI as an expandable tool-call trace, which doubles as the grounding audit trail.

The LLM is deliberately **not** in: ingestion or section parsing (deterministic regex — a model
that hallucinates a risk factor into the corpus poisons every downstream answer); any arithmetic
(every number in an answer traces to a tool result computed in SQL/Python; the model composes
prose around retrieved figures, never computes a margin itself); the dashboard's tables and charts
(direct API reads, not model output). The system prompt states the dataset is trailing-only and
that forward guidance/estimates/price targets must be declined — verified with a routing test
(`tests/test_agent_routing.py`) that asserts zero tool calls fire for that question and the answer
actually declines.

The hardest of the six required questions — "what new risk factors did NVDA add vs. the prior
year" — has no clean tool for "diff two large sections," so the model is left to search both
filings and synthesize. In testing it did this honestly: it reported the one new risk it could
concretely confirm (an OpenAI investment/partnership clause) and explicitly said which other
guesses it *couldn't* confirm from search results, rather than inventing a confident-sounding list.
That's the intended failure mode for a lexical-search-backed system — visible uncertainty, not
silent overreach.

## Backend, UI, and persistence choices

**Flask**, not FastAPI: the PDF explicitly allows "a lightweight alternative if justified." This
is a single-process, single-user internal tool serving both `/api/*` JSON and the Jinja dashboard
— one process, one container, no cross-service hop for the sake of it. **PostgreSQL** (a bonus per
the PDF) buys `tsvector`/GIN full-text search for filing chunks with zero extra infrastructure and
no embedding-provider dependency. **Plotly via CDN** for charts — interactive hover/zoom matters
for a price series, and it needs no frontend build step, consistent with plain Jinja + vanilla JS.

## The additional metric: Capex Intensity and Capex Cycle Beta

This universe is defined by one macro trade: MSFT and GOOGL are spending the AI data-center capex;
NVDA and ETN sell into it (silicon and electrical distribution gear, respectively); AAPL is the
control — a large-cap tech name deliberately *not* levered to it. **Capex intensity**
(capex ÷ revenue) shows a company is spending; **capex cycle beta** (company capex YoY ÷ FRED
Private Nonresidential Fixed Investment YoY) shows whether it's spending *faster than the economy
around it* — the actual question for an investor deciding whether a capex-cycle name is early or
late in the cycle. It's also a plausible leading indicator: rising hyperscaler capex intensity
today is NVDA/ETN revenue two-to-four quarters out.

## Tradeoffs and what got cut

No quarterly data (annual only — the required metrics are annual, quarterly triples period-
alignment complexity for no graded benefit). No vector/semantic search (lexical Postgres FTS only
— no embedding-provider dependency, and citations stay exact). No auth, caching layer, or
scheduled ingestion (single-analyst internal prototype; ingestion is a manual command plus a
committed snapshot). No Alembic migrations (one `schema.sql` applied at container init). No
attempt to detect or re-adjust stock splits (flagged instead of silently "fixed," which would risk
being wrong in a different way). No derivation of operating income where the direct tag is missing
(ETN) — unlike gross profit's clean two-term subtraction, operating income requires summing an
open-ended, company-specific list of opex lines, and an unreliable derived number is worse than a
visible gap.
