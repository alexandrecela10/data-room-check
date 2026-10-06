"""Build the case study page from the snapshot, so every number on it traces to data.

    .venv/bin/python -m case_study.build_page <out_dir>

Writes <out_dir>/index.html and the page images it needs into <out_dir>/img/.
Demo screenshots come from case_study/capture.py into the same img/ folder.
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

import markdown
import pdfplumber

from dataroom.ingest import ROOM, ingest_room

ROOT = Path(__file__).resolve().parent.parent
SNAP = json.loads((ROOT / "case_study" / "data" / "snapshot.json").read_text())
M = SNAP["methods"]
KEY = SNAP["answer_key"]

SHORT = {
    "02": "Audited accounts 2024", "03": "Audited accounts 2025", "04": "Monthly accounts 2025",
    "05": "Revenue per customer", "06": "Contract: largest customer", "07": "Contract: customer 2",
    "08": "Contract: customer 3", "09": "Bank loan", "10": "Who owns the company", "11": "Board minutes",
    "12": "Law firm letter", "13": "Office lease",
}
UNITS = [u for u in ingest_room(ROOM) if not u.file.startswith("01_")]
REV_KEY = next(k for k in KEY["slide_claims"] if k["id"] == "V4")
REV_PAGES = {(e["file"], e["page"]) for e in REV_KEY["evidence"]}


def esc(s) -> str:
    return html.escape(str(s))


def revenue(v: str, m: str) -> dict:
    return next(c for c in SNAP["runs"][v][m]["claims"] if "Revenue" in c["quote"])


def room_grid(claim: dict, label: str) -> str:
    """The data room as 64 passage cells, one row per file. Lit = the AI read it."""
    read = set(claim["retrieved"])
    rows, files = [], sorted({u.file for u in UNITS})
    for f in files:
        cells = []
        for u in [u for u in UNITS if u.file == f]:
            cls = "cell" + (" lit" if u.unit_id in read else "") + (" key" if (u.file, u.page) in REV_PAGES else "")
            tip = f"{SHORT[f[:2]]}, page {u.page}: {u.text[:90]}"
            cells.append(f'<span class="{cls}" title="{esc(tip)}"></span>')
        rows.append(f'<div class="row"><span class="fname">{SHORT[f[:2]]}</span>{"".join(cells)}</div>')
    n = len(read)
    hit = len({(u.file, u.page) for u in UNITS if u.unit_id in read} & REV_PAGES)
    return (f'<figure class="room"><figcaption><strong>{esc(label)}</strong> · read {n} of {len(UNITS)} passages · '
            f'right pages {hit} of {len(REV_PAGES)}</figcaption>{"".join(rows)}</figure>')


def bars(values: dict[str, float], fmt: str, title: str) -> str:
    """Horizontal bars, one series, labelled directly; <title> gives the hover tooltip."""
    w, rh, lw = 560, 34, 170
    top = max(values.values())
    out = [f'<figure class="chart"><figcaption>{esc(title)}</figcaption>'
           f'<svg viewBox="0 0 {w} {rh * len(values) + 8}" role="img" aria-label="{esc(title)}">']
    for i, (m, v) in enumerate(values.items()):
        y = i * rh + 4
        bw = max(2, (w - lw - 70) * v / top)
        label = fmt.format(v)
        out.append(f'<text x="0" y="{y + 20}" class="lab">{esc(m + ": " + M[m])}</text>'
                   f'<g><title>{esc(M[m])}: {esc(label)}</title>'
                   f'<rect x="{lw}" y="{y + 6}" width="{bw:.1f}" height="20" rx="4" class="bar"/></g>'
                   f'<text x="{lw + bw + 8:.1f}" y="{y + 20}" class="val">{esc(label)}</text>')
    out.append("</svg></figure>")
    return "".join(out)


def page_png(file: str, page: int, quote_first_cell: str, out: Path):
    with pdfplumber.open(ROOM / file) as pdf:
        p = pdf.pages[page - 1]
        im = p.to_image(resolution=110)
        hits = p.search(quote_first_cell)[:1]
        for h in hits:
            im.draw_rect((p.bbox[0] + 15, h["top"] - 3, p.bbox[2] - 15, h["bottom"] + 3),
                         fill=(255, 214, 0, 70), stroke=(214, 120, 0), stroke_width=2)
        im.save(str(out))


def verdict_cell(r: dict) -> str:
    v = r["values"]
    ok = r["verdict"] == "PASS"
    return (f'<td><span class="chip {"pass" if ok else "fail"}">{"Pass" if ok else "Fail"}</span> '
            f'<span class="dim">P {v["precision"]:.0%} · R {v["recall"]:.0%} · L {v["lineage"]:.0%}</span></td>')


def tree_html(m: str) -> str:
    """Depth-first from the root, so a child never prints before its parent."""
    nodes = SNAP["trees"][m]
    ids = {n["id"] for n in nodes}
    kids: dict = {}
    for n in nodes:
        kids.setdefault(n["parent"] if n["parent"] in ids else None, []).append(n)
    out = []

    def walk(parent, depth):
        for n in kids.get(parent, []):
            out.append(f'<div style="padding-left:{depth * 18}px"><span class="type">{n["type"].lower()}</span> '
                       f'{esc(n["name"])}</div>')
            walk(n["id"], depth + 1)
    walk(None, 0)
    return "".join(out)


def build(out: Path):
    img = out / "img"
    img.mkdir(parents=True, exist_ok=True)
    page_png("04_management_accounts_fy2025.pdf", 12, "Total revenue FY2025", img / "page-monthly-12.png")
    page_png("03_audited_accounts_fy2025.pdf", 3, "Revenue", img / "page-audited-3.png")

    b = SNAP["benchmark"]
    runs = SNAP["runs"]
    rf = SNAP["red_flags"]["v3"]["score"]
    secs = {m: round(x["steps"].get("find-evidence", {}).get("seconds", 0)
                     + x["steps"].get("pick-sections", {}).get("seconds", 0), 1) for m, x in b.items()}
    index_secs = round(b["B"]["steps"]["embed-passages"]["seconds"])
    grid_rows = "".join(f'<tr><td>{v}</td>{"".join(verdict_cell(runs[v][m]) for m in M)}</tr>' for v in ("v1", "v2", "v3"))
    bench_rows = "".join(
        f'<tr><td>{m}: {esc(M[m])}</td><td>{x["passages_shown_avg"]}</td><td>{x["tokens_in"]:,}</td>'
        f'<td>{x["tokens_out"]:,}</td><td>${x["cost_usd_10_claims"]:.3f}</td><td>{secs[m]}</td></tr>'
        for m, x in b.items())

    fields = dict(
        n_units=len(UNITS),
        grids="".join(room_grid(revenue("v3", m), f"{m}: {M[m]}") for m in M),
        lane_b1=room_grid(revenue("v1", "B"), "RAG, prompt v1: Confirmed (wrong)"),
        lane_a1=room_grid(revenue("v1", "A"), "One model call, prompt v1: Conflict (right)"),
        lane_b3=room_grid(revenue("v3", "B"), "RAG, prompt v3: Conflict (right)"),
        bars_passages=bars({m: x["passages_shown_avg"] for m, x in b.items()}, "{:g}",
                           "Passages the AI reads per slide number"),
        bars_cost=bars({m: x["cost_usd_10_claims"] for m, x in b.items()}, "${:.3f}",
                       "AI cost to check all 10 slide numbers (USD)"),
        bench_rows=bench_rows, grid_rows=grid_rows, index_secs=index_secs,
        price_in=SNAP["prices"]["input"], price_out=SNAP["prices"]["output"],
        tree_a=tree_html("A"), tree_b=tree_html("B"), tree_c=tree_html("C"), tree_d=tree_html("D"),
        flags_found=rf["found"], off_list=rf["off_list_found"],
        cost_min=f'{min(x["cost_usd_10_claims"] for x in b.values()):.2f}',
        cost_max=f'{max(x["cost_usd_10_claims"] for x in b.values()):.2f}',
    )
    docs = ROOT / "case_study" / "docs"
    for k, f in (("opp_doc", "opportunity-assessment.md"), ("prd_doc", "prd.md")):
        fields[k] = markdown.markdown((docs / f).read_text(), extensions=["tables"])
    page = TEMPLATE
    for k, v in fields.items():  # [[name]] placeholders: CSS braces and $ signs stay literal
        page = page.replace(f"[[{k}]]", str(v))
    assert "[[" not in page, page[page.index("[["):page.index("[[") + 40]
    (out / "index.html").write_text(page)
    print("wrote", out / "index.html")


TEMPLATE = (Path(__file__).parent / "page_template.html").read_text()

if __name__ == "__main__":
    build(Path(sys.argv[1]))
