"""Correctness rules tested against two real Postgres databases seeded from tests/fixtures/*.sql.

CI starts both (see .github/workflows/ci.yml) and sets QDS_FIXTURE_DB=1. Locally:

    createdb qds_md && psql -d qds_md -f tests/fixtures/marketdata.sql
    createdb qds_fund && psql -d qds_fund -f tests/fixtures/fundamentals.sql
    set the QDS_MARKETDATA_* / QDS_FUNDAMENTALS_* variables, QDS_FIXTURE_DB=1, then pytest

The live-data test (test_panel.py) stays opt-in with RUN_DB_INTEGRATION=1.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone

import psycopg2
import pytest

from quant_data_sdk import crosswalk
from quant_data_sdk.connections import get_fundamentals_connection, get_marketdata_connection
from quant_data_sdk.fundamentals import (FiscalPeriod, discover_annual_period, get_fundamental_asof,
                                         get_fundamentals_batch)
from quant_data_sdk.panel import get_panel, get_panel_row_auto
from quant_data_sdk.prices import get_price_asof

pytestmark = pytest.mark.skipif(os.environ.get("QDS_FIXTURE_DB") != "1",
                                reason="needs the two fixture databases (CI sets QDS_FIXTURE_DB=1)")

AAPL, MSFT, AMZN = 320193, 789019, 1018724
AAPL_FY2009 = FiscalPeriod(period_end=date(2009, 9, 26), period_start=date(2008, 9, 28))
AAPL_Q4_2009 = FiscalPeriod(period_end=date(2009, 9, 26), period_start=date(2009, 6, 28))
MSFT_FY2009 = FiscalPeriod(period_end=date(2009, 6, 30), period_start=date(2008, 7, 1))
BEFORE_10K = datetime(2009, 10, 1, tzinfo=timezone.utc)
BEFORE_10KA = datetime(2009, 12, 1, tzinfo=timezone.utc)
AFTER_10KA = datetime(2010, 2, 1, tzinfo=timezone.utc)


@pytest.fixture
def fund():
    conn = get_fundamentals_connection()
    yield conn
    conn.close()


@pytest.fixture
def md():
    conn = get_marketdata_connection()
    yield conn
    conn.close()


@pytest.fixture
def tickers(monkeypatch):
    """The crosswalk without the network: SEC's company_tickers.json shape, three rows."""
    raw = {"0": {"cik_str": AAPL, "ticker": "AAPL", "title": "Apple Inc."},
           "1": {"cik_str": MSFT, "ticker": "MSFT", "title": "MICROSOFT CORP"},
           "2": {"cik_str": AMZN, "ticker": "AMZN", "title": "AMAZON COM INC"}}
    monkeypatch.setattr(crosswalk, "_ticker_to_cik", None)
    monkeypatch.setattr(crosswalk, "_load_cached_or_fetch", lambda: raw)


# -- fundamentals: what was knowable when ---------------------------------------------------------------------------

def test_restatement_is_invisible_before_its_filing(fund):
    assert get_fundamental_asof(AAPL, "net_income", BEFORE_10KA, AAPL_FY2009, conn=fund).value == 5_704_000_000
    after = get_fundamental_asof(AAPL, "net_income", AFTER_10KA, AAPL_FY2009, conn=fund)
    assert after.value == 8_235_000_000 and after.source_accession == "0001193125-10-012091"


def test_nothing_is_known_before_the_first_filing(fund):
    assert get_fundamental_asof(AAPL, "net_income", BEFORE_10K, AAPL_FY2009, conn=fund) is None


def test_fiscal_period_needs_its_start_as_well_as_its_end(fund):
    """The fiscal year and its fourth quarter end on the same day; period_start tells them apart."""
    year = get_fundamental_asof(AAPL, "net_income", AFTER_10KA, AAPL_FY2009, conn=fund)
    quarter = get_fundamental_asof(AAPL, "net_income", AFTER_10KA, AAPL_Q4_2009, conn=fund)
    assert year.value == 8_235_000_000 and quarter.value == 1_670_000_000


def test_annual_discovery_ignores_a_trailing_twelve_months_context_in_a_10q(fund):
    as_of = datetime(2010, 8, 1, tzinfo=timezone.utc)          # after the 10-Q's annual-length TTM context was filed
    assert discover_annual_period(AMZN, "net_income", as_of, conn=fund) == FiscalPeriod(
        period_end=date(2009, 12, 31), period_start=date(2009, 1, 1))
    assert discover_annual_period(AAPL, "net_income", BEFORE_10K, conn=fund) is None


