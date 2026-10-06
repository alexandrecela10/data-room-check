"""Model provider behind one small interface.

The pipeline only calls `json(prompt)` and `embed(texts)`. Gemini is the default
provider; swapping it means writing another class with the same two methods.

Every call is cached on disk by a hash of (model, prompt). A cached run costs
nothing, gives the same output every time, and is how the demo ships stored
results. Each call is also appended to the call log for lineage.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"


class LLM(Protocol):
    name: str

    def json(self, prompt: str) -> dict | list: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _key(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:32]


class CachedLLM:
    """Wraps any LLM with a disk cache and a call log."""

    def __init__(self, inner: LLM, cache_dir: Path = CACHE, offline: bool = False):
        self.inner, self.name, self.offline = inner, inner.name, offline
        self.dir = cache_dir
        self.calls: list[dict] = []
        # Set after every call, read by tracing for the generation observation.
        self.last_model = self.last_usage = self.last_cache_hit = None

    def _cached(self, kind: str, payload: str, fn):
        path = self.dir / kind / f"{_key(self.name, payload)}.json"
        model = getattr(self.inner, "model" if kind == "json" else "embed_model", self.name)
        if path.exists():
            out = json.loads(path.read_text())["response"]
            hit, usage = True, None  # a replay spends no tokens
        else:
            if self.offline:
                raise RuntimeError(f"Offline and no cached {kind} response for this input")
            started = time.perf_counter()
            out = fn()
            seconds = round(time.perf_counter() - started, 3)
            usage = getattr(self.inner, "last_usage", None)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"model": self.name, "input": payload, "response": out, "usage": usage,
                                        "seconds": seconds}))
            hit = False
        self.last_model, self.last_usage, self.last_cache_hit = model, usage, hit
        self.calls.append({"kind": kind, "model": self.name, "cache_file": path.name, "cache_hit": hit})
        return out

    def json(self, prompt: str):
        return self._cached("json", prompt, lambda: self.inner.json(prompt))

    def embed(self, texts: list[str]) -> list[list[float]]:
        payload = json.dumps(texts)
        return self._cached("embed", payload, lambda: self.inner.embed(texts))


def load_env(path: Path = ROOT / ".env") -> None:
    """Minimal .env reader: KEY=value lines, existing variables win."""
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class GeminiLLM:
    """Gemini via google-genai. Reads GEMINI_API_KEY first, then GOOGLE_API_KEY."""

    def __init__(self):
        load_env()
        from google import genai
        from google.genai import types

        self._types = types
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self._client = genai.Client(api_key=key)
        self.model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
        self.embed_model = os.environ.get("GEMINI_EMBED_MODEL", "gemini-embedding-2")
        self.name = f"{self.model}+{self.embed_model}"
        self.last_usage = None

    def json(self, prompt: str):
        cfg = self._types.GenerateContentConfig(temperature=0, response_mime_type="application/json")
        for attempt in range(3):
            try:
                resp = self._client.models.generate_content(model=self.model, contents=prompt, config=cfg)
                um = resp.usage_metadata
                self.last_usage = {"input": um.prompt_token_count or 0,
                                   "output": (um.candidates_token_count or 0) + (um.thoughts_token_count or 0)}
                return json.loads(resp.text)
            except json.JSONDecodeError:
                if attempt == 2:
                    raise
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))

    def embed(self, texts: list[str]) -> list[list[float]]:
        # One request per text: gemini-embedding-2 merges a list of contents into a
        # single embedding, so batching would return one vector for many passages.
        out = []
        for t in texts:
            resp = self._client.models.embed_content(model=self.embed_model, contents=t)
            out.append(resp.embeddings[0].values)
        self.last_usage = None  # the embeddings API reports no token counts
        return out


def default_llm(offline: bool = False, name: str | None = None, cache_dir: Path = CACHE) -> CachedLLM:
    """Offline mode reads only the cache, so stored results replay with no key.

    `name` must be the model name the cache was filled with (runs/latest.json
    records it); the cache key includes it.
    """
    if offline:
        model_name = name or "gemini-3.8-flash+gemini-embedding-2"

        class _Stub:
            name = model_name

            def json(self, prompt):  # never reached: CachedLLM raises first
                raise RuntimeError

            def embed(self, texts):
                raise RuntimeError
        return CachedLLM(_Stub(), cache_dir=cache_dir, offline=True)
    return CachedLLM(GeminiLLM(), cache_dir=cache_dir)
