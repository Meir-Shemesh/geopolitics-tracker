"""Data layer for the tile-map trends page (docs/{lang}/trendsmap.html) - PROJECT_LOG 4.123.

Everything here is read from the same conservative display as trends.json (PROJECT_LOG 4.122): a country counts in
an article only if the article names it (country_aliases.named_countries), so every figure is a LOWER BOUND, and the
shares below are meant to be compared with themselves over time, not between countries (the tagging retention
differs by country: Iran keeps about 75% of its tags, Poland about 30%).

share(country, week), for a set of newspapers:
    for every newspaper that delivered at least one named country-article pair that week:
        its own share = (its named articles about the country) / (all its named country-article pairs that week)
    share = the plain mean of those per-newspaper shares.
A newspaper that prints twice as much therefore does not count twice as much, and a weekly magazine counts as much as
a daily. `pooled` (all pairs together) is kept only to measure how much that choice matters (see pooled_shares).

Two series, because the source roster grew from 4 to 14 papers over the archive:
    core - the nine papers of trends.CORE_V1, from CORE_FIRST_WEEK_START (the roster is stable there)
    all  - the fourteen papers of ALL_PAPERS_V1, from the first week; read it with scope_breaks in view
"""

import math
from collections import defaultdict
from datetime import date, datetime, timezone

from src.common import trends
from src.common.geo_taxonomy import COUNTRY_LIST

# First week of the core series: the Thursday week that starts 2026-09-10, the first one in which all nine papers are
# active (Washington Post replaced NYT International on 2026-09-12). Fixed by decision (3.11.2026), like CORE_V1.
CORE_FIRST_WEEK_START = "2026-09-10"

# The fourteen papers the 3.11 analysis called "all 14": CORE_V1 plus the five that joined or left the roster later.
ALL_PAPERS_V1 = trends.CORE_V1 + (
    "Frankfurter Allgemeine Zeitung",
    "Neue Zürcher Zeitung",
    "Globe and Mail",
    "Observer",
    "Wall Street Journal",
)

# A country-week with fewer named articles than this carries too little evidence: one article more or less moves its
# share visibly. A change is drawn only if the week AND its baseline both reach it (see is_low_evidence): a jump from
# 0.1% to 1.9% is not a change if either end rests on a handful of articles.
MIN_EVIDENCE_ARTICLES = 10

# The tile list is the keys of MAP_TILES below: fixed in code and changed by hand, once a month (rule below), so that a
# country crossing a line on some Tuesday never makes a tile appear or vanish between two publishes.
# TILE_MIN_NAMED_ARTICLES is the line a country has to reach in the core papers over the core weeks (about four per
# week) to be a candidate; the JSON reports the candidates without a tile (`unplaced`) and the tiles under the line
# (`tile_list.below_threshold`) so the monthly review has what it needs.
#   Monthly rule: on the first working day of each month read `unplaced` and `tile_list.below_threshold` in
#   assets/data/trends_map.json. Add a country that was in `unplaced` in two reviews in a row (find it a free cell in
#   MAP_TILES and in tile_outline.txt if the outline needs it); remove a tile that was under half the line (15) in two
#   reviews in a row. Change TILE_LIST_REVIEWED_ON in the same commit.
TILE_MIN_NAMED_ARTICLES = 30
TILE_LIST_REVIEWED_ON = "2026-11-03"

# Provisional tile grid (column, row), 14 x 7 cells, laid out by approximate geography on top of a faint world
# outline (src/publishing/assets/map/tile_outline.txt, drawn on the same grid). Pending the product owner's approval.
MAP_GRID_COLS = 14
MAP_GRID_ROWS = 7
MAP_TILES = {
    "CA": (1, 1), "US": (1, 2), "MX": (1, 3), "CU": (2, 3), "VE": (2, 4), "BR": (3, 5), "AR": (2, 6),
    "IE": (3, 1), "GB": (4, 1), "FR": (4, 2), "ES": (4, 3), "IT": (5, 2), "DE": (5, 1), "NO": (5, 0), "SE": (6, 0),
    "PL": (6, 1), "RS": (6, 2), "UA": (7, 1), "RU": (8, 1), "TR": (7, 2),
    "IL": (7, 3), "PS": (7, 4), "SA": (8, 3), "AE": (9, 3), "YE": (8, 4), "SD": (6, 4), "ET": (7, 5),
    "IR": (9, 2), "AF": (10, 2), "PK": (10, 3), "IN": (10, 4), "CN": (11, 2), "KP": (12, 1), "KR": (12, 2),
    "JP": (13, 2), "TW": (12, 3),
}

