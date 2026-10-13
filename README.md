# quant-data-sdk

Point-in-time-correct join layer over
[marketdata-lakehouse](https://github.com/narasimhamungi/marketdata-lakehouse) (prices) and
[pit-fundamentals-store](https://github.com/narasimhamungi/pit-fundamentals-store) (fundamentals),
for quant factor research — part of an applied finance/analytics portfolio.

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
queryable panel — resolving tickers to SEC identifiers from SEC's live
ticker map, batching multi-security fundamentals queries into a fixed
number of database round trips regardless of universe size, and
discovering each company's own fiscal reporting periods without manual
lookup.

## Data & tools

Python, PostgreSQL (`psycopg2`, `LATERAL` joins, `UNNEST`-based batch
querying), SEC EDGAR (`company_tickers.json`, XBRL company-facts via
pit-fundamentals-store), reconciled yfinance/Tiingo price data via
marketdata-lakehouse, `requests`, `python-dotenv`.

## Methodology

Two independent database connections, zero cross-repo Python imports —
each upstream system is treated as a database this SDK queries, not a
library it depends on, so all three repos stand alone. Every capability
was validated against real data: a real historical earnings
restatement, real SEC filings for four companies with different fiscal
calendars, and real reconciled price history.

## Correctness rules

Each rule closes a specific way a point-in-time join goes silently wrong.

1. **A fiscal period is pinned by both `period_start` and `period_end`**
   (`FiscalPeriod`), matching pit-fundamentals-store's compound key. A
   single filing can carry several duration contexts ending the same day
   (a quarter and a cumulative year); pinning the end date alone returns
   whichever sorts last.
2. **Annual periods are discovered only from `10-K` and `10-K/A` filings.**
   A 10-Q can carry a trailing-twelve-months context whose duration
   (~350–380 days) looks exactly like a fiscal year. On AMZN that context
   sits almost exactly between the real FY2009 and FY2010 net income.
3. **Prices are matched on ticker across every `dim_security` row the
   ticker has had**, not on the row valid at the as-of date.
   marketdata-lakehouse assigns `security_key` at load time
   (`WHERE is_current`) and never reassigns it, so a ticker's whole price
   history sits under whichever key was current when it was loaded.
4. **Restatements become visible only at their filing time.** This
   relies on pit-fundamentals-store's knowledge-time intervals, which
   collapse same-instant XBRL alias duplicates into one version and keep
   instant facts unique under `UNIQUE NULLS NOT DISTINCT`.

## Key findings

- **Point-in-time correctness depends on more than the data model.**
  End-date-only period selection and an identity key that is not
  temporally stable both return plausible, wrong numbers without an
  error.
- **Real filings carry cases clean fixtures don't.** Same-instant XBRL
  tag duplicates, a TTM context that looks like a fiscal year by
  duration, and a bank's noncontrolling-interest reporting ambiguity all
  come from real filings for real companies.
- **Coverage of a new case is what tests an assumption.** Each new
  company (a second, a different fiscal calendar, a financial-sector
  filer) exercised assumptions the earlier ones could not.

## Insight demonstrated

Correctness in point-in-time financial systems can't be asserted from a
clean data model — it has to be proven against real filings, real
restatements, and real edge cases, because the failure modes (silent
look-ahead bias, silently wrong period selection) don't announce
themselves the way a crash does.

## Employer takeaway

Demonstrates designing, building, and validating a correctness-critical
data system spanning multiple independently owned sources — the same
discipline required for point-in-time factor libraries, backtesting
infrastructure, and any pipeline where "it ran without error" isn't
evidence that it's right.

---

## Status (technical detail)

**Live-validated: fundamentals, price, the join between them, and
automatic fiscal-period discovery.**
`get_panel()` resolves a set of tickers — via SEC's ticker map, not a
hardcoded one — to `net_income`, `stockholders_equity`, and `adj_close`
as of any instant. Fundamentals are batched (two database round trips
regardless of universe size); price is one query per ticker.

Proven end-to-end against AAPL's FY2009 restatement (original 10-K vs.
the 10-K/A): `net_income` and `stockholders_equity` show their restated
values only after the amendment's actual filing date, `ROE` moves
accordingly, and `adj_close` resolves independently on both sides of
that boundary. Cross-checked against a second, independently ingested
company (MSFT).

AAPL and MSFT price coverage reaches back to 2009 through
marketdata-lakehouse's narrow historical backfill; yfinance/Tiingo
reconciliation over that extended history showed zero discrepancies and
zero single-source gaps.

`get_panel_row_auto(ticker, as_of)` discovers a company's own fiscal
period automatically: Amazon (CIK 1018724) resolves to its calendar-year
FY2009 with no manual input, returning its real net income ($902M).
JPMorgan Chase (a bank) surfaces a data-quality finding rather than a
code defect (see Known limitations). Four companies covered, three
different fiscal year-ends, one financial-sector filer.

## Architecture

```
src/quant_data_sdk/
├── connections.py    # two DB connections, env-based
├── crosswalk.py      # ticker -> CIK, from SEC's company_tickers.json
├── fundamentals.py   # FiscalPeriod, discover_annual_period(), single-cell + batched fundamentals_asof() wrappers
├── prices.py         # price lookup, ticker-matched across all dim_security history
└── panel.py          # get_panel() / get_panel_row() / get_panel_row_auto(), the join layer
scripts/
├── aapl_pit_demo.py                  # single-ticker restatement proof, full 3-field panel
├── multi_ticker_panel_demo.py        # multi-ticker crosswalk + batch proof
├── seed_historical_dim_security.py   # one-off: non-destructive AAPL/MSFT dim_security backfill
├── period_discovery_check.py         # check for discover_annual_period()
└── ticker_generalization_check.py    # CLI: python ... TICKER [YYYY-MM-DD] — run against AMZN, JPM
tests/
└── test_panel.py     # opt-in integration tests (RUN_DB_INTEGRATION=1)
```

## Known limitations

- **Crosswalk is current-mapping-only.** A ticker that's ever been
  reassigned or renamed won't resolve correctly to a historical identity.
- **Price resolution matches on ticker alone, not a temporally scoped
  identity** — a direct consequence of correctness rule 3.
- **Price side is not batched**, unlike fundamentals.
- **`stockholders_equity` doesn't mean the same thing for every
  company.** pit-fundamentals-store's concept mapping canonicalizes two
  different XBRL tags — `StockholdersEquity` (excludes noncontrolling
  interests) and the NCI-inclusive variant — to one canonical concept.
  Invisible for AAPL/MSFT/AMZN; real for JPM, where the figures differ
  by ~$4.5bn for the same fiscal year, and JPM's own filing history
  isn't consistent about which tag it uses. The query layer correctly
  returns whatever the canonical concept says was known at a given
  instant; the fix belongs in pit-fundamentals-store's `mapping.py`.
- **Validated at n=2 tickers for batching, n=4 for auto-discovery**
  (AAPL, MSFT, AMZN, JPM).
- **AAPL/MSFT price history is a narrow, deliberate exception** — the
  rest of the ~500-ticker universe in marketdata-lakehouse starts at
  2019.
- **No CI.** Unlike both sibling repos, there's no GitHub Actions
  workflow and no mocked unit-test layer — `test_panel.py` is opt-in and
  requires both live databases.

## Setup

```bash
cp .env.example .env
# fill in the DB credentials for both instances, plus QDS_SEC_USER_AGENT
pip install -e ".[test]"
python scripts/aapl_pit_demo.py
python scripts/multi_ticker_panel_demo.py
python scripts/period_discovery_check.py
RUN_DB_INTEGRATION=1 pytest -q
```

## Related repositories

1. [marketdata-lakehouse](https://github.com/narasimhamungi/marketdata-lakehouse) — multi-source market data and reconciliation.
2. [pit-fundamentals-store](https://github.com/narasimhamungi/pit-fundamentals-store) — point-in-time fundamentals and restatement integrity.
3. **quant-data-sdk** — this repo.
