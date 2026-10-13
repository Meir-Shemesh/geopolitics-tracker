"""One-off controlled experiment (2026-10-14): Sonnet (production analyze.py,
Stage 2 "deep analysis") vs. Gemini 4 Argon on real, already-published pages.

Same method as scripts/compare_screen_models_20261010.py's --vs gemini
experiment (reused principles, not a new pattern):
  * free dry run by default (--execute spends money): verifies the model id with
    models.list() AND one tiny live generateContent call (models.list() alone is
    documented as unreliable, see PROJECT_LOG 4.94), builds + reports the sample,
    counts tokens with the vendors' free count-tokens endpoints, estimates cost;
  * sample drawn from tracker.db (read-only, never written), ground truth = what
    was actually published (report_section_articles);
  * the production contract is reused byte-for-byte: SYSTEM_PROMPT and
    ANALYZE_TOOL["input_schema"] from src/analysis/analyze.py are the Gemini
    system_instruction / response_json_schema, and the user message has the same
    shape as analyze_page()'s.

Added for this stage (because extraction is multi-field, not a binary verdict):
  * a FRESH Sonnet run through the production analyze_page() on the same sample -
    the "published" rows were produced earlier (some before the 2026-10-04 scope
    change, and Sonnet is non-deterministic), so Sonnet-vs-published measures
    Sonnet's own run-to-run/prompt-version noise and is the yardstick for how much
    Argon-vs-published disagreement is actually meaningful;
  * a blind Haiku judge for stance_summary equivalence on matched pairs;
  * objective checks that need no ground truth: key_excerpt appears verbatim in the
    page text, author tokens appear in the page text, self-tagged "not applicable"
    articles, enum validity.

    python -m scripts.compare_analyze_models_20261014             # dry run
    python -m scripts.compare_analyze_models_20261014 --execute   # spends money
"""
import argparse
import difflib
import json
import os
import random
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from google import genai
from google.genai import types

from src.analysis.analyze import (
    ANALYZE_TOOL, MODEL as SONNET_MODEL, SYSTEM_PROMPT, _LETTERS_PAGE_NOTE, _SELF_EXCLUSION_RE,
    analyze_page, is_letters_page,
)
from src.common.db import get_connection

sys.stdout.reconfigure(encoding="utf-8")

ARGON_MODEL = "models/gemini-4-argon"
JUDGE_MODEL = "claude-haiku-4-5-20251001"
# Per-million-token prices are the ones stated in the request (Sonnet $2/$10,
# Argon $2/$10 through 2026-11-30, then $4/$20) - NOT independently verified here.
PRICE_IN, PRICE_OUT = 2.00, 10.00
SEED = 20261014
OUT_DIR = Path(__file__).resolve().parent / "output"
MAX_CHARS = 25_000  # keeps one outlier page from dominating the cost
NEW_SCOPE_FROM = "2026-10-05"  # zero-article pages before this were judged under the opinion-only prompt


# ---------------------------------------------------------------- sample ----

def _pages(conn):
    """Every relevant+completed page with its text, newspaper and article/published counts."""
    cur = conn.execute(
        """
        SELECT ps.file_id, ps.page_number, df.newspaper, df.report_date, ps.screened_at, ep.raw_text,
          (SELECT COUNT(*) FROM articles a WHERE a.file_id = ps.file_id AND a.page_number = ps.page_number),
          (SELECT COUNT(*) FROM articles a JOIN report_section_articles r ON r.article_id = a.id
            WHERE a.file_id = ps.file_id AND a.page_number = ps.page_number)
        FROM page_screening ps
        JOIN downloaded_files df ON df.id = ps.file_id
        JOIN extracted_pages ep ON ep.file_id = ps.file_id AND ep.page_number = ps.page_number
        WHERE ps.is_relevant = 1 AND ps.analysis_status = 'completed'
          AND length(ep.raw_text) BETWEEN 400 AND ?
        """,
        (MAX_CHARS,),
    )
    return [dict(zip(("file_id", "page_number", "newspaper", "report_date", "screened_at", "raw_text", "n_art", "n_pub"), r))
            for r in cur.fetchall()]


