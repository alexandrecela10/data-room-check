"""The guided demo: every step renders, the example replays, an edited deck runs live (fake model)."""

import os

import pytest
from streamlit.testing.v1 import AppTest

APP = "../app.py"


def go(at, step):
    at.sidebar.radio[0].set_value(step).run()
    assert not at.exception, at.exception


@pytest.fixture
def at():
    return AppTest.from_file(APP, default_timeout=180).run()


def test_every_step_renders_before_a_check(at):
    assert not at.exception
    for step in at.sidebar.radio[0].options:
        go(at, step)


def test_example_deck_journey(at):
    at.button(key="next-2. Meet your data room").click().run()
    assert at.session_state.step == "2. Meet your data room"
    go(at, "3. Run the check")
    next(b for b in at.button if b.label == "Show the results").click().run()
    assert at.session_state.step == "4. Read your results"
    assert at.session_state.results["source"] == "stored"
    for m in "ABCD":
        at.radio(key="m1").set_value(m).run()
        assert not at.exception
    go(at, "5. Look under the hood")
    go(at, "6. How we got here")


def test_edited_deck_runs_live_with_all_four_methods(monkeypatch, at):
    monkeypatch.setenv("DRC_FAKE_LLM", "1")
    for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    at.radio[0].set_value("edited").run()
    at.button[0].click().run()  # "Build my deck" with the default numbers
    assert not at.exception
    go(at, "3. Run the check")
    next(b for b in at.button if b.label == "Check my deck").click().run()
    assert not at.exception, at.exception
    res = at.session_state.results
    assert res["source"] == "live"
    assert set(res["claims"]) == {"A", "B", "C", "D"}
    assert at.session_state.live_used == 1
    go(at, "5. Look under the hood")
