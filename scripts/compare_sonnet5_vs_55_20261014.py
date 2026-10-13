"""Follow-up to compare_analyze_models_20261014.py (2026-10-14): production
claude-sonnet-5 vs claude-sonnet-5-5 on the SAME 64 pages, same prompt/schema/
request shape/metrics. The page set and the claude-sonnet-5 results are loaded from
the earlier run's raw output (scripts/output/compare_analyze_models_20261014_raw.json),
so only claude-sonnet-5-5 is generated here (budget cap $2 - a second claude-sonnet-5
run would not fit). Page text is re-read from tracker.db by (file_id, page_number).

    python -m scripts.compare_sonnet5_vs_55_20261014
"""
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import anthropic
from dotenv import load_dotenv

import scripts.compare_analyze_models_20261014 as base
from src.analysis.analyze import ANALYZE_TOOL, SYSTEM_PROMPT, is_letters_page
from src.common.db import get_connection

sys.stdout.reconfigure(encoding="utf-8")
NEW_MODEL = "claude-sonnet-5-5"
COST_CAP = 2.00


def run_model(client, page, model):
    t0 = time.time()
    try:
        r = client.messages.create(
            model=model, max_tokens=8192, thinking={"type": "adaptive"}, output_config={"effort": "medium"},
            # claude-sonnet-5-5 rejects a forced tool_choice ("tool"/"any") with a 400 (observed 2026-10-14,
            # all 64 calls) - "auto" is the only change to the production request shape (same fix as
            # claude-opus-5-5, see CLAUDE.md synthesize.py notes). A reply without a tool_use block is
            # counted as an error below, never silently as "no articles".
            system=SYSTEM_PROMPT, tools=[ANALYZE_TOOL], tool_choice={"type": "auto"},
            messages=[{"role": "user", "content": base.user_message(page)}])
        tu = next((b for b in r.content if b.type == "tool_use"), None)
        if tu is None:
            return {"error": f"no tool_use block (stop_reason={r.stop_reason})", "articles": None, "seconds": time.time() - t0,
                    "usage": {"input": r.usage.input_tokens, "output": r.usage.output_tokens, "thoughts": 0}}
        return {"error": None, "articles": tu.input["articles"], "seconds": time.time() - t0,
                "usage": {"input": r.usage.input_tokens, "output": r.usage.output_tokens, "thoughts": 0}}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:300]}", "articles": None, "seconds": time.time() - t0}


def main():
    load_dotenv()
    raw = json.loads((base.OUT_DIR / "compare_analyze_models_20261014_raw.json").read_text(encoding="utf-8"))
    conn = get_connection()
    sample, results = [], {"sonnet5": {}, "sonnet55": {}}
    for k, v in raw.items():
        f, p = map(int, k.split(":"))
        text = conn.execute("SELECT raw_text FROM extracted_pages WHERE file_id=? AND page_number=?", (f, p)).fetchone()[0]
        page = {"file_id": f, "page_number": p, "newspaper": v["newspaper"], "stratum": v["stratum"], "raw_text": text,
                "letters": is_letters_page(text), "published": v["published"]}
        sample.append(page)
        results["sonnet5"][(f, p)] = v["sonnet"]
    conn.close()
    client = anthropic.Anthropic()
    with ThreadPoolExecutor(max_workers=4) as ex:
        for page, r in zip(sample, ex.map(lambda pg: run_model(client, pg, NEW_MODEL), sample)):
            results["sonnet55"][(page["file_id"], page["page_number"])] = r
    errs = [r["error"] for r in results["sonnet55"].values() if r["error"]]
    print(f"{NEW_MODEL}: done, {len(errs)} error(s) {errs[:3]}")

    report = {"scores": {}, "cost": {}}
    for name in results:
        agg, per = base.score(sample, results[name], name)
        report["scores"][name] = {"aggregate": agg, "per_stratum": per}
        tin = sum(r.get("usage", {}).get("input", 0) for r in results[name].values())
        tout = sum(r.get("usage", {}).get("output", 0) for r in results[name].values())
        secs = sorted(r["seconds"] for r in results[name].values())
        report["cost"][name] = {"input_tokens": tin, "output_tokens": tout,
                                "usd": round(tin / 1e6 * base.PRICE_IN + tout / 1e6 * base.PRICE_OUT, 3), "median_s": round(secs[len(secs) // 2], 2)}
        print(f"\n== {name} ==\n{json.dumps(agg, ensure_ascii=False)}\n{json.dumps(per, ensure_ascii=False)}\ncost: {report['cost'][name]}")

    key = lambda p: (p["file_id"], p["page_number"])
    rng = random.Random(base.SEED)
    judge = {}
    for name in results:
        tally = {"same": 0, "partial": 0, "different": 0}
        for p in sample:
            r = results[name][key(p)]
            if r["articles"] is None:
                continue
            truth = [t for t in p["published"] if not base._SELF_EXCLUSION_RE.match(t["stance_summary"].strip())]
            for a, t, _ in base.match(r["articles"], truth)[0]:
                x, y = (a["stance_summary"], t["stance_summary"]) if rng.random() < 0.5 else (t["stance_summary"], a["stance_summary"])
                tally[base.judge_stance(client, x, y, t["key_excerpt"])] += 1
        judge[name] = tally
        print("stance judge", name, "vs published:", tally)
    report["stance_judge_vs_published"] = judge

    m = ex_ = agree = 0
    only55 = only5 = 0
    for p in sample:
        a, s = results["sonnet55"][key(p)]["articles"], results["sonnet5"][key(p)]["articles"]
        if a is None or s is None:
            continue
        pairs, extra55, extra5 = base.match(a, s)
        m += len(pairs); only55 += len(extra55); only5 += len(extra5)
        agree += int((len(a) > 0) == (len(s) > 0))
    report["sonnet55_vs_sonnet5"] = {"matched": m, "only_in_55": only55, "only_in_5": only5, "page_include_agree": agree}
    print("5.5 vs 5:", report["sonnet55_vs_sonnet5"])
    total = sum(c["usd"] for c in report["cost"].values() if c is not report["cost"]["sonnet5"])
    print(f"new spend (5.5 run only): ${report['cost']['sonnet55']['usd']}  (cap ${COST_CAP})")
    (base.OUT_DIR / "compare_sonnet5_vs_55_20261014.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (base.OUT_DIR / "compare_sonnet5_vs_55_20261014_raw.json").write_text(json.dumps(
        {f"{p['file_id']}:{p['page_number']}": {"stratum": p["stratum"], "newspaper": p["newspaper"], "sonnet55": results["sonnet55"][key(p)]} for p in sample},
        ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
