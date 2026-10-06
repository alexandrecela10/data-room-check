"""Run the pipeline and store everything a reviewer needs to retrace it.

    .venv/bin/python -m dataroom.run             # live: calls Gemini, fills the cache
    .venv/bin/python -m dataroom.run --offline   # replays from the cache, no key needed

Writes runs/latest.json (full results) and the DuckDB tables `claims`,
`results`, `red_flags` and `calls` (the query log: every model call, with the
cache file holding its exact prompt and raw response).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from dataroom.ingest import DB, ingest_room, save
from dataroom.llm import default_llm
from dataroom.pipeline import run, save_run

ROOT = Path(__file__).resolve().parent.parent
LATEST = ROOT / "runs" / "latest.json"


def to_duckdb(out: dict, db: Path = DB) -> None:
    con = duckdb.connect(str(db))
    con.execute("CREATE OR REPLACE TABLE claims AS SELECT * FROM read_json_auto(?)", [_tmp(out["claims"])])
    rows = [{"method": m, "claim_id": r["claim_id"], "slide": r["slide"], "quote": r["quote"],
             "status": r["status"], "label": r["label"], "computed_value": r["computed_value"],
             "evidence": json.dumps(r["evidence"]), "retrieved": json.dumps(r["retrieved"])}
            for m, rs in out["results"].items() for r in rs]
    con.execute("CREATE OR REPLACE TABLE results AS SELECT * FROM read_json_auto(?)", [_tmp(rows)])
    con.execute("CREATE OR REPLACE TABLE red_flags AS SELECT * FROM read_json_auto(?)", [_tmp(out["red_flags"])])
    con.execute("CREATE OR REPLACE TABLE calls AS SELECT * FROM read_json_auto(?)", [_tmp(out["calls"])])
    con.close()


def _tmp(rows) -> str:
    path = ROOT / "runs" / ".tmp.json"
    path.write_text(json.dumps(rows or [{}], default=list))
    return str(path)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="replay cached model calls only")
    ap.add_argument("--methods", default="ABCD")
    args = ap.parse_args(argv)

    save(ingest_room())
    previous = json.loads(LATEST.read_text())["model"] if LATEST.exists() else None
    llm = default_llm(offline=args.offline, name=previous)
    out = run(llm, methods=tuple(args.methods))
    out["run_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_run(out, LATEST)
    to_duckdb(out)
    hits = sum(c["cache_hit"] for c in out["calls"])
    print(f"{len(out['claims'])} slide claims, {len(out['red_flags'])} red flag findings, "
          f"{len(out['calls'])} model calls ({hits} from cache) -> {LATEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
