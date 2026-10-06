"""Data Room Check: a guided demo, written to you, the analyst.

The example deck replays stored results (no key, no cost). An edited or uploaded
deck is checked live with all four methods, on the owner's Gemini key, capped.
Run: .venv/bin/streamlit run app.py
"""

from __future__ import annotations

import io
import json
import os
from datetime import date
from functools import lru_cache
from pathlib import Path

import pdfplumber
import streamlit as st
import yaml
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parent
ROOM = ROOT / "data" / "room"
DECK = ROOM / "01_investor_presentation.pdf"
SNAP = json.loads((ROOT / "case_study" / "data" / "snapshot.json").read_text())
FACTS = yaml.safe_load((ROOT / "data" / "facts.yaml").read_text())
KEY = SNAP["answer_key"]
METHODS = SNAP["methods"]
PRICE = SNAP["prices"]

SESSION_CAP = 3   # live checks per visitor
MAX_PAGES = 15    # uploaded deck size limits
MAX_BYTES = 5 * 1024 * 1024
DAILY_CAP = 30    # live checks per day, all visitors

STATUS = {
    "confirmed": ("Confirmed", "green", "The data room shows the same number."),
    "contradicted": ("Contradicted", "red", "The data room shows a different number."),
    "conflict": ("Conflict", "orange", "Two documents disagree. Both are shown, the tool doesn't pick."),
    "not_found": ("Not found", "gray", "Nothing in the data room states it. The tool says so instead of guessing."),
    "unverified": ("Unverified", "violet", "The AI cited something code couldn't find on the page, so it isn't shown as fact."),
}
CHECK_NAMES = {
    "change_of_control": "Change of owner clause", "legal_claims": "Legal claim",
    "contracts_ending": "Contract ending soon", "unpaid_taxes": "Unpaid taxes",
    "covenant_breach": "Loan condition broken", "customer_concentration": "One customer over 20%",
    "other": "Not on the list",
}
METHOD_HOW = {
    "A": "Sends the whole data room to the AI for every number. No search.",
    "B": "Searches first (RAG): the 8 closest passages by meaning and keywords, at most 2 per file.",
    "C": "Reads the table of contents first (PageIndex): the AI picks up to 6 sections, then reads them.",
    "D": "Both: search keeps the 3 closest files, then the AI walks only their tables of contents.",
}
FILES = {
    "01_investor_presentation.pdf": "The seller's deck",
    "02_audited_accounts_fy2024.pdf": "Audited accounts, 2024",
    "03_audited_accounts_fy2025.pdf": "Audited accounts, 2025",
    "04_management_accounts_fy2025.pdf": "Monthly accounts, 2025 (prepared by management)",
    "05_customer_revenue_analysis.pdf": "Revenue per customer",
    "06_contract_halden_retail.pdf": "Contract: largest customer",
    "07_contract_corvo_home.pdf": "Contract: second customer",
    "08_contract_pellam_outdoor.pdf": "Contract: third customer",
    "09_senior_facility_agreement.pdf": "Bank loan agreement",
    "10_shareholder_register.pdf": "Who owns the company",
    "11_board_minutes.pdf": "Board meeting minutes",
    "12_letter_hollis_grant.pdf": "Letter from a law firm",
    "13_office_lease.pdf": "Office lease",
}
# Slide editor fields: facts.yaml deck key -> (label, step, format)
EDITABLE = {
    "revenue_fy2025": ("Revenue FY2025 ($M), slide 4", 0.1, "%.1f"),
    "gross_margin_pct": ("Gross margin (%), slide 5", 1, "%d"),
    "revenue_kept_pct": ("Net revenue retention (%), slide 5", 1, "%d"),
    "customers": ("Customers, slide 6", 1, "%d"),
    "largest_customer_pct": ("Largest customer (% of revenue), slide 6", 1, "%d"),
    "employees": ("Employees, slide 8", 1, "%d"),
    "loan_musd": ("Senior term loan ($M), slide 9", 0.1, "%.1f"),
}
STEPS = ["1. Pick your deck", "2. Meet your data room", "3. Run the check", "4. Read your results",
         "5. Look under the hood", "6. How we got here"]

st.set_page_config(page_title="Data Room Check", layout="wide")
ss = st.session_state
ss.setdefault("step", STEPS[0])
if "goto" in ss:  # set by buttons; applied before the step radio renders
    ss.step = ss.pop("goto")
