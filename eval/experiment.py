"""Run the eval as a Langfuse experiment: one item per retrieval method.

    .venv/bin/python -m eval.experiment            # current prompt version
    .venv/bin/python -m eval.experiment --version v1

Uses the SDK experiment runner (https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk).
Each item runs the pipeline for one method; item evaluators score it against
the answer key; a run evaluator reports the pass/fail verdict. Runs are named
by prompt version so iterations line up side by side under Experiments.

Model calls are cached, so re-running an old prompt version costs nothing.
Without Langfuse keys it still prints the same scores locally.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from dataroom import tracing
from dataroom.llm import default_llm, load_env
from dataroom.pipeline import Room, run
from dataroom.prompts import CURRENT
from dataroom.retrieve import METHOD_NAMES
from eval.score import KEY, PRECISION_BAR, RECALL_BAR, score

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"


def task_factory(room, llm, version, key, outputs):
    def task(*, item, **kwargs):
        data = item["input"] if isinstance(item, dict) else item.input
        out = run(llm, methods=(data["method"],), room=room, version=version)
        rep = score(out, key)["methods"][data["method"]]
        outputs[data["method"]] = (out, rep)
        return {k: rep[k] for k in ("wrong_numbers_flagged", "correct_numbers_wrongly_flagged",
                                    "precision", "recall", "lineage", "evidence_pages_found", "verdict")} | {
            "values": rep["values"], "statuses": rep["statuses"]}
    return task


def _evaluators():
    from langfuse import Evaluation

    def metric(name, bar=None):
        def ev(*, output, **kwargs):
            v = output["values"][name]
            comment = f"bar {bar:.0%}" if bar is not None else None
            return Evaluation(name=name, value=round(v, 4), comment=comment)
        ev.__name__ = name
        return ev

    def verdict(*, output, **kwargs):
        return Evaluation(name="pass", value=1.0 if output["verdict"] == "PASS" else 0.0, comment=output["verdict"])

    return [metric("precision", PRECISION_BAR), metric("recall", RECALL_BAR), metric("lineage", 1.0),
            metric("evidence_pages_found"), verdict]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=CURRENT)
    ap.add_argument("--methods", default="ABCD")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--bench", action="store_true",
                    help="fresh cache: every call live, so tokens and latency compare fairly across methods")
    args = ap.parse_args(argv)

    load_env()
    room = Room.load()
    latest = RUNS / "latest.json"
    previous = json.loads(latest.read_text())["model"] if latest.exists() else None
    from dataroom.llm import CACHE
    cache_dir = ROOT / "data" / f"cache-bench-{args.version}" if args.bench else CACHE
    llm = default_llm(offline=args.offline, name=previous, cache_dir=cache_dir)
    tag = f"{args.version}-bench" if args.bench else args.version
    key = yaml.safe_load(KEY.read_text())
    outputs: dict = {}
    data = [{"input": {"data_room": "fintech-a", "method": m},
             "expected_output": {"wrong_numbers": 4, "red_flags": 6, "precision_bar": PRECISION_BAR,
                                 "recall_bar": RECALL_BAR},
             "metadata": {"method_name": METHOD_NAMES[m]}} for m in args.methods]
    task = task_factory(room, llm, args.version, key, outputs)

    c = tracing.client()
    if c is not None:
        result = c.run_experiment(
            name="data-room-check",
            run_name=f"prompt-{tag}",
            description=f"Fintech A answer key, prompt {args.version}, methods {args.methods}",
            data=data, task=task, evaluators=_evaluators(), max_concurrency=1,
            metadata={"prompt_version": args.version, "model": llm.name},
        )
        print(result.format())
        tracing.flush()
    else:
        print("Langfuse keys not set: scoring locally only.")
        for item in data:
            task(item=item)

    for m, (out, rep) in outputs.items():
        out["cache_dir"] = str(cache_dir.relative_to(ROOT))
        (RUNS / f"{tag}-{m}.json").write_text(json.dumps(out, indent=2, default=list))
        print(f"{args.version} {m} ({METHOD_NAMES[m]}): precision {rep['precision']}, recall {rep['recall']}, "
              f"lineage {rep['lineage']}, pages {rep['evidence_pages_found']} -> {rep['verdict']}")
        print(f"   statuses {rep['statuses']}")
        for u in rep["unverified"]:
            print(f"   unverified {u}")
    rf = score(next(iter(outputs.values()))[0], key)["red_flags"]
    print(f"red flags: found {rf['found']} (off-list {rf['off_list_found']}), missed {rf['missed']}, "
          f"false {rf['false_findings']}, advice {rf['advice_leakage']}")


if __name__ == "__main__":
    main()