def _articles_of(conn, file_id, page_number):
    rows = conn.execute(
        "SELECT id, headline, author, region_topic, stance_summary, key_excerpt FROM articles "
        "WHERE file_id = ? AND page_number = ? ORDER BY id", (file_id, page_number)).fetchall()
    out = []
    for r in rows:
        a = dict(zip(("id", "headline", "author", "region_topic", "stance_summary", "key_excerpt"), r))
        a["country_codes"] = [x[0] for x in conn.execute("SELECT country_code FROM article_countries WHERE article_id = ?", (a["id"],))]
        a["conflict_zones"] = [x[0] for x in conn.execute("SELECT conflict_zone FROM article_conflict_zones WHERE article_id = ?", (a["id"],))]
        out.append(a)
    return out


def _tokens(s):
    return {t for t in re.findall(r"\w+", s.lower()) if len(t) > 2}


def build_sample(conn):
    rng = random.Random(SEED)
    pages = _pages(conn)
    for p in pages:
        p["letters"] = is_letters_page(p["raw_text"])
    taken = set()
    sample = []

    def take(stratum, cands, n):
        cands = [c for c in cands if (c["file_id"], c["page_number"]) not in taken]
        rng.shuffle(cands)
        # spread across newspapers: round-robin by paper so one source (the Economist is 30% of the archive) can't fill a stratum
        by_paper = {}
        for c in cands:
            by_paper.setdefault(c["newspaper"], []).append(c)
        picked = []
        while len(picked) < n and any(by_paper.values()):
            for paper in sorted(by_paper):
                if by_paper[paper] and len(picked) < n:
                    picked.append(by_paper[paper].pop())
        for c in picked:
            c["stratum"] = stratum
            taken.add((c["file_id"], c["page_number"]))
            sample.append(c)

    pub = [p for p in pages if p["n_art"] > 0 and p["n_art"] == p["n_pub"]]
    take("A_multi_article_published", [p for p in pub if p["n_art"] >= 3], 14)
    take("B_single_article_published", [p for p in pub if p["n_art"] == 1], 10)
    take("C1_letters_with_published_item", [p for p in pages if p["letters"] and p["n_pub"] >= 1], 6)
    take("C2_letters_nothing_published", [p for p in pages if p["letters"] and p["n_art"] == 0], 6)
    take("D_domestic_excluded_post_scope_change",
         [p for p in pages if p["n_art"] == 0 and not p["letters"] and p["screened_at"] >= NEW_SCOPE_FROM and len(p["raw_text"]) > 1500], 14)

    # E: pages where production Sonnet emitted a self-tagged "not applicable" article (pre-filter era)
    self_pages = {(r[0], r[1]) for r in conn.execute(
        "SELECT file_id, page_number FROM articles WHERE lower(stance_summary) LIKE 'not applicable%' OR lower(stance_summary) LIKE 'n/a%' "
        "OR lower(stance_summary) LIKE 'not geopolitical%' OR lower(stance_summary) LIKE 'non-geopolitical%' OR lower(stance_summary) LIKE 'not a geopolitical%'")}
    take("E_self_tagged_not_applicable", [p for p in pages if (p["file_id"], p["page_number"]) in self_pages], 8)

    # F: a stored author that does not occur in the page text at all (the leak/garble failure mode)
    leak = []
    for p in pages:
        for a in _articles_of(conn, p["file_id"], p["page_number"]):
            au = a["author"].strip()
            if au and not (_tokens(au) & _tokens(p["raw_text"])) and (p["file_id"], p["page_number"]) not in taken:
                leak.append(p)
                break
    take("F_author_not_in_page_text", leak, 5)

    # G: the two documented scope-gate cases (PROJECT_LOG 4.75): France student protests, WaPo deportation investigation
    gate = []
    for r in conn.execute("SELECT DISTINCT file_id, page_number FROM articles WHERE "
                          "(lower(headline||' '||region_topic) LIKE '%french student%' OR lower(headline||' '||region_topic) LIKE '%france%protest%' "
                          "OR lower(headline||' '||region_topic) LIKE '%deportation%')"):
        for p in pages:
            if (p["file_id"], p["page_number"]) == (r[0], r[1]) and p["n_art"] == p["n_pub"] and p["newspaper"] in ("Washington Post", "Guardian", "Daily Telegraph", "Economist", "Süddeutsche Zeitung", "Die Welt"):
                gate.append(p)
    take("G_scope_gate_documented_cases", gate, 5)

    for p in sample:
        p["published"] = _articles_of(conn, p["file_id"], p["page_number"])
    return sample