ss.setdefault("deck_choice", "example")
ss.setdefault("deck_bytes", DECK.read_bytes())
ss.setdefault("results", None)
ss.setdefault("live_used", 0)


# ------------------------------------------------------------------ helpers

@st.cache_resource
def daily_counter() -> dict:
    return {}


def esc(text: str) -> str:
    """Streamlit renders $...$ as LaTeX; money must show as text."""
    return str(text).replace("$", "\\$")


def md(text: str, **kw):
    st.markdown(esc(text), **kw)


def cap(text: str, **kw):
    st.caption(esc(text), **kw)


def badge(status: str) -> str:
    label, color, _ = STATUS.get(status, (status, "gray", ""))
    return f":{color}-background[{label}]"


@lru_cache(maxsize=256)
def _render(pdf_bytes: bytes, page: int, quotes: tuple[str, ...], resolution: int = 100):
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        p = pdf.pages[page - 1]
        im = p.to_image(resolution=resolution)
        for q in quotes:
            for box in _find(p, q):
                im.draw_rect(box, fill=(255, 214, 0, 70), stroke=(214, 120, 0), stroke_width=2)
        return im.original


@lru_cache(maxsize=32)
def _file_bytes(file: str) -> bytes:
    return (ROOM / file).read_bytes()


def page_image(file: str, page: int, quotes=(), resolution=100):
    data = ss.deck_bytes if file.startswith("01_") else _file_bytes(file)
    return _render(data, page, tuple(quotes), resolution)


def page_count(data: bytes) -> int:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return len(pdf.pages)


def _find(p, quote: str) -> list[tuple]:
    """Boxes for a quote. Table rows ("Revenue | 36.2") box the whole row."""
    if "|" in quote:
        first = quote.split("|")[0].strip()
        hits = p.search(first) if first else []
        return [(p.bbox[0] + 15, h["top"] - 2, p.bbox[2] - 15, h["bottom"] + 2) for h in hits[:1]]
    for attempt in (quote, " ".join(quote.split()[:7]), " ".join(quote.split()[:4])):
        hits = p.search(attempt) if attempt else []
        if hits:
            return [(h["x0"] - 2, h["top"] - 2, h["x1"] + 2, h["bottom"] + 2) for h in hits[:1]]
    return []


def key_claim_for(quote: str, slide: int) -> dict | None:
    for k in KEY["slide_claims"]:
        if k["slide"] == slide and fuzz.partial_ratio(k["claim"], quote) >= 85:
            return k
    return None


def stored_results() -> dict:
    return {
        "source": "stored",
        "claims": {m: SNAP["runs"]["v3"][m]["claims"] for m in METHODS},
        "red_flags": SNAP["red_flags"]["v3"]["findings"],
        "cost": {m: {"tokens_in": b["tokens_in"], "tokens_out": b["tokens_out"], "cost_usd": b["cost_usd_10_claims"],
                     "seconds": round(b["steps"].get("find-evidence", {}).get("seconds", 0)
                                      + b["steps"].get("pick-sections", {}).get("seconds", 0), 1)}
                 for m, b in SNAP["benchmark"].items()},
    }


def show_evidence(ev: list[dict]):
    for e in ev:
        tick = "Code found this quote on this page." if e["verified"] else f"Code rejected it: {e['reason']}."
        role = {"operand": " (used in the calculation)", "context": " (context)"}.get(e.get("role"), "")
        md(f"**{FILES.get(e['file'], e['file'])}, page {e['page']}**{role}  \n> {e['quote']}  \n{tick}")


def next_button(label: str, target: str):
    if st.button(label, type="primary", key=f"next-{target}"):
        ss.goto = target
        st.rerun()


def live_available() -> tuple[bool, str]:
    if os.environ.get("DRC_FAKE_LLM") == "1":
        return True, ""
    try:
        from dataroom.llm import load_env
        load_env()
    except Exception:
        pass
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        return False, "Live checks are switched off on this copy of the demo (no model key)."
    today = daily_counter().get(str(date.today()), 0)
    if today >= DAILY_CAP:
        return False, f"Today's {DAILY_CAP} live checks are used up. Come back tomorrow, or explore the example deck."
    if ss.live_used >= SESSION_CAP:
        return False, f"You've used your {SESSION_CAP} live checks. The example deck still works."
    return True, ""


# ------------------------------------------------------------------ layout

