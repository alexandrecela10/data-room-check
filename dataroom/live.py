"""Check a visitor's deck against the Fintech A data room, with all four methods.

The data room never changes, so its red flag reviews and search index come from
the cache: a visitor pays only for reading their deck and for the slide numbers
that changed. Each method gets its own model client (usage is tracked per call,
so clients can't be shared across threads), and the methods run in parallel.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from dataroom import tracing
from dataroom.ingest import ROOM, ingest_file, ingest_room
from dataroom.llm import CACHE, CachedLLM, GeminiLLM, load_env
from dataroom.pipeline import Room, check_claim, extract_claims, hunt_red_flags
from dataroom.prompts import CURRENT, VERSIONS
from dataroom.retrieve import METHOD_NAMES

DECK_NAME = "01_your_deck.pdf"
MAX_PAGES = 15
MAX_BYTES = 5 * 1024 * 1024


def make_llm() -> CachedLLM:
    """Gemini, or the test double when DRC_FAKE_LLM=1 (tests run offline)."""
    if os.environ.get("DRC_FAKE_LLM") == "1":
        from tests.fake_llm import FakeLLM
        return CachedLLM(FakeLLM(), cache_dir=Path(tempfile.gettempdir()) / "drc-fake-cache")
    load_env()
    return CachedLLM(GeminiLLM(), cache_dir=CACHE)


def room_with_deck(deck_bytes: bytes) -> tuple[Room, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="drc-"))
    path = tmp / DECK_NAME
    path.write_bytes(deck_bytes)
    base = [asdict(u) for u in ingest_room(ROOM) if not u.file.startswith("01_")]
    deck = [asdict(u) for u in ingest_file(path)]
    return Room(base + deck), tmp


def _cost(llm: CachedLLM, price: dict) -> dict:
    tok_in = tok_out = live = 0
    seconds = 0.0
    for c in llm.calls:
        d = json.loads((llm.dir / c["kind"] / c["cache_file"]).read_text())
        if not c["cache_hit"]:
            live += 1
            seconds += d.get("seconds", 0.0)
            u = d.get("usage") or {}
            tok_in += u.get("input", 0)
            tok_out += u.get("output", 0)
    return {"live_calls": live, "cached_calls": len(llm.calls) - live, "tokens_in": tok_in, "tokens_out": tok_out,
            "cost_usd": round((tok_in * price["input"] + tok_out * price["output"]) / 1e6, 4),
            "seconds": round(seconds, 1)}


def check_deck(deck_bytes: bytes, price: dict, progress=None) -> dict:
    """progress(method, done, total) is called from the main thread only."""
    room, tmp = room_with_deck(deck_bytes)
    prompts = VERSIONS[CURRENT]
    started = time.perf_counter()
    try:
        reader = make_llm()
        with tracing.trace_run(method="claims", tags=["demo", "visitor-deck", CURRENT],
                               metadata={"data_room": "fintech-a", "deck": "visitor"}, version=CURRENT,
                               environment="demo"):
            with tracing.observe("check-data-room", input={"data_room": "fintech-a", "step": "extract slide claims",
                                                           "deck": "visitor"}) as root:
                claims = [c for c in extract_claims(room, reader, prompts) if c["slide_verified"]]
                root.update(output={"claims": len(claims)})

        llms = {m: make_llm() for m in METHOD_NAMES}
        done = {m: 0 for m in METHOD_NAMES}

        def one_method(m):
            out = []
            with tracing.trace_run(method=m, tags=["demo", "visitor-deck", f"method-{m}", CURRENT],
                                   metadata={"data_room": "fintech-a", "deck": "visitor", "method": m},
                                   version=CURRENT, environment="demo"):
                with tracing.observe("check-data-room", input={"data_room": "fintech-a",
                                                               "method": METHOD_NAMES[m], "deck": "visitor"}) as root:
                    for c in claims:
                        out.append(check_claim(c, room, llms[m], m, prompts))
                        done[m] += 1
                    root.update(output={s: sum(r["status"] == s for r in out)
                                        for s in ("confirmed", "contradicted", "conflict", "not_found", "unverified")})
            return out

        with ThreadPoolExecutor(max_workers=len(METHOD_NAMES)) as pool:
            futures = {m: pool.submit(one_method, m) for m in METHOD_NAMES}
            while not all(f.done() for f in futures.values()):
                if progress:
                    for m in METHOD_NAMES:
                        progress(m, done[m], len(claims))
                time.sleep(0.5)
            results = {m: f.result() for m, f in futures.items()}
        if progress:
            for m in METHOD_NAMES:
                progress(m, len(claims), len(claims))

        with tracing.trace_run(method="red-flags", tags=["demo", "visitor-deck", CURRENT],
                               metadata={"data_room": "fintech-a", "deck": "visitor"}, version=CURRENT,
                               environment="demo"):
            with tracing.observe("check-data-room", input={"data_room": "fintech-a", "step": "red flag hunt"}) as root:
                flags = hunt_red_flags(room, reader, prompts)
                root.update(output={"findings": len(flags)})
        tracing.flush()
        return {
            "source": "live",
            "claims": {m: rs for m, rs in results.items()},
            "red_flags": flags,
            "cost": {m: _cost(llms[m], price) for m in METHOD_NAMES} | {"shared": _cost(reader, price)},
            "seconds": round(time.perf_counter() - started, 1),
            "deck_file": DECK_NAME,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
