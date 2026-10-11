"""One-off, read-only cost estimate across the whole pipeline (2026-10-11).

Standalone analysis script - connects to tracker.db in read-only mode, counts
operational volume per stage, and estimates cumulative API spend to date.

IMPORTANT CAVEAT, confirmed by this script's own schema check (step 2 below):
tracker.db has NO token/usage/cost tracking columns anywhere - every number
below is an ESTIMATE built from empirically-measured per-unit token averages
already on record in PROJECT_LOG (sections 4.41/4.42, full real token counts
from actual API responses on two specific days), plus this session's own
measured Haiku 4.5 sample (100 pages, screen.py, 2026-10-10 model comparison).
It is not a replacement for real usage logging - see PROJECT_LOG action item
44 (no Admin API key/console access in this environment to verify against an
actual account balance).

Pricing note: the rates given in the request ($0.25/$1.25 for Haiku, $3/$15
for Sonnet) do NOT match the models this pipeline actually runs. The
production models are `claude-haiku-4-5-20251001` (screen.py) and
`claude-sonnet-5` (analyze.py, synthesize.py) - verified just now against the
live claude.com/pricing page:
  - Claude Haiku 4.5: $1.00 / $5.00 per MTok (cache read $0.10, write $1.25)
  - Claude Sonnet 5:  $2.00 / $10.00 per MTok (cache read $0.20, write $2.50)
This script uses the verified real rates, not the ones supplied, and prints
both so the discrepancy is visible rather than silently "corrected away".

Usage: python -m scripts.estimate_api_costs_20261011
"""
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "tracker.db"

# --- Verified pricing (claude.com/pricing, checked 2026-10-11) -------------
PRICING = {
    "haiku-4.5": {"input": 1.00, "output": 5.00, "cache_read": 0.10, "cache_write": 1.25},
    "sonnet-5":  {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
}

# --- Empirically-measured per-unit token averages ---------------------------
# Screen (Haiku 4.5), per PAGE screened - averaged across 3 real measurements:
#   PROJECT_LOG 4.41 (275 pages): input=1,491,708 output=13,753  -> 5424.4 / 50.0
#   PROJECT_LOG 4.42 (867 pages): input=2,682,773 output=41,984  -> 3094.3 / 48.4
#   this session's Haiku 4.5/5.5 comparison (100 pages, 2026-10-10):
#     input=426,685 output=8,029 -> 4266.9 / 80.3
SCREEN_INPUT_PER_PAGE = (5424.4 + 3094.3 + 4266.9) / 3
SCREEN_OUTPUT_PER_PAGE = (50.0 + 48.4 + 80.3) / 3

# Analyze (Sonnet 5), per PAGE with analysis_status='completed' - averaged
# across 2 real measurements (PROJECT_LOG explicitly flags that counting via
# the `articles` table alone undercounts pages analyzed-and-found-empty, so
# both denominators here are the corrected page_screening-based counts):
#   PROJECT_LOG 4.41 (124 pages): input=1,044,177 output=26,245 -> 8421.0 / 211.7
#   PROJECT_LOG 4.42 (469 pages): input=2,505,495 output=80,772 -> 5342.0 / 172.2
ANALYZE_INPUT_PER_PAGE = (8421.0 + 5342.0) / 2
ANALYZE_OUTPUT_PER_PAGE = (211.7 + 172.2) / 2

# Synthesize Stage 1 (topic grouping, 1 call per report date), scaled by
# volume rather than treated as flat, since the 2 real measurements scale
# almost exactly linearly with article/topic count:
#   4.41: 96 articles -> input=16,527 (172.2/article); 57 topics -> output=4,490 (78.8/topic)
#   4.42: 156 articles -> input=26,441 (169.5/article); 61 topics -> output=4,897 (80.3/topic)
SYNTH_STAGE1_INPUT_PER_ARTICLE = (172.2 + 169.5) / 2
SYNTH_STAGE1_OUTPUT_PER_SECTION = (78.8 + 80.3) / 2

# Synthesize Stage 2 (per-topic comparison, 1 call per report_section), plus
# one prompt-cache WRITE per report date (the shared system prompt is cached
# once, then read by every other call that day):
#   4.41 (56 calls): input=34,734 (620.3/call) output=39,324 (702.2/call)
#                    cache_write=1,334 (once/day) cache_read=73,370 (1310.2/call)
#   4.42 (58 calls): input=51,306 (884.6/call) output=49,909 (860.5/call)
#                    cache_write=1,334 (once/day) cache_read=76,038 (1311.0/call)
SYNTH_STAGE2_INPUT_PER_SECTION = (620.3 + 884.6) / 2
SYNTH_STAGE2_OUTPUT_PER_SECTION = (702.2 + 860.5) / 2
SYNTH_STAGE2_CACHE_READ_PER_SECTION = (1310.2 + 1311.0) / 2
SYNTH_STAGE2_CACHE_WRITE_PER_REPORT = 1334.0


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def check_schema_for_token_columns(conn: sqlite3.Connection) -> None:
    print("=" * 78)
    print("STEP 1-2: Schema check - looking for any token/usage/cost tracking columns")
    print("=" * 78)
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )]
    found_any = False
    for t in tables:
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({t})")]
        token_cols = [c for c in cols if any(k in c.lower() for k in ("token", "usage", "cost"))]
        if token_cols:
            found_any = True
            print(f"  {t}: FOUND token-related column(s): {token_cols}")
    if not found_any:
        print("  No token/usage/cost columns found in any table.")
        print("  -> Every figure below is an ESTIMATE from measured per-unit averages,")
        print("     not a read of actual recorded usage. See PROJECT_LOG action item 44.")
    print()