# ------------------------------------------------------------------ calls ----

def user_message(page):
    letters_note = _LETTERS_PAGE_NOTE if page["letters"] else ""
    return f"Newspaper: {page['newspaper']}\n{letters_note}Page text:\n\n{page['raw_text']}"


def verify_argon():
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    listed = ARGON_MODEL in {m.name for m in client.models.list()}
    r = client.models.generate_content(
        model=ARGON_MODEL, contents='Reply with the JSON {"ok": true}',
        config=types.GenerateContentConfig(max_output_tokens=200, response_mime_type="application/json"))
    return client, listed, r.text


def argon_config(think: bool):
    kwargs = dict(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_json_schema=ANALYZE_TOOL["input_schema"],
        max_output_tokens=8192,
    )
    if not think:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    return types.GenerateContentConfig(**kwargs)


def run_argon(client, page, think):
    t0 = time.time()
    try:
        r = client.models.generate_content(model=ARGON_MODEL, contents=user_message(page), config=argon_config(think))
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:300]}", "articles": None, "seconds": time.time() - t0}
    u = r.usage_metadata
    usage = {"input": (u.prompt_token_count or 0) if u else 0,
             "output": (u.candidates_token_count or 0) if u else 0,
             "thoughts": (getattr(u, "thoughts_token_count", 0) or 0) if u else 0}
    if not r.text:
        return {"error": f"no text (finish_reason={r.candidates[0].finish_reason if r.candidates else None})", "articles": None, "usage": usage, "seconds": time.time() - t0}
    try:
        arts = json.loads(r.text)["articles"]
    except Exception as e:
        return {"error": f"bad json ({e}): {r.text[:200]!r}", "articles": None, "usage": usage, "seconds": time.time() - t0}
    return {"error": None, "articles": arts, "usage": usage, "seconds": time.time() - t0}


def run_sonnet(client, page):
    """Production analyze_page(), plus a second identical call is NOT made - one fresh sample per page."""
    t0 = time.time()
    try:
        # analyze_page() returns only the articles; replicate its request to also capture usage.
        response = client.messages.create(
            model=SONNET_MODEL, max_tokens=8192, thinking={"type": "adaptive"}, output_config={"effort": "medium"},
            system=SYSTEM_PROMPT, tools=[ANALYZE_TOOL], tool_choice={"type": "tool", "name": "record_articles"},
            messages=[{"role": "user", "content": user_message(page)}])
        tool_use = next(b for b in response.content if b.type == "tool_use")
        return {"error": None, "articles": tool_use.input["articles"],
                "usage": {"input": response.usage.input_tokens, "output": response.usage.output_tokens, "thoughts": 0},
                "seconds": time.time() - t0}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:300]}", "articles": None, "seconds": time.time() - t0}


JUDGE_TOOL = {
    "name": "judge", "description": "Compare two summaries of the same newspaper piece.",
    "input_schema": {"type": "object", "properties": {"verdict": {"type": "string", "enum": ["same", "partial", "different"]}},
                     "required": ["verdict"], "additionalProperties": False},
}


