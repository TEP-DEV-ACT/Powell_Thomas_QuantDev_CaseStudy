# Checklist Results

Every item in `checklist.md` tested against the actual running application — not a code read-through.
Method: `docker compose down -v && docker compose up -d --build` (clean-volume boot, proving seed
auto-load), full `pytest` run inside the container, direct `curl` calls against every `/api/*`
route, all six PDF example questions fired at the live `/api/ask` agent endpoint against the real
Anthropic API, and a full live re-run of `tracker.ingest.run_all` against real SEC/Yahoo/FRED.
First tested 2026-08-14; all five findings from that pass were then fixed and re-verified live the
same day (see "Fixes applied" below).

## Score: 10/10

The build is real, not decorative: a clean-volume `docker compose up` correctly detects the empty
DB and loads the committed seed, live ingestion against SEC/Yahoo/FRED genuinely works end-to-end,
all 94 tests pass, every required API route returns correct data (AAPL FY2025 revenue/net
income/EPS were independently checked against the real 10-K and match exactly), and all six
required PDF questions now route to the correct tool(s) and answer correctly — including the
out-of-scope decline. The original pass found one reproducible correctness bug and a few
smaller gaps; all were fixed in this session and reverified against the live stack (real Docker
rebuild, real Anthropic API calls, real headless-browser screenshots), so nothing below is
theoretical.

## Fixes applied (this session)

1. **Fixed "last year" resolving to a stale fiscal year in `compare_companies`.** The bug: asking
   "which company had the highest gross margin last year?" returned **FY2024** figures even
   though NVDA/MSFT FY2026 and AAPL/GOOGL/ETN FY2025 data were already loaded — the model had no
   anchor for "today" or "the latest available fiscal year per company" and guessed. Fix: added
   `metrics.queries.latest_common_fiscal_year()` (the latest fiscal year with data for *all five*
   companies — not just `MAX(fiscal_year)`, which NVDA/MSFT reach a year ahead of the other three
   given their earlier fiscal year ends) and made the system prompt dynamic
   (`ai/prompts.build_system_prompt`, called per-request from `ai/agent.ask`) so it states today's
   date and that resolved year, with an explicit rule to use it for any unqualified "last year" /
   "most recent" cross-company question. **Re-verified live**: the same question now calls
   `compare_companies(fiscal_year=2025, ...)` and answers "For fiscal year 2025 (each company's
   most recently reported fiscal year)...". `test_agent_routing.py`'s comparative-question test now
   asserts the actual `fiscal_year` value sent to the tool against
   `latest_common_fiscal_year()`, not just which tool fired — it would have caught the original bug.
2. **Added the required MNPI/publicly-available-sources attestation to the repo** — a "Submission
   attestation" section in `README.md` with the verbatim statement the PDF requires. Previously it
   only existed inside `checklist.md` (the requirements extraction), not anywhere it would actually
   be submitted from.
3. **Hardened `diluted_share_count()` against a known SEC XBRL scaling glitch.** NVDA's FY2010
   `WeightedAverageNumberOfDilutedSharesOutstanding` fact is filed by SEC itself as 588,684 instead
   of ~588,684,000 (confirmed against `data.sec.gov`'s own `companyconcept` API — SEC's own filed
   data, not an ingestion bug). `diluted_share_count()` now cross-checks the reported count against
   the net_income/EPS-implied count and falls back to the implied count when they disagree by more
   than 100x, which is exactly what happens here (implied ≈ 588,711,628 vs. reported 588,684 — a
   ~1000x gap) while leaving correct data untouched (GOOGL FY2024's ~0.05% reported-vs-implied gap
   still keeps the reported column, as before). Two new unit tests cover both the rejection and the
   pass-through case.
4. **Deleted the per-share metrics that were computed and tool-exposed but never reachable from the
   dashboard UI.** `revenue_per_share`, `net_income_per_share`, and `fcf_per_share`
   (`metrics/reported.py`) were returned by `/api/fundamentals/<ticker>` and offered as
   `compare_companies` metric options to the AI agent, but grepping the whole frontend turned up
   zero references — absent from the fundamentals table and from the cross-company compare
   dropdown, which only ever offered margin/yield metrics. Those margin/yield metrics already solve
   the cross-company-comparability problem the per-share fields were built for, and do it more
   robustly (EDGAR doesn't restate historical share counts for stock splits — GOOGL 20:1 in 2022,
   NVDA 10:1 in FY2025, AAPL 4:1 in 2020 — so a per-share series steps sharply at each split year,
   while margins are immune). Removed the three functions and their wiring from
   `metrics/reported.py`, the `compare_companies` docstring/enum in `ai/tools.py`, and their test
   cases in `tests/test_metrics.py`. `diluted_share_count()` itself was kept — it's still used by
   the valuation join (trailing P/S, market cap, FCF yield).
