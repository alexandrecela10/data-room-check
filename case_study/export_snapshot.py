"""Freeze the evidence the demo and the case study show, into case_study/data/snapshot.json.

    .venv/bin/python -m case_study.export_snapshot

Sources, so every number on the page traces back:
- Scores, statuses, passages shown: runs/{version}-{method}.json, scored by eval/score.py.
- Tokens per call: the model cache (data/cache), which stores the usage of the
  original live call. v1 calls predate usage capture, so their tokens are unobserved.
- Prices and latency: live (non-cached) generations in Langfuse.
- Trace trees: one claim's subtree per method, fetched from Langfuse.
"""

from __future__ import annotations

import json
import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

from dataroom.llm import load_env
from dataroom.retrieve import METHOD_NAMES
from eval.score import KEY, score

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
CACHE = ROOT / "data" / "cache"
OUT = ROOT / "case_study" / "data" / "snapshot.json"
VERSIONS = ["v1", "v2", "v3"]
METHODS = ["A", "B", "C", "D"]
TREE_CLAIM = "Revenue FY2025: $38.0M."  # the claim RAG wrongly confirmed on v1


def step_of(kind: str, prompt: str) -> str:
    if kind == "embed":
        return "embed-passages"
    if "List every claim" in prompt:
        return "extract-slide-claims"
    if "Run each check" in prompt:
        return "review-file"
    if "table of contents" in prompt:
        return "pick-sections"
    return "find-evidence"


def tokens_by_step(calls: list[dict], cache: Path = CACHE) -> dict:
    out = defaultdict(lambda: {"calls": 0, "live_calls": 0, "input": 0, "output": 0, "seconds": 0.0,
                               "usage_known": True})
    for c in calls:
        d = json.loads((cache / c["kind"] / c["cache_file"]).read_text())
        s = out[step_of(c["kind"], d["input"])]
        s["calls"] += 1
        if not c["cache_hit"]:
            s["live_calls"] += 1
            s["seconds"] = round(s["seconds"] + d.get("seconds", 0.0), 2)
        u = d.get("usage")
        if u:
            s["input"] += u.get("input", 0)
            s["output"] += u.get("output", 0)
        elif c["kind"] == "json":
            s["usage_known"] = False
    return dict(out)


# ------------------------------------------------------------- Langfuse

def _lf():
    load_env()
    return os.environ["LANGFUSE_BASE_URL"], (os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])


def fetch_observations(**params) -> list[dict]:
    base, auth = _lf()
    rows, cursor = [], None
    while True:
        p = {**params, "limit": 1000, **({"cursor": cursor} if cursor else {})}
        r = requests.get(f"{base}/api/public/v2/observations", auth=auth, params=p, timeout=60)
        r.raise_for_status()
        d = r.json()
        rows += d["data"]
        cursor = (d.get("meta") or {}).get("cursor")
        if not cursor or not d["data"]:
            return rows


def live_generation_stats() -> dict:
    """Prices per million tokens and median latency per (version, method, step), live calls only."""
    gens = fetch_observations(type="GENERATION", fields="core,basic,model,usage,metrics,metadata",
                              fromStartTime="2026-10-05T00:00:00Z")
    live = [g for g in gens if str((g.get("metadata") or {}).get("cache_hit")).lower() == "false"]
    price_in = [g["costDetails"]["input"] / g["usageDetails"]["input"] * 1e6 for g in live
                if g.get("costDetails", {}).get("input") and g.get("usageDetails", {}).get("input")]
    price_out = [g["costDetails"]["output"] / g["usageDetails"]["output"] * 1e6 for g in live
                 if g.get("costDetails", {}).get("output") and g.get("usageDetails", {}).get("output")]
    lat = defaultdict(list)
    for g in live:
        m = g.get("metadata") or {}
        if g.get("latency") is not None:
            lat[(m.get("prompt_version"), m.get("method"), g["name"])].append(g["latency"])
    return {
        "price_per_1m": {"input": round(statistics.median(price_in), 4) if price_in else None,
                         "output": round(statistics.median(price_out), 4) if price_out else None,
                         "source": f"Langfuse cost / usage on {len(live)} live generations"},
        "latency_s": {"|".join(str(x) for x in k): round(statistics.median(v), 2) for k, v in lat.items()},
    }


def claim_subtree(trace_id: str) -> list[dict]:
    """The observations under the check-slide-claim span for TREE_CLAIM."""
    obs = fetch_observations(traceId=trace_id, fields="core,basic,io,metadata,usage,metrics")
    roots = [o for o in obs if o["name"] == "check-slide-claim" and TREE_CLAIM in json.dumps(o.get("input"))]
    if not roots:
        return []
    keep, frontier = {roots[0]["id"]}, [roots[0]["id"]]
    while frontier:
        nxt = [o["id"] for o in obs if o.get("parentObservationId") in frontier]
        keep.update(nxt)
        frontier = nxt
    rows = []
    for o in sorted((o for o in obs if o["id"] in keep), key=lambda o: o["startTime"]):
        rows.append({"id": o["id"], "parent": o.get("parentObservationId"), "type": o["type"], "name": o["name"],
                     "latency_s": o.get("latency"), "usage": o.get("usageDetails") or {},
                     "output": _short(o.get("output"))})
    return rows


