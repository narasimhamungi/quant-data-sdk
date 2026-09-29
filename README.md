# quant-data-sdk

Point-in-time-correct join layer over `marketdata-lakehouse` (prices) and
`pit-fundamentals-store` (fundamentals), for quant factor research — part
of an applied finance/analytics portfolio.

## Problem

Quant factor research needs fundamentals and prices joined *as of a
specific historical instant*, not as they look today. Two independently
owned systems, each internally correct, don't automatically compose into
a correct joint query — the seams between them are exactly where
look-ahead bias and silent misjoins hide.

## Why it matters

A backtest that can "see" a restated financial figure before it was
actually filed, or that silently joins a company's quarterly figure
where it meant the annual one, produces a confidently wrong result — the
kind of error that survives code review and only surfaces once real
capital is behind it.

## What was built

A point-in-time-correct SDK that joins a bitemporal SEC fundamentals
store and a multi-source reconciled market-data lakehouse into a single
queryable panel — resolving tickers to SEC identifiers live, batching
multi-security fundamentals queries into a fixed number of database
round trips regardless of universe size, and automatically discovering
each company's own fiscal reporting periods without manual lookup.

## Data & tools

Python, PostgreSQL (`psycopg2`, `LATERAL` joins, `UNNEST`-based batch
querying), SEC EDGAR (`company_tickers.json`, XBRL company-facts via
pit-fundamentals-store), reconciled yfinance/Tiingo price data via
marketdata-lakehouse, `requests`, `python-dotenv`.

## Methodology

Two independent database connections, zero cross-repo Python imports —
each upstream system is treated as a database this SDK queries, not a
library it depends on, so all three repos can stand alone. Every
capability was live-validated against real data before being trusted:
a real historical earnings restatement, real SEC filings for four
companies with different fiscal calendars, real reconciled price
history — never a synthetic fixture standing in for the real thing.
Every bug found was traced to its actual mechanism before being fixed,
and after every fix the previously-proven cases were re-run by hand
before moving on — manual re-verification, not an automated regression
suite (see Known limitations).

## Key findings

- **Point-in-time correctness bugs are easy to introduce and easy to
  miss.** Pinning a fiscal period by end-date alone isn't enough — a
  single filing can carry multiple duration contexts ending the same
  day (a quarter and a cumulative year, for instance), and a
  security's database identity is not necessarily temporally stable
  the way a schema's naming implies.
- **Live-validated testing against real financial data surfaces defects
  that clean fixtures never would.** A same-instant XBRL tag collision,
  a trailing-twelve-months context that looks exactly like a fiscal
  year by duration alone, and a bank's noncontrolling-interest reporting
  ambiguity were each found by testing against real filings for real
  companies — not by anticipating them in advance.
- **A correctness claim and a tested correctness claim are different
  things.** Two of the six defects found here were in code that had
  already been written, reviewed, and believed correct; neither was
  visible until a genuinely new case (a second company, a fourth
  company, a company past a new filing boundary) exercised the
  assumption that was actually wrong.

## Insight demonstrated

Correctness in point-in-time financial systems can't be asserted from a
clean data model — it has to be proven against real filings, real
restatements, and real edge cases, because the failure modes (silent
look-ahead bias, silently wrong period selection) don't announce
themselves the way a crash does.

## Employer takeaway

Demonstrates designing, building, and rigorously validating a
correctness-critical data system spanning multiple independently owned
sources — the same discipline required for point-in-time factor
libraries, backtesting infrastructure, and any pipeline where "it ran
without error" isn't evidence that it's right.

---

## Status (technical detail)

**Fully live-validated: fundamentals, price, the join between them, and
automatic fiscal-period discovery.**
`get_panel()` resolves an arbitrary set of tickers — via a live SEC
crosswalk, not a hardcoded map — to `net_income`, `stockholders_equity`,
and `adj_close` as of any instant. Fundamentals are batched (two
database round trips regardless of universe size); price is currently
one query per ticker.

Proven end-to-end against AAPL's FY2009 restatement (original 10-K vs.
the 10-K/A): `net_income` and `stockholders_equity` correctly show their
restated values only after the amendment's actual filing date, `ROE`
moves accordingly, and `adj_close` resolves independently on both sides
of that boundary. Cross-checked against a second, independently-ingested
company (MSFT).

Price coverage for AAPL and MSFT reaches back to 2009 (previously 2019)
after extending marketdata-lakehouse's own ingestion — yfinance/Tiingo
reconciliation across the entire newly-extended history came back with
zero discrepancies and zero single-source gaps.

`get_panel_row_auto(ticker, as_of)` discovers a company's own fiscal
period automatically. Proven against a third company, Amazon (CIK
1018724) — correctly discovered its calendar-year FY2009 with zero
manual input, returning its real net income ($902M). Extended to a
fourth, JPMorgan Chase (a bank) — surfaced a genuine data-quality
finding rather than a code bug (see Known limitations). Four companies
covered, three different fiscal year-ends, one financial-sector filer.

## Bugs found and fixed along the way

Six real bugs, not hypothetical edge cases — three in pit-fundamentals-store, three here:

