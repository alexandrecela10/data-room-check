"""Build step 1: the data room, the answer key and page lineage."""

import ast
from pathlib import Path

import pytest
import yaml

from dataroom.ingest import ROOM, ingest_room, normalise, page_text, sha256

ROOT = Path(__file__).resolve().parent.parent
KEY = yaml.safe_load((ROOT / "eval" / "answer_key.yaml").read_text())


@pytest.fixture(scope="module")
def units():
    return ingest_room()


def test_room_has_13_files_and_10_slides():
    files = sorted(ROOM.glob("*.pdf"))
    assert len(files) == 13
    import pdfplumber
    with pdfplumber.open(ROOM / KEY["deck_file"]) as pdf:
        assert len(pdf.pages) == 10


def test_every_page_has_at_least_one_unit(units):
    import pdfplumber
    for path in ROOM.glob("*.pdf"):
        with pdfplumber.open(path) as pdf:
            for n in range(1, len(pdf.pages) + 1):
                assert any(u.file == path.name and u.page == n for u in units), f"{path.name} p.{n} has no unit"


def test_every_unit_has_full_lineage(units):
    hashes = {p.name: sha256(p) for p in ROOM.glob("*.pdf")}
    ids = [u.unit_id for u in units]
    assert len(ids) == len(set(ids)), "unit IDs must be unique"
    for u in units:
        assert u.file_sha256 == hashes[u.file]
        assert u.page >= 1 and u.section_path and u.text
        assert u.unit_id.startswith(Path(u.file).stem + f":p{u.page}:")


def test_unit_ids_are_stable_across_runs(units):
    assert [u.unit_id for u in units] == [u.unit_id for u in ingest_room()]


def test_tables_stay_whole(units):
    top10 = [u for u in units if u.kind == "table" and "Halden Retail Group | 11.22" in u.text]
    assert len(top10) == 1
    assert "Total | 36.20" in top10[0].text


def test_sections_follow_headings(units):
    u = next(u for u in units if "Change of control" in u.text)
    assert u.section_path.endswith("14. Mandatory prepayment")


def _quotes():
    deck = KEY["deck_file"]
    for c in KEY["slide_claims"]:
        yield c["id"], deck, c["slide"], c["claim"]
        for ev in c["evidence"]:
            yield c["id"], ev["file"], ev["page"], ev["quote"]
    for f in KEY["red_flags"]:
        for ev in f["evidence"]:
            yield f["id"], ev["file"], ev["page"], ev["quote"]


@pytest.mark.parametrize("item_id,file,page,quote", list(_quotes()))
def test_answer_key_quote_is_on_its_page(units, item_id, file, page, quote):
    assert normalise(quote) in page_text(units, file, page), f"{item_id}: quote not on {file} p.{page}"


def test_answer_key_counts():
    claims = KEY["slide_claims"]
    assert sum(c["status"] != "confirmed" for c in claims) == 4
    assert sum(c["status"] == "confirmed" for c in claims) == 6
    flags = KEY["red_flags"]
    assert sum(not f["on_list"] for f in flags) == 2


def test_red_flag_checks_cover_answer_key():
    checks = {c["id"] for c in yaml.safe_load((ROOT / "config" / "red_flags.yaml").read_text())["checks"]}
    for f in KEY["red_flags"]:
        assert f["check"] in checks
    for c in KEY["expected_clear"]:
        assert c["check"] in checks


def test_pipeline_never_reads_the_answer_key():
    """Only eval/ and tests/ may touch answer_key.yaml. show_key is a reviewer tool."""
    for path in (ROOT / "dataroom").glob("*.py"):
        if path.name == "show_key.py":
            continue
        assert "answer_key" not in path.read_text(), f"{path.name} mentions the answer key"
