"""Langfuse tracing, following https://langfuse.com/docs/observability/best-practices.

One trace per data room check ("check-data-room"). Inside it:

    check-data-room (span)                      input: data room + method, output: counts
    ├─ extract-slide-claims (generation)        each AI call is its own generation
    ├─ check-slide-claim (chain)                one per claim and method
    │  ├─ retrieve-passages (retriever)         A, B or C; output: passage IDs
    │  │  ├─ embed-passages (embedding)         B only
    │  │  └─ pick-sections (generation)         C only
    │  ├─ find-evidence (generation)
    │  └─ verify-evidence (guardrail)           code checks; output: status + reasons
    └─ hunt-red-flags (chain)
       ├─ review-file (generation)              one per file, all pages
       └─ verify-findings (guardrail)

Names are stable and verb-first; run-specific values go in metadata and tags.
Inputs are set explicitly (never raw function arguments).

Tracing is off unless LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set, so
tests and offline replays send nothing. All data is fictional; no masking needed.
"""

from __future__ import annotations

import os
from contextlib import contextmanager



def enabled() -> bool:
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


_client = None


def client():
    """Create the Langfuse client lazily, after .env has been loaded."""
    global _client
    if _client is None and enabled():
        if os.environ.get("LANGFUSE_BASE_URL") and not os.environ.get("LANGFUSE_HOST"):
            os.environ["LANGFUSE_HOST"] = os.environ["LANGFUSE_BASE_URL"]
        # The OTel span exporter uses plain urllib3, which reads the system CA store.
        # On a Homebrew Python that store can fail to verify cloud.langfuse.com, so
        # point it at certifi's bundle, which requests and httpx already use.
        if not os.environ.get("OTEL_EXPORTER_OTLP_CERTIFICATE"):
            import certifi
            os.environ["OTEL_EXPORTER_OTLP_CERTIFICATE"] = certifi.where()
        from langfuse import get_client
        _client = get_client()
    return _client


class _NoOp:
    id = None
    trace_id = None

    def update(self, **kwargs):
        return self

    def score(self, **kwargs):
        return None

    def score_trace(self, **kwargs):
        return None


@contextmanager
def observe(name: str, as_type: str = "span", **attrs):
    """Context manager for one observation; yields a no-op when tracing is off."""
    c = client()
    if c is None:
        yield _NoOp()
        return
    with c.start_as_current_observation(name=name, as_type=as_type, **attrs) as obs:
        yield obs


@contextmanager
def trace_run(*, method: str, tags: list[str], metadata: dict, version: str, environment: str = "development"):
    """Root attributes shared by every observation in one check."""
    c = client()
    if c is None:
        yield
        return
    from langfuse import propagate_attributes
    with propagate_attributes(trace_name="check-data-room", version=version, tags=tags,
                              metadata={k: str(v) for k, v in metadata.items()}, environment=environment):
        yield


def generation_attrs(llm) -> dict:
    """Model, token usage and cache status of the model call that just ran."""
    attrs = {"model": getattr(llm, "last_model", None) or getattr(llm, "name", None),
             "metadata": {"cache_hit": getattr(llm, "last_cache_hit", None)}}
    usage = getattr(llm, "last_usage", None)
    if usage:
        attrs["usage_details"] = usage
    return attrs


def flush():
    c = client()
    if c is not None:
        c.flush()
