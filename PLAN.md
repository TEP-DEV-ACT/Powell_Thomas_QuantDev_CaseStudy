# Fundamentals Tracker — Implementation Plan

> **Deliverable #2** — the AI-assisted scoping output produced with Claude Code before starting the
> build. Written after reading the case study PDF and before writing any application code.

## Context

This is a greenfield build for the Schonfeld FE COO Team Quantitative Developer case study
(`FE Quant Developer - Case Study.pdf`). The repo currently contains only the PDF and an empty
`ToDo.md`.

**The problem:** an equity analyst covering NVDA / MSFT / AAPL / GOOGL / ETN has to bounce between
EDGAR's XBRL viewer, a market data terminal, and 300-page 10-K PDFs to answer questions that span
all three — "how did MSFT's revenue grow last year, and what did management attribute it to?"
No single tool joins the reported numbers to the market price to the filing narrative.

**What we're building:** a runnable dashboard that ingests all three sources into PostgreSQL,
serves fundamentals / prices / derived metrics through a Flask app, and puts a Claude tool-use
agent on top that decides — per question — whether it needs the structured numbers, the filing
text, or both, and answers only from what it retrieved.

**Graded on** (per the PDF): engineering quality, data & analytical design, AI integration,
dashboard quality, product judgment, scope discipline, communication. Time box ~8–10 hours,
72-hour deadline. Knowing what to cut is explicitly part of the signal.

### Decisions made up front

