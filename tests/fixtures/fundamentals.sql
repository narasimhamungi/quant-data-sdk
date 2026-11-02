-- Fixture for quant-data-sdk's CI: pit-fundamentals-store's schema (copied verbatim from
-- sql/schema/001_initial.sql at github.com/narasimhamungi/pit-fundamentals-store) plus a handful of facts.
--
-- AAPL FY2009 net income is the real restatement the live integration test uses: 5,704m in the 10-K
-- filed 2009-10-27, 8,235m in the 10-K/A filed 2010-01-25. Every other value is a fixture value, chosen
-- only to exercise one correctness rule each:
--   * a 3-month AAPL context ending on the same day as the fiscal year (FiscalPeriod must pin period_start);
--   * an annual-length trailing-twelve-month context in a 10-Q (must not be "discovered" as a fiscal year);
--   * instant balance-sheet facts with period_start NULL (NULL-safe matching in the batch query);
--   * MSFT, for a second company in the batch.
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE TABLE IF NOT EXISTS company(cik BIGINT PRIMARY KEY,ticker TEXT,company_name TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS filing(
 accession_number TEXT PRIMARY KEY,cik BIGINT NOT NULL REFERENCES company(cik),form TEXT NOT NULL,filing_date DATE NOT NULL,
 report_date DATE,primary_document TEXT,source_url TEXT NOT NULL,retrieved_at TIMESTAMPTZ NOT NULL,UNIQUE(cik,accession_number));
CREATE TABLE IF NOT EXISTS fundamental_fact(
 fact_id BIGSERIAL PRIMARY KEY,cik BIGINT NOT NULL REFERENCES company(cik),concept TEXT NOT NULL,raw_concept TEXT NOT NULL,
 period_start DATE,period_end DATE NOT NULL,value NUMERIC NOT NULL,unit TEXT NOT NULL,source_accession TEXT NOT NULL REFERENCES filing(accession_number),
 filing_type TEXT NOT NULL,source_url TEXT NOT NULL,valid_time TSTZRANGE NOT NULL,knowledge_time TSTZRANGE NOT NULL,
 filed_at TIMESTAMPTZ NOT NULL,effective_from TIMESTAMPTZ NOT NULL,effective_to TIMESTAMPTZ,
 dimensions JSONB NOT NULL DEFAULT '{}'::jsonb,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CONSTRAINT fact_period CHECK(period_start IS NULL OR period_start<=period_end),
 CONSTRAINT fact_effective CHECK(effective_to IS NULL OR effective_to>effective_from),
 CONSTRAINT fact_filed CHECK(filed_at=effective_from),
 -- NULLS NOT DISTINCT is load-bearing, not a style choice. Instant facts
 -- (balance-sheet items: assets, liabilities, equity, cash) have no
 -- period_start, so period_start IS NULL for all of them. Under SQL's
 -- default NULLS DISTINCT semantics, NULL != NULL, so a plain UNIQUE
 -- constraint never fires for those rows and ON CONFLICT DO NOTHING below
 -- silently inserts a duplicate on every re-run — verified empirically
 -- against Postgres 16: a second identical load produced 4 rows from 2.
 -- That breaks idempotency for exactly the facts the DAGs re-ingest
 -- daily, and duplicates would then double every point-in-time query
 -- result. Requires Postgres 15+ (docker-compose pins postgres:16-alpine).
 UNIQUE NULLS NOT DISTINCT (source_accession,cik,concept,raw_concept,period_start,period_end,unit,value));
CREATE INDEX IF NOT EXISTS ix_fact_logical ON fundamental_fact(cik,concept,period_end);
CREATE INDEX IF NOT EXISTS ix_fact_filed ON fundamental_fact(filed_at);
CREATE INDEX IF NOT EXISTS ix_fact_knowledge_gist ON fundamental_fact USING GIST(knowledge_time);

CREATE OR REPLACE FUNCTION fundamentals_asof(p_cik BIGINT,p_concept TEXT,p_as_of TIMESTAMPTZ)
RETURNS TABLE(cik BIGINT,concept TEXT,raw_concept TEXT,period_start DATE,period_end DATE,value NUMERIC,unit TEXT,filed_at TIMESTAMPTZ,source_accession TEXT,source_url TEXT)
LANGUAGE sql STABLE AS $$
SELECT f.cik,f.concept,f.raw_concept,f.period_start,f.period_end,f.value,f.unit,f.filed_at,f.source_accession,f.source_url
FROM fundamental_fact f WHERE f.cik=p_cik AND f.concept=p_concept AND f.knowledge_time @> p_as_of
ORDER BY f.period_end,f.filed_at;
$$;

-- Named fundamentals_LATEST, deliberately not fundamentals_asof. This view
-- returns the most recently filed version of each fact — the restated,
-- current-best value. That is the OPPOSITE of point-in-time. Giving it the
-- function's name would be legal in Postgres (functions and relations are
-- separate namespaces), but `SELECT * FROM fundamentals_asof` would then
-- silently return the look-ahead-biased answer to anyone who assumed the
-- name meant what it says. Use this for "what does Apple's FY2009 net income look like today";
-- use fundamentals_asof(cik, concept, as_of) for "what was knowable on date X".
CREATE OR REPLACE VIEW fundamentals_latest AS
SELECT DISTINCT ON(cik,concept,period_start,period_end,unit) *
FROM fundamental_fact ORDER BY cik,concept,period_start,period_end,unit,filed_at DESC;


INSERT INTO company(cik, ticker, company_name) VALUES
 (320193, 'AAPL', 'Apple Inc.'),
 (789019, 'MSFT', 'Microsoft Corporation'),
 (1018724, 'AMZN', 'Amazon.com, Inc.');