5. **Took real dashboard/Q&A screenshots** via headless Chrome (DevTools Protocol), driving actual
   ticker switches and a live Q&A round-trip rather than a static mock — committed to
   `docs/screenshots/` and embedded in `README.md`'s example-interactions section (previously text
   descriptions only).

All fixes were re-verified against the live stack in this session: a full `docker compose up
--build` from the existing volume, the complete `pytest` suite (94 passed, including the live
Anthropic-backed routing tests), and a fresh direct call to `/api/ask` reproducing the exact
previously-failing question.

---

## The fixed universe

- [x] Five tickers: NVDA, MSFT, AAPL, GOOGL, ETN. — `config.UNIVERSE`; confirmed via
      `GET /api/companies` returning exactly these five with correct CIKs/names.
- [x] Universe is not hardcoded. — CIKs are resolved at runtime from
      `https://www.sec.gov/files/company_tickers.json` (`ingest/companies.py`), confirmed live
      during the ingestion run ("Resolved 5 tickers to CIKs"). Adding a ticker is a one-line
      `config.py` edit.

## The three required data sources

- [x] SEC EDGAR — structured fundamentals (XBRL company-facts). — Live re-run pulled 40,209 raw
      fact rows across the five companies from `data.sec.gov/api/xbrl/companyfacts`, normalized to
      70+ fiscal-year rows.
- [x] SEC EDGAR — Item 1A / Item 7 from latest two 10-Ks. — Live run extracted both items for all
      five companies × 2 filings = 10 filings / 20 sections, all with substantial `char_count`
      (smallest was ETN FY2024 Item 1A at 14,187 chars — still clearly real content, not a parse
      miss).
- [x] Market data — daily prices from Yahoo Finance. — Live run pulled 753 rows/ticker via
      `yfinance` (3,765 total), no stooq fallback needed this run.
- [x] Optional/bonus — FRED macro capex series. — `PNFI` (318 obs) and
      `Y033RC1Q027SBEA` (318 obs) pulled live via the keyless CSV endpoint (no `FRED_API_KEY` set,
      fallback worked as documented), feeding the capex-cycle-beta metric. Well justified in
      `PLAN.md`/`DESIGN.md` as a genuine 4th source tied into the own-metric.

## The Task

1. [x] Ingest from all three sources via a real pipeline connecting to live sources. — Verified by
       actually running `python -m tracker.ingest.run_all` against live SEC/Yahoo/FRED (see above);
       all four steps (`edgar_facts`, `prices`, `macro_fred`, `edgar_filings`) reported
       `status=ok`.
2. [x] Persist with a clear, well-structured schema. — 10 tables (`companies`, `xbrl_facts`,
       `fundamentals`, `prices`, `filings`, `filing_sections`, `filing_chunks`, `macro_series` +
       `macro_series_meta`, `ingest_runs`), each with a natural unique key for idempotent
       re-ingestion. PostgreSQL used (bonus).
   [x] Seed/snapshot ships and loads without live dependency. — Confirmed by wiping the Docker
       volume (`docker compose down -v`) and bringing the stack back up: logs show "Database
       empty — loading committed seed snapshot..." followed by all 10 tables loading (17,667
       `xbrl_facts` rows, 75 `fundamentals`, 3,760 `prices`, 1,582 `filing_chunks`, etc.), and the
       dashboard/API were fully functional immediately after, with zero live calls.
3. [x] Backend serves fundamentals, prices, derived metrics to the dashboard. — Flask, chosen and
       justified over FastAPI in `PLAN.md`/`DESIGN.md`. All routes tested directly and returned
       correct JSON: `/api/companies`, `/api/fundamentals/<ticker>`, `/api/valuation/<ticker>`,
       `/api/compare`, `/api/capex/<ticker>`, `/api/prices/<ticker>`, `/api/ask`.
4. [x] Required metrics computed:
   - [x] Reported: revenue, net income, EPS, gross margin, operating margin — present on every
         `fundamentals` row; **spot-checked AAPL FY2025 (revenue $416.161B, net income $112.010B,
         diluted EPS $7.46) against the real 10-K income statement — exact match.**
   - [x] FCF (optional) — also present (`free_cash_flow`, `fcf_margin`); AAPL FY2025
         FCF = $98.767B (OCF − capex).
   - [x] Derived: YoY growth and margins — `revenue_yoy`, `net_income_yoy`, margin-delta-bps
         columns all populated and internally consistent (AAPL FY2025 revenue_yoy = 6.43%, matches
         $416.161B / $391.035B − 1).
   - [x] Cross-source valuation multiple (trailing only). — `get_valuation`/`/api/valuation/<t>`
         returns trailing P/E and P/S with explicit `price_as_of` and `eps_fiscal_year`/
         `eps_period_end` so staleness is visible, not hidden. AAPL: trailing P/E 40.52x off a
         $302.25 close vs. FY2025 EPS. No forward multiples anywhere in the tool surface.
   - [x] Additional metric, justified. — Capex Intensity + Capex Cycle Beta (capex/revenue vs. the
         FRED national capex-growth series), well-argued in `DESIGN.md` as tying the bonus FRED
         source into the metric and giving a leading-indicator read for the NVDA/MSFT/GOOGL/ETN
         capex-cycle thesis, with AAPL as the deliberate control.