# The one place that decides how a tile is called on the page. "Palestine" is not a country in the way the other tiles are,
# so the label is the people (the code stays PS everywhere in the data and on the mobile tile). Anything not listed here
# uses COUNTRY_LIST. Only the page reads this; the rest of the site is not touched.
DISPLAY_NAME_OVERRIDES = {
    "PS": {"he": "פלסטינים", "en": "Palestinians", "de": "Palästinenser"},
}

# Tile labels that would not fit a 54px tile in full. Only the exceptions; everything else uses COUNTRY_LIST.
TILE_SHORT_NAMES = {
    "US": {"he": "ארה\"ב", "en": "USA", "de": "USA"},
    "GB": {"en": "UK", "de": "UK"},
    "AE": {"he": "איחוד האמירויות", "en": "UAE", "de": "VAE"},
    "SA": {"he": "סעודיה", "en": "Saudi Arabia", "de": "Saudi-Arabien"},
    "KP": {"he": "צפון קוריאה", "en": "N. Korea", "de": "Nordkorea"},
    "KR": {"he": "דרום קוריאה", "en": "S. Korea", "de": "Südkorea"},
}


def last_full_week(weeks: list[dict]) -> int:
    """Index of the latest week with a full seven days of data: the page opens on it, not on a partial week."""
    full = [i for i, w in enumerate(weeks) if not w["partial"]]
    return full[-1] if full else max(len(weeks) - 1, 0)


def tile_display_name(code: str, lang: str, default: str) -> str:
    return DISPLAY_NAME_OVERRIDES.get(code, {}).get(lang, default)


def _week_grid(conn) -> list[tuple[date, date]]:
    """The same weekly grid trends.json uses: anchored at the first report date, from the UNFILTERED date range."""
    dates = sorted({date.fromisoformat(r[1]) for r in trends.get_country_date_source_rows(conn)})
    return trends.week_chunks(dates[0], dates[-1]) if dates else []


def _week_of(d: date, chunks: list[tuple[date, date]]) -> int | None:
    return trends._week_index_for(d, chunks)


