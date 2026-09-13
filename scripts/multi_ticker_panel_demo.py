"""
Multi-ticker panel demo — the v1 proof of concept.

Exercises get_panel() across two independently-ingested companies at
once: the SEC crosswalk resolving both tickers to CIKs, and the batched
query fetching net_income + stockholders_equity for both in two round
trips total instead of four. Not a restatement demo (MSFT has none in
this window) — this is specifically testing that the multi-security
machinery works at all, which has never been exercised against live
data before this run.

as_of=2010-08-01 is after both companies' relevant filings: AAPL's
10-K/A (2010-01-25) and MSFT's FY2009 10-K (2010-07-30) — both FY2009
annual figures should be fully knowable by this date.

Run:
  python scripts/multi_ticker_panel_demo.py
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from quant_data_sdk.fundamentals import FiscalPeriod
from quant_data_sdk.panel import get_panel

AS_OF = datetime(2010, 8, 1, tzinfo=timezone.utc)

TICKER_PERIODS = {
    "AAPL": FiscalPeriod(period_end=date(2009, 9, 26), period_start=date(2008, 9, 28)),
    "MSFT": FiscalPeriod(period_end=date(2009, 6, 30), period_start=date(2008, 7, 1)),
}


def main() -> None:
    panel = get_panel(TICKER_PERIODS, AS_OF)

    for ticker, row in panel.items():
        print(f"{ticker} as of {AS_OF.date()} (FY period {row.period.period_end}):")
        print(f"  {row}\n")

    missing = [t for t, r in panel.items() if r.net_income is None or r.equity is None]
    if missing:
        print(f"Missing fundamentals for: {missing} — check ingestion coverage.")
        return

    print("All requested tickers resolved via the crosswalk and returned fundamentals.")
    for ticker, row in panel.items():
        print(f"{ticker}: net_income={row.net_income:,.0f}  equity={row.equity:,.0f}  ROE={row.roe:.4f}")


if __name__ == "__main__":
    main()