def judge_stance(client, a, b, excerpt):
    r = client.messages.create(
        model=JUDGE_MODEL, max_tokens=100, tools=[JUDGE_TOOL], tool_choice={"type": "tool", "name": "judge"},
        system="Two analysts summarized the same newspaper piece. Say whether summary A and B state the same central claim/facts: "
               "'same' (same core claim), 'partial' (overlapping but one misses/changes a key point), 'different' (different or contradictory claim). Ignore wording and length.",
        messages=[{"role": "user", "content": f"Verbatim excerpt for context: {excerpt}\n\nSummary A: {a}\n\nSummary B: {b}"}])
    return next(b_ for b_ in r.content if b_.type == "tool_use").input["verdict"]


# --------------------------------------------------------------- scoring ----

def _norm(s):
    return " ".join(re.findall(r"\w+", s.lower()))


def pair_score(x, y):
    h = difflib.SequenceMatcher(None, _norm(x["headline"]), _norm(y["headline"])).ratio()
    tx, ty = _tokens(x["key_excerpt"]), _tokens(y["key_excerpt"])
    e = len(tx & ty) / max(1, len(tx | ty))
    return max(h, e)


def match(predicted, truth, threshold=0.6):
    """Greedy one-to-one matching by headline/excerpt similarity. Returns (pairs, unmatched_pred, unmatched_truth)."""
    scored = sorted(((pair_score(p, t), i, j) for i, p in enumerate(predicted) for j, t in enumerate(truth)), reverse=True)
    used_p, used_t, pairs = set(), set(), []
    for s, i, j in scored:
        if s < threshold:
            break
        if i in used_p or j in used_t:
            continue
        used_p.add(i); used_t.add(j); pairs.append((predicted[i], truth[j], s))
    return pairs, [p for i, p in enumerate(predicted) if i not in used_p], [t for j, t in enumerate(truth) if j not in used_t]


def objective_checks(articles, raw_text):
    norm_text = _norm(raw_text)
    text_tokens = _tokens(raw_text)
    n = len(articles)
    excerpt_ok = sum(1 for a in articles if a["key_excerpt"].strip() and _norm(a["key_excerpt"]) in norm_text)
    # an excerpt with minor whitespace/hyphenation differences is still "found" if 90% of its tokens are in the page
    excerpt_loose = sum(1 for a in articles if a["key_excerpt"].strip() and len(_tokens(a["key_excerpt"]) & text_tokens) >= 0.9 * max(1, len(_tokens(a["key_excerpt"]))))
    author_nonempty = [a for a in articles if a["author"].strip()]
    author_missing = sum(1 for a in author_nonempty if not (_tokens(a["author"]) & text_tokens))
    self_tagged = sum(1 for a in articles if _SELF_EXCLUSION_RE.match(a["stance_summary"].strip())
                      or re.search(r"not (a )?geopolitical|no international dimension|purely domestic", a["stance_summary"][:160], re.I))
    return {"n": n, "excerpt_verbatim": excerpt_ok, "excerpt_loose": excerpt_loose, "authors": len(author_nonempty),
            "author_not_in_text": author_missing, "self_tagged": self_tagged}


# ------------------------------------------------------------------- main ----

def composition(sample):
    from collections import Counter
    print(f"\nSample: {len(sample)} pages")
    for s, n in sorted(Counter(p["stratum"] for p in sample).items()):
        print(f"  {s:42s} {n}")
    print("  by newspaper:", dict(Counter(p["newspaper"] for p in sample)))
    print(f"  published articles in sample (ground truth): {sum(len(p['published']) for p in sample)}; "
          f"chars: median {sorted(len(p['raw_text']) for p in sample)[len(sample)//2]}, max {max(len(p['raw_text']) for p in sample)}")


