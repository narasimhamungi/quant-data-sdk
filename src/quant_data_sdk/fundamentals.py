"""
Wrappers around pit-fundamentals-store's fundamentals_asof(cik, concept,
as_of) SQL function, plus a period-discovery helper that queries
fundamental_fact directly.

Calls fundamentals_asof() ONLY where a FiscalPeriod is already known.
Never queries fundamentals_latest.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from .connections import get_fundamentals_connection

logger = logging.getLogger(__name__)

# Annual duration heuristic for discover_annual_period(): period_end minus
# period_start, in days. 365 is the obvious center; the [350, 380] window
# absorbs 52/53-week fiscal calendars (AAPL's FY2009 was 363 days, MSFT's
# was 364) without also matching a 9-month cumulative context (~270 days)
# or a quarterly one (~90 days).
#
# NOT sufficient on its own — confirmed against real AMZN data, not a
# hypothetical: a 10-Q can carry a trailing-twelve-months duration
# context alongside its quarterly one, which is annual-LENGTH without
# being a fiscal year. AMZN's period_start=2009-07-01/period_end=2010-06-30
# (filing_type='10-Q', filed 2010-07-23) is exactly this — an annual-shaped
# TTM window, not FY2009 or FY2010. Restricting to 10-K/10-K-A filings
# below is what actually distinguishes "a fiscal year" from "a duration
# that happens to be a year long."
_ANNUAL_DURATION_MIN_DAYS = 350
_ANNUAL_DURATION_MAX_DAYS = 380
_ANNUAL_FILING_TYPES = ("10-K", "10-K/A")


@dataclass(frozen=True)
class FiscalPeriod:
    """
    (period_start, period_end) together are pit-fundamentals-store's
    real compound key for "one fiscal period" — see key_for_fact() in
    that repo's temporal.py. A single filing routinely tags more than
    one duration context ending on the same date (a 3-month quarterly
    figure and a 9-month or full-year cumulative figure both ending
    2009-09-30, for instance) — period_end alone does not disambiguate
    between them.

    period_start is None only for instant facts (balance-sheet items
    like stockholders_equity) — those have no duration, so there's
    nothing to disambiguate.
    """
    period_end: date
    period_start: Optional[date] = None


@dataclass
class FundamentalFact:
    cik: int
    concept: str
    raw_concept: str
    period_start: Optional[date]
    period_end: date
    value: float
    unit: str
    filed_at: datetime
    source_accession: str
    source_url: str


def discover_annual_period(
    cik: int,
    concept: str,
    as_of: datetime,
    conn=None,
) -> Optional[FiscalPeriod]:
    """
    Find the most recent ANNUAL-duration FiscalPeriod known for
    (cik, concept) as of as_of, without the caller already knowing it.

    Every FiscalPeriod used in this SDK so far (AAPL's FY2009, MSFT's
    FY2009) was found by hand, via a one-off diagnostic query against
    fundamental_fact — a pattern that doesn't scale past the first
    couple of companies. This makes that discovery step part of the SDK
    instead of a manual step outside it.

    Deliberately does NOT use fundamentals_asof() — that function
    requires already knowing period_end, which is exactly what's being
    discovered here. Queries fundamental_fact directly, restricted to
    rows whose knowledge_time covers as_of (the same correctness
    property used everywhere else in this SDK), filtered to
    annual-duration candidates by (period_end - period_start) AND to
    10-K/10-K-A filings specifically — duration length alone is not
    enough (see _ANNUAL_FILING_TYPES comment above) — and picks the
    most recently-ending one.

    If more than one candidate shares the same (latest) period_end —
    which would mean the heuristic itself is ambiguous for this
    company — that's logged, not silently resolved.
    """
    own_conn = conn is None
    conn = conn or get_fundamentals_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT period_start, period_end
                FROM fundamental_fact
                WHERE cik = %s
                  AND concept = %s
                  AND period_start IS NOT NULL
                  AND (period_end - period_start) BETWEEN %s AND %s
                  AND filing_type = ANY(%s)
                  AND knowledge_time @> %s
                ORDER BY period_end DESC, period_start DESC
                LIMIT 2
                """,
                (
                    cik, concept, _ANNUAL_DURATION_MIN_DAYS, _ANNUAL_DURATION_MAX_DAYS,
                    list(_ANNUAL_FILING_TYPES), as_of,
                ),
            )
            rows = cur.fetchall()
        if not rows:
            return None
        if len(rows) > 1 and rows[0][1] == rows[1][1]:
            logger.warning(
                "cik=%s concept=%s as_of=%s: multiple annual-duration candidates "
                "share period_end=%s (period_starts %s and %s) — the annual "
                "heuristic is ambiguous for this company. Keeping period_start=%s.",
                cik, concept, as_of, rows[0][1], rows[0][0], rows[1][0], rows[0][0],
            )
        return FiscalPeriod(period_start=rows[0][0], period_end=rows[0][1])
    finally:
        if own_conn:
            conn.close()