def paper_week_counts(rows, chunks) -> dict[tuple[str, int], dict[str, set[int]]]:
    """{(newspaper, week): {country_code: {article_id}}} from get_country_article_rows(named_only=True)."""
    counts: dict[tuple[str, int], dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    for cc, rdate, newspaper, article_id in rows:
        wi = _week_of(date.fromisoformat(rdate), chunks)
        if wi is not None:
            counts[(newspaper, wi)][cc].add(article_id)
    return counts


def _reporting(counts, papers, week):
    """[(newspaper, {country: n_articles}, pairs)] for the papers that delivered a named pair in the week."""
    out = []
    for p in papers:
        per_country = counts.get((p, week))
        if not per_country:
            continue
        sizes = {cc: len(ids) for cc, ids in per_country.items()}
        pairs = sum(sizes.values())
        if pairs:
            out.append((p, sizes, pairs))
    return out


def equal_weight_shares(counts, papers, week, codes) -> tuple[dict[str, float | None], dict[str, int], int, int]:
    """(share %, named articles, papers reporting, pairs) for `codes` in one week. share is None when no paper
    reported that week. The shares of countries outside `codes` are not lost: they stay in every paper's denominator."""
    reporting = _reporting(counts, papers, week)
    n_papers = len(reporting)
    shares: dict[str, float | None] = {}
    named: dict[str, int] = {}
    for cc in codes:
        named[cc] = sum(sizes.get(cc, 0) for _, sizes, _ in reporting)
        shares[cc] = (100.0 * sum(sizes.get(cc, 0) / pairs for _, sizes, pairs in reporting) / n_papers) if n_papers else None
    return shares, named, n_papers, sum(pairs for _, _, pairs in reporting)


def pooled_shares(counts, papers, week, codes) -> dict[str, float | None]:
    """The alternative definition: all papers' pairs pooled. Only used to measure the difference."""
    reporting = _reporting(counts, papers, week)
    total = sum(pairs for _, _, pairs in reporting)
    return {cc: (100.0 * sum(sizes.get(cc, 0) for _, sizes, _ in reporting) / total) if total else None for cc in codes}


def tile_codes(counts, chunks, core_first: int, min_articles: int = TILE_MIN_NAMED_ARTICLES) -> list[str]:
    """Countries with at least `min_articles` named articles in the core papers over the core weeks, sorted by code."""
    totals: dict[str, int] = defaultdict(int)
    for (paper, week), per_country in counts.items():
        if paper in trends.CORE_V1 and week >= core_first:
            for cc, ids in per_country.items():
                totals[cc] += len(ids)
    return sorted(cc for cc, n in totals.items() if n >= min_articles)


def is_low_evidence(n_now: float, n_base: float, minimum: int = MIN_EVIDENCE_ARTICLES) -> bool:
    """A change is not coloured when the week OR its baseline has fewer than `minimum` named articles (product owner,
    3.11: when in doubt, do not count). 1 -> 14 articles is therefore striped too: the 1 cannot carry a share."""
    return n_now < minimum or n_base < minimum


def baseline_weeks(week: int, first_week: int, base: int) -> list[int]:
    """The `base` weeks before `week`. Strict: empty unless all of them lie inside the series, so a 4-week baseline
    never quietly becomes a 1-week one (core series: 7 steps with base 1, 4 steps with base 4)."""
    return list(range(week - base, week)) if week - base >= first_week else []


def signs_agree(delta: float, delta_pooled: float) -> bool:
    """True when the two definitions of the share move the same way. Zero agrees only with zero: a change that is
    nothing under one definition and something under the other has no clear direction."""
    return (delta > 0) == (delta_pooled > 0) and (delta < 0) == (delta_pooled < 0)


def change_vs_baseline(share: list, named: list, week: int, first_week: int, base: int, minimum: int = MIN_EVIDENCE_ARTICLES,
                       pooled: list | None = None):
    """(delta in percentage points, low_evidence, unclear_direction) for one tile, or None when there is no baseline
    week. `unclear_direction` is True when the pooled share (all pairs together) moves the opposite way to the
    per-newspaper share; a tile with it is shown like a low-evidence one (product owner, 3.11). The same arithmetic
    runs in the page's JavaScript; tests/test_trends_map.py keeps the two in step."""
    prior = baseline_weeks(week, first_week, base)
    if not prior or share[week] is None:
        return None
    base_share = sum(share[w] or 0.0 for w in prior) / len(prior)
    base_named = sum(named[w] for w in prior) / len(prior)
    delta = share[week] - base_share
    unclear = False
    if pooled is not None and pooled[week] is not None:
        base_pooled = sum(pooled[w] or 0.0 for w in prior) / len(prior)
        unclear = not signs_agree(delta, pooled[week] - base_pooled)
    return delta, is_low_evidence(named[week], base_named, minimum), unclear


# The map page's JavaScript paints a tile from t = min(1, sqrt(|change| / FULL_SCALE_PP)); the home-page miniature
# keeps the same t, rounded to MINI_STEPS steps (tests/test_trends_map_mini.py reads the page's constant, so the two
# cannot drift apart unnoticed).
FULL_SCALE_PP = 3.5
MINI_STEPS = 10
MINI_SERIES = "core"
MINI_BASE = 1


def mini_bucket(delta: float) -> int:
    """Signed colour step of a change, -MINI_STEPS..MINI_STEPS: the map's intensity t, rounded."""
    t = min(1.0, math.sqrt(abs(delta) / FULL_SCALE_PP))
    step = int(t * MINI_STEPS + 0.5)
    return step if delta >= 0 else -step


def build_trends_map_mini(data: dict) -> dict:
    """The small payload behind the home-page miniature (assets/data/trends_map_mini.json): per tile, only how it is
    drawn for the page's opening view (default week, core series, one-week baseline), using change_vs_baseline - the
    same function and the same rules as the page: "low" = striped (thin evidence or no clear direction), "none" = no
    baseline, an integer = colour step. No change figures, no names. {} when there is no data."""
    if not data or "series" not in data:
        return {}
    series = data["series"][MINI_SERIES]
    week = data["default_week"]
    first = series["first_week"]
    tiles = []
    for t in data["tiles"]:
        c = series["countries"][t["code"]]
        res = change_vs_baseline(c["share"], c["n_named"], week, first, MINI_BASE, data["counting"]["min_evidence_articles"], c.get("pooled_share"))
        if res is None:
            state = "none"
        else:
            delta, thin, unclear = res
            state = "low" if (thin or unclear) else mini_bucket(delta)
        tiles.append({"c": t["code"], "x": t["col"], "y": t["row"], "s": state})
    w = data["weeks"][week]
    return {"week_start": w["start"], "week_end": w["end"], "grid": data["grid"], "steps": MINI_STEPS, "tiles": tiles}


def _series_block(counts, papers, weeks, first_week, codes, with_papers) -> dict:
    n_weeks = len(weeks)
    share = {cc: [None] * n_weeks for cc in codes}
    pooled = {cc: [None] * n_weeks for cc in codes}
    named = {cc: [0] * n_weeks for cc in codes}
    other = [None] * n_weeks
    reporting_n = [0] * n_weeks
    pairs_n = [0] * n_weeks
    for w in range(first_week, n_weeks):
        s, n, k, pairs = equal_weight_shares(counts, papers, w, codes)
        reporting_n[w], pairs_n[w] = k, pairs
        p = pooled_shares(counts, papers, w, codes)
        for cc in codes:
            share[cc][w] = None if s[cc] is None else round(s[cc], 3)
            pooled[cc][w] = None if p[cc] is None else round(p[cc], 3)
            named[cc][w] = n[cc]
        other[w] = None if not k else round(max(0.0, 100.0 - sum(s[cc] for cc in codes)), 3)
    block = {
        "papers": list(papers),
        "first_week": first_week,
        "papers_reporting": reporting_n,
        "named_pairs": pairs_n,
        "other_share": other,
        "countries": {cc: {"share": share[cc], "pooled_share": pooled[cc], "n_named": named[cc]} for cc in codes},
    }
    if with_papers:
        per_paper = {}
        for p in papers:
            p_share = {cc: [None] * n_weeks for cc in codes}
            p_named = {cc: [0] * n_weeks for cc in codes}
            for w in range(first_week, n_weeks):
                per_country = counts.get((p, w))
                pairs = sum(len(ids) for ids in per_country.values()) if per_country else 0
                if not pairs:
                    continue
                for cc in codes:
                    n = len(per_country.get(cc, ()))
                    p_named[cc][w] = n
                    p_share[cc][w] = round(100.0 * n / pairs, 3)
            per_paper[p] = {"countries": {cc: {"share": p_share[cc], "n_named": p_named[cc]} for cc in codes}}
        block["per_paper"] = per_paper
    return block


def build_trends_map(conn, display_names: dict[str, str] | None = None) -> dict:
    """The whole trends_map.json payload. `display_names` maps the DB newspaper key to its printed name."""
    chunks = _week_grid(conn)
    if not chunks:
        return {}
    rows = trends.get_country_article_rows(conn, named_only=True)
    counts = paper_week_counts(rows, chunks)
    core_first = next((i for i, (a, _) in enumerate(chunks) if a.isoformat() >= CORE_FIRST_WEEK_START), len(chunks))
    candidates = tile_codes(counts, chunks, core_first)
    codes = sorted(MAP_TILES)
    # A country that reaches the threshold but has no cell in MAP_TILES gets no tile: say so instead of dropping it silently.
    unplaced = [cc for cc in candidates if cc not in MAP_TILES]
    below_threshold = [cc for cc in codes if cc not in candidates]

    backlog = trends._week_backlog_dates(chunks, trends.detect_backlog_dates(conn))
    report_dates = sorted({date.fromisoformat(r[1]) for r in trends.get_country_date_source_rows(conn)})
    weeks = []
    for i, (ws, we) in enumerate(chunks):
        flagged = backlog.get(i, [])
        weeks.append({
            "start": ws.isoformat(),
            "end": we.isoformat(),
            "days": (we - ws).days + 1,
            "partial": (we - ws).days + 1 < trends.WEEK_LENGTH_DAYS,
            "report_dates": sum(1 for d in report_dates if ws <= d <= we),
            "has_backlog": bool(flagged),
            "backlog_dates": flagged,
        })

    breaks = []
    for b in trends.scope_breaks_for_json():
        bd = date.fromisoformat(b["date"])
        b["week"] = next((i for i, (a, z) in enumerate(chunks) if a <= bd <= z), None)
        breaks.append(b)

    names = display_names or {}
    tiles = []
    for cc in codes:
        info = COUNTRY_LIST.get(cc, {})
        col, row = MAP_TILES[cc]
        short = TILE_SHORT_NAMES.get(cc, {})
        tiles.append({
            "code": cc, "col": col, "row": row,
            **{f"name_{lang}": tile_display_name(cc, lang, info.get(f"name_{lang}", cc)) for lang in ("he", "en", "de")},
            **{f"short_{lang}": tile_display_name(cc, lang, short.get(lang, info.get(f"name_{lang}", cc))) for lang in ("he", "en", "de")},
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counting": {
            "method": "named_only",
            "lower_bound": True,
            "share": "equal_weight_per_newspaper",
            "direction_check": "pooled_share_sign_must_agree",
            "min_evidence_articles": MIN_EVIDENCE_ARTICLES,
            "tile_min_named_articles": TILE_MIN_NAMED_ARTICLES,
        },
        "grid": {"cols": MAP_GRID_COLS, "rows": MAP_GRID_ROWS},
        "default_week": last_full_week(weeks),
        "unplaced": unplaced,
        "tile_list": {"reviewed_on": TILE_LIST_REVIEWED_ON, "min_named_articles": TILE_MIN_NAMED_ARTICLES, "below_threshold": below_threshold},
        "weeks": weeks,
        "scope_breaks": breaks,
        "newspapers": {p: names.get(p, p) for p in ALL_PAPERS_V1},
        "tiles": tiles,
        "series": {
            "core": _series_block(counts, trends.CORE_V1, weeks, core_first, codes, with_papers=True),
            "all": _series_block(counts, ALL_PAPERS_V1, weeks, 0, codes, with_papers=False),
        },
    }
