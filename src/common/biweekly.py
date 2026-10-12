"""Pure date-math for the biweekly narrative-trends report's fixed cadence:
Thursday-to-Wednesday, 14 days, anchored to the archive's own first report
date (2026-08-20, confirmed Thursday) - see CLAUDE.md for the full
specification and PROJECT_LOG 4.82 for why this anchor/cadence was chosen as
the *current default* (not yet a final decision on which weekday to start on
- that is explicitly left open for a separate decision).

No side effects, no DB access - shared by synthesize_biweekly.py (decides
whether a period is due when run by hand with no arguments),
scripts/biweekly_autorun.py (the scheduled overnight run - see
latest_closed_period), daily_autorun.py (its "is a closed period missing"
warning) and publish.py (lists closed periods for the hub page).
"""
from datetime import date, timedelta

ANCHOR_START = date(2026, 8, 20)  # first Thursday the archive's daily reports begin on
PERIOD_LENGTH_DAYS = 14


def period_containing(d: date) -> tuple[date, date]:
    """Returns (start, end) of the 14-day period `d` falls in, counting from
    ANCHOR_START - always returns a pair, even if `d` is before the anchor
    (a negative offset still divides evenly) or the period isn't finished yet."""
    offset = (d - ANCHOR_START).days
    period_index = offset // PERIOD_LENGTH_DAYS
    start = ANCHOR_START + timedelta(days=period_index * PERIOD_LENGTH_DAYS)
    end = start + timedelta(days=PERIOD_LENGTH_DAYS - 1)
    return start, end


def period_closing_on(d: date) -> tuple[date, date] | None:
    """Returns (start, end) if `d` is exactly the closing day (end date) of a
    period, else None. This is the check daily_autorun.py's conditional
    biweekly step uses: "did a period just close today?" """
    start, end = period_containing(d)
    return (start, end) if end == d else None


def all_closed_periods_through(d: date) -> list[tuple[date, date]]:
    """Every period whose end date is on or before `d`, oldest first - used
    for one-off backfill/migration, not by the daily automation check."""
    periods = []
    start = ANCHOR_START
    while True:
        end = start + timedelta(days=PERIOD_LENGTH_DAYS - 1)
        if end > d:
            break
        periods.append((start, end))
        start = end + timedelta(days=1)
    return periods


def latest_closed_period(as_of: date, max_age_days: int | None = None) -> tuple[date, date] | None:
    """The most recent period that had fully ended BEFORE `as_of` (its end date
    is yesterday or earlier), or None if there is none - or if it ended more
    than `max_age_days` days before `as_of`.

    This, not period_closing_on(), is the right question for anything that
    runs after midnight: the overnight biweekly run fires early on Thursday,
    when "today" is already the first day of the NEXT period and
    period_closing_on(today) is None by definition."""
    closed = all_closed_periods_through(as_of - timedelta(days=1))
    if not closed:
        return None
    start, end = closed[-1]
    if max_age_days is not None and (as_of - end).days > max_age_days:
        return None
    return start, end
