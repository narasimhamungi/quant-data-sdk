"""
Generalization check: does get_panel_row_auto() work on a ticker with no
manually-diagnosed FiscalPeriod supplied?

Generalized from a one-off AMZN-specific script into a reusable CLI tool
— hardcoding a new ticker into a fresh copy of this file each time would
just recreate the exact "manual diagnosis" bottleneck this whole feature
exists to remove, one level up.

Usage:
  python scripts/ticker_generalization_check.py TICKER [YYYY-MM-DD]

Second argument (as_of) defaults to 2010-08-01, matching every other
check in this project so results stay directly comparable.

adj_close will be None for any ticker/date outside AAPL/MSFT's narrow
2009+ price backfill — expected, not a failure; see README.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone

from quant_data_sdk.panel import get_panel_row_auto

DEFAULT_AS_OF = datetime(2010, 8, 1, tzinfo=timezone.utc)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/ticker_generalization_check.py TICKER [YYYY-MM-DD]")
        sys.exit(1)

    ticker = sys.argv[1].upper()
    as_of = (
        datetime.combine(date.fromisoformat(sys.argv[2]), datetime.min.time(), tzinfo=timezone.utc)
        if len(sys.argv) > 2
        else DEFAULT_AS_OF
    )

    row = get_panel_row_auto(ticker, as_of)
    print(f"{ticker} as of {as_of.date()}:")
    print(f"  {row}\n")

    if row.net_income is None:
        print(
            "FAIL: net_income is None — either this ticker hasn't been ingested "
            "into pit-fundamentals-store yet, or discover_annual_period() found "
            "no annual (10-K/10-K-A) context for it. Check ingestion first."
        )
        return

    duration_days = (row.period.period_end - row.period.period_start).days
    print(f"Discovered period: {row.period}  ({duration_days} days)")
    print(f"net_income: {row.net_income:,.0f}")
    print(f"equity:     {row.equity:,.0f}" if row.equity is not None else "equity:     None")
    print(f"ROE:        {row.roe:.4f}" if row.roe is not None else "ROE:        None")

    if not (350 <= duration_days <= 380):
        print(f"\nUNEXPECTED: {duration_days} days is not annual-shaped — investigate before trusting this.")
    else:
        print("\nDiscovered period is annual-shaped and came from a 10-K/10-K-A filing — no manual diagnosis required.")

    print(
        "\nadj_close: None (expected outside AAPL/MSFT's 2009+ backfill)"
        if row.adj_close is None
        else f"\nadj_close: {row.adj_close}"
    )


if __name__ == "__main__":
    main()
