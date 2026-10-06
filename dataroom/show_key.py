"""Print every answer-key item with the page text that proves it.

Run: .venv/bin/python -m dataroom.show_key
This is the manual check for build step 1: each line should say FOUND.
"""

from pathlib import Path

import yaml

from dataroom.ingest import ingest_room, normalise, page_text

ROOT = Path(__file__).resolve().parent.parent


def main():
    key = yaml.safe_load((ROOT / "eval" / "answer_key.yaml").read_text())
    units = ingest_room()
    deck = key["deck_file"]
    items = [("slide", c) for c in key["slide_claims"]] + [("flag", f) for f in key["red_flags"]]
    for kind, item in items:
        head = (f"{item['id']}  slide {item['slide']}: {item['claim']}  -> {item['status']}"
                if kind == "slide" else f"{item['id']}  [{item['check']}] {item['finding']}")
        print(head)
        if kind == "slide":
            ok = normalise(item["claim"]) in page_text(units, deck, item["slide"])
            print(f"    {'FOUND' if ok else 'MISSING'}  {deck} p.{item['slide']}")
        for ev in item["evidence"]:
            ok = normalise(ev["quote"]) in page_text(units, ev["file"], ev["page"])
            print(f"    {'FOUND' if ok else 'MISSING'}  {ev['file']} p.{ev['page']}: \"{ev['quote']}\"")
        print()


if __name__ == "__main__":
    main()
