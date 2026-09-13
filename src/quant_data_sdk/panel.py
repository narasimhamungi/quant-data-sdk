"""
Point-in-time-correct panel construction.

get_panel() is the core implementation — get_panel_row() and
get_panel_row_auto() are single-ticker convenience wrappers over it.

Every period must be a FiscalPeriod (period_start + period_end) — see
fundamentals.py for why period_end alone was ambiguous. get_panel_row()
requires the caller to already know it; get_panel_row_auto() discovers
it via fundamentals.discover_annual_period() instead — the latter is
what actually removes the "diagnose this by hand first" bottleneck that
every ticker used so far has gone through.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .crosswalk import get_cik_for_ticker
from .fundamentals import FiscalPeriod, discover_annual_period, get_fundamentals_batch
from .prices import get_price_asof


@dataclass
class PanelRow:
    ticker: str
    as_of: datetime
    period: FiscalPeriod
    net_income: Optional[float]
    equity: Optional[float]
    roe: Optional[float]
    adj_close: Optional[float]
    price_trading_date: Optional[object]
    price_reconciliation_flag: Optional[str]


def get_panel(ticker_periods: dict[str, FiscalPeriod], as_of: datetime) -> dict[str, PanelRow]:
    tickers = list(ticker_periods.keys())
    cik_by_ticker = {t: get_cik_for_ticker(t) for t in tickers}

    net_income_requests = [
        (cik_by_ticker[t], "net_income", ticker_periods[t]) for t in tickers
    ]
    equity_requests = [
        (cik_by_ticker[t], "stockholders_equity",
         FiscalPeriod(period_end=ticker_periods[t].period_end, period_start=None))
        for t in tickers
    ]
    net_income_facts = get_fundamentals_batch(net_income_requests, as_of)
    equity_facts = get_fundamentals_batch(equity_requests, as_of)

    out: dict[str, PanelRow] = {}
    for t in tickers:
        cik = cik_by_ticker[t]
        period = ticker_periods[t]
        ni_fact = net_income_facts.get((cik, "net_income"))
        eq_fact = equity_facts.get((cik, "stockholders_equity"))
        price = get_price_asof(t, as_of)

        net_income = ni_fact.value if ni_fact else None
        equity = eq_fact.value if eq_fact else None
        roe = (
            net_income / equity
            if (net_income is not None and equity not in (None, 0))
            else None
        )

        out[t] = PanelRow(
            ticker=t, as_of=as_of, period=period,
            net_income=net_income, equity=equity, roe=roe,
            adj_close=price.adj_close if price else None,
            price_trading_date=price.trading_date if price else None,
            price_reconciliation_flag=price.reconciliation_flag if price else None,
        )
    return out


def get_panel_row(ticker: str, as_of: datetime, period: FiscalPeriod) -> PanelRow:
    """Single-ticker convenience wrapper over get_panel(). Requires the
    caller to already know ticker's FiscalPeriod."""
    return get_panel({ticker: period}, as_of)[ticker]


def get_panel_row_auto(ticker: str, as_of: datetime) -> PanelRow:
    """
    Fully auto-discovering version of get_panel_row(): resolves CIK via
    the crosswalk, discovers the most recent annual fiscal period known
    as of as_of via discover_annual_period() (against net_income — an
    arbitrary but reasonable anchor concept, since it's the one concept
    confirmed present for every company ingested so far), then proceeds
    exactly like get_panel_row(). No FiscalPeriod needs to be known in
    advance — this is what actually removes the "diagnose it by hand
    with psql first" step every ticker has needed until now.
    """
    cik = get_cik_for_ticker(ticker)
    period = discover_annual_period(cik, "net_income", as_of)
    if period is None:
        raise ValueError(
            f"No annual net_income period found for {ticker} (CIK {cik}) as of "
            f"{as_of} — check whether this company has actually been ingested "
            f"into pit-fundamentals-store at all."
        )
    return get_panel_row(ticker, as_of, period)