INSERT INTO filing(accession_number, cik, form, filing_date, report_date, source_url, retrieved_at) VALUES
 ('0001193125-09-214859', 320193, '10-K',   '2009-10-27', '2009-09-26', 'https://www.sec.gov/fixture/aapl-10k-2009',  '2026-11-02T00:00:00Z'),
 ('0001193125-10-012091', 320193, '10-K/A', '2010-01-25', '2009-09-26', 'https://www.sec.gov/fixture/aapl-10ka-2009', '2026-11-02T00:00:00Z'),
 ('0001193125-09-158735', 789019, '10-K',   '2009-07-30', '2009-06-30', 'https://www.sec.gov/fixture/msft-10k-2009',  '2026-11-02T00:00:00Z'),
 ('0001193125-10-030774', 1018724, '10-K',  '2010-01-29', '2009-12-31', 'https://www.sec.gov/fixture/amzn-10k-2009',  '2026-11-02T00:00:00Z'),
 ('0001193125-10-166277', 1018724, '10-Q',  '2010-07-23', '2010-06-30', 'https://www.sec.gov/fixture/amzn-10q-2010q2','2026-11-02T00:00:00Z');

-- knowledge_time: from the filing date until a later filing supersedes the same (cik, concept, period).
INSERT INTO fundamental_fact(cik, concept, raw_concept, period_start, period_end, value, unit, source_accession,
                             filing_type, source_url, valid_time, knowledge_time, filed_at, effective_from, effective_to) VALUES
 -- AAPL FY2009 net income: original, then the restatement
 (320193, 'net_income', 'NetIncomeLoss', '2008-09-28', '2009-09-26', 5704000000, 'USD', '0001193125-09-214859', '10-K',
  'https://www.sec.gov/fixture/aapl-10k-2009', '[2008-09-28,2009-09-27)', '[2009-10-27T00:00:00Z,2010-01-25T00:00:00Z)',
  '2009-10-27T00:00:00Z', '2009-10-27T00:00:00Z', '2010-01-25T00:00:00Z'),
 (320193, 'net_income', 'NetIncomeLoss', '2008-09-28', '2009-09-26', 8235000000, 'USD', '0001193125-10-012091', '10-K/A',
  'https://www.sec.gov/fixture/aapl-10ka-2009', '[2008-09-28,2009-09-27)', '[2010-01-25T00:00:00Z,)',
  '2010-01-25T00:00:00Z', '2010-01-25T00:00:00Z', NULL),
 -- AAPL fourth-quarter context ending the same day (fixture value)
 (320193, 'net_income', 'NetIncomeLoss', '2009-06-28', '2009-09-26', 1670000000, 'USD', '0001193125-09-214859', '10-K',
  'https://www.sec.gov/fixture/aapl-10k-2009', '[2009-06-28,2009-09-27)', '[2009-10-27T00:00:00Z,)',
  '2009-10-27T00:00:00Z', '2009-10-27T00:00:00Z', NULL),
 -- AAPL equity at 2009-09-26 (instant; fixture values), original then restated
 (320193, 'stockholders_equity', 'StockholdersEquity', NULL, '2009-09-26', 27832000000, 'USD', '0001193125-09-214859', '10-K',
  'https://www.sec.gov/fixture/aapl-10k-2009', '[2009-09-26,2009-09-27)', '[2009-10-27T00:00:00Z,2010-01-25T00:00:00Z)',
  '2009-10-27T00:00:00Z', '2009-10-27T00:00:00Z', '2010-01-25T00:00:00Z'),
 (320193, 'stockholders_equity', 'StockholdersEquity', NULL, '2009-09-26', 31640000000, 'USD', '0001193125-10-012091', '10-K/A',
  'https://www.sec.gov/fixture/aapl-10ka-2009', '[2009-09-26,2009-09-27)', '[2010-01-25T00:00:00Z,)',
  '2010-01-25T00:00:00Z', '2010-01-25T00:00:00Z', NULL),
 -- MSFT FY2009 (fixture values)
 (789019, 'net_income', 'NetIncomeLoss', '2008-07-01', '2009-06-30', 14569000000, 'USD', '0001193125-09-158735', '10-K',
  'https://www.sec.gov/fixture/msft-10k-2009', '[2008-07-01,2009-07-01)', '[2009-07-30T00:00:00Z,)',
  '2009-07-30T00:00:00Z', '2009-07-30T00:00:00Z', NULL),
 (789019, 'stockholders_equity', 'StockholdersEquity', NULL, '2009-06-30', 39558000000, 'USD', '0001193125-09-158735', '10-K',
  'https://www.sec.gov/fixture/msft-10k-2009', '[2009-06-30,2009-07-01)', '[2009-07-30T00:00:00Z,)',
  '2009-07-30T00:00:00Z', '2009-07-30T00:00:00Z', NULL),
 -- AMZN: FY2009 from the 10-K, and a later 10-Q's trailing-twelve-month context (annual length, not a fiscal year)
 (1018724, 'net_income', 'NetIncomeLoss', '2009-01-01', '2009-12-31', 902000000, 'USD', '0001193125-10-030774', '10-K',
  'https://www.sec.gov/fixture/amzn-10k-2009', '[2009-01-01,2010-01-01)', '[2010-01-29T00:00:00Z,)',
  '2010-01-29T00:00:00Z', '2010-01-29T00:00:00Z', NULL),
 (1018724, 'net_income', 'NetIncomeLoss', '2009-07-01', '2010-06-30', 1200000000, 'USD', '0001193125-10-166277', '10-Q',
  'https://www.sec.gov/fixture/amzn-10q-2010q2', '[2009-07-01,2010-07-01)', '[2010-07-23T00:00:00Z,)',
  '2010-07-23T00:00:00Z', '2010-07-23T00:00:00Z', NULL);