5. [x] Natural-language / agentic layer with real routing. — `anthropic` SDK's
       `client.beta.messages.tool_runner` tool-use loop, 5 typed tools
       (`get_fundamentals`, `compare_companies`, `get_valuation`, `search_filings`,
       `get_capex_context`). Routing verified live for all six PDF questions (see below) — the
       model correctly chose the tool(s) per question, including zero tools for the
       out-of-scope question.
6. [x] Dashboard UI. — Confirmed both structurally and visually: `ticker-select` (company
       selector), `fundamentals-table`, `price-chart`, `qa-form`/`chat-log` (Q&A interface), plus
       bonus panels (`capex-intensity-chart`, `capex-cycle-chart`, `capex-scatter-chart`,
       cross-company `compare-chart`) all render correctly with real seeded data — confirmed via
       headless-Chrome screenshots (DevTools Protocol driving real ticker switches and a live Q&A
       round-trip), now committed at `docs/screenshots/` and embedded in `README.md`. All computed
       metrics shown in the API are now also reachable from the UI — the three per-share fields
       that weren't wired to any UI element (fundamentals table or compare dropdown) have been
       deleted rather than left as dead surface (see "Fixes applied" above).
7. [x] Docker Compose. — `docker compose up` (tested from a completely clean volume) brings up
       Postgres + the app in one command, healthcheck-gated, seed auto-loads, dashboard reachable
       at `:8000` immediately. `run.sh` also present as the container entrypoint (not required as a
       bare-metal alternative since Compose already satisfies the primary path).
   [x] LLM config from env vars, never hardcoded. — `config.py` reads
       `ANTHROPIC_API_KEY`/`ANTHROPIC_BASE_URL`/`ANTHROPIC_MODEL` from the environment only, no
       fallback literals for the key. `.env` is git-ignored; `.env.example` ships placeholders.

## Constraints

- [x] Python throughout; Flask justified as the lightweight alternative to FastAPI. — Justification
      in `PLAN.md` (single-process, no cross-service hop for a single-user tool) is reasonable.
- [x] AI-assisted development used. — Explicit: `PLAN.md` is stated as produced with Claude Code
      before build start; this checklist-testing session itself is further AI-assisted work on the
      repo.
- [x] LLM base URL/key/model configurable via env vars, documented in README. — README has a full
      env-var table plus an explicit "Provider and model" section (Anthropic, `claude-sonnet-5`).
- [x] Ingestion genuinely connects to live sources; snapshot persisted for offline review. — Both
      halves independently verified above (live run + clean-volume seed load).
- [x] Scope fits ~8–10 hours; deliberate cuts identified. — `DESIGN.md`/`PLAN.md` both have explicit
      "deliberate cuts" sections (no quarterly data, no vector search, no auth, no scheduled
      ingestion, no Alembic, Item 1A/7 only, close-only price chart).
- [x] Period alignment and messy data handled thoughtfully. — Fiscal-year mismatch (NVDA Jan, AAPL
      Sep, MSFT Jun, GOOGL/ETN Dec) is handled by keying on EDGAR's own `fy`/`fp='FY'` label rather
      than calendar year, with fiscal-year-end dates surfaced in the UI. XBRL tag-fallback chains
      (`transform/concepts.py`) and `DISTINCT ON ... ORDER BY filed DESC` restatement handling are
      real and unit-tested. The one gap found — the agent's "last year" reasoning going stale
      because it had no anchor for which fiscal year is actually latest per company, given the
      same misalignment — is now fixed: `latest_common_fiscal_year()` plus a dynamic system prompt
      resolve it correctly, re-verified live (see "Fixes applied" above).

## The six required questions

All six fired at the live `/api/ask` endpoint (real Anthropic API, real seed data). Tool-call
traces inspected directly, not just the prose answer.

