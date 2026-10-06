"""Build step 2: code checks, the three retrieval methods, red flags, scoring."""

import json

import pytest
import yaml

from dataroom import retrieve, verify
from dataroom.llm import CachedLLM
from dataroom.pipeline import Room, check_claim, hunt_red_flags, run
from eval.score import KEY, score
from tests.fake_llm import CLAIMS, FakeLLM


@pytest.fixture(scope="module")
def room():
    return Room.load()


@pytest.fixture(scope="module")
def full_run(room):
    return run(FakeLLM(), room=room)


# ------------------------------------------------------------ code checks

def test_quote_matching_tolerates_spacing_but_not_other_pages(room):
    page = room.page_text("09_senior_facility_agreement.pdf", 4)
    assert verify.quote_on_page("the Borrower must  repay the loan in full", page)
    other = room.page_text("09_senior_facility_agreement.pdf", 1)
    assert not verify.quote_on_page("the Borrower must repay the loan in full", other)


def test_invented_quote_fails(room):
    page = room.page_text("12_letter_hollis_grant.pdf", 1)
    assert not verify.quote_on_page("Our client claims $4.5M for breach of a licence", page)


def test_value_must_appear_in_quote():
    assert verify.value_in_quote(36.2, "Revenue | 36.2")
    assert verify.value_in_quote(4200000, "Daniel Okafor | 4,200,000 | 42.0")
    assert not verify.value_in_quote(38.0, "Revenue | 36.2")
    assert verify.value_in_quote(3, "The company sells three products")


def test_wrong_page_citation_is_unverified(room):
    ev = {"unit_id": "03_audited_accounts_fy2025:p4:u1", "quote": "Revenue | 36.2", "value": 36.2,
          "unit": "$M", "period": "FY2025", "role": "direct"}
    out = verify.check_evidence(ev, room.by_id, room.page_text)
    assert not out["verified"] and out["reason"] == "quote not on cited page"


def test_wrong_period_is_unverified(room):
    ev = {"unit_id": "02_audited_accounts_fy2024:p3:u1", "quote": "Revenue | 30.1", "value": 30.1,
          "unit": "$M", "period": "FY2025", "role": "direct"}
    assert verify.check_evidence(ev, room.by_id, room.page_text)["reason"] == "period not on page"


def test_arithmetic_happens_in_code():
    ev = [{"verified": True, "value": 11.22}, {"verified": True, "value": 36.20}]
    assert verify.compute({"op": "ratio_pct", "numerator": 0, "denominator": 1}, ev) == 31.0
    ev[1]["verified"] = False
    assert verify.compute({"op": "ratio_pct", "numerator": 0, "denominator": 1}, ev) is None


@pytest.mark.parametrize("values,expected", [
    ([68.0], "confirmed"), ([36.2], "contradicted"), ([36.2, 38.0], "conflict"), ([], "not_found"),
])
def test_status_is_decided_by_numbers(values, expected):
    claim = {"value": 38.0 if expected != "confirmed" else 68, "unit": "$M" if expected != "confirmed" else "%"}
    ev = [{"verified": True, "value": v, "role": "direct"} for v in values]
    assert verify.decide(claim, ev, None)[0] == expected


def test_only_unverified_evidence_gives_unverified_status():
    ev = [{"verified": False, "value": 1, "role": "direct"}]
    assert verify.decide({"value": 1, "unit": "count"}, ev, None)[0] == "unverified"


def test_advice_words_are_caught():
    assert verify.advice_in("We recommend you avoid this deal") == ["avoid", "recommend"]
    assert verify.advice_in("The loan must be repaid if owners change.") == []


# ------------------------------------------------------------ retrieval

def test_method_a_shows_everything(room):
    assert retrieve.method_a(CLAIMS[0], room.evidence_units) == room.evidence_units


def test_method_b_returns_top_k(room):
    picked = retrieve.method_b(CLAIMS[2], room.evidence_units, FakeLLM())
    assert len(picked) == retrieve.TOP_K


def test_method_c_follows_the_tree(room):
    tree = retrieve.build_tree(room.evidence_units)
    assert len(tree) == 12  # every file except the deck
    picked = retrieve.method_c(CLAIMS[6], room.evidence_units, FakeLLM())
    assert {u["unit_id"] for u in picked} == {"05_customer_revenue_analysis:p2:u1"}