1. `NULL`-handling duplicate-insert bug in `fundamental_fact`'s unique
   constraint (pit-fundamentals-store, pre-existing, already fixed).
2. `fundamentals_asof` / `fundamentals_latest` naming collision
   (pit-fundamentals-store, pre-existing, already fixed).
3. Zero-width `knowledge_time` interval when two facts share an
   identical `filed_at` (pit-fundamentals-store's `temporal.py`) —
   same-instant XBRL alias duplicates treated as sequential temporal
   versions instead of collapsed. Found via AAPL ingestion, confirmed
   not to recur on MSFT's independent ingestion after the fix.
4. Unscoped period selection (this repo). Querying "the most recent
   fact" without pinning both `period_start` and `period_end` silently
   returns whichever duration context sorts last. Fixed via
   `FiscalPeriod`, matching pit-fundamentals-store's own compound key.
5. Wrong theory of how prices join to security identity (this repo).
   `prices.py` originally filtered `dim_security` by
   `effective_from`/`effective_to`, but marketdata-lakehouse's price
   loader resolves `security_key` via `WHERE is_current` at ingestion
   time, never per the date each row represents, and never reassigns it
   afterward. Confirmed by testing: a correct historical `dim_security`
   row for AAPL didn't unblock a single 2009 price lookup, because no
   fact row was ever written against that key. Fixed by matching on
   ticker across every `dim_security` row a ticker has ever had.
6. Annual-duration heuristic matched a TTM context from a 10-Q, not a
   fiscal year (this repo). Duration length alone (~350–380 days)
   isn't sufficient — a 10-Q can carry a trailing-twelve-months context
   alongside its quarterly one. Found on AMZN: a value sitting almost
   exactly between its real FY2009 and FY2010 net income, from a
   `filing_type='10-Q'` filing. Fixed by restricting to `filing_type IN
   ('10-K', '10-K/A')`; re-verified AAPL and MSFT still resolve
   identically after the fix.

## Architecture

```
src/quant_data_sdk/
├── connections.py    # two DB connections, env-based
├── crosswalk.py       # ticker -> CIK, live from SEC's company_tickers.json
├── fundamentals.py    # FiscalPeriod, discover_annual_period(), single-cell + batched fundamentals_asof() wrappers
├── prices.py          # price lookup, ticker-matched across all dim_security history
└── panel.py            # get_panel() / get_panel_row() / get_panel_row_auto(), the join layer
scripts/
├── aapl_pit_demo.py                     # single-ticker restatement proof, full 3-field panel
├── multi_ticker_panel_demo.py            # multi-ticker crosswalk + batch proof
├── seed_historical_dim_security.py       # one-off: non-destructive AAPL/MSFT dim_security backfill
├── period_discovery_check.py             # regression check for discover_annual_period()
└── ticker_generalization_check.py        # CLI: python ... TICKER [YYYY-MM-DD] — run against AMZN, JPM
tests/
└── test_panel.py       # opt-in integration tests (RUN_DB_INTEGRATION=1)
```

## Known limitations, disclosed not hidden

- **Crosswalk is current-mapping-only.** A ticker that's ever been
  reassigned or renamed won't resolve correctly to a historical identity.
- **Price resolution matches on ticker alone, not a temporally-scoped
  identity** — a direct consequence of bug #5 above.
- **Price side is not batched**, unlike fundamentals.
- **`stockholders_equity` doesn't mean the same thing for every
  company.** pit-fundamentals-store's concept mapping canonicalizes two
  different XBRL tags — `StockholdersEquity` (excludes noncontrolling
  interests) and the NCI-inclusive variant — to one canonical concept.
  Invisible for AAPL/MSFT/AMZN; real for JPM, where the figures differ
  by ~$4.5bn for the same fiscal year, and even JPM's own filing history
  isn't consistent about which tag it uses. Not a quant-data-sdk bug —
  the query layer correctly returns whatever the canonical concept says
  was known at a given instant. The real fix belongs in
  pit-fundamentals-store's `mapping.py`, not here.
- **Only validated at n=2 tickers for batching, n=4 for auto-discovery**
  (AAPL, MSFT, AMZN, JPM).
- **AAPL/MSFT price history is a narrow, deliberate exception** — the
  rest of the ~500-ticker universe in marketdata-lakehouse still starts
  at 2019.
- **No CI.** Unlike both sibling repos in this sequence, there's no
  GitHub Actions workflow and no mocked/fast unit-test layer —
  `test_panel.py` is opt-in-only and requires live databases.

## Setup

```bash
cp .env.example .env
# fill in real DB credentials for both instances, plus QDS_SEC_USER_AGENT
pip install -e ".[test]"
python scripts/aapl_pit_demo.py
python scripts/multi_ticker_panel_demo.py
python scripts/period_discovery_check.py
```

## Related portfolio sequence

1. `marketdata-lakehouse` — multi-source market data and reconciliation.
2. `pit-fundamentals-store` — point-in-time fundamentals and restatement integrity.
3. **`quant-data-sdk`** — this repo.
