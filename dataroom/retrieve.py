"""Four ways to choose the data room passages the AI sees for one slide claim.

A. One model call: every passage in the data room (no search).
B. RAG: rank passages by meaning (embeddings) and by shared keywords, merge the
   two rankings, keep the top K.
C. PageIndex: show the AI each file's table of contents (section headings and
   pages, no body text). It picks sections; we pass the text of those sections.
D. RAG + PageIndex: RAG ranks files, keeps the top few; the AI then walks only
   those files' tables of contents, as in C. This is the two-stage design that
   scales: search narrows hundreds of files, the tree keeps sections whole.

All three return a list of unit dicts, so the verify step is identical and the
comparison isolates retrieval.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter

from dataroom import tracing
from dataroom.prompts import PAGEINDEX

TOP_K = 6
MAX_SECTIONS = 6
RRF_K = 60  # standard reciprocal rank fusion constant

STOP = set("the a an of and or to in on for is was are by with at from as its it this that be".split())


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9$%.]+", text.lower()) if t not in STOP]


# ---------------------------------------------------------------- A: one call

def method_a(claim: dict, units: list[dict], llm=None, prompts=None) -> list[dict]:
    return list(units)


# ---------------------------------------------------------------- B: RAG

def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _bm25(query: list[str], docs: list[list[str]], k1=1.5, b=0.75) -> list[float]:
    n = len(docs)
    avg = sum(len(d) for d in docs) / n
    df = Counter(t for d in docs for t in set(d))
    scores = []
    for d in docs:
        tf = Counter(d)
        s = 0.0
        for t in query:
            if t in tf:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avg))
        scores.append(s)
    return scores


def unit_text_for_search(u: dict) -> str:
    return f"{u['section_path']}. {u['text']}"


def _fused_ranking(claim: dict, units: list[dict], llm) -> Counter:
    """Embeddings ranking + keyword ranking, merged by reciprocal rank fusion."""
    query = f"{claim.get('metric', '')}: {claim['quote']}"
    with tracing.observe("embed-passages", as_type="embedding",
                         input={"passages": len(units), "query": query}) as obs:
        vectors = llm.embed([unit_text_for_search(u) for u in units])
        qvec = llm.embed([query])[0]
        obs.update(output={"vectors": len(vectors) + 1, "dimensions": len(qvec)}, **tracing.generation_attrs(llm))
    by_meaning = sorted(range(len(units)), key=lambda i: -_cosine(qvec, vectors[i]))
    kw = _bm25(tokens(query), [tokens(unit_text_for_search(u)) for u in units])
    by_keyword = sorted(range(len(units)), key=lambda i: -kw[i])
    fused = Counter()
    for ranking in (by_meaning, by_keyword):
        for rank, i in enumerate(ranking):
            fused[i] += 1 / (RRF_K + rank + 1)
    return fused


def method_b(claim: dict, units: list[dict], llm, prompts=None) -> list[dict]:
    fused = _fused_ranking(claim, units, llm)
    cfg = (prompts or {}).get("rag") or {"top_k": TOP_K, "max_per_file": None}
    picked, per_file = [], Counter()
    for i, _ in fused.most_common():
        f = units[i]["file"]
        if cfg["max_per_file"] and per_file[f] >= cfg["max_per_file"]:
            continue  # diversity: near-duplicate pages from one file can't fill the shortlist
        picked.append(units[i])
        per_file[f] += 1
        if len(picked) == cfg["top_k"]:
            break
    return picked


# ---------------------------------------------------------------- C: PageIndex

def build_tree(units: list[dict]) -> list[dict]:
    """File > section > pages. Section IDs are stable: file stem + order."""
    tree, seen = [], {}
    for u in units:
        f = next((x for x in tree if x["file"] == u["file"]), None)
        if f is None:
            f = {"file": u["file"], "title": u["section_path"].split(" > ")[0], "sections": []}
            tree.append(f)
        heading = u["section_path"].split(" > ")[-1]
        key = (u["file"], u["section_path"])
        if key not in seen:
            sid = f"{u['file'].split('_')[0]}.s{len(f['sections']) + 1}"
            seen[key] = {"id": sid, "heading": heading, "pages": [], "unit_ids": []}
            f["sections"].append(seen[key])
        s = seen[key]
        if u["page"] not in s["pages"]:
            s["pages"].append(u["page"])
        s["unit_ids"].append(u["unit_id"])
    return tree


def outline(tree: list[dict]) -> str:
    lines = []
    for f in tree:
        lines.append(f"{f['file']}: {f['title']}")
        for s in f["sections"]:
            pages = ",".join(str(p) for p in s["pages"])
            lines.append(f"  [{s['id']}] {s['heading']} (p.{pages})")
    return "\n".join(lines)


def method_c(claim: dict, units: list[dict], llm, prompts=None) -> list[dict]:
    tree = build_tree(units)
    template = (prompts or {}).get("pageindex", PAGEINDEX)
    prompt = template.format(quote=claim["quote"], metric=claim.get("metric", ""),
                             period=claim.get("period", ""), n=MAX_SECTIONS, outline=outline(tree))
    with tracing.observe("pick-sections", as_type="generation", input=[{"role": "user", "content": prompt}]) as gen:
        picked = llm.json(prompt)
        gen.update(output=picked, **tracing.generation_attrs(llm))
    ids = picked.get("section_ids", []) if isinstance(picked, dict) else []
    wanted = set()
    for f in tree:
        for s in f["sections"]:
            if s["id"] in ids[:MAX_SECTIONS]:
                wanted.update(s["unit_ids"])
    return [u for u in units if u["unit_id"] in wanted]


# ---------------------------------------------------------------- D: RAG + PageIndex

def method_d(claim: dict, units: list[dict], llm, prompts=None) -> list[dict]:
    """Stage 1: RAG scores each file by its best passage, keeps the top N files.
    Stage 2: PageIndex over those files only."""
    n_files = ((prompts or {}).get("hybrid") or {"files": 3})["files"]
    fused = _fused_ranking(claim, units, llm)
    best = Counter()
    for i, score in fused.items():
        f = units[i]["file"]
        best[f] = max(best[f], score)
    keep = {f for f, _ in best.most_common(n_files)}
    return method_c(claim, [u for u in units if u["file"] in keep], llm, prompts)


METHODS = {"A": method_a, "B": method_b, "C": method_c, "D": method_d}
METHOD_NAMES = {"A": "One model call", "B": "RAG", "C": "PageIndex", "D": "RAG + PageIndex"}


def describe(units: list[dict]) -> str:
    return json.dumps([u["unit_id"] for u in units])
