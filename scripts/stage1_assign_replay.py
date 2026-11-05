"""Experiment (read-only on production data): does the stage-1 assignment pass place stranded articles sensibly?

Works on a COPY of a tracker.db backup and writes only a JSON/Markdown result file - never a production table,
never api_usage (TRACKER_NO_USAGE_LOG is set before anything is imported).

  A) "prod":   the topics stage 1+2 actually produced for a day (stored report_sections) + the articles that
               actually became fallback sections -> assignment pass only (one small call per day).
  B) "replay": stage 1 run again from scratch on the day's articles (one call, no retry, no stage 2), then the
               assignment pass on whatever that fresh grouping left unassigned.

Costs are counted from the returned usage (Sonnet 5: $2 / $10 per million tokens) with a hard cap.

  python -m scripts.stage1_assign_replay --db <copy of tracker.db> --dates 2026-11-05 2026-10-24 2026-10-31 --out <dir>
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

os.environ["TRACKER_NO_USAGE_LOG"] = "1"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anthropic  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from src.reporting import synthesize as syn  # noqa: E402

PRICE_IN, PRICE_OUT = 2.0, 10.0  # USD per million tokens (Sonnet 5)


def cost(usage: dict) -> float:
    return (usage["input_tokens"] * PRICE_IN + usage["output_tokens"] * PRICE_OUT
            + usage.get("cache_creation_input_tokens", 0) * PRICE_IN * 1.25
            + usage.get("cache_read_input_tokens", 0) * PRICE_IN * 0.1) / 1e6


def load_articles(conn, date):
    return [dict(r) for r in conn.execute(
        """SELECT a.id, a.newspaper, a.headline, a.region_topic, a.stance_summary, a.key_excerpt, a.author
           FROM articles a JOIN downloaded_files df ON df.id = a.file_id
           WHERE COALESCE(df.report_date, date(df.published_at)) = ? ORDER BY a.newspaper, a.id""", (date,))]


def stored_topics(conn, date):
    topics, fallback = [], []
    for s in conn.execute("SELECT id, topic_label_en, category FROM report_sections WHERE report_date=? ORDER BY id", (date,)):
        ids = [r[0] for r in conn.execute("SELECT article_id FROM report_section_articles WHERE section_id=?", (s["id"],))]
        (fallback if s["category"] == "additional_coverage" else topics).append(
            {"topic_label_en": s["topic_label_en"], "article_ids": ids})
    fb_ids = [i for t in fallback for i in t["article_ids"]]
    return topics, fb_ids


def describe(mapping, unassigned, topics, by_id):
    rows = []
    for i in unassigned:
        a = by_id[i]
        n = mapping.get(i)
        rows.append({"article_id": i, "newspaper": a["newspaper"], "headline": a["headline"],
                     "region_topic": a["region_topic"],
                     "assigned_to": topics[n - 1]["topic_label_en"] if n else None,
                     "topic_size": len(topics[n - 1]["article_ids"]) if n else None})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--dates", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cap", type=float, default=0.90, help="stop before a call if spend so far exceeds this (USD)")
    ap.add_argument("--skip-replay", action="store_true")
    args = ap.parse_args()
    load_dotenv(Path(os.environ.get("TRACKER_ENV", "")) if os.environ.get("TRACKER_ENV") else None)
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    client = anthropic.Anthropic()
    spent, result = 0.0, {}

    for date in args.dates:
        arts = load_articles(conn, date)
        by_id = {a["id"]: a for a in arts}
        valid = set(by_id)
        day = {"articles": len(arts)}

        # A) production topics + actual fallbacks
        topics, fb_ids = stored_topics(conn, date)
        fb_ids = [i for i in fb_ids if i in valid]
        day["prod"] = {"topics": len(topics), "fallback_articles": len(fb_ids)}
        if fb_ids and spent < args.cap:
            mapping, usage = syn.assign_unassigned_to_topics(client, [by_id[i] for i in fb_ids], topics)
            spent += cost(usage)
            day["prod"].update(assigned=len(mapping), left=len(fb_ids) - len(mapping), usage=usage,
                               rows=describe(mapping, fb_ids, topics, by_id))
            print(f"[{date}] prod: {len(mapping)}/{len(fb_ids)} placed, output {usage['output_tokens']} tok, spent ${spent:.3f}")

        # B) fresh stage 1, then the pass
        if not args.skip_replay and spent < args.cap:
            new_topics, u1 = syn.group_articles_into_topics(client, arts)
            spent += cost(u1)
            missing, duplicated, ratio = syn.compute_stage1_problem_ratio(new_topics, valid)
            day["replay"] = {"topics": len(new_topics), "stage1_output_tokens": u1["output_tokens"],
                             "stop_reason": u1.get("stop_reason"), "unassigned": len(missing),
                             "multi_assigned": len(duplicated), "ratio": round(ratio, 4)}
            print(f"[{date}] replay stage 1: {len(new_topics)} topics, {len(missing)} unassigned, "
                  f"{len(duplicated)} multi, out {u1['output_tokens']} tok, spent ${spent:.3f}")
            if missing and spent < args.cap:
                un = sorted(missing)
                mapping, usage = syn.assign_unassigned_to_topics(client, [by_id[i] for i in un], new_topics)
                spent += cost(usage)
                day["replay"].update(assigned=len(mapping), left=len(un) - len(mapping), usage=usage,
                                     rows=describe(mapping, un, new_topics, by_id))
                print(f"[{date}] replay pass: {len(mapping)}/{len(un)} placed, spent ${spent:.3f}")
        result[date] = day

    result["_spent_usd"] = round(spent, 4)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "assign_replay_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"total spent ${spent:.4f}; results in {out}")


if __name__ == "__main__":
    main()
