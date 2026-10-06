"""Coverage-trend data layer (country/region x week) - groundwork for a future
trends page, NOT a page itself (see PROJECT_LOG 4.78/4.79 for the diagnostic
and the empirical tuning behind every constant below; CLAUDE.md for the
"REPORT_DATE_SQL is the only allowed day-grouping expression" rule this module
follows).

The core metric throughout is DISTINCT SOURCES (newspapers) covering a
country/region in a given period - not raw article count. This was chosen
and empirically verified (4.78) to be far more resistant to the volume-vs-
importance distortion already documented in Known Limitations: a backlog day
that absorbs several real calendar days' worth of articles still only has as
many distinct newspapers as actually published that nominal day, so its
distinct-source count is a much smaller artifact than its raw article count
(concrete example measured: France on 2026-10-02 showed 57 articles but only
5 distinct sources - a day with an ordinary source-count).

Two different granularities serve two different purposes, intentionally not
conflated:
  - DAY-level density (fraction of the archive's report-dates a country is
    tagged on at all) is the GATING signal - which countries have enough
    real data to trust a trend at all. Week-level presence turned out NOT to
    discriminate with only ~7 weeks of archive (4.79): almost any country
    that is ever mentioned shows up in most weeks just by having one hit in
    a 7-day window, so day-level density is used for the gate even though...
  - ...WEEK-level aggregation is what a future trend view would actually
    plot - smooths over the sharpest single-day backlog artifacts (a
    backlog day's inflated distinct-source count blends into that week's
    total rather than standing alone as a visible spike).
"""

from collections import defaultdict
from datetime import date, timedelta

from src.common.db import REPORT_DATE_SQL
from src.common.geo_taxonomy import COUNTRY_TO_REGION

# --- Backlog/retroactive-resynthesis detection (empirically tuned, 4.79) ---
# Flags a report_date as a volume outlier if its total raw article count is
# at least this many times the median of its `window` nearest neighbors (by
# position in the sequence of dates that actually have a report - not
# calendar adjacency, since the archive has real gaps, e.g. 2026-08-31/09-01/
# 09-02 are missing entirely and must not count as "low neighbors").
# Verified against the 6 known cases documented in PROJECT_LOG 4.78
# (2026-08-28, 09-03, 09-11, 09-18, 09-25, 10-02 - backlog-merge and
# rescope-retroactive-resynthesis days already on record): window=3,
# threshold=2.5 catches exactly these 6 with ZERO false positives on the
# other 38 report-dates. threshold=2.0 also catches all 6 but adds one
# borderline extra (2026-08-29, itself plausibly backlog-adjacent but not
# one of the 6 originally identified) - 2.5 was chosen as the cleaner cut.
BACKLOG_NEIGHBOR_WINDOW = 3
BACKLOG_RATIO_THRESHOLD = 2.5

# --- Country exposure gate (empirically tuned, 4.79) ---
# A simple "appears in >=60% of weeks" gate was tested and rejected: with
# only ~7 weeks in the archive so far, mere day-level presence is too coarse
# a signal - 81/93 countries already clear 60% of weeks just from one
# mention somewhere in each window, which does not match the much starker
# day-level split actually observed (median country present on 19/44 days;
# a distinct cluster of 11 present on 95-100% of days, then a real gap down
# to the next tier at 84%). The gate below uses DAY-level density instead
# (see module docstring) - 0.85 lands exactly on that gap: it isolates
# {CA, CN, DE, FR, GB, IL, IR, PS, RU, UA, US} (11 countries) and nothing
# else, stable across the whole 0.85-0.95 range tested.
COUNTRY_DAY_COVERAGE_THRESHOLD = 0.85

WEEK_LENGTH_DAYS = 7


