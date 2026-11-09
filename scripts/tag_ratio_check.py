"""Country tags per article, adjusted for newspaper mix and day kind, with a z-score against sync days (PROJECT_LOG 4.135).

Read-only (opens tracker.db with mode=ro), no API calls. Used by the post-run verification (which lives outside the
repository and imports this module) and runnable by hand:

    python -m scripts.tag_ratio_check [--from 2026-10-10] [--to 2026-11-09] [--db <path>]

Method. For a report date d the expected number of tags is the sum over newspapers of (articles of that newspaper on d) x
(tags per article of that newspaper in the reference days of the same kind: weekday vs Saturday/Sunday). The adjusted ratio
is actual / expected, so a day heavy in a newspaper that tags little does not look like a drop. The spread of the same ratio
on the reference days themselves (each computed against the OTHER reference days) gives mean and standard deviation per day
kind, and z = (ratio - mean) / sd. The same is done for NAMED tags (country named in headline, summary or excerpt - the
ones the trends map counts).

Reference days are FROZEN to the last sync window before batch analysis began (2026-10-10 .. 2026-11-06), so the reference
does not drift as batch days accumulate. The accepted batch effect (about -3% tags per article, PROJECT_LOG 4.135) is
therefore inside the ratio of every batch day; the alert thresholds are on z, not on the raw gap.
"""
import argparse
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

REFERENCE_FIRST = "2026-10-10"
REFERENCE_LAST = "2026-11-06"   # last report date analyzed with regular (sync) calls
Z_ALERT_ONE_DAY = -2.0
Z_ALERT_STREAK = -1.5
STREAK_DAYS = 3
MIN_ARTICLES = 20               # a day with fewer analyzed articles has no meaningful ratio
FIELDS = ("A", "tags", "named")


def day_kind(day: str) -> str:
    return "weekend" if date.fromisoformat(day).weekday() >= 5 else "weekday"


def load_day_metrics(conn: sqlite3.Connection, first: str, last: str) -> dict:
    """{report_date: {newspaper: {"A": articles, "tags": tags, "named": named tags}}} for first..last."""
    from src.common.country_aliases import article_text, named_countries
    rd = "COALESCE(df.report_date, date(df.published_at))"
    conn.row_factory = sqlite3.Row
    codes = defaultdict(list)
    for r in conn.execute("SELECT article_id, country_code FROM article_countries ORDER BY id"):
        codes[r["article_id"]].append(r["country_code"])
    out: dict = defaultdict(lambda: defaultdict(lambda: dict.fromkeys(FIELDS, 0)))
    for r in conn.execute(
            f"SELECT a.id, {rd} AS d, df.newspaper AS n, a.headline, a.stance_summary, a.key_excerpt FROM articles a "
            f"JOIN downloaded_files df ON df.id = a.file_id WHERE {rd} >= ? AND {rd} <= ?", (first, last)):
        tags = codes.get(r["id"], [])
        named = named_countries(article_text(r["headline"], r["stance_summary"], r["key_excerpt"]))
        cell = out[r["d"]][r["n"]]
        cell["A"] += 1
        cell["tags"] += len(tags)
        cell["named"] += sum(1 for t in tags if t in named)
    return {d: {n: dict(v) for n, v in papers.items()} for d, papers in out.items()}


def reference_days(metrics: dict, first: str = REFERENCE_FIRST, last: str = REFERENCE_LAST) -> list[str]:
    return sorted(d for d in metrics if first <= d <= last and sum(p["A"] for p in metrics[d].values()) >= MIN_ARTICLES)


def _baseline(metrics: dict, ref: list[str], kind: str, exclude: str | None = None) -> dict:
    b: dict = defaultdict(lambda: dict.fromkeys(FIELDS, 0))
    for d in ref:
        if d == exclude or day_kind(d) != kind:
            continue
        for n, cell in metrics[d].items():
            for f in FIELDS:
                b[n][f] += cell[f]
    return b


def ratio_vs(metrics: dict, day: str, base: dict, key: str):
    """(actual, expected, ratio) of `key` on `day` against per-newspaper baseline rates; newspapers without a baseline are skipped."""
    act = exp = 0.0
    for n, cell in metrics[day].items():
        b = base.get(n)
        if b and b["A"]:
            act += cell[key]
            exp += cell["A"] * b[key] / b["A"]
    return act, exp, (act / exp if exp else None)


def spreads(metrics: dict, ref: list[str], key: str) -> dict:
    """{kind: (mean, sd, n)} of the leave-one-day-out adjusted ratio over the reference days of that kind."""
    out = {}
    for kind in ("weekday", "weekend"):
        rs = []
        for d in ref:
            if day_kind(d) != kind:
                continue
            r = ratio_vs(metrics, d, _baseline(metrics, ref, kind, exclude=d), key)[2]
            if r is not None:
                rs.append(r)
        out[kind] = (statistics.mean(rs), statistics.pstdev(rs), len(rs)) if len(rs) >= 3 else (None, None, len(rs))
    return out