def get_fundamental_asof(
    cik: int,
    concept: str,
    as_of: datetime,
    period: Optional[FiscalPeriod] = None,
    conn=None,
) -> Optional[FundamentalFact]:
    """
    Fact known as of `as_of`, for one (cik, concept) pair.

    fundamentals_asof() returns one row per (period_start, period_end)
    whose knowledge_time covers as_of — every duration context the
    company has ever reported for that concept, not just the one you
    meant. Pass a FiscalPeriod to pin both period_start and period_end;
    omitting it falls back to "last row after sorting by period_end
    only," which is provisional at best.

    After filtering to a specific FiscalPeriod, at most one row should
    remain — knowledge_time ranges within a single (period_start,
    period_end) group are non-overlapping by construction. If more than
    one still comes back, that's logged rather than silently resolved.
    """
    own_conn = conn is None
    conn = conn or get_fundamentals_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT cik, concept, raw_concept, period_start, period_end, "
                "value, unit, filed_at, source_accession, source_url "
                "FROM fundamentals_asof(%s, %s, %s)",
                (cik, concept, as_of),
            )
            rows = cur.fetchall()
        if period is not None:
            rows = [
                r for r in rows
                if r[4] == period.period_end and r[3] == period.period_start
            ]
        if len(rows) > 1:
            logger.warning(
                "cik=%s concept=%s period=%s as_of=%s: %d rows matched a single "
                "FiscalPeriod — expected at most 1. Keeping the last one seen.",
                cik, concept, period, as_of, len(rows),
            )
        if not rows:
            return None
        r = rows[-1]
        return FundamentalFact(
            cik=r[0], concept=r[1], raw_concept=r[2], period_start=r[3],
            period_end=r[4], value=float(r[5]), unit=r[6], filed_at=r[7],
            source_accession=r[8], source_url=r[9],
        )
    finally:
        if own_conn:
            conn.close()


def get_fundamentals_batch(
    requests_: list[tuple[int, str, FiscalPeriod]],
    as_of: datetime,
    conn=None,
) -> dict[tuple[int, str], Optional[FundamentalFact]]:
    """
    Batched version of get_fundamental_asof: one round trip for many
    (cik, concept, FiscalPeriod) triples at a single as_of instant.

    Reuses fundamentals_asof() via a LATERAL join rather than
    reimplementing its knowledge_time @> as_of logic in Python.

    period_start may be NULL (instant facts) — matched with
    IS NOT DISTINCT FROM, the same NULL-safe comparison
    pit-fundamentals-store's own schema already relies on for its
    UNIQUE NULLS NOT DISTINCT constraint.
    """
    if not requests_:
        return {}
    own_conn = conn is None
    conn = conn or get_fundamentals_connection()
    ciks = [r[0] for r in requests_]
    concepts = [r[1] for r in requests_]
    period_starts = [r[2].period_start for r in requests_]
    period_ends = [r[2].period_end for r in requests_]
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT req.cik, req.concept, req.period_start, req.period_end,
                       fa.raw_concept, fa.value, fa.unit,
                       fa.filed_at, fa.source_accession, fa.source_url
                FROM unnest(%s::bigint[], %s::text[], %s::date[], %s::date[])
                     AS req(cik, concept, period_start, period_end)
                CROSS JOIN LATERAL fundamentals_asof(req.cik, req.concept, %s) fa
                WHERE fa.period_end = req.period_end
                  AND fa.period_start IS NOT DISTINCT FROM req.period_start
                """,
                (ciks, concepts, period_starts, period_ends, as_of),
            )
            rows = cur.fetchall()

        resolved: dict[tuple[int, str], FundamentalFact] = {}
        for r in rows:
            key = (r[0], r[1])
            if key in resolved:
                logger.warning(
                    "Multiple facts resolved for cik=%s concept=%s period_start=%s "
                    "period_end=%s at as_of=%s — keeping the last row seen.",
                    r[0], r[1], r[2], r[3], as_of,
                )
            resolved[key] = FundamentalFact(
                cik=r[0], concept=r[1], raw_concept=r[4], period_start=r[2],
                period_end=r[3], value=float(r[5]), unit=r[6], filed_at=r[7],
                source_accession=r[8], source_url=r[9],
            )

        return {(cik, concept): resolved.get((cik, concept)) for cik, concept, _ in requests_}
    finally:
        if own_conn:
            conn.close()