| Decision | Choice | Rationale to carry into `DESIGN.md` |
|---|---|---|
| UI | **Flask** (Jinja + vanilla JS) | Chosen deliberately over Streamlit for control over layout |
| Backend | **Same Flask app** serves UI *and* `/api/*` JSON | PDF allows "a lightweight alternative if justified" — one process, one container, no cross-service hop for a single-user internal tool |
| Persistence | **PostgreSQL** | Bonus per the PDF; gives us `tsvector` full-text search for filings for free |
| LLM | **Claude, `claude-sonnet-5`** via official `anthropic` SDK | Base URL / key / model all env-driven so graders can point their proxy at it |
| AI shape | **Tool-use agent loop** (5 typed tools) | Routing is emergent and inspectable; satisfies "more than free-text chat" |
| Filing retrieval | **Section-parse → chunk → Postgres FTS** | No embedding-provider dependency (graders' proxy may not serve embeddings); exact citations |
| Bonus dataset | **FRED** macro capex series | A genuine 4th source — EDGAR capex alone is not "alternative" |
| Own metric | **Capex Intensity + Capex Cycle Beta** | Ties the bonus dataset into the metric instead of bolting it on |
| Packaging | **Docker Compose** | `docker compose up` → Postgres + app + seeded data |

---

## Architecture

```
                 ┌──────────────── ingestion (offline, idempotent) ────────────────┐
  data.sec.gov ──┤ companyfacts XBRL ──► xbrl_facts ──► fundamentals (normalized)  │
  sec.gov/Arch ──┤ 10-K HTML ──► section parser ──► filing_sections ──► chunks+FTS │──► PostgreSQL
  Yahoo (yfin) ──┤ daily OHLCV ──────────────────► prices                          │
  FRED          ─┤ macro capex series ───────────► macro_series                    │
                 └────────────────────────────────────────────────────────────────┘
                                              │
                        ┌─────────────────────┴──────────────────────┐
                        │   Flask app (single process)               │
                        │   • /api/*  JSON  ← metrics layer          │
                        │   • /       Jinja dashboard                │
                        │   • /api/ask → Claude tool-use agent loop  │
                        └────────────────────────────────────────────┘
```

**Hard separation of concerns:** `ingest/` only writes raw-ish landing tables. `transform/`
normalizes. `metrics/` is pure functions over normalized data. `web/` and `ai/` only read.
No ingestion is triggered by a web request — the dashboard runs entirely off stored data.

---

## Data model

`src/tracker/db/schema.sql` — every table gets a natural unique key so re-ingestion is idempotent
(`ON CONFLICT DO UPDATE`).

| Table | Purpose | Key columns |
|---|---|---|
| `companies` | The configurable universe | `ticker` PK, `cik`, `name`, `fiscal_year_end_month` |
| `xbrl_facts` | Raw landing for EDGAR facts — audit trail | uniq `(cik, concept, unit, fy, fp, form, accn)`; also `period_start/end`, `filed`, `value` |
| `fundamentals` | Normalized **annual** statement facts | uniq `(ticker, fiscal_year)`; `period_end`, `revenue`, `net_income`, `eps_diluted`, `gross_profit`, `operating_income`, `capex`, `operating_cash_flow`, `source_accn`, `filed_at` |
| `prices` | Daily OHLCV | uniq `(ticker, trade_date)` |
| `filings` | 10-K metadata | uniq `(ticker, accession_no)`; `fiscal_year`, `filing_date`, `period_end`, `primary_doc_url` |
| `filing_sections` | Item 1A / Item 7 extracted text | uniq `(filing_id, item)`; `item ∈ {'1A','7'}`, `char_count`, `text` |
| `filing_chunks` | Search unit | `section_id`, `chunk_index`, `text`, `tsv tsvector` + **GIN index** |
| `macro_series` | FRED observations | uniq `(series_id, obs_date)`; `value`, plus a `macro_series_meta` table for title/units/source URL |
| `ingest_runs` | Provenance / freshness | `source`, `started_at`, `finished_at`, `status`, `row_count`, `notes` |

### Handling messy data — the three real problems

1. **Fiscal-year misalignment.** NVDA ends in Jan, AAPL Sep, MSFT Jun, GOOGL/ETN Dec. We key on
   the *fiscal year label* from EDGAR (`fy` + `fp='FY'`), never on calendar year, and the UI
   labels every row `FY2024 (ended 2024-09-28)` so the analyst is never misled into comparing
   across mismatched windows. `DESIGN.md` states this explicitly as a known limitation of
   cross-company comparison.
2. **Restatements / duplicate facts.** EDGAR returns the same `(concept, fy)` from multiple
   filings. We keep everything in `xbrl_facts` and select into `fundamentals` by
   `DISTINCT ON (cik, concept, fy) ... ORDER BY filed DESC` — latest filed wins, prior versions
   remain queryable.
3. **Inconsistent XBRL tags.** `src/tracker/transform/concepts.py` holds an ordered fallback chain
   per logical concept, e.g. revenue:
   `RevenueFromContractWithCustomerExcludingAssessedTax` → `Revenues` →
   `RevenueFromContractWithCustomerIncludingAssessedTax` → `SalesRevenueNet`.
   First chain member that yields a value for that `(cik, fy)` wins; the chosen tag is recorded so
   the UI/writeup can show which tag backed each number. Same pattern for EPS, gross profit,
   operating income, capex (`PaymentsToAcquirePropertyPlantAndEquipment` →
   `PaymentsToAcquireProductiveAssets`), and OCF.

---

## Metrics

`src/tracker/metrics/` — pure functions, unit-tested against hand-checked fixtures.

**Reported** (`reported.py`): revenue, net income, diluted EPS, gross margin = gross profit /
revenue, operating margin = operating income / revenue. FCF = OCF − capex (the PDF's optional
extra; we get it for free since capex is already required for the bonus metric).

**Derived** (`derived.py`): YoY growth for every reported line; margin deltas in basis points.

**Cross-source** (`valuation.py`) — the required EDGAR × market join:
- **Trailing P/E** = latest close ÷ latest reported annual diluted EPS
- **P/S** = (latest close × diluted shares outstanding) ÷ latest reported annual revenue

Both are explicitly trailing. The join is a lookup of the most recent `prices` row against the
most recent `fundamentals` row for the ticker, with the as-of dates surfaced in the API response
so the analyst can see the price is live-ish and the EPS is up to a year stale.

**Own metric** (`capex.py`) — the graded open-ended one:
- **Capex Intensity** = capex ÷ revenue, per fiscal year. How much of every revenue dollar is
  being ploughed back into physical/compute capacity.
- **Capex Cycle Beta** = (company capex YoY %) ÷ (national capex YoY %), using the FRED series as
  the denominator.

*Why this metric:* this universe is defined by one macro trade. MSFT and GOOGL are spending the AI
data-center capex; NVDA and ETN are selling into it (silicon and electrical distribution gear
respectively); AAPL is the control — a large-cap tech name deliberately *not* levered to it. Capex
intensity alone tells you a company is spending; the cycle beta tells you whether it is spending
*faster than the economy around it*, which is the actual question for an investor deciding if a
capex-cycle name is early or late. It also reads as a leading indicator: hyperscaler capex
intensity rising is NVDA/ETN revenue two-to-four quarters out. Visualised as a dual-axis chart
(company intensity bars vs FRED index line) plus a cross-company scatter.

---

## Ingestion

`src/tracker/ingest/` — each module is independently runnable (`python -m tracker.ingest.prices`)
and writes an `ingest_runs` row. `run_all.py` orchestrates.

**1. `edgar_facts.py`** — `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json`.
CIKs resolved at runtime from `https://www.sec.gov/files/company_tickers.json`, **not hardcoded** —
adding a ticker is a one-line change in `config.py`. Requires a descriptive `User-Agent` header
(SEC blocks otherwise) and ≤10 req/s rate limiting.

**2. `edgar_filings.py`** — `https://data.sec.gov/submissions/CIK{cik:010d}.json` → filter
`form == '10-K'`, take the latest two → build the primary-document URL under
`https://www.sec.gov/Archives/edgar/data/{cik}/{accn_nodashes}/{primaryDocument}` → fetch HTML.

**3. `transform/sections.py`** — the fiddly bit. Strip HTML to text (BeautifulSoup, drop
`<script>/<style>/<table>` where tables are pure numerics), then locate `Item 1A` and `Item 7` by
a tolerant regex over normalized whitespace, bounded by the next item heading (`Item 1B`, `Item 7A`
respectively). **Guard against the table-of-contents false positive** by taking the *last* match
when multiple candidates exist and rejecting sections under a minimum character threshold. Log a
warning and record `char_count` so a bad parse is visible rather than silent. Chunk at ~1200 chars
on paragraph boundaries with overlap; store with a generated `tsvector`.

**4. `prices.py`** — `yfinance`, ~3 years daily OHLCV per ticker. Fallback to `stooq` CSV if
yfinance throws (it is periodically rate-limited); note the fallback in `ingest_runs.notes`.

**5. `macro_fred.py`** — FRED. Primary series: `PNFI` (Private Nonresidential Fixed Investment,
quarterly SAAR) as the reliable anchor, plus an information-processing-equipment series.
**Action item during implementation:** confirm the exact info-processing series ID against
`https://api.stlouisfed.org/fred/series/search` rather than trusting a remembered ID — put the
resolved IDs in `config.py`. Auth: use `FRED_API_KEY` if set; otherwise fall back to the
**no-key CSV endpoint** `https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}`, so the
build never hard-blocks on a key the graders don't have.

**Seed/snapshot** (required by the PDF): `ingest/seed.py --export` dumps every table to
gzipped CSV under `data/seed/`, committed to the repo. `seed.py --load` restores. Docker Compose's
app entrypoint runs `--load` when the DB is empty, so **`docker compose up` works with zero network
access** at review time. Live ingestion is a separate explicit command.

---

## AI layer

`src/tracker/ai/` — Claude tool-use agent loop via `client.beta.messages.tool_runner`
(official `anthropic` SDK; `@beta_tool`-decorated Python functions, schemas generated from
signatures). Max ~6 iterations.

### Tools exposed to the model

| Tool | Returns | Answers |
|---|---|---|
| `get_fundamentals(ticker, years)` | Reported + derived lines per fiscal year | "NVDA revenue and net income, last three fiscal years" |
| `compare_companies(metric, fiscal_year)` | That metric across all five, ranked | "Which had the highest gross margin last year?" |
| `get_valuation(ticker)` | Trailing P/E, P/S, price + as-of dates | "AAPL's trailing P/E right now" |
| `search_filings(query, ticker=None, item=None, fiscal_year=None)` | Ranked chunks with `ticker / FY / item / accession` citations | "What new risk factors did NVDA add?" |
| `get_capex_context(ticker)` | Capex intensity series + FRED cycle + cycle beta | The own-metric questions |

Routing is the model's choice of tools, and it is **surfaced in the UI** — the answer panel shows
the tool-call trace, so the analyst can see the system pulled `get_fundamentals('MSFT')` *and*
`search_filings('revenue growth drivers', ticker='MSFT', item='7')` for a cross-modal question.
That trace is also the grounding audit trail.

### Where the LLM deliberately is *not*

- **No LLM in ingestion or parsing.** Section extraction is deterministic regex; a model that
  hallucinates a risk factor into the corpus poisons every downstream answer.
- **No LLM in arithmetic.** Every number in an answer comes from a tool result computed in SQL or
  Python. The model composes prose around retrieved figures; it never computes a margin.
- **No LLM in the dashboard's tables and charts.** Those are direct API reads. The model is a
  question-answering surface, not the data path.

### Grounding and failure modes
- System prompt: answer only from tool results; cite ticker + fiscal year for every figure and
  filing item + accession for every narrative claim; if the tools return nothing, say so.
- **Out-of-scope handling** for "what is the forward guidance for next quarter?": the tool surface
  contains no forward-looking data, and the system prompt states the dataset is trailing-only and
  that forward guidance, estimates, and price targets must be declined rather than inferred.
  This is covered by an explicit test.
- Known failure modes to document: FTS is lexical, so heavily paraphrased narrative questions can
  miss; a bad Item-7 parse degrades a company silently (mitigated by `char_count` monitoring); a
  stale price makes P/E look wrong (mitigated by returning as-of dates).

---

## Dashboard

`src/tracker/web/` — Flask + Jinja + a small amount of vanilla JS; **Plotly** via CDN for charts
(interactive hover/zoom matters for a price chart, and it needs no build step).

Single page, four regions:
1. **Company selector** — the five tickers, driven by `config.UNIVERSE`.
2. **Fundamentals table** — revenue, net income, EPS, gross margin, operating margin, FCF, **capex
   intensity**, one column per fiscal year, with YoY deltas colour-coded. Fiscal-year-end date
   shown in the header.
3. **Price chart** — daily close, with fiscal-year-end markers so price context lines up with the
   reported periods.
4. **Capex panel** (the own metric) — company capex intensity vs the FRED cycle, dual axis, plus a
   five-company scatter of intensity vs revenue growth.
5. **Q&A panel** — question box, streamed answer, expandable tool-call trace, citation chips that
   link to the source filing on EDGAR.

A slim **cross-company view** (all five on the selected metric) reuses `compare_companies` and is
cheap to add once that tool exists.

---

## Files to create

```
docker-compose.yml, Dockerfile, requirements.txt, .env.example, run.sh, .gitignore
README.md            ← run instructions, env vars, provider/model, 2–3 example interactions
PLAN.md              ← this document (deliverable #2)
DESIGN.md            ← the 1–2 page writeup (deliverable #4)
data/seed/*.csv.gz   ← committed snapshot

src/tracker/
  config.py                  UNIVERSE, FRED series IDs, env loading
  db/{schema.sql,models.py,session.py}
  ingest/{edgar_facts,edgar_filings,prices,macro_fred,run_all,seed}.py
  ingest/_http.py            shared session: SEC User-Agent, rate limit, retry/backoff
  transform/{concepts,normalize,sections}.py
  metrics/{reported,derived,valuation,capex}.py
  ai/{tools,agent,prompts}.py
  web/{app,routes_api,routes_ui}.py, templates/, static/

tests/
  test_concepts.py     tag fallback chains against fixture JSON
  test_metrics.py      margins, YoY, P/E, capex intensity — hand-checked numbers
  test_sections.py     Item 1A/7 parse on a committed 10-K fixture, incl. the TOC trap
  test_agent_routing.py  the six PDF questions → asserts which tools fired, and that the
                         forward-guidance question is declined
  test_api.py          endpoint smoke tests against the seed
```

Key env vars (`.env.example`): `DATABASE_URL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`,
`ANTHROPIC_MODEL` (default `claude-sonnet-5`), `SEC_USER_AGENT`, `FRED_API_KEY` (optional).

---

## Build order

1. Scaffold: repo layout, `requirements.txt`, `config.py`, Docker Compose with Postgres, `schema.sql`.
2. `_http.py` + `edgar_facts.py` → raw facts landing. Verify against NVDA by eye.
3. `concepts.py` + `normalize.py` → `fundamentals`. **Manually verify FY2024 revenue for all five
   against the actual 10-Ks before building anything on top.**
4. `prices.py`, `macro_fred.py`.
5. `edgar_filings.py` + `sections.py` + chunking/FTS. Spot-check every extracted section length.
6. `metrics/` + unit tests.
7. Flask API routes; then the dashboard UI.
8. `ai/tools.py` → `agent.py`; run the six PDF questions.
9. `seed.py` export → commit snapshot; wire the Compose auto-load; verify a clean
   `docker compose up` on an empty volume.
10. `README.md`, `DESIGN.md`, screenshots.

---

## Deliberate cuts

- **No quarterly data** — annual only. The required metrics are annual; quarterly triples the
  period-alignment complexity for no graded benefit.
- **No semantic/vector search** — lexical FTS only, for the reasons above.
- **No auth, no multi-user state, no caching layer** — single-analyst internal prototype.
- **No scheduled/incremental ingestion** — manual commands plus a committed snapshot.
- **No Alembic migrations** — a single `schema.sql` applied at container init.
- **Item 1A/7 only** — not the whole 10-K. That is what the PDF asks for, and the rest is noise.
- **Price chart is close-only**, not candlestick — analysts get candles elsewhere.

---

## Verification

**End-to-end (the reviewer path):**
```bash
cp .env.example .env      # add ANTHROPIC_API_KEY
docker compose up         # Postgres + app + auto-loaded seed
# → open http://localhost:8000
```
Confirm with **networking to SEC/Yahoo/FRED blocked** that the dashboard and Q&A still fully work
off the seed — this is an explicit PDF requirement.

**Live ingestion (proves the wiring is real):**
```bash
docker compose exec app python -m tracker.ingest.run_all
docker compose exec app psql $DATABASE_URL -c "select source,status,row_count from ingest_runs order by started_at desc limit 10"
```

**Data correctness:** cross-check FY2024 revenue, net income, and diluted EPS for all five tickers
against the actual 10-K income statements. Confirm each fiscal-year row's `period_end` matches the
company's real fiscal year end. Confirm both 10-K years are present per company with non-trivial
`char_count` on Item 1A and Item 7.

**Tests:** `pytest` — the routing test is the important one; it asserts the six PDF questions
produce the right tool selection, and that forward guidance is declined rather than invented.

**Manual Q&A pass** — run all six PDF questions plus variants through the UI, and verify every
number in each answer traces back to a tool result shown in the trace panel.

---

## Open item

An **Anthropic API key** is needed to test the agent loop end to end. It goes in `.env`
(git-ignored); `.env.example` ships with a placeholder. Default model is `claude-sonnet-5`; base URL
and model stay env-driven so the graders can point their own LLM proxy at it. `FRED_API_KEY` is
optional — ingestion falls back to FRED's keyless CSV endpoint.