def series(metrics: dict, days: list[str] | None = None, ref: list[str] | None = None) -> list[dict]:
    """One row per report date: raw and adjusted tags per article and named tags, each with its z-score."""
    ref = ref if ref is not None else reference_days(metrics)
    sp_tags, sp_named = spreads(metrics, ref, "tags"), spreads(metrics, ref, "named")
    rows = []
    for d in sorted(days if days is not None else metrics):
        if d not in metrics:
            continue
        articles = sum(p["A"] for p in metrics[d].values())
        if articles < MIN_ARTICLES:
            continue
        kind = day_kind(d)
        base = _baseline(metrics, ref, kind, exclude=d if d in ref else None)
        row = {"day": d, "kind": kind, "articles": articles, "in_reference": d in ref,
               "raw_tags_per_article": sum(p["tags"] for p in metrics[d].values()) / articles,
               "raw_named_per_article": sum(p["named"] for p in metrics[d].values()) / articles}
        for key, sp, name in (("tags", sp_tags, "tags"), ("named", sp_named, "named")):
            act, exp, ratio = ratio_vs(metrics, d, base, key)
            mean, sd, _ = sp[kind]
            row[f"{name}_ratio"] = ratio
            row[f"{name}_expected"] = exp
            row[f"{name}_actual"] = act
            row[f"{name}_z"] = ((ratio - mean) / sd) if ratio is not None and sd else None
        rows.append(row)
    return rows


def alert_decision(rows: list[dict]) -> tuple[bool, list[str]]:
    """rows = the series ending at the day being checked (consecutive report dates, oldest first).
    Alert when today's z < Z_ALERT_ONE_DAY, or the last STREAK_DAYS consecutive calendar days all have z < Z_ALERT_STREAK."""
    reasons = []
    if not rows or rows[-1].get("tags_z") is None:
        return False, ["no ratio for the day (too few articles or no reference)"]
    today = rows[-1]
    if today["tags_z"] < Z_ALERT_ONE_DAY:
        reasons.append(f"z {today['tags_z']:+.2f} is below {Z_ALERT_ONE_DAY:+.1f} on {today['day']}")
    last = rows[-STREAK_DAYS:]
    consecutive = len(last) == STREAK_DAYS and all(
        (date.fromisoformat(b["day"]) - date.fromisoformat(a["day"])).days == 1 for a, b in zip(last, last[1:]))
    if consecutive and all(r["tags_z"] is not None and r["tags_z"] < Z_ALERT_STREAK for r in last):
        reasons.append(f"{STREAK_DAYS} consecutive days with z below {Z_ALERT_STREAK:+.1f} ("
                       + ", ".join(f"{r['day'][5:]}: {r['tags_z']:+.2f}" for r in last) + ")")
    return bool(reasons), reasons


def format_table(rows: list[dict]) -> str:
    f = lambda x, p=3: "-" if x is None else f"{x:.{p}f}"
    lines = ["| date | kind | ref | articles | tags/article | adjusted ratio | z | named/article | named ratio | named z |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['day']} | {'wkend' if r['kind'] == 'weekend' else 'wkday'} | {'sync' if r['in_reference'] else 'batch/new'} | {r['articles']} | "
                     f"{f(r['raw_tags_per_article'])} | {f(r['tags_ratio'])} | {f(r['tags_z'], 2)} | "
                     f"{f(r['raw_named_per_article'])} | {f(r['named_ratio'])} | {f(r['named_z'], 2)} |")
    return "\n".join(lines)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from", dest="first", default=REFERENCE_FIRST)
    ap.add_argument("--to", dest="last", default=date.today().isoformat())
    ap.add_argument("--db", default=str(REPO / "data" / "processed" / "tracker.db"))
    a = ap.parse_args()
    conn = sqlite3.connect(f"file:{Path(a.db).as_posix()}?mode=ro", uri=True)
    metrics = load_day_metrics(conn, min(a.first, REFERENCE_FIRST), a.last)
    ref = reference_days(metrics)
    rows = [r for r in series(metrics, ref=ref) if a.first <= r["day"] <= a.last]
    sp = spreads(metrics, ref, "tags")
    print(f"reference: {len(ref)} sync days {REFERENCE_FIRST}..{REFERENCE_LAST}; tags-ratio spread on them: "
          + "; ".join(f"{k} mean {m:.3f} sd {s:.3f} (n={n})" for k, (m, s, n) in sp.items() if m is not None))
    print(format_table(rows))
    alert, reasons = alert_decision(rows)
    print(f"\nalert on the last day: {'YES - ' + '; '.join(reasons) if alert else 'no'}")


if __name__ == "__main__":
    main()