def week_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Sequential WEEK_LENGTH_DAYS-day chunks from start to end (the last
    chunk may be shorter) - anchored at the archive's own first date, not
    calendar-Monday-aligned. Same simple-chunking philosophy already used by
    scripts/analytics_report.py's within_month_weeks() for the periodic
    email reports - reimplemented locally rather than imported, since src/
    never imports from scripts/ (see CLAUDE.md)."""
    chunks = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=WEEK_LENGTH_DAYS - 1), end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def _week_index_for(d: date, chunks: list[tuple[date, date]]) -> int | None:
    for i, (ws, we) in enumerate(chunks):
        if ws <= d <= we:
            return i
    return None


def get_daily_article_totals(conn) -> dict[str, int]:
    """{report_date: total article count that day} - the raw signal
    detect_backlog_dates() runs its ratio test against."""
    # Alias deliberately NOT "report_date" - downloaded_files.report_date is
    # a real (mostly-NULL) column in scope via the join, and SQLite resolves
    # a bare GROUP BY/ORDER BY name to that column in preference to a
    # same-named SELECT-list alias. Using "report_date" here silently
    # grouped by the raw nullable column instead of the computed
    # REPORT_DATE_SQL expression - caught only by testing against known
    # values (PROJECT_LOG 4.79), not visible from the query text alone.
    query = f"""
        SELECT {REPORT_DATE_SQL} AS rdate, COUNT(DISTINCT a.id) AS n
        FROM articles a
        JOIN downloaded_files df ON df.id = a.file_id
        GROUP BY rdate
        ORDER BY rdate
    """
    return {row["rdate"]: row["n"] for row in conn.execute(query)}


def detect_backlog_dates(
    conn,
    window: int = BACKLOG_NEIGHBOR_WINDOW,
    ratio_threshold: float = BACKLOG_RATIO_THRESHOLD,
) -> set[str]:
    """Report-dates whose total article count is a volume outlier relative
    to their nearest neighbors in the existing report-date sequence - a
    data-driven stand-in for the previously-manual list of known backlog/
    retroactive-resynthesis days (see module docstring for the empirical
    tuning behind the defaults)."""
    totals = get_daily_article_totals(conn)
    dates = sorted(totals)
    flagged = set()
    for i, d in enumerate(dates):
        neighbor_idx = list(range(max(0, i - window), i)) + list(
            range(i + 1, min(len(dates), i + 1 + window))
        )
        if not neighbor_idx:
            continue
        neighbor_counts = sorted(totals[dates[j]] for j in neighbor_idx)
        mid = len(neighbor_counts) // 2
        baseline = (
            neighbor_counts[mid]
            if len(neighbor_counts) % 2
            else (neighbor_counts[mid - 1] + neighbor_counts[mid]) / 2
        )
        if baseline and totals[d] / baseline >= ratio_threshold:
            flagged.add(d)
    return flagged


def get_country_date_source_rows(conn) -> list[tuple[str, str, str]]:
    """Every distinct (country_code, report_date, newspaper) triple - the
    finest-grained signal everything else in this module is built from.
    Deliberately NOT pre-aggregated to (country, date) here: week-bucketing
    needs to re-count DISTINCT sources per week, and aggregating per-day
    first and summing would double-count a source that published on two
    different days of the same week."""
    # Alias "rdate", not "report_date" - see get_daily_article_totals()'s
    # comment for why the latter silently groups/orders by the wrong column
    # (a real, mostly-NULL downloaded_files.report_date in scope via the
    # join) instead of this computed expression. This query has no GROUP BY/
    # ORDER BY naming the alias, but kept consistent for the same reason and
    # to avoid the trap resurfacing if this query is ever extended.
    query = f"""
        SELECT DISTINCT ac.country_code, {REPORT_DATE_SQL} AS rdate, a.newspaper
        FROM article_countries ac
        JOIN articles a ON a.id = ac.article_id
        JOIN downloaded_files df ON df.id = a.file_id
    """
    return [(row["country_code"], row["rdate"], row["newspaper"]) for row in conn.execute(query)]


def get_country_day_coverage_fractions(conn) -> dict[str, float]:
    """{country_code: fraction of the archive's report-dates it is tagged on
    at all} - the GATING signal (see module docstring for why this is used
    instead of week-level presence)."""
    rows = get_country_date_source_rows(conn)
    all_dates = {r[1] for r in rows}
    total_days = len(all_dates)
    days_per_country: dict[str, set[str]] = defaultdict(set)
    for cc, rdate, _ in rows:
        days_per_country[cc].add(rdate)
    return {cc: len(days) / total_days for cc, days in days_per_country.items()} if total_days else {}


def eligible_countries(conn, threshold: float = COUNTRY_DAY_COVERAGE_THRESHOLD) -> set[str]:
    """Countries with enough day-level density to trust a trend view for
    (see COUNTRY_DAY_COVERAGE_THRESHOLD's tuning note)."""
    fractions = get_country_day_coverage_fractions(conn)
    return {cc for cc, frac in fractions.items() if frac >= threshold}


def _week_backlog_dates(chunks: list[tuple[date, date]], backlog_dates: set[str]) -> dict[int, list[str]]:
    """week_index -> sorted list of the specific backlog-flagged dates whose
    calendar day falls inside that week (empty list if none). Kept as an
    explicit list rather than collapsing straight to a boolean: with only 6
    known backlog days spread across 7 weeks of archive, a bare true/false
    flags 6 of the 7 weeks (verified in practice, PROJECT_LOG 4.79) - a
    future view needs to know WHICH day(s) specifically to annotate a point,
    not just that the week containing it isn't pristine."""
    result: dict[int, list[str]] = defaultdict(list)
    for i, (ws, we) in enumerate(chunks):
        for bd in backlog_dates:
            if ws <= date.fromisoformat(bd) <= we:
                result[i].append(bd)
    for i in result:
        result[i].sort()
    return dict(result)


def _build_week_trends(conn, group_by) -> dict:
    """Shared implementation for build_country_week_trends() (group_by=None,
    keys by country_code directly) and build_region_week_trends() (group_by=
    COUNTRY_TO_REGION.get, keys by region, dropping unmapped countries)."""
    rows = get_country_date_source_rows(conn)
    if not rows:
        return {}

    all_dates = sorted({date.fromisoformat(r[1]) for r in rows})
    chunks = week_chunks(all_dates[0], all_dates[-1])
    week_backlog = _week_backlog_dates(chunks, detect_backlog_dates(conn))

    buckets: dict[tuple[str, int], set[str]] = defaultdict(set)
    for cc, rdate, newspaper in rows:
        key = group_by(cc) if group_by else cc
        if key is None:
            continue
        wi = _week_index_for(date.fromisoformat(rdate), chunks)
        if wi is not None:
            buckets[(key, wi)].add(newspaper)

    result: dict[str, list[dict]] = defaultdict(list)
    for (key, wi), sources in buckets.items():
        ws, we = chunks[wi]
        flagged = week_backlog.get(wi, [])
        result[key].append(
            {
                "week_start": ws.isoformat(),
                "week_end": we.isoformat(),
                "n_sources": len(sources),
                "has_backlog": bool(flagged),
                "backlog_dates": flagged,
            }
        )
    for key in result:
        result[key].sort(key=lambda r: r["week_start"])
    return dict(result)


def build_country_week_trends(conn) -> dict:
    """{country_code: [{week_start, week_end, n_sources, has_backlog,
    backlog_dates}, ...]} for every country that appears at all (callers
    filter by eligible_countries() themselves - this function does not
    gate, so it stays useful for inspection/debugging of ungated countries
    too).

    n_sources is the count of DISTINCT newspapers covering that country
    within the week (re-deduplicated across the week's days, not a sum of
    daily counts - see get_country_date_source_rows()). backlog_dates lists
    which specific date(s) inside that week's calendar span were flagged by
    detect_backlog_dates() (empty if none); has_backlog is just
    bool(backlog_dates) for callers that only need a flag."""
    return _build_week_trends(conn, group_by=None)


def build_region_week_trends(conn) -> dict:
    """Same shape as build_country_week_trends(), aggregated to the 8 fixed
    regions in geo_taxonomy.COUNTRY_TO_REGION instead of countries. Not
    gated by eligible_countries() / an equivalent region threshold - regions
    aggregate many countries each, so sparsity was not observed to be a
    concern for them (not empirically re-verified per-region here; revisit
    if a region turns out thin when this is actually built into a view)."""
    return _build_week_trends(conn, group_by=COUNTRY_TO_REGION.get)
