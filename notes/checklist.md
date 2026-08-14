# Case Study Requirements Checklist

Extracted directly from `FE Quant Developer - Case Study.pdf`. This is a plain requirements
checklist only — it is not checked against the current state of the app.

## The fixed universe

- [ ] Five tickers: NVDA, MSFT, AAPL, GOOGL, ETN.
- [ ] Universe is not hardcoded — adding/swapping a ticker is a configuration change, not a
      rewrite.

## The three required data sources

- [ ] SEC EDGAR — structured fundamentals (XBRL company-facts data).
- [ ] SEC EDGAR — filing narrative: Item 1A "Risk Factors" and Item 7 "MD&A" from each company's
      latest two annual 10-K filings.
- [ ] Market data — daily/period prices for the five tickers from Yahoo Finance (or Stooq, Alpha
      Vantage free tier, or equivalent).
- [ ] Optional/bonus — any freely available alternative dataset, well justified.

## The Task

1. [ ] Ingest from all three sources via a real pipeline connecting to the live sources.
2. [ ] Persist the ingested data with a clear, well-structured schema (technology is a free
       choice; PostgreSQL is a bonus but not required).
   [ ] Ship a seed/snapshot of the ingested data so the dashboard and Q&A layer can run and be
       tested without depending on live API availability at review time.
3. [ ] Wire up a backend to serve fundamentals, prices, and derived metrics to the dashboard
       (FastAPI is the expected natural fit; a lightweight alternative is acceptable if justified).
4. [ ] Compute the required metrics:
   - [ ] Reported: revenue, net income, EPS, gross margin, operating margin (free cash flow
         optional).
   - [ ] Derived: year-over-year growth and margins.
   - [ ] At least one cross-source valuation multiple joining EDGAR + market data (e.g. trailing
         P/E or P/S), trailing only — no forward estimates.
   - [ ] At least one additional metric of your own choosing, analytically meaningful to an
         equity investor, justified in the writeup.
5. [ ] Add a natural-language / agentic layer answering questions spanning both the structured
       numbers and the filing narrative — tool use / function calling, structured outputs,
       retrieval, or an agent loop (more than free-text chat). The key graded behavior is
       **routing**: the system deciding whether a question needs structured numbers, filing text,
       or both.
6. [ ] Build a dashboard UI as the primary interface, including at minimum:
   - [ ] A company selector (the five tickers).
   - [ ] A fundamentals table showing the required metrics (including the additional one) for
         the selected company, with year-over-year comparisons.
   - [ ] A price chart for the selected company.
   - [ ] A Q&A interface for the natural-language layer.
   - [ ] (Not required but welcome) additional panels, cross-company views, or visualisations of
         the additional metric.
7. [ ] Containerize the full stack via Docker Compose (bonus) so `docker compose up` brings up
       the app, data store, and any other services in a single command — **or**, if not
       containerized, ship a `run.sh` bash script that installs dependencies and starts the full
       application in a single command, alongside a committed dependency file (`requirements.txt`
       or `pyproject.toml`).
   [ ] LLM configuration (base URL, API key, model name) is read from environment variables,
       never hardcoded.

## Constraints

- [ ] Python is used throughout; FastAPI backend expected but a lightweight alternative is fine
      if justified.
- [ ] AI-assisted development used (Claude Code, Cursor, or similar).
- [ ] LLM base URL, API key, and model name are all configurable via environment variables, and
      the exact provider/model used is documented in the README.
- [ ] Ingestion genuinely connects to the live sources, and a snapshot is persisted so everything
      else runs without live API dependency at review time.
- [ ] Scope fits roughly 8–10 hours of work within the 72-hour submission window; deliberate cuts
      are identified.
- [ ] Period alignment and messy data are handled thoughtfully (not assumed away).

## The six questions the service should handle

- [ ] "What were NVDA's revenue and net income for the last three fiscal years?" (structured)
- [ ] "Which of the five companies had the highest gross margin last year?" (derived, comparative)
- [ ] "What is AAPL's trailing P/E right now?" (cross-source join)
- [ ] "What new risk factors did NVDA add in its latest 10-K versus the prior year?" (filing text)
- [ ] "How did MSFT's revenue grow last year, and what did management attribute it to?"
      (cross-modal — numbers + MD&A)
- [ ] "What is the company's forward guidance for next quarter?" (out of scope — the system
      should decline or say it doesn't have that, not invent an answer)

## Deliverables

1. [ ] A GitHub repo containing all code.
2. [ ] An AI planning document — the scoping/planning output produced with the AI-assisted
       development tool before starting to build (e.g. `PLAN.md`).
3. [ ] A README that lets the full stack be run and the dashboard opened in one command, and
       includes:
   - [ ] Required environment variables (including LLM config) and how to point the service at a
         different model.
   - [ ] Which provider and exact model(s) were used.
   - [ ] 2–3 example interactions — dashboard screenshots/descriptions and natural-language Q&A
         examples.
4. [ ] A short design writeup (~1–2 pages) covering:
   - [ ] Architecture and data model — what was built and why.
   - [ ] How the three sources were integrated (especially the cross-source join).
   - [ ] Where the LLM was used, where it deliberately wasn't, and the reasoning.
   - [ ] Choice of backend, UI framework, and data persistence technology, and why.
   - [ ] The additional analytical metric — what it is, why it was picked, and what it tells an
         investor.
   - [ ] Key tradeoffs, and what was deliberately left out given the time box.

## Evaluation criteria

- [ ] Engineering quality — clean, idiomatic, well-structured Python; sensible project layout;
      tests, docs, and error handling proportional to a prototype.
- [ ] Data & analytical design — thoughtful data model for time-series financial data (period
      alignment, messy/restated data); sound multi-source integration; clear separation of
      ingestion vs. serving.
- [ ] AI integration — the model used where it earns its place (routing, tool use, structured
      outputs, or retrieval over naive prompting); grounded answers; awareness of failure modes
      and when not to use the model.
- [ ] Dashboard & presentation quality — a UI an analyst would actually open; clear layout,
      readable data display, usable Q&A interface; the additional metric visualised or surfaced
      in a way that adds genuine insight.
- [ ] Product judgment — a clear sense of the user and the problem; genuinely useful output.
- [ ] Scope & pragmatism — a working prototype with deliberate, well-reasoned cuts.
- [ ] Communication — clear README and writeup; reproducible; easy to follow.

## Submission

- [ ] File/repo naming format: `LastName_FirstName_QuantDev_CaseStudy`.
- [ ] Submitted within 72 hours of receiving the case to `pgeoffroy@schonfeld.com`.
- [ ] Submission includes, verbatim: *"I have completed the following Schonfeld Case Study solely
      using publicly available sources of information. Accordingly, I further confirm that I have
      not used any Material Non-Public Information (within the meaning of U.S. federal securities
      laws) and information that is subject to a duty or contractual restriction to a third
      party."*