def test_method_d_narrows_files_then_follows_the_tree(room):
    picked = retrieve.method_d(CLAIMS[6], room.evidence_units, FakeLLM(), {"hybrid": {"files": 3}})
    assert {u["file"] for u in picked} <= {u["file"] for u in room.evidence_units}
    assert len({u["file"] for u in picked}) <= 3


def test_hidden_passage_means_not_found(room):
    """If retrieval or the model misses the evidence, the answer is not found, never a guess."""
    r = check_claim(CLAIMS[5], room, FakeLLM(drop_units={"05_customer_revenue_analysis:p1:u1"}), "A")
    assert r["status"] == "not_found"


def test_citing_a_passage_not_shown_is_unverified(room):
    class Sneaky(FakeLLM):
        def json(self, prompt):
            out = super().json(prompt)
            if "A slide claims" in prompt:
                return {"evidence": [{"unit_id": "05_customer_revenue_analysis:p1:u1",
                                      "quote": "Active customers at 31 December 2025: 372.", "value": 372,
                                      "unit": "count", "period": "", "role": "direct"}], "computation": None}
            return out
    claim = CLAIMS[5]
    r = check_claim(claim, room, Sneaky(), "C")  # C shows no customer-list page for this claim
    if "05_customer_revenue_analysis:p1:u1" not in r["retrieved"]:
        assert r["status"] == "unverified"


# ------------------------------------------------------------ red flags

def test_red_flag_hunt_reads_every_file(room):
    prompts = []

    class Spy(FakeLLM):
        def json(self, prompt):
            prompts.append(prompt)
            return super().json(prompt)
    hunt_red_flags(room, Spy())
    assert sum("Run each check" in p for p in prompts) == 13


# ------------------------------------------------------------ end to end + scoring

def test_full_run_passes_on_a_careful_model(full_run):
    rep = score(full_run, yaml.safe_load(KEY.read_text()))
    a = rep["methods"]["A"]
    assert a["wrong_numbers_flagged"] == "4 of 4"
    assert a["correct_numbers_wrongly_flagged"] == "0 of 6"
    assert a["exact_status"] == "10 of 10"
    assert a["verdict"] == "PASS"
    assert rep["red_flags"]["found"] == "6 of 6"
    assert rep["red_flags"]["off_list_found"] == "2 of 2"


def test_method_scores_differ_when_retrieval_misses(full_run):
    rep = score(full_run, yaml.safe_load(KEY.read_text()))
    a = rep["methods"]["A"]["evidence_pages_found"]
    assert a.startswith("12 of 12")
    for m in "BC":
        assert "of 12" in rep["methods"][m]["evidence_pages_found"]


def test_false_flags_drop_precision_below_the_bar(full_run):
    bad = json.loads(json.dumps(full_run, default=list))
    for i in range(2):  # 10 real of 12 = 83%, under the 90% bar
        bad["red_flags"].append({"flag_id": f"Fx{i}", "verified": True, "file": "10_shareholder_register.pdf",
                                 "page": 1, "quote": "Total | 10,000,000 | 100.0", "advice_words": []})
    rep = score(bad, yaml.safe_load(KEY.read_text()))
    assert rep["methods"]["A"]["verdict"].startswith("KILL") and "precision" in rep["methods"]["A"]["verdict"]


def test_one_unverified_item_triggers_kill(full_run):
    bad = json.loads(json.dumps(full_run, default=list))
    bad["red_flags"][0]["verified"] = False
    bad["red_flags"][0]["reason"] = "quote not on cited page"
    rep = score(bad, yaml.safe_load(KEY.read_text()))
    assert "lineage" in rep["methods"]["A"]["verdict"]


def test_cache_replays_without_the_model(tmp_path, room):
    live = CachedLLM(FakeLLM(), cache_dir=tmp_path)
    first = run(live, methods=("A",), room=room)
    class Dead:
        name = "fake"
        def json(self, p): raise RuntimeError("no network")
        def embed(self, t): raise RuntimeError("no network")
    replay = run(CachedLLM(Dead(), cache_dir=tmp_path, offline=True), methods=("A",), room=room)
    assert [r["status"] for r in first["results"]["A"]] == [r["status"] for r in replay["results"]["A"]]
    assert all(c["cache_hit"] for c in replay["calls"])