def test_batch_matches_instant_facts_null_safely_in_one_round_trip(fund):
    eq = FiscalPeriod(period_end=date(2009, 9, 26))            # balance-sheet item: period_start is NULL
    out = get_fundamentals_batch([(AAPL, "net_income", AAPL_FY2009), (AAPL, "stockholders_equity", eq),
                                  (MSFT, "net_income", MSFT_FY2009)], BEFORE_10KA, conn=fund)
    assert out[(AAPL, "net_income")].value == 5_704_000_000
    assert out[(AAPL, "stockholders_equity")].value == 27_832_000_000
    assert out[(MSFT, "net_income")].value == 14_569_000_000


def test_the_store_refuses_a_duplicate_instant_fact(fund):
    """UNIQUE NULLS NOT DISTINCT: a re-load of an instant fact must not double it."""
    with fund.cursor() as cur, pytest.raises(psycopg2.errors.UniqueViolation):
        cur.execute("""INSERT INTO fundamental_fact(cik, concept, raw_concept, period_start, period_end, value, unit,
                       source_accession, filing_type, source_url, valid_time, knowledge_time, filed_at, effective_from)
                       SELECT cik, concept, raw_concept, period_start, period_end, value, unit, source_accession,
                              filing_type, source_url, valid_time, knowledge_time, filed_at, effective_from
                       FROM fundamental_fact WHERE cik = %s AND concept = 'stockholders_equity' LIMIT 1""", (MSFT,))
    fund.rollback()


# -- prices: the gold layer ------------------------------------------------------------------------------------------

def test_price_is_the_last_close_on_or_before_the_as_of_date(md):
    p = get_price_asof("AAPL", datetime(2009, 11, 29, tzinfo=timezone.utc), conn=md)      # a Sunday
    assert p.trading_date == date(2009, 11, 27) and p.adj_close == pytest.approx(24.10)
    assert get_price_asof("AAPL", datetime(2009, 9, 1, tzinfo=timezone.utc), conn=md) is None


def test_a_superseded_security_row_without_prices_does_not_hide_the_history(md):
    """AAPL's 2009 SCD-2 row has no price rows (as in the real data); the lookup still finds its 2009 prices."""
    with md.cursor() as cur:
        cur.execute("SELECT count(*) FROM dim_security WHERE ticker = 'AAPL' AND NOT is_current")
        assert cur.fetchone()[0] == 1
    p = get_price_asof("AAPL", datetime(2009, 12, 1, tzinfo=timezone.utc), conn=md)
    assert p.trading_date == date(2009, 11, 30) and p.reconciliation_flag == "agreed"


def test_only_one_current_row_per_ticker(md):
    with md.cursor() as cur, pytest.raises(psycopg2.errors.UniqueViolation):
        cur.execute("INSERT INTO dim_security(ticker, effective_from, is_current) VALUES ('AAPL', '2011-01-01', TRUE)")
    md.rollback()


def test_reconciliation_flag_travels_with_the_price(md):
    p = get_price_asof("AAPL", datetime(2010, 2, 1, tzinfo=timezone.utc), conn=md)
    assert p.reconciliation_flag == "disagreed" and p.primary_source == "yfinance"


# -- crosswalk and the panel -----------------------------------------------------------------------------------------

def test_crosswalk_is_case_insensitive_and_loud_on_unknown_tickers(tickers):
    assert crosswalk.get_cik_for_ticker("aapl") == AAPL
    with pytest.raises(ValueError, match="not found"):
        crosswalk.get_cik_for_ticker("ZZZZ")


def test_panel_joins_both_databases_at_one_instant(tickers):
    before = get_panel({"AAPL": AAPL_FY2009, "MSFT": MSFT_FY2009}, BEFORE_10KA)
    after = get_panel({"AAPL": AAPL_FY2009, "MSFT": MSFT_FY2009}, AFTER_10KA)
    assert before["AAPL"].net_income == 5_704_000_000 and after["AAPL"].net_income == 8_235_000_000
    assert before["AAPL"].roe == pytest.approx(5_704 / 27_832)
    assert after["AAPL"].roe == pytest.approx(8_235 / 31_640)
    assert before["AAPL"].price_trading_date == date(2009, 11, 30)
    assert after["MSFT"].adj_close == pytest.approx(21.56) and after["MSFT"].equity == 39_558_000_000


def test_auto_discovery_end_to_end(tickers):
    row = get_panel_row_auto("AAPL", AFTER_10KA)
    assert row.period == AAPL_FY2009 and row.net_income == 8_235_000_000
    with pytest.raises(ValueError, match="No annual net_income period"):
        get_panel_row_auto("AAPL", BEFORE_10K)
