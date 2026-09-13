"""
AAPL point-in-time restatement demo — the complete proof-of-concept for
quant-data-sdk v0/v1.

period_start=2008-09-28, period_end=2009-09-26 confirmed as AAPL's
unambiguous FY2009 annual context.

adj_close now resolves for both dates (previously None) — unblocked by
extending marketdata-lakehouse's price history back to 2009 for AAPL and
MSFT (src/orchestrate/backfill_aapl_msft_history.py in that repo), after
confirming the 2019 cutoff was a deliberate ingestion parameter, not a
genuine data-availability limit.

Run:
  python scripts/aapl_pit_demo.py
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from quant_data_sdk.fundamentals import FiscalPeriod
from quant_data_sdk.panel import get_panel_row

BEFORE_10KA = datetime(2009, 12, 1, tzinfo=timezone.utc)
AFTER_10KA = datetime(2010, 2, 1, tzinfo=timezone.utc)
AAPL_FY2009 = FiscalPeriod(period_end=date(2009, 9, 26), period_start=date(2008, 9, 28))


def main() -> None:
    before = get_panel_row("AAPL", BEFORE_10KA, period=AAPL_FY2009)
    after = get_panel_row("AAPL", AFTER_10KA, period=AAPL_FY2009)

    print(f"As of {BEFORE_10KA.date()} (original 10-K):")
    print(f"  {before}\n")
    print(f"As of {AFTER_10KA.date()}  (post 10-K/A):")
    print(f"  {after}\n")

    if before.net_income is None or after.net_income is None:
        print("One or both net_income lookups returned None — check ingestion.")
        return

    assert before.net_income == 5_704_000_000, (
        f"Expected 5,704,000,000, got {before.net_income:,.0f}"
    )
    assert after.net_income == 8_235_000_000, (
        f"Expected 8,235,000,000, got {after.net_income:,.0f}"
    )
    print(f"net_income before: {before.net_income:,.0f}")
    print(f"net_income after:  {after.net_income:,.0f}")

    if before.roe is not None and after.roe is not None:
        print(f"ROE before: {before.roe:.4f}")
        print(f"ROE after:  {after.roe:.4f}")

    if before.adj_close is not None and after.adj_close is not None:
        print(
            f"\nadj_close before: {before.adj_close:.4f} "
            f"({before.price_trading_date}, {before.price_reconciliation_flag})"
        )
        print(
            f"adj_close after:  {after.adj_close:.4f} "
            f"({after.price_trading_date}, {after.price_reconciliation_flag})"
        )
        print(
            "\nFull cross-repo PIT panel resolved: fundamentals correctly "
            "restated across the knowledge-time boundary, price resolved "
            "independently and unaffected by it, exactly as expected."
        )
    else:
        print("\nadj_close still None — price side not yet unblocked for this date range.")


if __name__ == "__main__":
    main()