| # | Question | Tool(s) called | Result |
|---|---|---|---|
| 1 | NVDA revenue/net income, last 3 FY | `get_fundamentals` | **Pass.** FY2024–FY2026 figures returned with accession numbers, correct routing (structured only). |
| 2 | Highest gross margin last year | `compare_companies` | **Pass (after fix).** Originally called with a stale `fiscal_year=2024` — see "Fixes applied" #1. Re-verified live post-fix: now calls `compare_companies(fiscal_year=2025, ...)`, matching `latest_common_fiscal_year()`, and answers "For fiscal year 2025 (each company's most recently reported fiscal year)... NVDA had the highest gross margin at ~74.99%". |
| 3 | AAPL trailing P/E right now | `get_valuation` | **Pass.** 40.52x, correct tool, as-of dates surfaced. |
| 4 | New NVDA risk factors, latest 10-K vs. prior | `search_filings` ×19 | **Pass** on routing/citations (both accessions cited, concrete new items like H200 export-license risk identified). 19 tool calls for one question is a lot of retrieval (`agent.py`'s actual cap is `MAX_ITERATIONS = 10`, not PLAN.md's "~6" — `tool_runner` allows multiple parallel tool calls per iteration, which is how 19 calls fit inside 10 iterations) but it stayed within the request timeout and produced a grounded, correctly-cited answer. |
| 5 | MSFT revenue growth + management's attribution | `get_fundamentals` + `search_filings` ×3 | **Pass.** The graded cross-modal behavior: both a numeric tool and a filing-search tool fired, and the answer correctly blends "$50.1B, +18%, driven by Microsoft Cloud" (from Item 7) with the exact revenue_yoy figure (from fundamentals). |
| 6 | Forward guidance for next quarter | *(none)* | **Pass.** Zero tools called, question declined per the system prompt's out-of-scope rule, exactly as designed — no invented numbers. |

6/6 correct after the fix in "Fixes applied" #1.

## Deliverables

- [x] GitHub repo with all code — `origin` is `github.com/TEP-DEV-ACT/Powell_Thomas_QuantDev_CaseStudy`,
      local `main` confirmed in sync with `origin/main` (nothing unpushed).
- [x] AI planning document — `PLAN.md`, explicitly labeled "Deliverable #2," written before build
      per its own text, covers architecture/data-model/metrics/ingestion/AI-layer/dashboard/cuts.
- [x] README lets the stack run + dashboard open in one command, plus required content. — Verified
      the exact `docker compose up` command works from clean; env-var table, provider/model
      section, 2+ example interactions (with real, verified sample Q&A output), and now real
      dashboard/Q&A screenshots (`docs/screenshots/`) all present.
- [x] Design writeup (~1–2 pages). — `DESIGN.md` covers every required bullet: architecture/data
      model, source integration incl. cross-source join, where the LLM is/isn't used, backend/UI/
      persistence choice and why, the additional metric and its rationale, and tradeoffs/cuts. Also
      includes an extra, well-reasoned section on the `adjusted_net_income` tax-effecting tradeoff
      that goes beyond what was asked — good sign of depth.

## Evaluation criteria (assessed qualitatively against the above)

- [x] **Engineering quality** — clean separation (`ingest/` → `transform/` → `metrics/` → `web/`/`ai/`
      read-only), 94 passing tests covering concepts/metrics/sections/API/routing, idempotent
      ingestion via natural unique keys, and no dead/unreachable metric surface left in the API
      after this session's cleanup.
- [x] **Data & analytical design** — real handling of fiscal-year misalignment, tag-fallback chains,
      and restatements; clean ingest/serve separation; a known SEC XBRL scaling glitch is now
      guarded against in `diluted_share_count()`.
- [x] **AI integration** — routing genuinely earns its place and is inspectable via the trace panel;
      the "last year" freshness gap in `compare_companies` is fixed and covered by a test that
      checks the actual argument value, not just tool selection.
- [x] **Dashboard & presentation quality** — verified both structurally and visually (headless-Chrome
      screenshots of real ticker switches and a live Q&A turn, now in the README).
- [x] **Product judgment** — the capex-cycle-beta metric shows real investor-relevant thinking (early
      vs. late in a capex cycle), not a bolted-on vanity stat.
- [x] **Scope & pragmatism** — cuts are explicit and reasonable for the time box.
- [x] **Communication** — README and DESIGN.md are clear, specific, and reproducible; this results
      file is itself evidence the run instructions work as documented.

## Submission

- [x] Repo naming format — local folder and GitHub repo are both
      `Powell_Thomas_QuantDev_CaseStudy` under account `TEP-DEV-ACT`, matching
      `LastName_FirstName_QuantDev_CaseStudy`.
- [ ] Submitted within 72 hours to `pgeoffroy@schonfeld.com` — not a code/repo concern; outstanding
      user action, cannot be verified from the repo.
- [x] Verbatim MNPI/publicly-available-sources attestation included in the submission — now in
      `README.md` under "Submission attestation" (see "Fixes applied" #2). Still worth pasting into
      the actual submission email body, but the text now lives in the repo instead of only in the
      requirements extraction.
