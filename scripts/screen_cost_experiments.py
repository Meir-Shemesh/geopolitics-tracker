"""Historical-archive experiments on cheaper screening (options 3 and 4 of the 2026-10-20 cost review,
PROJECT_LOG 4.107). Read-only on tracker.db, writes nothing to it, touches no live run: it samples
pages the pipeline already screened and analyzed, replays the SCREEN call with variants, and compares
each variant's verdict with what the analysis stage later produced from the same page.

    python -m scripts.screen_cost_experiments              # sample 120 + 120 + 60 pages, ~$4
    python -m scripts.screen_cost_experiments --per-group 20   # a cheap smoke run

Groups (ground truth = how the page ended up in the real pipeline):
  P+  relevant at screening and analysis produced >= 1 article   (must NOT be lost)
  P0  relevant at screening and analysis produced 0 articles      (the waste we want to avoid)
  N   rejected at screening                                       (must not start passing - extra cost)

Variants:
  strict      same Haiku, full page text, a stricter prompt ("a full article with an international angle")
  trunc4000   the production prompt, only the first 4,000 characters of the page
  trunc7000   the production prompt, only the first 7,000 characters of the page
"""
import argparse
import json
import math
import os
import random
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

os.environ["TRACKER_NO_USAGE_LOG"] = "1"  # experiments must not write to the pipeline's api_usage table
sys.stdout.reconfigure(encoding="utf-8")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import anthropic  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from src.analysis import screen  # noqa: E402
from src.common.db import DB_PATH  # noqa: E402

HAIKU_IN, HAIKU_OUT = 1.00, 5.00  # $/Mtok - list price, not verified against the account
START, END = "2026-10-05", "2026-10-19"
OUT_DIR = PROJECT_ROOT / "scripts" / "output" / "screen_cost_experiments_20261020"

STRICT_PROMPT = screen.SYSTEM_PROMPT.split("This is a deliberately WIDE")[0] + """This is a SELECTIVE screening step. A later, more careful (and expensive) stage analyzes every page you pass, so a page that yields nothing there is wasted money. Mark true only when the page contains at least one SUBSTANTIAL piece - a full article, column, editorial, analysis or report of several paragraphs - whose subject has a clear international, cross-border or foreign-policy dimension (wars and conflicts, diplomacy, sanctions, trade between states, migration across borders, international institutions, a government's stance toward another state, and the like).

Mark false when geopolitical content is limited to a headline or a one-line mention, a very short news brief, a photo caption or infographic, a table of figures or listings, or when the page's articles are domestic-only (local politics, crime, sport, culture, business of a single country) with no cross-border angle. If the page is a mix, judge by its most substantial article. Keep the bar for a real article with an international angle LOW - a genuine geopolitical article must still pass; only the thin or purely domestic page should be rejected.

Call record_screening with:
- is_relevant: true or false as above.
- reasoning: one short sentence (under 30 words) naming the article that decided it, or why none qualifies.
"""

VARIANTS = {
    # The production prompt on the full page text, replayed: shows how many of the pages that passed in
    # production would pass AGAIN - the model's own run-to-run noise, which every other variant's
    # "lost pages" has to be read against.
    "baseline": {"prompt": screen.SYSTEM_PROMPT, "chars": None, "groups": ("P+", "P0")},
    "strict": {"prompt": STRICT_PROMPT, "chars": None, "groups": ("P+", "P0")},
    "trunc4000": {"prompt": screen.SYSTEM_PROMPT, "chars": 4000, "groups": ("P+", "P0", "N")},
    "trunc7000": {"prompt": screen.SYSTEM_PROMPT, "chars": 7000, "groups": ("P+", "P0", "N")},
}


