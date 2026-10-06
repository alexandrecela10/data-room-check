"""Code checks on everything the AI returns. The AI never decides a status.

1. Lineage: the quote must be on the cited page (close match, to survive PDF
   spacing), and the unit ID must exist.
2. Value: the number the AI reported must appear in its own quote.
3. Unit and period: the unit marker and the period must appear on the page.
4. Arithmetic: ratios are computed here from verified values only.
5. Status: confirmed / contradicted / conflict / not found, decided by comparing
   numbers, never by the AI's opinion.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from dataroom.ingest import normalise

QUOTE_MIN_SCORE = 90  # partial_ratio out of 100; see test_quote_matching

NUMBER = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])\d+(?:\.\d+)?")


WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())}
NUMBER_WORD = re.compile(r"\b(" + "|".join(WORDS) + r")\b", re.IGNORECASE)


def numbers_in(text: str) -> list[float]:
    """Digits, plus number words up to twelve ("three products")."""
    found = [float(m.replace(",", "")) for m in NUMBER.findall(text)]
    return found + [float(WORDS[m.lower()]) for m in NUMBER_WORD.findall(text)]


def quote_on_page(quote: str, page_text: str) -> bool:
    q, p = normalise(quote), normalise(page_text)
    if not q:
        return False
    if q in p:
        return True
    return fuzz.partial_ratio(q, p) >= QUOTE_MIN_SCORE


def value_in_quote(value, quote: str) -> bool:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    return any(abs(n - v) < 1e-9 for n in numbers_in(quote))


def unit_on_page(unit: str, quote: str, page_text: str) -> bool:
    if unit == "%":
        return "%" in quote or "%" in page_text
    if unit == "$M":
        return "$" in quote or "($M)" in page_text or "$" in page_text
    return True  # counts and years carry no marker


def period_on_page(period: str, page_text: str, section_path: str) -> bool:
    if not period:
        return True
    return period in page_text or period in section_path


def same_value(a: float, b: float, unit: str) -> bool:
    """Tolerance: half a point for percentages, 1% relative for money, exact otherwise."""
    if unit == "%":
        return abs(a - b) <= 0.5
    if unit == "$M":
        return abs(a - b) <= 0.01 * max(abs(a), abs(b))
    return a == b


def check_evidence(ev: dict, units_by_id: dict, page_text_of) -> dict:
    """Return the evidence item with a `verified` flag and the reason if not."""
    out = dict(ev)
    u = units_by_id.get(ev.get("unit_id"))
    if u is None:
        return {**out, "verified": False, "reason": "unknown unit ID"}
    out.update(file=u["file"], page=u["page"], section_path=u["section_path"])
    page = page_text_of(u["file"], u["page"])
    quote = ev.get("quote", "")
    if not quote_on_page(quote, page):
        return {**out, "verified": False, "reason": "quote not on cited page"}
    if ev.get("role", "direct") != "context":
        if not value_in_quote(ev.get("value"), quote):
            return {**out, "verified": False, "reason": "value not in quote"}
        if not unit_on_page(ev.get("unit", ""), quote, page):
            return {**out, "verified": False, "reason": "unit not on page"}
        if not period_on_page(ev.get("period", ""), page, u["section_path"]):
            return {**out, "verified": False, "reason": "period not on page"}
    return {**out, "verified": True, "reason": ""}


def compute(computation: dict | None, evidence: list[dict]) -> float | None:
    """Ratio as a percentage, from two verified operand values."""
    if not computation or computation.get("op") != "ratio_pct":
        return None
    try:
        num = evidence[int(computation["numerator"])]
        den = evidence[int(computation["denominator"])]
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    if not (num["verified"] and den["verified"]) or float(den["value"]) == 0:
        return None
    return round(100 * float(num["value"]) / float(den["value"]), 1)


def decide(claim: dict, evidence: list[dict], computed: float | None) -> tuple[str, str]:
    """Status and label for one slide claim, from verified evidence only."""
    unit = claim.get("unit", "")
    direct = [float(e["value"]) for e in evidence
              if e["verified"] and e.get("role", "direct") == "direct"]
    if computed is not None:
        values, label = [computed], "computed"
    else:
        values, label = direct, "stated"
    if not values:
        any_unverified = any(not e["verified"] for e in evidence)
        return ("unverified" if any_unverified else "not_found"), ""
    matches = [same_value(float(claim["value"]), v, unit) for v in set(values)]
    if all(matches):
        return "confirmed", label
    if not any(matches):
        return "contradicted", label
    return "conflict", label


ADVICE_WORDS = re.compile(
    r"\b(should|recommend\w*|advis\w*|we suggest|attractive|good investment|bad investment|"
    r"avoid|walk away|go ahead|do not invest|invest in|buy|sell)\b", re.IGNORECASE)


def advice_in(text: str) -> list[str]:
    """Recommendation words in AI-written text (never applied to quotes)."""
    return sorted({m.lower() for m in ADVICE_WORDS.findall(text or "")})