with st.sidebar:
    md("### Your journey")
    st.radio("Step", STEPS, key="step", label_visibility="collapsed")
    st.divider()
    deck_label = {"example": "Example deck", "edited": "Your edited deck", "uploaded": "Your uploaded deck"}
    md(f"**Deck:** {deck_label[ss.deck_choice]}")
    md(f"**Checked:** {'yes, ' + ss.results['source'] if ss.results else 'not yet'}")
    cap("Fintech A, its documents, people and numbers are fictional.")

st.title("Data Room Check")
md(
    "You're an analyst at a family office. The family is putting money into **Fintech A**, alongside a "
    "bigger investor who leads the deal. You have 2 to 3 weeks to read the company's documents, called the "
    "**data room**. The seller's slides (the **deck**) are written to sell. Your job: find what's wrong or missing "
    "before the family decides. This tool does the reading with you. **It states facts. You decide.**"
)

# ------------------------------------------------------------------ 1. deck

if ss.step == STEPS[0]:
    st.header("Step 1. Pick the deck you want to check")
    choice = st.radio(
        "Which deck?",
        ["example", "edited", "uploaded"],
        format_func={"example": "The Fintech A deck (the example: instant, already checked)",
                     "edited": "The Fintech A deck, with numbers you change (checked live)",
                     "uploaded": "Upload your own deck about Fintech A, as a PDF (checked live)"}.get,
        index=["example", "edited", "uploaded"].index(ss.deck_choice),
    )
    if choice != ss.deck_choice:
        ss.deck_choice, ss.results = choice, None
        ss.deck_bytes = DECK.read_bytes()

    if choice == "edited":
        md("Change any number, then build your deck. **Try this:** set the largest customer to 31%. "
                    "That's what the data room says. Does it flip to Confirmed?")
        with st.form("edit"):
            cols = st.columns(2)
            vals = {}
            for i, (k, (label, step, fmt)) in enumerate(EDITABLE.items()):
                v = FACTS["deck"][k]
                vals[k] = cols[i % 2].number_input(label, value=float(v) if step < 1 else int(v), step=step, format=fmt)
            if st.form_submit_button("Build my deck"):
                from scripts.make_data_room import deck as build_deck
                out = ROOT / "data" / ".edited_deck.pdf"
                build_deck(vals, out)
                ss.deck_bytes, ss.results = out.read_bytes(), None
                st.success("Your deck is built. Scroll down to see it.")
    elif choice == "uploaded":
        md("Your deck is checked against **Fintech A's** documents. A deck about another company will "
                    "mostly come back Not found. That's the tool refusing to guess.")
        cap("Your deck's text is sent to Google Gemini and logged for debugging. Don't upload anything "
                   f"confidential. Up to {MAX_PAGES} pages, 5 MB.")
        up = st.file_uploader("Your deck (PDF)", type=["pdf"])
        if up is not None:
            data = up.getvalue()
            if len(data) > MAX_BYTES:
                st.error("That file is over 5 MB.")
            elif page_count(data) > MAX_PAGES:
                st.error(f"That deck has more than {MAX_PAGES} pages.")
            else:
                ss.deck_bytes, ss.results = data, None

    st.subheader("This is the deck you'll check")
    n = page_count(ss.deck_bytes)
    for row in range(0, n, 5):
        cols = st.columns(5)
        for i, col in enumerate(cols):
            if row + i < n:
                col.image(page_image("01_deck", row + i + 1, (), 60), caption=f"Slide {row + i + 1}")
    next_button("Next: meet your data room", STEPS[1])

# ------------------------------------------------------------------ 2. data room

elif ss.step == STEPS[1]:
    st.header("Step 2. Meet your data room")
    md("These 13 files are what the seller shared. A real data room holds hundreds. "
                "Open any page: this is what you'd read by hand.")
    left, right = st.columns([2, 3])
    with left:
        for f, desc in list(FILES.items())[1:]:
            md(f"- **{desc}** ({page_count(_file_bytes(f))} pages)")
    with right:
        f = st.selectbox("Open a file", list(FILES)[1:], format_func=FILES.get)
        pg = st.number_input("Page", 1, page_count(_file_bytes(f)), 1)
        st.image(page_image(f, int(pg)), width="stretch")
    next_button("Next: run the check", STEPS[2])

# ------------------------------------------------------------------ 3. run