def _short(x, n=400):
    s = json.dumps(x) if not isinstance(x, str) else x
    return s if len(s) <= n else s[:n] + "..."


# ------------------------------------------------------------- main

def main():
    key = yaml.safe_load(KEY.read_text())
    stats = live_generation_stats()
    price = stats["price_per_1m"]
    snap = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "methods": METHOD_NAMES, "prices": price, "runs": {}, "red_flags": {}, "trees": {}}
    for v in VERSIONS:
        snap["runs"][v] = {}
        for m in METHODS:
            path = RUNS / f"{v}-{m}.json"
            if not path.exists():
                continue
            run = json.loads(path.read_text())
            rep = score(run, key)
            mr = rep["methods"][m]
            toks = tokens_by_step(run["calls"])
            check_steps = ["find-evidence", "pick-sections"]
            known = all(toks.get(s, {}).get("usage_known", True) for s in check_steps)
            cost = None
            if known and price["input"] and price["output"]:
                cost = sum(toks.get(s, {}).get("input", 0) * price["input"] + toks.get(s, {}).get("output", 0) * price["output"]
                           for s in check_steps) / 1e6
            claims = []
            for r in run["results"][m]:
                claims.append({k: r.get(k) for k in ("claim_id", "slide", "quote", "metric", "value", "unit", "status",
                                                      "label", "computed_value", "retrieved")}
                              | {"evidence": [{k: e.get(k) for k in ("file", "page", "section_path", "quote", "value",
                                                                     "role", "verified", "reason")} for e in r["evidence"]]})
            snap["runs"][v][m] = {
                "name": METHOD_NAMES[m], "verdict": mr["verdict"], "values": mr["values"],
                "precision": mr["precision"], "recall": mr["recall"], "lineage": mr["lineage"],
                "evidence_pages_found": mr["evidence_pages_found"], "statuses": mr["statuses"],
                "passages_shown": [len(r["retrieved"]) for r in run["results"][m]],
                "claim_check_tokens": {s: toks.get(s) for s in check_steps + ["embed-passages"] if s in toks},
                "claim_check_cost_usd": round(cost, 4) if cost is not None else None,
                "latency_s": {s: stats["latency_s"].get(f"{v}|{m}|{s}") for s in check_steps},
                "trace_id": run.get("trace_ids", {}).get(m),
                "claims": claims,
            }
            snap["red_flags"][v] = {"score": rep["red_flags"], "findings": [
                {k: f.get(k) for k in ("flag_id", "check_id", "file", "page", "quote", "observation", "verified", "reason")}
                for f in run["red_flags"]]}
        for m in METHODS:
            tid = snap["runs"][v].get(m, {}).get("trace_id")
            if v == "v3" and tid:
                snap["trees"][m] = claim_subtree(tid)
    # Benchmark: v3 re-run with an empty cache, every call live, so cost and time compare fairly.
    snap["benchmark"] = {}
    for m in METHODS:
        path = RUNS / f"v3-bench-{m}.json"
        if not path.exists():
            continue
        run = json.loads(path.read_text())
        rep = score(run, key)["methods"][m]
        toks = tokens_by_step(run["calls"], ROOT / run["cache_dir"])
        steps = {s: toks[s] for s in ("embed-passages", "pick-sections", "find-evidence") if s in toks}
        cost = sum(t["input"] * price["input"] + t["output"] * price["output"] for t in steps.values()) / 1e6
        snap["benchmark"][m] = {
            "name": METHOD_NAMES[m], "verdict": rep["verdict"], "values": rep["values"],
            "steps": steps,
            "tokens_in": sum(t["input"] for t in steps.values()),
            "tokens_out": sum(t["output"] for t in steps.values()),
            "cost_usd_10_claims": round(cost, 4),
            "seconds_10_claims": round(sum(t["seconds"] for t in steps.values()), 1),
            "passages_shown_avg": round(sum(len(r["retrieved"]) for r in run["results"][m]) / len(run["results"][m]), 1),
            "note": "Embeddings are computed once per data room and reused across claims and methods; "
                    "the embeddings API reports no token counts.",
        }
        shared = {s: toks[s] for s in ("extract-slide-claims", "review-file") if s in toks and toks[s]["live_calls"]}
        if shared:
            snap["benchmark_shared"] = shared
    snap["answer_key"] = key
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snap, indent=2, default=list))
    print(f"wrote {OUT.relative_to(ROOT)}  prices {price}")
    for v in VERSIONS:
        for m, r in snap["runs"][v].items():
            print(v, m, r["verdict"][:40], "shown", r["passages_shown"], "cost", r["claim_check_cost_usd"],
                  "lat", r["latency_s"])
    for m, b in snap.get("benchmark", {}).items():
        print("bench", m, b["verdict"], "tokens", b["tokens_in"], b["tokens_out"], "cost $", b["cost_usd_10_claims"],
              "seconds", b["seconds_10_claims"], "passages", b["passages_shown_avg"])
    print("shared", snap.get("benchmark_shared"))
    for m, t in snap["trees"].items():
        print("tree", m, len(t), "nodes:", [n["name"] for n in t])


if __name__ == "__main__":
    main()
