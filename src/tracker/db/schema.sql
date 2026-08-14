-- Fundamentals Tracker schema. Every table has a natural unique key so
-- ingestion is idempotent (ON CONFLICT DO UPDATE). Applied once at container
-- init; no migration framework (see PLAN.md "Deliberate cuts").

CREATE TABLE IF NOT EXISTS companies (
    ticker                  TEXT PRIMARY KEY,
    cik                     INTEGER NOT NULL,
    name                    TEXT NOT NULL,
    fiscal_year_end_month   SMALLINT
);

-- Raw landing for EDGAR XBRL facts — kept in full as an audit trail even
-- when a concept/fy pair is later superseded by a restated filing.
CREATE TABLE IF NOT EXISTS xbrl_facts (
    id              BIGSERIAL PRIMARY KEY,
    cik             INTEGER NOT NULL,
    ticker          TEXT NOT NULL REFERENCES companies(ticker),
    concept         TEXT NOT NULL,
    unit            TEXT NOT NULL,
    fy              INTEGER NOT NULL,
    fp              TEXT NOT NULL,
    form            TEXT NOT NULL,
    accn            TEXT NOT NULL,
    period_start    DATE,
    period_end      DATE,
    filed           DATE NOT NULL,
    value           NUMERIC NOT NULL,
    UNIQUE (cik, concept, unit, fy, fp, form, accn)
);
CREATE INDEX IF NOT EXISTS idx_xbrl_facts_lookup ON xbrl_facts (cik, concept, fy);

-- Normalized annual statement facts, one row per (ticker, fiscal_year).
-- Populated by transform/normalize.py selecting the latest-filed value per
-- concept via the tag fallback chains in transform/concepts.py.
CREATE TABLE IF NOT EXISTS fundamentals (
    id                  BIGSERIAL PRIMARY KEY,
    ticker              TEXT NOT NULL REFERENCES companies(ticker),
    fiscal_year         INTEGER NOT NULL,
    period_end          DATE,
    revenue             NUMERIC,
    revenue_tag         TEXT,
    net_income          NUMERIC,
    net_income_tag      TEXT,
    eps_diluted         NUMERIC,
    eps_diluted_tag     TEXT,
    diluted_shares      NUMERIC,
    diluted_shares_tag  TEXT,
    gross_profit        NUMERIC,
    gross_profit_tag    TEXT,
    operating_income    NUMERIC,
    operating_income_tag TEXT,
    capex               NUMERIC,
    capex_tag           TEXT,
    operating_cash_flow NUMERIC,
    operating_cash_flow_tag TEXT,
    nonoperating_income NUMERIC,
    nonoperating_income_tag TEXT,
    source_accn         TEXT,
    filed_at            DATE,
    UNIQUE (ticker, fiscal_year)
);

-- Added after the initial schema — CREATE TABLE IF NOT EXISTS above won't run
-- again against an existing database, so new columns need an explicit,
-- idempotent ALTER (see PLAN.md "no migration framework").
ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS nonoperating_income NUMERIC;
ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS nonoperating_income_tag TEXT;
ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS income_tax_expense NUMERIC;
ALTER TABLE fundamentals ADD COLUMN IF NOT EXISTS income_tax_expense_tag TEXT;

CREATE TABLE IF NOT EXISTS prices (
    id          BIGSERIAL PRIMARY KEY,
    ticker      TEXT NOT NULL REFERENCES companies(ticker),
    trade_date  DATE NOT NULL,
    open        NUMERIC,
    high        NUMERIC,
    low         NUMERIC,
    close       NUMERIC NOT NULL,
    volume      BIGINT,
    source      TEXT NOT NULL DEFAULT 'yfinance',
    UNIQUE (ticker, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_prices_ticker_date ON prices (ticker, trade_date);

CREATE TABLE IF NOT EXISTS filings (
    id              BIGSERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL REFERENCES companies(ticker),
    accession_no    TEXT NOT NULL,
    fiscal_year     INTEGER,
    filing_date     DATE,
    period_end      DATE,
    primary_doc_url TEXT NOT NULL,
    UNIQUE (ticker, accession_no)
);

CREATE TABLE IF NOT EXISTS filing_sections (
    id          BIGSERIAL PRIMARY KEY,
    filing_id   BIGINT NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
    item        TEXT NOT NULL CHECK (item IN ('1A', '7')),
    char_count  INTEGER NOT NULL,
    text        TEXT NOT NULL,
    UNIQUE (filing_id, item)
);

CREATE TABLE IF NOT EXISTS filing_chunks (
    id          BIGSERIAL PRIMARY KEY,
    section_id  BIGINT NOT NULL REFERENCES filing_sections(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    text        TEXT NOT NULL,
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    UNIQUE (section_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_filing_chunks_tsv ON filing_chunks USING GIN (tsv);

CREATE TABLE IF NOT EXISTS macro_series (
    id          BIGSERIAL PRIMARY KEY,
    series_id   TEXT NOT NULL,
    obs_date    DATE NOT NULL,
    value       NUMERIC,
    UNIQUE (series_id, obs_date)
);

CREATE TABLE IF NOT EXISTS macro_series_meta (
    series_id   TEXT PRIMARY KEY,
    title       TEXT,
    units       TEXT,
    source_url  TEXT
);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id          BIGSERIAL PRIMARY KEY,
    source      TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status      TEXT NOT NULL,
    row_count   INTEGER,
    notes       TEXT
);
