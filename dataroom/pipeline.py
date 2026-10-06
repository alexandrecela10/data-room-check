"""The checking pipeline: the model reads and drafts, code checks and decides.

1. Extract slide claims (AI), check each quote is on its slide (code).
2. For each claim, pick passages with method A, B or C, ask the AI for evidence,
   then verify every evidence item and decide the status (code).
3. Hunt red flags file by file over every page (AI), verify each quote (code).
4. Scan AI-written text for recommendation words (code).

Prompts live in dataroom/prompts.py, one entry per version.
Tracing (dataroom/tracing.py) wraps each step; it is a no-op without Langfuse keys.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import yaml

from dataroom import retrieve, tracing, verify
from dataroom.ingest import ROOM, ingest_room
from dataroom.prompts import CURRENT, RULES, VERSIONS

ROOT = Path(__file__).resolve().parent.parent
DECK_PREFIX = "01_"
RED_FLAGS = ROOT / "config" / "red_flags.yaml"


def _passages(units: list[dict]) -> str:
    return "\n".join(f"[{u['unit_id']}] ({u['file']} p.{u['page']}, {u['section_path']}) {u['text']}"
                     for u in units)


class Room:
    """Units plus lookups the checks need."""

    def __init__(self, units: list[dict]):
        self.units = units
        self.by_id = {u["unit_id"]: u for u in units}
        self._pages: dict[tuple, str] = {}
        for u in units:
            k = (u["file"], u["page"])
            self._pages[k] = (self._pages.get(k, "") + " " + u["text"]).strip()
        self.deck = [u for u in units if u["file"].startswith(DECK_PREFIX)]
        self.evidence_units = [u for u in units if not u["file"].startswith(DECK_PREFIX)]
        self.files = sorted({u["file"] for u in units})

    def page_text(self, file: str, page: int) -> str:
        return self._pages.get((file, page), "")

    @classmethod
    def load(cls, room: Path = ROOM) -> "Room":
        return cls([asdict(u) for u in ingest_room(room)])


def _ask(llm, name: str, prompt: str, metadata: dict | None = None):
    """One model call = one generation observation, with model, tokens and cache status."""
    messages = [{"role": "user", "content": prompt}]  # chat format renders readably in Langfuse
    with tracing.observe(name, as_type="generation", input=messages, metadata=metadata or {}) as gen:
        out = llm.json(prompt)
        attrs = tracing.generation_attrs(llm)
        attrs["metadata"] = {**(metadata or {}), **attrs["metadata"]}
        gen.update(output=out, **attrs)
    return out


# ------------------------------------------------------------ 1. slide claims

def extract_claims(room: Room, llm, prompts: dict) -> list[dict]:
    raw = _ask(llm, "extract-slide-claims",
               prompts["claims"].format(rules=RULES, passages=_passages(room.deck)))
    claims = []
    for i, c in enumerate(raw.get("claims", []) if isinstance(raw, dict) else []):
        page = room.page_text(room.deck[0]["file"], int(c.get("slide", 0)))
        ok = verify.quote_on_page(c.get("quote", ""), page) and verify.value_in_quote(c.get("value"), c.get("quote", ""))
        claims.append({**c, "claim_id": f"K{i + 1}", "slide_verified": ok})
    return claims


# ------------------------------------------------------------ 2. evidence

def check_claim(claim: dict, room: Room, llm, method: str, prompts: dict | None = None) -> dict:
    prompts = prompts or VERSIONS[CURRENT]
    meta = {"claim_id": claim.get("claim_id"), "slide": claim.get("slide"), "method": method}
    with tracing.observe("check-slide-claim", as_type="chain", metadata=meta,
                         input={"slide": claim.get("slide"), "claim": claim["quote"]}) as step:
        with tracing.observe("retrieve-passages", as_type="retriever",
                             input={"claim": claim["quote"], "method": retrieve.METHOD_NAMES[method]},
                             metadata=meta) as ret:
            picked = retrieve.METHODS[method](claim, room.evidence_units, llm, prompts=prompts)
            ret.update(output={"passages": [u["unit_id"] for u in picked]},
                       metadata={**meta, "passages_returned": len(picked), "passages_available": len(room.evidence_units)})

        raw = _ask(llm, "find-evidence", prompts["evidence"].format(
            rules=RULES, passages=_passages(picked), quote=claim["quote"], metric=claim.get("metric", ""),
            value=claim.get("value"), unit=claim.get("unit", ""), period=claim.get("period", "") or "none"), meta)
        raw = raw if isinstance(raw, dict) else {}

        with tracing.observe("verify-evidence", as_type="guardrail", metadata=meta,
                             input={"claim": claim["quote"], "evidence": raw.get("evidence", [])}) as guard:
            evidence = [verify.check_evidence(e, room.by_id, room.page_text) for e in raw.get("evidence", [])]
            # Evidence the AI cited from outside the passages it was shown is not lineage-safe.
            shown = {u["unit_id"] for u in picked}
            for e in evidence:
                if e["verified"] and e.get("unit_id") not in shown:
                    e.update(verified=False, reason="cited a passage it was not shown")
            computed = verify.compute(raw.get("computation"), evidence)
            status, label = verify.decide(claim, evidence, computed)
            guard.update(output={"status": status, "label": label, "computed_value": computed,
                                 "unverified": [e["reason"] for e in evidence if not e["verified"]]})
        step.update(output={"status": status, "label": label, "computed_value": computed,
                            "evidence": [f"{e.get('file')} p.{e.get('page')}: {e.get('quote')}"
                                         for e in evidence if e["verified"]]})
    return {**claim, "method": method, "retrieved": [u["unit_id"] for u in picked],
            "retrieved_pages": sorted({(u["file"], u["page"]) for u in picked}),
            "evidence": evidence, "computation": raw.get("computation"), "computed_value": computed,
            "status": status, "label": label}


# ------------------------------------------------------------ 3. red flags

def hunt_red_flags(room: Room, llm, prompts: dict | None = None) -> list[dict]:
    prompts = prompts or VERSIONS[CURRENT]
    checks = yaml.safe_load(RED_FLAGS.read_text())["checks"]
    check_text = "\n".join(f"- {c['id']}: {c['ask']}" for c in checks)
    valid = {c["id"] for c in checks}
    findings = []
    with tracing.observe("hunt-red-flags", as_type="chain",
                         input={"files": room.files, "checks": sorted(valid)}) as hunt:
        for f in room.files:  # every file, every page: no search, so coverage is complete
            units = [u for u in room.units if u["file"] == f]
            raw = _ask(llm, "review-file", prompts["flags"].format(
                rules=RULES, checks=check_text, file=f, passages=_passages(units)), {"file": f, "pages": len({u["page"] for u in units})})
            with tracing.observe("verify-findings", as_type="guardrail", metadata={"file": f},
                                 input=raw.get("findings", []) if isinstance(raw, dict) else raw) as guard:
                file_findings = []
                for item in raw.get("findings", []) if isinstance(raw, dict) else []:
                    ev = verify.check_evidence({**item, "role": "context"}, room.by_id, room.page_text)
                    if ev["verified"] and ev.get("file") != f:
                        ev.update(verified=False, reason="cited a passage outside this file")
                    if item.get("check_id") not in valid:
                        ev.update(verified=False, reason="unknown check")
                    ev["advice_words"] = verify.advice_in(item.get("observation", ""))
                    file_findings.append(ev)
                guard.update(output=[{"check": x.get("check_id"), "verified": x["verified"], "reason": x["reason"],
                                      "advice_words": x["advice_words"]} for x in file_findings])
            findings.extend(file_findings)
        for i, x in enumerate(findings):
            x["flag_id"] = f"F{i + 1}"
        hunt.update(output={"findings": len(findings), "verified": sum(x["verified"] for x in findings)})
    return findings


# ------------------------------------------------------------ 4. run

def run(llm, methods=("A", "B", "C", "D"), room: Room | None = None, version: str = CURRENT) -> dict:
    """One full check. Each method gets its own trace; the red flag hunt gets one too."""
    room = room or Room.load()
    prompts = VERSIONS[version]
    first_call = len(getattr(llm, "calls", []))  # one model client can serve several runs
    meta = {"data_room": "fintech-a", "files": len(room.files), "prompt_version": version}

    with tracing.trace_run(method="claims", tags=["slide-claims", version], metadata=meta, version=version):
        with tracing.observe("check-data-room", input={"data_room": "fintech-a", "step": "extract slide claims"}) as root:
            claims = extract_claims(room, llm, prompts)
            root.update(output={"claims": len(claims), "on_slide": sum(c["slide_verified"] for c in claims)})

    results = {}
    for m in methods:
        with tracing.trace_run(method=m, tags=[f"method-{m}", retrieve.METHOD_NAMES[m], version],
                               metadata={**meta, "method": m}, version=version):
            with tracing.observe("check-data-room", input={"data_room": "fintech-a",
                                                           "method": retrieve.METHOD_NAMES[m]}) as root:
                results[m] = [check_claim(c, room, llm, m, prompts) for c in claims if c["slide_verified"]]
                counts = {s: sum(r["status"] == s for r in results[m])
                          for s in ("confirmed", "contradicted", "conflict", "not_found", "unverified")}
                root.update(output=counts)
                results[m + "_trace_id"] = getattr(root, "trace_id", None)

    with tracing.trace_run(method="red-flags", tags=["red-flags", version], metadata=meta, version=version):
        with tracing.observe("check-data-room", input={"data_room": "fintech-a", "step": "red flag hunt"}) as root:
            flags = hunt_red_flags(room, llm, prompts)
            root.update(output={"findings": len(flags)})
            flags_trace = getattr(root, "trace_id", None)

    trace_ids = {k[0]: results.pop(k) for k in list(results) if k.endswith("_trace_id")}
    trace_ids["red_flags"] = flags_trace
    tracing.flush()
    return {
        "model": llm.name,
        "prompt_version": version,
        "files": room.files,
        "file_hashes": {u["file"]: u["file_sha256"] for u in room.units},
        "claims": claims,
        "results": results,
        "red_flags": flags,
        "trace_ids": trace_ids,
        "calls": getattr(llm, "calls", [])[first_call:],
    }


def save_run(out: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, default=list))
