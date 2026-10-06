"""Score a run against the answer key. The only code that reads the key.

    .venv/bin/python -m eval.score            # scores runs/latest.json

Metrics (PRD, Success Metrics and Kill criteria):
- Wrong slide numbers flagged (of 4), per method.
- Correct slide numbers wrongly flagged (of 6), per method.
- Evidence pages found: share of answer-key evidence pages each method put in
  front of the AI.
- Red flags found (of 6), and how many of the 2 off-list ones.
- Lineage: verified items / all items. Kill if below 100%.
- Precision: real flags / all flags. Kill if below 95%.
- Advice leakage: findings whose wording recommends something.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from rapidfuzz import fuzz

from dataroom.ingest import normalise

ROOT = Path(__file__).resolve().parent.parent
KEY = ROOT / "eval" / "answer_key.yaml"
LATEST = ROOT / "runs" / "latest.json"
FLAGGED = {"contradicted", "conflict"}

# Bars set by Alex on 2026-10-05: precision at least 90% (was 95% in the PRD),
# recall 100% (wrong slide numbers flagged + red flags found), lineage 100%.
PRECISION_BAR = 0.90
RECALL_BAR = 1.0


def _match_claim(key_claim: dict, results: list[dict]) -> dict | None:
    best, score = None, 0
    for r in results:
        if int(r["slide"]) != key_claim["slide"]:
            continue
        s = fuzz.partial_ratio(normalise(r["quote"]), normalise(key_claim["claim"]))
        if s > score:
            best, score = r, s
    return best if score >= 85 else None


def _finding_matches(finding: dict, flag: dict) -> bool:
    if not finding.get("verified"):
        return False
    for ev in flag["evidence"]:
        if finding.get("file") == ev["file"] and finding.get("page") == ev["page"]:
            if fuzz.partial_ratio(normalise(finding.get("quote", "")), normalise(ev["quote"])) >= 80:
                return True
    return False


def score(run: dict, key: dict) -> dict:
    flags_key = key["red_flags"]
    findings = run["red_flags"]
    true_findings = [f for f in findings if any(_finding_matches(f, k) for k in flags_key)]
    found = [k for k in flags_key if any(_finding_matches(f, k) for f in findings)]
    flag_items = len(findings)
    flag_verified = sum(bool(f.get("verified")) for f in findings)
    advice = [f["flag_id"] for f in findings if f.get("advice_words")]

    report = {"model": run["model"], "red_flags": {
        "found": f"{len(found)} of {len(flags_key)}",
        "off_list_found": f"{sum(not k['on_list'] for k in found)} of {sum(not k['on_list'] for k in flags_key)}",
        "missed": [k["id"] for k in flags_key if k not in found],
        "findings": len(findings), "true_findings": len(true_findings),
        "false_findings": [f["flag_id"] for f in findings if f not in true_findings],
        "advice_leakage": advice,
    }, "methods": {}}

    for method, results in run["results"].items():
        wrong = [k for k in key["slide_claims"] if k["status"] != "confirmed"]
        right = [k for k in key["slide_claims"] if k["status"] == "confirmed"]
        matched = {k["id"]: _match_claim(k, results) for k in key["slide_claims"]}
        flagged_wrong = [k["id"] for k in wrong if matched[k["id"]] and matched[k["id"]]["status"] in FLAGGED]
        false_slide = [k["id"] for k in right if matched[k["id"]] and matched[k["id"]]["status"] in FLAGGED]
        exact = [k["id"] for k in key["slide_claims"] if matched[k["id"]] and matched[k["id"]]["status"] == k["status"]]

        # Evidence pages found: did the method put the key's evidence pages in front of the AI?
        want = got = 0
        for k in key["slide_claims"]:
            pages = {(e["file"], e["page"]) for e in k["evidence"]}
            r = matched[k["id"]]
            seen = {tuple(p) for p in r["retrieved_pages"]} if r else set()
            want += len(pages)
            got += len(pages & seen)

        # Precision over everything the tool flags: slide flags plus red flag findings.
        slide_flags = [r for r in results if r["status"] in FLAGGED]
        wrong_ids = {id(matched[k["id"]]) for k in wrong if matched[k["id"]]}
        true_slide = [r for r in slide_flags if id(r) in wrong_ids]
        total_flags = len(slide_flags) + sum(bool(f.get("verified")) for f in findings)
        true_flags = len(true_slide) + len(true_findings)
        precision = true_flags / total_flags if total_flags else 0.0

        # Lineage: every evidence item and every finding, verified by code or not.
        ev_items = [e for r in results for e in r["evidence"]]
        items = len(ev_items) + flag_items
        verified = sum(e["verified"] for e in ev_items) + flag_verified
        lineage = verified / items if items else 0.0

        recall_hits = len(flagged_wrong) + len(found)
        recall_total = len(wrong) + len(flags_key)
        recall = recall_hits / recall_total

        kill = []
        if lineage < 1.0:
            kill.append(f"lineage {lineage:.0%} < 100%")
        if precision < PRECISION_BAR:
            kill.append(f"precision {precision:.0%} < {PRECISION_BAR:.0%}")
        if recall < RECALL_BAR:
            kill.append(f"recall {recall:.0%} < {RECALL_BAR:.0%}")
        report["methods"][method] = {
            "wrong_numbers_flagged": f"{len(flagged_wrong)} of {len(wrong)}",
            "correct_numbers_wrongly_flagged": f"{len(false_slide)} of {len(right)}",
            "exact_status": f"{len(exact)} of {len(key['slide_claims'])}",
            "missed_claims": [k for k, v in matched.items() if v is None],
            "evidence_pages_found": f"{got} of {want} ({got / want:.0%})",
            "lineage": f"{verified} of {items} ({lineage:.0%})",
            "unverified": [
                {"claim": r["claim_id"], "unit_id": e.get("unit_id"), "reason": e["reason"]}
                for r in results for e in r["evidence"] if not e["verified"]
            ] + [{"flag": f["flag_id"], "unit_id": f.get("unit_id"), "reason": f["reason"]}
                 for f in findings if not f.get("verified")],
            "precision": f"{true_flags} of {total_flags} ({precision:.0%})",
            "recall": f"{recall_hits} of {recall_total} ({recall:.0%})",
            "values": {"precision": precision, "recall": recall, "lineage": lineage,
                       "evidence_pages_found": got / want if want else 0.0},
            "statuses": {k: (v["status"] if v else "not extracted") for k, v in matched.items()},
            "verdict": "KILL: " + "; ".join(kill) if kill else "PASS",
        }
    return report


def main():
    run = json.loads(LATEST.read_text())
    key = yaml.safe_load(KEY.read_text())
    rep = score(run, key)
    rep["prompt_version"] = run.get("prompt_version", "v1")
    (ROOT / "eval" / "report.json").write_text(json.dumps(rep, indent=2))
    rf = rep["red_flags"]
    print(f"Model: {rep['model']}  Prompt: {rep['prompt_version']}")
    print(f"Red flags found: {rf['found']} (off-list {rf['off_list_found']}), missed {rf['missed']}, "
          f"false findings {rf['false_findings']}, advice leakage {len(rf['advice_leakage'])}")
    print()
    head = ["Metric"] + [f"{m}" for m in rep["methods"]]
    rows = ["wrong_numbers_flagged", "correct_numbers_wrongly_flagged", "exact_status",
            "evidence_pages_found", "lineage", "precision", "recall", "verdict"]
    print(" | ".join(head))
    for r in rows:
        print(" | ".join([r] + [str(rep["methods"][m][r]) for m in rep["methods"]]))
    for m, v in rep["methods"].items():
        print(f"\n{m} statuses: {v['statuses']}")
        for u in v["unverified"]:
            print(f"  unverified: {u}")


if __name__ == "__main__":
    main()