elif ss.step == STEPS[2]:
    st.header("Step 3. Run the check")
    md(
        "Here's what happens when you press the button:\n"
        "1. **The AI reads your deck** and lists every number someone could check.\n"
        "2. **Four search methods** each pick which pages the AI reads to find the evidence. They run side by side.\n"
        "3. **Code checks every answer:** the quote must be on the cited page, and the number in the quote. "
        "Code does the arithmetic and decides the status, never the AI.\n"
        "4. **The AI reads every page of every file** against 7 red flag checks. No search here, so nothing is skipped."
    )
    if ss.deck_choice == "example":
        st.info("The example deck was checked already. You'll see the stored results, instantly and for free.")
        if st.button("Show the results", type="primary"):
            ss.results = stored_results()
            ss.goto = STEPS[3]
            st.rerun()
    else:
        ok, why = live_available()
        md(f"Live checks left for you: **{max(0, SESSION_CAP - ss.live_used)} of {SESSION_CAP}**. "
                    "A check takes 1 to 2 minutes. Numbers you didn't change come from the cache, so they're fast.")
        if not ok:
            st.warning(why)
        elif st.button("Check my deck", type="primary"):
            from dataroom.live import check_deck
            bars = {m: st.progress(0.0, text=f"{m}: {METHODS[m]}") for m in METHODS}

            def progress(m, done, total):
                bars[m].progress(done / total if total else 1.0, text=f"{m}: {METHODS[m]} ({done} of {total} numbers)")

            with st.spinner("Reading your deck..."):
                try:
                    ss.results = check_deck(ss.deck_bytes, PRICE, progress)
                except Exception as e:  # show a plain message, keep the session usable
                    st.error(f"The check failed: {e}")
                    ss.results = None
            if ss.results:
                ss.live_used += 1
                counter = daily_counter()
                counter[str(date.today())] = counter.get(str(date.today()), 0) + 1
                ss.goto = STEPS[3]
                st.rerun()

# ------------------------------------------------------------------ 4. results

elif ss.step == STEPS[3]:
    st.header("Step 4. Read your results")
    res = ss.results
    if not res:
        st.info("Run the check first.")
        next_button("Go to step 3", STEPS[2])
        st.stop()
    method = st.radio("Show the results from method", list(METHODS), horizontal=True,
                      format_func=lambda m: f"{m}: {METHODS[m]}", key="m1")
    cap(METHOD_HOW[method] + " Step 5 compares all four.")
    claims = res["claims"][method]
    cols = st.columns(5)
    for col, (s, (label, _, _)) in zip(cols, STATUS.items()):
        col.metric(label, sum(c["status"] == s for c in claims))

    st.subheader("The numbers in your deck")
    for c in claims:
        extra = f" Code computed **{c['computed_value']}%**." if c.get("computed_value") is not None else ""
        md(f"Slide {c['slide']}: \"{c['quote']}\" {badge(c['status'])}{extra}")
    if not claims:
        st.warning("The AI found no checkable numbers in this deck.")
        st.stop()

    pick = st.selectbox("Open one. Where's the proof?", claims,
                        format_func=lambda c: f"Slide {c['slide']}: {c['quote']}", key="c1")
    left, right = st.columns([2, 3])
    with left:
        md(f"### {badge(pick['status'])}")
        md(STATUS[pick["status"]][2])
        if pick.get("label") == "computed":
            md("**Computed:** the AI found the figures, then code did the arithmetic.")
        show_evidence(pick["evidence"])
        k = key_claim_for(pick["quote"], pick["slide"]) if ss.deck_choice == "example" else None
        if k:
            with st.expander("Check it against the answer key"):
                md(f"The answer key, written before the first run, says **{k['status']}**"
                            + (f" (true value {k['true_value']})." if k.get("true_value") else "."))
    with right:
        st.image(page_image("01_deck", int(pick["slide"]), (pick["quote"],), 110), caption=f"Your deck, slide {pick['slide']}", width="stretch")
        for f, pg in sorted({(e["file"], e["page"]) for e in pick["evidence"] if e["verified"]}):
            quotes = tuple(e["quote"] for e in pick["evidence"] if e["file"] == f and e["page"] == pg)
            st.image(page_image(f, pg, quotes), caption=f"{FILES.get(f, f)}, page {pg}", width="stretch")

    st.subheader("Red flags, from every page of every file")
    md("Nobody asked about these. The AI read all 13 files against the same 7 checks, and code "
                "confirmed each quote is on its page.")
    for fl in [f for f in res["red_flags"] if f.get("verified")]:
        with st.expander(esc(f"{CHECK_NAMES.get(fl.get('check_id'), fl.get('check_id'))}: {fl.get('observation')}")):
            md(f"**{FILES.get(fl['file'], fl['file'])}, page {fl['page']}**  \n> {fl['quote']}")
            st.image(page_image(fl["file"], fl["page"], (fl["quote"],)), width="stretch")
    next_button("Next: look under the hood", STEPS[4])

