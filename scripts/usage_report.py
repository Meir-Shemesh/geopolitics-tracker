"""Read-only report of the API spend recorded in tracker.db's api_usage table (PROJECT_LOG 4.107).

    python -m scripts.usage_report                 # last 14 days, per day and per stage
    python -m scripts.usage_report --since 2026-10-21
    python -m scripts.usage_report --stage analyze --since 2026-10-21 --by-ref   # heaviest pages/topics

Costs are computed here from the token counts, with the list prices below. They are an estimate of
the Anthropic invoice, not a copy of it - the console remains the source of truth for what was
billed. Cache writes are priced at 1.25x and cache reads at 0.1x the input price.
"""
import argparse
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.common.db import DB_PATH  # noqa: E402

# $ per million tokens (input, output). Sonnet 5 as used by the biweekly usage summary; Haiku 4.5 at its
# standard list price - not verified against the account. Unknown models are reported as "?" not guessed.
PRICES = {
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int, cache_write: int, cache_read: int) -> float | None:
    if model not in PRICES:
        return None
    p_in, p_out = PRICES[model]
    return (input_tokens * p_in + cache_write * p_in * 1.25 + cache_read * p_in * 0.10 + output_tokens * p_out) / 1e6


def fetch_rows(conn: sqlite3.Connection, since: str, stage: str | None):
    query = ("SELECT run_date, stage, model, ref, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens "
             "FROM api_usage WHERE run_date >= ?")
    params: list = [since]
    if stage:
        query += " AND stage = ?"
        params.append(stage)
    return conn.execute(query + " ORDER BY run_date, stage", params).fetchall()


def summarize(rows, key) -> dict:
    out: dict = {}
    for r in rows:
        agg = out.setdefault(key(r), {"calls": 0, "in": 0, "out": 0, "cw": 0, "cr": 0, "cost": 0.0, "unpriced": 0})
        agg["calls"] += 1
        agg["in"] += r[4]
        agg["out"] += r[5]
        agg["cw"] += r[6]
        agg["cr"] += r[7]
        c = cost_usd(r[2], r[4], r[5], r[6], r[7])
        if c is None:
            agg["unpriced"] += 1
        else:
            agg["cost"] += c
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", default=(date.today() - timedelta(days=13)).isoformat())
    parser.add_argument("--stage", default=None, help="Only this stage (screen, analyze, synthesize_stage1, ...).")
    parser.add_argument("--by-ref", action="store_true", help="With --stage: the 15 most expensive refs (page or topic).")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    try:
        rows = fetch_rows(conn, args.since, args.stage)
    except sqlite3.OperationalError:
        print("No api_usage table yet - it is created by the next pipeline run (init_db).")
        return 0
    finally:
        pass
    conn.close()
    if not rows:
        print(f"No usage recorded since {args.since}. Logging starts with the first run after PROJECT_LOG 4.107.")
        return 0

    header = f"{'':<28}{'calls':>7}{'input':>12}{'cache-w':>10}{'cache-r':>11}{'output':>10}{'est. $':>9}"
    def line(label, a):
        flag = "  (+%d unpriced model)" % a["unpriced"] if a["unpriced"] else ""
        return f"{label:<28}{a['calls']:>7}{a['in']:>12,}{a['cw']:>10,}{a['cr']:>11,}{a['out']:>10,}{a['cost']:>9.2f}{flag}"

    for title, key in (("PER DAY", lambda r: r[0]), ("PER STAGE", lambda r: r[1])):
        print(f"\n{title} (since {args.since})\n{header}")
        data = summarize(rows, key)
        for k in sorted(data):
            print(line(k, data[k]))
        print(line("TOTAL", summarize(rows, lambda r: "t")["t"]))

    print(f"\nPER DAY x STAGE\n{header}")
    for k, a in sorted(summarize(rows, lambda r: f"{r[0]} {r[1]}").items()):
        print(line(k, a))

    if args.by_ref:
        refs = summarize(rows, lambda r: r[3] or "(no ref)")
        print(f"\nMOST EXPENSIVE REFS\n{header}")
        for k, a in sorted(refs.items(), key=lambda kv: -kv[1]["cost"])[:15]:
            print(line(str(k)[:27], a))
    return 0


if __name__ == "__main__":
    sys.exit(main())