def sample_pages(conn: sqlite3.Connection, per_group: int, seed: int) -> list[dict]:
    base = f"""
        SELECT ps.file_id, ps.page_number, df.newspaper, ep.raw_text, ps.is_relevant,
               (SELECT COUNT(*) FROM articles a WHERE a.file_id = ps.file_id AND a.page_number = ps.page_number) AS n_articles
        FROM page_screening ps
        JOIN extracted_pages ep ON ep.file_id = ps.file_id AND ep.page_number = ps.page_number
        JOIN downloaded_files df ON df.id = ps.file_id
        WHERE ps.model_used LIKE 'claude-haiku%'
          AND COALESCE(df.report_date, date(df.published_at)) BETWEEN '{START}' AND '{END}'
          AND LENGTH(ep.raw_text) > 300 """
    rng = random.Random(seed)
    groups = {
        "P+": conn.execute(base + "AND ps.is_relevant = 1 AND ps.analysis_status = 'completed'").fetchall(),
        "N": conn.execute(base + "AND ps.is_relevant = 0").fetchall(),
    }
    groups["P0"] = [r for r in groups["P+"] if r["n_articles"] == 0]
    groups["P+"] = [r for r in groups["P+"] if r["n_articles"] > 0]
    out = []
    for name, size in (("P+", per_group), ("P0", per_group), ("N", max(1, per_group // 2))):
        for r in rng.sample(groups[name], min(size, len(groups[name]))):
            out.append({"group": name, "file_id": r["file_id"], "page": r["page_number"], "newspaper": r["newspaper"],
                        "chars": len(r["raw_text"]), "n_articles": r["n_articles"], "text": r["raw_text"]})
    return out


def run_variant(client, name: str, pages: list[dict]) -> dict:
    spec = VARIANTS[name]
    targets = [p for p in pages if p["group"] in spec["groups"]]

    def one(p):
        text = p["text"][: spec["chars"]] if spec["chars"] else p["text"]
        for attempt in range(3):
            try:
                r = client.with_options(timeout=60.0).messages.create(
                    model=screen.MODEL, max_tokens=300, system=spec["prompt"], tools=[screen.SCREEN_TOOL],
                    tool_choice={"type": "tool", "name": "record_screening"}, messages=[{"role": "user", "content": text}])
                tu = next(b for b in r.content if b.type == "tool_use")
                return (p["file_id"], p["page"]), bool(tu.input["is_relevant"]), tu.input["reasoning"], r.usage.input_tokens, r.usage.output_tokens
            except Exception as exc:  # noqa: BLE001
                if attempt == 2:
                    return (p["file_id"], p["page"]), None, f"ERROR {exc!r}", 0, 0

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(one, targets))
    return {
        "verdicts": {f"{k[0]}:{k[1]}": {"relevant": v, "why": why} for k, v, why, _, _ in results},
        "input_tokens": sum(r[3] for r in results), "output_tokens": sum(r[4] for r in results),
        "errors": sum(1 for r in results if r[1] is None),
    }


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def evaluate(pages: list[dict], res: dict) -> dict:
    v = res["verdicts"]
    by = {g: [p for p in pages if p["group"] == g and f"{p['file_id']}:{p['page']}" in v and v[f"{p['file_id']}:{p['page']}"]["relevant"] is not None] for g in ("P+", "P0", "N")}
    def passed(p): return v[f"{p['file_id']}:{p['page']}"]["relevant"]
    out = {}
    if by["P+"]:
        kept = [p for p in by["P+"] if passed(p)]
        lo, hi = wilson(len(kept), len(by["P+"]))
        arts_all = sum(p["n_articles"] for p in by["P+"])
        arts_kept = sum(p["n_articles"] for p in kept)
        out["P+"] = {"n": len(by["P+"]), "kept": len(kept), "recall": len(kept) / len(by["P+"]), "recall_ci95": [lo, hi],
                     "articles_total": arts_all, "articles_kept": arts_kept, "article_recall": arts_kept / arts_all if arts_all else None,
                     "lost_pages": [f"{p['file_id']}:{p['page']} ({p['newspaper']}, {p['n_articles']} art)" for p in by["P+"] if not passed(p)]}
    if by["P0"]:
        rej = [p for p in by["P0"] if not passed(p)]
        lo, hi = wilson(len(rej), len(by["P0"]))
        out["P0"] = {"n": len(by["P0"]), "rejected": len(rej), "rejected_share": len(rej) / len(by["P0"]), "rejected_ci95": [lo, hi]}
    if by["N"]:
        flipped = [p for p in by["N"] if passed(p)]
        out["N"] = {"n": len(by["N"]), "now_passing": len(flipped), "share": len(flipped) / len(by["N"])}
    out["cost_usd"] = (res["input_tokens"] * HAIKU_IN + res["output_tokens"] * HAIKU_OUT) / 1e6
    out["avg_input_tokens"] = res["input_tokens"] / max(1, sum(len(by[g]) for g in by))
    out["errors"] = res["errors"]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--per-group", type=int, default=120)
    parser.add_argument("--seed", type=int, default=20261020)
    parser.add_argument("--only", default=None, help="Run just this variant and merge it into the existing results.json.")
    args = parser.parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    client = anthropic.Anthropic()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    pages = sample_pages(conn, args.per_group, args.seed)
    conn.close()
    counts = {g: sum(1 for p in pages if p["group"] == g) for g in ("P+", "P0", "N")}
    print(f"sample ({START}..{END}): {counts}, avg chars {sum(p['chars'] for p in pages) / len(pages):.0f}", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {"generated_at": datetime.now().isoformat(timespec="seconds"), "window": [START, END], "sample": counts, "variants": {}}
    results_path = OUT_DIR / "results.json"
    if args.only and results_path.exists():
        report = json.loads(results_path.read_text(encoding="utf-8"))
    total_cost = 0.0
    for name in ([args.only] if args.only else VARIANTS):
        print(f"running {name} ...", flush=True)
        res = run_variant(client, name, pages)
        ev = evaluate(pages, res)
        report["variants"][name] = {"metrics": ev, "verdicts": res["verdicts"]}
        total_cost += ev["cost_usd"]
        print(json.dumps({k: v for k, v in ev.items() if k != "P+"} | {"P+": {k: v for k, v in ev.get("P+", {}).items() if k != "lost_pages"}}, ensure_ascii=False), flush=True)
    report["total_cost_usd"] = report.get("total_cost_usd", 0.0) + total_cost if args.only else total_cost
    (OUT_DIR / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"experiment cost ~${total_cost:.2f}; results in {OUT_DIR / 'results.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