def get_counts(conn: sqlite3.Connection) -> dict:
    counts = {}
    counts["page_screening_total"] = conn.execute("SELECT COUNT(*) c FROM page_screening").fetchone()["c"]
    counts["page_screening_relevant"] = conn.execute(
        "SELECT COUNT(*) c FROM page_screening WHERE is_relevant=1"
    ).fetchone()["c"]
    counts["pages_analyzed"] = conn.execute(
        "SELECT COUNT(*) c FROM page_screening WHERE analysis_status='completed'"
    ).fetchone()["c"]
    counts["articles_total"] = conn.execute("SELECT COUNT(*) c FROM articles").fetchone()["c"]
    counts["reports_total"] = conn.execute("SELECT COUNT(*) c FROM reports").fetchone()["c"]
    counts["report_sections_total"] = conn.execute("SELECT COUNT(*) c FROM report_sections").fetchone()["c"]

    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "biweekly_periods" in tables:
        counts["biweekly_periods_total"] = conn.execute("SELECT COUNT(*) c FROM biweekly_periods").fetchone()["c"]
    else:
        counts["biweekly_periods_total"] = None
    if "biweekly_topics" in tables:
        counts["biweekly_topics_total"] = conn.execute("SELECT COUNT(*) c FROM biweekly_topics").fetchone()["c"]
    else:
        counts["biweekly_topics_total"] = None
    return counts


def cost(model: str, input_tok: float, output_tok: float, cache_read_tok: float = 0, cache_write_tok: float = 0) -> float:
    p = PRICING[model]
    return (
        input_tok / 1_000_000 * p["input"]
        + output_tok / 1_000_000 * p["output"]
        + cache_read_tok / 1_000_000 * p["cache_read"]
        + cache_write_tok / 1_000_000 * p["cache_write"]
    )


