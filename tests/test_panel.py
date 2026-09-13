"""
v0/v1 integration tests — run against real data.

Opt-in like pit-fundamentals-store's own DB integration test
(RUN_DB_INTEGRATION=1).
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone

import pytest

from quant_data_sdk.fundamentals import FiscalPeriod
from quant_data_sdk.panel import get_panel, get_panel_row

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION") != "1",
    reason="requires both live Postgres instances with AAPL and MSFT data loaded",
)

BEFORE_10KA = datetime(2009, 12, 1, tzinfo=timezone.utc)
AFTER_10KA = datetime(2010, 2, 1, tzinfo=timezone.utc)
AAPL_FY2009 = FiscalPeriod(period_end=date(2009, 9, 26), period_start=date(2008, 9, 28))
MSFT_FY2009 = FiscalPeriod(period_end=date(2009, 6, 30), period_start=date(2008, 7, 1))


def test_restatement_not_visible_before_its_filing_date():
    before = get_panel_row("AAPL", BEFORE_10KA, period=AAPL_FY2009)
    after = get_panel_row("AAPL", AFTER_10KA, period=AAPL_FY2009)

    assert before.net_income == 5_704_000_000
    assert after.net_income == 8_235_000_000


def test_multi_ticker_panel_resolves_both():
    as_of = datetime(2010, 8, 1, tzinfo=timezone.utc)
    panel = get_panel({"AAPL": AAPL_FY2009, "MSFT": MSFT_FY2009}, as_of)

    assert panel["AAPL"].net_income is not None
    assert panel["MSFT"].net_income is not None
    assert panel["AAPL"].equity is not None
    assert panel["MSFT"].equity is not None
