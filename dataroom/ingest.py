"""Split every data room PDF into text units with full lineage.

A unit is one section of one page (prose) or one whole table. Each unit keeps:
unit_id, file name, file SHA-256, page number (1-based), section path and kind.
That lineage is what lets code later prove a quote sits on the page the AI cited.

Sections come from font size: the generator writes document titles at 18pt and
section headings at 13pt (see scripts/make_data_room.py). A heading stays the
current section until the next heading, including across page breaks.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, asdict
from pathlib import Path

import duckdb
import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
ROOM = ROOT / "data" / "room"
DB = ROOT / "data" / "dataroom.duckdb"

TITLE_MIN_SIZE = 16
HEADING_MIN_SIZE = 12


@dataclass
class Unit:
    unit_id: str
    file: str
    file_sha256: str
    page: int
    section_path: str
    kind: str  # "text" or "table"
    text: str


def normalise(text: str) -> str:
    """Collapse whitespace so quotes match regardless of PDF line breaks."""
    return re.sub(r"\s+", " ", text).strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lines(words):
    """Group words into lines by their top coordinate, keeping font size."""
    lines = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if lines and abs(lines[-1]["top"] - w["top"]) < 2:
            lines[-1]["text"] += " " + w["text"]
        else:
            lines.append({"top": w["top"], "size": w["size"], "text": w["text"]})
    return lines


def _inside(word, bbox) -> bool:
    x0, top, x1, bottom = bbox
    return x0 <= word["x0"] and word["x1"] <= x1 and top <= word["top"] and word["bottom"] <= bottom


def ingest_file(path: Path) -> list[Unit]:
    digest = sha256(path)
    units: list[Unit] = []
    title, heading = "", ""
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables()
            words = page.extract_words(extra_attrs=["size"])
            prose = [w for w in words if not any(_inside(w, t.bbox) for t in tables)]

            # Each block is (top, section_path, kind, text). Prose lines join the
            # block of the current heading; each table is its own block, kept whole.
            blocks: list[list] = []
            for line in _lines(prose):
                if line["size"] >= TITLE_MIN_SIZE:
                    title = line["text"] if not blocks or blocks[-1][2] != "title" else title + " " + line["text"]
                    blocks.append([line["top"], title, "title", ""])
                    continue
                if line["size"] >= HEADING_MIN_SIZE:
                    heading = line["text"]
                    blocks.append([line["top"], f"{title} > {heading}", "text", ""])
                    continue
                if not blocks or blocks[-1][2] != "text":
                    blocks.append([line["top"], f"{title} > {heading}" if heading else title, "text", ""])
                blocks[-1][3] += " " + line["text"]
            for tb in tables:
                rows = tb.extract()
                text = " ; ".join(" | ".join(c or "" for c in row) for row in rows)
                # A table belongs to the last heading above it on this page.
                above = [b for b in blocks if b[0] < tb.bbox[1] and b[2] != "title"]
                path_ = above[-1][1] if above else f"{title} > {heading}"
                blocks.append([tb.bbox[1], path_, "table", text])

            n = 0
            for top, section, kind, text in sorted(blocks, key=lambda b: b[0]):
                text = normalise(text)
                if kind == "title" or not text:
                    continue
                n += 1
                units.append(Unit(
                    unit_id=f"{path.stem}:p{page_no}:u{n}",
                    file=path.name, file_sha256=digest, page=page_no,
                    section_path=section, kind=kind, text=text,
                ))
    return units


def ingest_room(room: Path = ROOM) -> list[Unit]:
    units: list[Unit] = []
    for path in sorted(room.glob("*.pdf")):
        units.extend(ingest_file(path))
    return units


def page_text(units: list[Unit], file: str, page: int) -> str:
    """All unit text on one page, in order. Used to check quotes."""
    return " ".join(u.text for u in units if u.file == file and u.page == page)


def save(units: list[Unit], db: Path = DB) -> None:
    con = duckdb.connect(str(db))
    con.execute("DROP TABLE IF EXISTS units")
    con.execute("""CREATE TABLE units (unit_id TEXT PRIMARY KEY, file TEXT, file_sha256 TEXT,
                   page INTEGER, section_path TEXT, kind TEXT, text TEXT)""")
    con.executemany("INSERT INTO units VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [tuple(asdict(u).values()) for u in units])
    con.close()


if __name__ == "__main__":
    us = ingest_room()
    save(us)
    print(f"{len(us)} units from {len({u.file for u in us})} files, "
          f"{len({(u.file, u.page) for u in us})} pages -> {DB.relative_to(ROOT)}")