def main():
    print(f"Connecting read-only to {DB_PATH}")
    conn = connect_readonly(DB_PATH)

    check_schema_for_token_columns(conn)

    print("=" * 78)
    print("STEP 3: Operational volume counts")
    print("=" * 78)
    c = get_counts(conn)
    print(f"  page_screening (total pages evaluated):        {c['page_screening_total']:>8,}")
    print(f"    of which flagged is_relevant=1:              {c['page_screening_relevant']:>8,}")
    print(f"  pages analyzed (analysis_status='completed'):  {c['pages_analyzed']:>8,}")
    print(f"  articles identified (articles table):          {c['articles_total']:>8,}")
    print(f"  reports (report dates):                        {c['reports_total']:>8,}")
    print(f"  report_sections (daily, all dates):            {c['report_sections_total']:>8,}")
    if c["biweekly_periods_total"] is not None:
        print(f"  biweekly_periods:                              {c['biweekly_periods_total']:>8,}")
        print(f"  biweekly_topics:                               {c['biweekly_topics_total']:>8,}")
    conn.close()

    print()
    print("=" * 78)
    print("STEP 4: Pricing used (verified live against claude.com/pricing, 2026-10-11)")
    print("=" * 78)
    print("  NOTE: the rates given in the request (Haiku $0.25/$1.25, Sonnet $3/$15)")
    print("  do not match this pipeline's actual production models. Using the real,")
    print("  verified rates for the models this code actually calls instead:")
    for model, p in PRICING.items():
        print(f"    {model}: input ${p['input']:.2f}/MTok, output ${p['output']:.2f}/MTok, "
              f"cache read ${p['cache_read']:.2f}/MTok, cache write ${p['cache_write']:.2f}/MTok")

    print()
    print("=" * 78)
    print("STEP 5: Estimated tokens and cost by stage")
    print("(per-unit rates are empirical averages from PROJECT_LOG 4.41/4.42 and this")
    print(" session's own measurement - see the module docstring/comments for sources)")
    print("=" * 78)

    rows = []

    # Screen - Haiku 4.5, per page_screening row
    screen_input = c["page_screening_total"] * SCREEN_INPUT_PER_PAGE
    screen_output = c["page_screening_total"] * SCREEN_OUTPUT_PER_PAGE
    screen_cost = cost("haiku-4.5", screen_input, screen_output)
    rows.append(("Screen (Haiku 4.5)", c["page_screening_total"], "pages", screen_input, screen_output, 0, 0, screen_cost))

    # Analyze - Sonnet 5, per page analyzed
    analyze_input = c["pages_analyzed"] * ANALYZE_INPUT_PER_PAGE
    analyze_output = c["pages_analyzed"] * ANALYZE_OUTPUT_PER_PAGE
    analyze_cost = cost("sonnet-5", analyze_input, analyze_output)
    rows.append(("Analyze (Sonnet 5)", c["pages_analyzed"], "pages", analyze_input, analyze_output, 0, 0, analyze_cost))

    # Synthesize Stage 1 - Sonnet 5, scaled by articles (input) and sections (output)
    s1_input = c["articles_total"] * SYNTH_STAGE1_INPUT_PER_ARTICLE
    s1_output = c["report_sections_total"] * SYNTH_STAGE1_OUTPUT_PER_SECTION
    s1_cost = cost("sonnet-5", s1_input, s1_output)
    rows.append(("Synthesize Stage 1 (Sonnet 5)", c["reports_total"], "reports", s1_input, s1_output, 0, 0, s1_cost))

    # Synthesize Stage 2 - Sonnet 5, per section + one cache-write per report
    s2_input = c["report_sections_total"] * SYNTH_STAGE2_INPUT_PER_SECTION
    s2_output = c["report_sections_total"] * SYNTH_STAGE2_OUTPUT_PER_SECTION
    s2_cache_read = c["report_sections_total"] * SYNTH_STAGE2_CACHE_READ_PER_SECTION
    s2_cache_write = c["reports_total"] * SYNTH_STAGE2_CACHE_WRITE_PER_REPORT
    s2_cost = cost("sonnet-5", s2_input, s2_output, s2_cache_read, s2_cache_write)
    rows.append(("Synthesize Stage 2 (Sonnet 5)", c["report_sections_total"], "sections", s2_input, s2_output, s2_cache_read, s2_cache_write, s2_cost))

    biweekly_note = ""
    biweekly_cost = 0.0
    if c["biweekly_topics_total"]:
        # Same per-topic Sonnet-5-with-caching mechanism as daily Stage 2 - applied
        # as an ANALOGOUS proxy, not a separately-measured rate (none on record).
        bw_input = c["biweekly_topics_total"] * SYNTH_STAGE2_INPUT_PER_SECTION
        bw_output = c["biweekly_topics_total"] * SYNTH_STAGE2_OUTPUT_PER_SECTION
        bw_cache_read = c["biweekly_topics_total"] * SYNTH_STAGE2_CACHE_READ_PER_SECTION
        bw_cache_write = (c["biweekly_periods_total"] or 0) * SYNTH_STAGE2_CACHE_WRITE_PER_REPORT
        biweekly_cost = cost("sonnet-5", bw_input, bw_output, bw_cache_read, bw_cache_write)
        rows.append(("Biweekly synthesis (Sonnet 5, proxy rate)", c["biweekly_topics_total"], "topics", bw_input, bw_output, bw_cache_read, bw_cache_write, biweekly_cost))
        biweekly_note = "  (biweekly uses the daily Stage-2 rate as an analogous proxy - not separately measured)"

    print(f"\n  {'Stage':<38}{'Units':>10} {'unit':<9}{'Input tok':>14}{'Output tok':>12}{'Cache R':>10}{'Cache W':>9}{'Est. $':>10}")
    print("  " + "-" * 110)
    total_cost = 0.0
    for name, units, unit_label, inp, out, cr, cw, stage_cost in rows:
        print(f"  {name:<38}{units:>10,} {unit_label:<9}{inp:>14,.0f}{out:>12,.0f}{cr:>10,.0f}{cw:>9,.0f}{stage_cost:>10.2f}")
        total_cost += stage_cost
    if biweekly_note:
        print(biweekly_note)

    print("  " + "-" * 110)
    print(f"  {'TOTAL ESTIMATED COST (Screen+Analyze+Synthesize, all time)':<91}${total_cost:>8.2f}")
    print()
    print("  Render/Publish stages make no Anthropic API calls - $0 by design.")
    print()
    print("  This is an ESTIMATE built from a handful of real measured days, applied")
    print("  uniformly across the whole archive. Actual spend will differ - page/article")
    print("  length varies a lot by source and day, and these samples are a small part")
    print("  of the full history. Treat this as an order-of-magnitude figure, not a bill.")


if __name__ == "__main__":
    main()
