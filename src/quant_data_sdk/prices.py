"""
Price lookup against marketdata-lakehouse's gold layer
(fact_price_daily_consensus, dim_security, dim_date).

CORRECTED from an earlier version that filtered dim_security by
effective_from/effective_to to find "the security identity valid on
as_of's date." That was based on a wrong theory of the schema.
build_fact_price_daily_consensus() (that repo's own loader) resolves
security_key via `WHERE is_current` at the moment a price BATCH is
ingested — not per the date each individual price row represents — and
its INSERT uses `ON CONFLICT (security_key, date_key) DO UPDATE`, so a
price row's security_key never changes after the fact even if
dim_security later splits into a new current row. Practically: a
ticker's entire price history, however many years back it goes, ends up
stored under whichever security_key was current when that batch was
loaded — not under any date-appropriate historical security_key.

Confirmed by testing, not just inferred: adding a correct, non-orphaned
historical dim_security row for AAPL (effective 2009-2010) did NOT
unblock a single 2009 price lookup, because no fact_price_daily_consensus
row was ever written against that key — proving the old filter was
matching the wrong dimension row on principle, not just on missing data.

This version matches on ticker alone, across every dim_security row
that ticker has ever had, and lets the INNER JOIN naturally select only
the security_key(s) that actually have price rows. This sacrifices
genuine point-in-time identity resolution on the price side (a ticker
that was ever reassigned to a different company would misresolve here)
— but that's now an honestly-stated limitation matching how the
underlying data is actually keyed, not a theoretical one being silently
carried by a filter that never did anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from .connections import get_marketdata_connection


@dataclass
class PriceAsOf:
    ticker: str
    trading_date: date
    adj_close: float
    primary_source: str
    reconciliation_flag: str


def get_price_asof(ticker: str, as_of: datetime, conn=None) -> Optional[PriceAsOf]:
    """
    Most recent adj_close on or before as_of's calendar date, for any
    security_key ever associated with this ticker (see module docstring
    for why "any," not "the one valid as of this date").
    """
    own_conn = conn is None
    conn = conn or get_marketdata_connection()
    as_of_date = as_of.date() if isinstance(as_of, datetime) else as_of
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT dd.date, fp.adj_close, fp.primary_source, fp.reconciliation_flag
                FROM fact_price_daily_consensus fp
                JOIN dim_security ds ON ds.security_key = fp.security_key
                JOIN dim_date dd ON dd.date_key = fp.date_key
                WHERE ds.ticker = %s
                  AND dd.date <= %s
                ORDER BY dd.date DESC
                LIMIT 1
                """,
                (ticker, as_of_date),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return PriceAsOf(
            ticker=ticker,
            trading_date=row[0],
            adj_close=float(row[1]),
            primary_source=row[2],
            reconciliation_flag=row[3],
        )
    finally:
        if own_conn:
            conn.close()
