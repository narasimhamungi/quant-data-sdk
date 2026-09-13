"""
Regression check for discover_annual_period() / get_panel_row_auto().

AAPL expects FY2009 (period_end=2009-09-26) — its FY2010 10-K doesn't
file until ~October 2010, safely after AS_OF.

MSFT expects FY2010 (period_end=2010-06-30), NOT FY2009 — corrected
after a first version of this test wrongly expected FY2009 here.
MSFT's fiscal year ends in June, and its FY2010 10-K was filed
2010-07-30 (confirmed against real data pulled earlier in this
project) — before AS_OF=2010-08-01. discover_annual_period() correctly
found the objectively most recent annual period known at that instant;
the original "expected" value in this test was simply stale, not the
discovery code. This is actually a better check than a same-year
comparison would have been: two companies with different fiscal
calendars, queried at the identical instant, correctly resolving to
DIFFERENT most-recent annual periods.

Run:
  python scripts/period_discovery_check.py
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from quant_data_sdk.crosswalk import get_cik_for_ticker
from quant_data_sdk.fundamentals import discover_annual_period
from quant_data_sdk.panel import get_panel_row_auto

AS_OF = datetime(2010, 8, 1, tzinfo=timezone.utc)

EXPECTED_PERIOD = {
    "AAPL": (date(2008, 9, 28), date(2009, 9, 26)),
    "MSFT": (date(2009, 7, 1), date(2010, 6, 30)),
}
EXPECTED_NET_INCOME = {
    "AAPL": 8_235_000_000,
    "MSFT": 18_760_000_000,
}


def main() -> None:
    all_passed = True

    for ticker, (expected_start, expected_end) in EXPECTED_PERIOD.items():
        cik = get_cik_for_ticker(ticker)
        period = discover_annual_period(cik, "net_income", AS_OF)
        print(f"{ticker}: discover_annual_period -> {period}")

        if period is None or period.period_start != expected_start or period.period_end != expected_end:
            print(f"  FAIL: expected period_start={expected_start}, period_end={expected_end}")
            all_passed = False
            continue
        print("  matches the expected period.")

        row = get_panel_row_auto(ticker, AS_OF)
        print(f"  get_panel_row_auto -> net_income={row.net_income}, adj_close={row.adj_close}")
        if row.net_income != EXPECTED_NET_INCOME[ticker]:
            print(f"  FAIL: expected net_income={EXPECTED_NET_INCOME[ticker]}")
            all_passed = False
        else:
            print("  matches expected net_income.")

    print("\nALL CHECKS PASSED" if all_passed else "\nSOME CHECKS FAILED — see above")


if __name__ == "__main__":
    main()