# ------------------------------------------------------------------ 5. under the hood

elif ss.step == STEPS[4]:
    st.header("Step 5. Look under the hood")
    res = ss.results or stored_results()
    md("All four methods use the same AI and the same code checks. **Only the way they pick what the "
                "AI reads changes.** That choice decides the cost, the speed, and what can be missed.")
    claims_a = res["claims"]["A"]
    pick = st.selectbox("Pick a number from your deck", claims_a,
                        format_func=lambda c: f"Slide {c['slide']}: {c['quote']}", key="c2")
    k = key_claim_for(pick["quote"], pick["slide"])
    want = {(e["file"], e["page"]) for e in k["evidence"]} if k else set()
    cols = st.columns(4)
    for col, m in zip(cols, METHODS):
        r = next((c for c in res["claims"][m] if c["quote"] == pick["quote"]), None)
        with col:
            md(f"#### {m}: {METHODS[m]}")
            cap(METHOD_HOW[m])
            if r is None:
                md("Not checked by this method.")
                continue
            md(badge(r["status"]))
            st.metric("Passages the AI read", len(r["retrieved"]))
            if want:
                shown = {(u.split(":")[0] + ".pdf", int(u.split(":")[1][1:])) for u in r["retrieved"]}
                st.metric("Right pages among them", f"{len(want & shown)} of {len(want)}")
            with st.expander("Which passages"):
                for u in r["retrieved"]:
                    f, p, _ = u.split(":")
                    md(f"- {FILES.get(f + '.pdf', f)}, {p.replace('p', 'page ')}")

    st.subheader("What each method cost on your deck" if res["source"] == "live" else "What each method cost (10 numbers)")
    rows = [{"Method": f"{m}: {METHODS[m]}", "AI tokens in": c["tokens_in"], "AI tokens out": c["tokens_out"],
             "Cost (USD)": c["cost_usd"], "AI time, s": c["seconds"]} for m, c in res["cost"].items() if m in METHODS]
    st.dataframe(rows, hide_index=True, width="stretch")
    cap(f"Price: ${PRICE['input']} per million tokens in, ${PRICE['output']} out (from Langfuse). "
               + ("Numbers you didn't change came from the cache and cost nothing." if res["source"] == "live"
                  else "From one fresh run with every call live."))

    st.subheader("The steps, as traced in Langfuse (revenue claim, example deck)")
    tcols = st.columns(4)
    for col, m in zip(tcols, METHODS):
        nodes = SNAP["trees"].get(m, [])
        dot = ["digraph{rankdir=TB;node[shape=box,style=rounded,fontname=Helvetica,fontsize=10];"]
        for n in nodes:
            # Structure only: this trace replayed cached calls, so its timings aren't real latencies.
            dot.append(f'"{n["id"]}"[label="{n["name"]}\\n({n["type"].lower()})"];')
            if n["parent"] and any(x["id"] == n["parent"] for x in nodes):
                dot.append(f'"{n["parent"]}"->"{n["id"]}";')
        dot.append("}")
        with col:
            md(f"**{m}: {METHODS[m]}**")
            st.graphviz_chart("".join(dot), width="stretch")
    cap("Generation = an AI call. Retriever = picking passages. Guardrail = the code checks.")
    next_button("Next: how we got here", STEPS[5])

# ------------------------------------------------------------------ 6. history