def dry_run(sample, ac):
    gem, listed, probe = verify_argon()
    print(f"\nModel check: {ARGON_MODEL} in models.list(): {listed}; live generateContent probe returned: {probe!r}")
    in_tok_g = sum(gem.models.count_tokens(model=ARGON_MODEL, contents=user_message(p)).total_tokens for p in sample)
    sys_g = gem.models.count_tokens(model=ARGON_MODEL, contents=SYSTEM_PROMPT).total_tokens
    in_tok_a = 0
    for p in sample:
        in_tok_a += ac.messages.count_tokens(model=SONNET_MODEL, system=SYSTEM_PROMPT, tools=[ANALYZE_TOOL],
                                             messages=[{"role": "user", "content": user_message(p)}]).input_tokens
    est_out = sum(max(1, len(p["published"])) * 260 for p in sample)
    print(f"Argon input tokens (exact, count_tokens): pages-only {in_tok_g:,} + system {sys_g:,} x {len(sample)} = {in_tok_g + sys_g * len(sample):,}")
    print(f"Sonnet input tokens (exact, count_tokens incl. system+tool): {in_tok_a:,}")
    print(f"Output tokens (ESTIMATE ~260/article, thinking excluded): {est_out:,}")
    for label, tin, tout in (("Argon, 1 variant (no thinking tokens)", in_tok_g + sys_g * len(sample), est_out),
                             ("Sonnet fresh run (thinking adds unknown output)", in_tok_a, est_out)):
        print(f"  {label}: ~${tin/1e6*PRICE_IN + tout/1e6*PRICE_OUT:.2f}  (input ${tin/1e6*PRICE_IN:.2f}, output ${tout/1e6*PRICE_OUT:.2f})")
    print("  + Haiku judge on matched pairs (small) ; Argon is run in up to 2 variants (default thinking / thinking_budget=0)")
    print("\nDry run complete - nothing generated beyond the one-token probe. Re-run with --execute.")


def score(sample, results, label):
    """Aggregate metrics for one model's results against the published ground truth."""
    from collections import defaultdict
    agg = defaultdict(int)
    per_stratum = defaultdict(lambda: defaultdict(int))
    cc_j, cz_eq = [], []
    for p in sample:
        r = results[(p["file_id"], p["page_number"])]
        st = p["stratum"]
        if r["articles"] is None:
            agg["errors"] += 1
            continue
        arts = r["articles"]
        truth = [t for t in p["published"] if not _SELF_EXCLUSION_RE.match(t["stance_summary"].strip())]
        pairs, extra, missing = match(arts, truth)
        agg["pages"] += 1
        agg["pred_articles"] += len(arts); agg["truth_articles"] += len(truth)
        agg["matched"] += len(pairs); agg["extra"] += len(extra); agg["missing"] += len(missing)
        agg["page_include_agree"] += int((len(arts) > 0) == (len(truth) > 0))
        per_stratum[st]["pages"] += 1
        per_stratum[st]["pages_with_articles"] += int(len(arts) > 0)
        per_stratum[st]["pred"] += len(arts); per_stratum[st]["truth"] += len(truth); per_stratum[st]["matched"] += len(pairs)
        for a, t, _ in pairs:
            agg["author_equal"] += int(_norm(a["author"]) == _norm(t["author"]))
            agg["both_author_empty"] += int(not a["author"].strip() and not t["author"].strip())
            cc_j.append(len(set(a["country_codes"]) & set(t["country_codes"])) / max(1, len(set(a["country_codes"]) | set(t["country_codes"]))))
            cz_eq.append(int(set(a["conflict_zones"]) == set(t["conflict_zones"])))
        oc = objective_checks(arts, p["raw_text"])
        for k, v in oc.items():
            agg["obj_" + k] += v
    agg["country_jaccard_mean"] = round(sum(cc_j) / len(cc_j), 3) if cc_j else None
    agg["conflict_zone_equal_rate"] = round(sum(cz_eq) / len(cz_eq), 3) if cz_eq else None
    return dict(agg), {k: dict(v) for k, v in per_stratum.items()}