elif ss.step == STEPS[5]:
    st.header("Step 6. How we got here")
    md("The bar to ship: **every result proven by code (lineage 100%), no missed issue (recall 100%), "
                "and at least 90% of flags real (precision).** The answer key was written before the first run "
                "and never changed.")
    table = []
    for v in ("v1", "v2", "v3"):
        row = {"Prompt": v}
        for m in METHODS:
            r = SNAP["runs"][v].get(m)
            if r:
                vals = r["values"]
                row[f"{m}: {METHODS[m]}"] = (("PASS" if r["verdict"] == "PASS" else "FAIL")
                                            + f" · P {vals['precision']:.0%} · R {vals['recall']:.0%} · L {vals['lineage']:.0%}")
        table.append(row)
    st.dataframe(table, hide_index=True, width="stretch")
    cap("P = precision, R = recall, L = lineage.")
    md(
        "- **v1:** the AI skipped the customer count when it differed from the slide, and flagged the deal's own terms.\n"
        "- **v2:** fixed both. One call (A) then tagged a loan quote with a period the page doesn't state, so code "
        "rejected it. RAG (B) still missed a page.\n"
        "- **v3:** periods only when the page states them. RAG keeps at most 2 passages per file. All four pass, "
        "and pass again on a fresh rerun."
    )
    st.subheader("Why search said a wrong number was right")
    md(
        "Slide 4 says **Revenue FY2025: $38.0M**. The audited accounts say **$36.2M**. The $38.0M comes from the "
        "monthly accounts, which include a **$1.8M one-off fee** the auditors moved to 2026. A correct check says "
        f"{badge('conflict')}. On prompt v1, RAG said {badge('confirmed')}."
    )

    def revenue(v, m):
        return next(c for c in SNAP["runs"][v][m]["claims"] if "Revenue" in c["quote"])

    def pages_read(claim) -> dict:
        out: dict = {}
        for u in claim["retrieved"]:
            f, p, _ = u.split(":")
            out.setdefault(f + ".pdf", set()).add(int(p[1:]))
        return out

    def files_grid(claim):
        """One chip per file: what this method put in front of the AI."""
        read = pages_read(claim)
        lines = []
        for f, desc in list(FILES.items())[1:]:
            if f in read:
                pg = ", ".join(str(p) for p in sorted(read[f]))
                lines.append(f":green-background[Read] {desc}, page {pg}")
            else:
                mark = " **(the $36.2M is here)**" if f == "03_audited_accounts_fy2025.pdf" else ""
                lines.append(f":gray-background[Not read] {desc}{mark}")
        md("  \n".join(lines))

    def figures(claim):
        found = [e for e in claim["evidence"] if e["verified"] and e.get("role", "direct") == "direct"]
        if not found:
            md("No figure found.")
        for e in found:
            md(f"**${float(e['value']):.1f}M** from {FILES.get(e['file'], e['file'])}, page {e['page']}")

    lanes = [("v1", "B", "RAG on prompt v1", "wrong"), ("v1", "A", "One model call on prompt v1", "right"),
             ("v3", "B", "RAG on prompt v3, after the fix", "right")]
    cols = st.columns(3)
    for col, (v, m, title, verdict) in zip(cols, lanes):
        c = revenue(v, m)
        with col:
            md(f"#### {title}")
            md(f"Result: {badge(c['status'])} ({verdict})")
            md("**1. What the AI was given to read**")
            files_grid(c)
            md("**2. The revenue figures it found**")
            figures(c)
            md("**3. What code decided**")
            vals = sorted({float(e["value"]) for e in c["evidence"] if e["verified"] and e.get("role", "direct") == "direct"})
            if vals == [38.0]:
                md("Every figure it saw equals the slide's $38.0M, so code confirmed it. "
                            "Code compares numbers. It can't know a page it never saw.")
            else:
                md(f"It saw {' and '.join(f'${x:.1f}M' for x in vals)}. They disagree, so code reported a "
                            "conflict and showed both sources.")

    md("**The two pages, side by side**")
    p1, p2 = st.columns(2)
    p1.image(page_image("04_management_accounts_fy2025.pdf", 12, ("Total revenue FY2025: $38.0M",)),
             caption="Monthly accounts, page 12: RAG read this ($38.0M, one-off fee included)", width="stretch")
    p2.image(page_image("03_audited_accounts_fy2025.pdf", 3, ("Revenue | 36.2",)),
             caption="Audited accounts, page 3: RAG on v1 never read this ($36.2M)", width="stretch")

    md(
        "**Why it happened.** Search ranks passages that look like the question. The 12 monthly pages all say "
        "\"Revenue\" and \"FY2025\", so they crowded out the one audited table.  \n"
        "**The fix (v3).** At most 2 passages per file. The audited page made the shortlist, and RAG found the conflict.  \n"
        "**The lesson.** Every quote RAG gave was real, so the code checks passed. Checks catch a wrong quote. "
        "They can't catch a page that was never read. That's why the red flag hunt reads every page, with no search."
    )
    st.info("These prompts were tuned on this one data room. A second data room they've never seen is the next test.")