def execute(sample, ac):
    gem, listed, probe = verify_argon()
    print(f"Argon verified live: {probe!r} (in models.list(): {listed})")
    # thinking probe on 3 real pages: does default-thinking Argon actually spend thinking tokens?
    probe_pages = sample[:3]
    for think in (True, False):
        outs = [run_argon(gem, p, think) for p in probe_pages]
        print(f"  probe think={think}: errors={[o['error'] for o in outs]}, thoughts tokens={[o.get('usage', {}).get('thoughts') for o in outs]}, "
              f"out tokens={[o.get('usage', {}).get('output') for o in outs]}")
    results = {"sonnet": {}, "argon_think": {}, "argon_nothink": {}}
    key = lambda p: (p["file_id"], p["page_number"])

    def go(name, fn):
        with ThreadPoolExecutor(max_workers=4) as ex:
            for p, r in zip(sample, ex.map(fn, sample)):
                results[name][key(p)] = r
        errs = sum(1 for r in results[name].values() if r["error"])
        print(f"{name}: done, {errs} error(s)")

    go("sonnet", lambda p: run_sonnet(ac, p))
    go("argon_think", lambda p: run_argon(gem, p, True))
    go("argon_nothink", lambda p: run_argon(gem, p, False))

    report = {"sample": [{k: v for k, v in p.items() if k != "raw_text"} | {"chars": len(p["raw_text"])} for p in sample], "scores": {}, "cost": {}}
    for name in results:
        agg, per = score(sample, results[name], name)
        report["scores"][name] = {"aggregate": agg, "per_stratum": per}
        tin = sum(r.get("usage", {}).get("input", 0) for r in results[name].values())
        tout = sum(r.get("usage", {}).get("output", 0) + r.get("usage", {}).get("thoughts", 0) for r in results[name].values())
        secs = sum(r["seconds"] for r in results[name].values())
        report["cost"][name] = {"input_tokens": tin, "output_tokens_incl_thoughts": tout, "usd": round(tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT, 3), "seconds_total": round(secs, 1)}
        print(f"\n== {name} ==\n{json.dumps(agg, ensure_ascii=False)}\ncost: {report['cost'][name]}")

    # published-vs-model stance judging on matched pairs (blind: A/B order randomized per pair)
    rng = random.Random(SEED)
    judge = {}
    for name in results:
        tally = {"same": 0, "partial": 0, "different": 0}
        for p in sample:
            r = results[name][key(p)]
            if r["articles"] is None:
                continue
            truth = [t for t in p["published"] if not _SELF_EXCLUSION_RE.match(t["stance_summary"].strip())]
            for a, t, _ in match(r["articles"], truth)[0]:
                x, y = (a["stance_summary"], t["stance_summary"]) if rng.random() < 0.5 else (t["stance_summary"], a["stance_summary"])
                tally[judge_stance(ac, x, y, t["key_excerpt"])] += 1
        judge[name] = tally
        print(f"stance judge {name} vs published: {tally}")
    report["stance_judge_vs_published"] = judge

    # cross-model agreement: Argon vs the FRESH Sonnet run
    cross = {}
    for name in ("argon_think", "argon_nothink"):
        m = ex_ = 0
        pages_agree = 0
        for p in sample:
            a, s = results[name][key(p)]["articles"], results["sonnet"][key(p)]["articles"]
            if a is None or s is None:
                continue
            pairs, extra, missing = match(a, s)
            m += len(pairs); ex_ += len(extra) + len(missing)
            pages_agree += int((len(a) > 0) == (len(s) > 0))
        cross[name] = {"matched": m, "unmatched_either_side": ex_, "page_include_agree": pages_agree}
    report["argon_vs_fresh_sonnet"] = cross
    print("Argon vs fresh Sonnet:", cross)

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "compare_analyze_models_20261014.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    # raw per-page outputs, for manual review of disagreements (kept out of the summary JSON on purpose)
    raw = {f"{p['file_id']}:{p['page_number']}": {"newspaper": p["newspaper"], "stratum": p["stratum"],
           "published": p["published"], **{n: results[n][key(p)] for n in results}} for p in sample}
    (OUT_DIR / "compare_analyze_models_20261014_raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nWrote {OUT_DIR / 'compare_analyze_models_20261014.json'} and ..._raw.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="actually run the models (spends money)")
    args = parser.parse_args()
    load_dotenv()
    conn = get_connection()
    sample = build_sample(conn)
    conn.close()
    composition(sample)
    ac = anthropic.Anthropic()
    if args.execute:
        execute(sample, ac)
    else:
        dry_run(sample, ac)


if __name__ == "__main__":
    main()
