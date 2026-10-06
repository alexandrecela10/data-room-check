"""Every prompt version, kept side by side so any run can be reproduced.

Change log (one line per version, the reason, and the run it answered):
- v1 (2026-10-04): first version. Run 0: precision 80 to 82%, customer count not found.
- v2 (2026-10-05): evidence: report the data room's figure even when it differs, undated
  slide claims use the latest period. Red flags: skip the proposed transaction's own terms.
  Run: C passed; A lost lineage (a period the page doesn't state); B missed the revenue conflict.
- v3 (2026-10-05): evidence: set a period only when the passage or its heading states it.
  RAG: top 8 passages, at most 2 per file, so 12 near-identical monthly pages can't crowd out
  the audited accounts.
"""

RULES = """Rules:
- Use only the passages given. Never use outside knowledge.
- Copy quotes exactly, word for word, from one passage. Keep a quote short: the sentence or table row that holds the figure.
- Report facts only. Never give advice, opinions or recommendations.
- Return valid JSON only."""

CLAIMS = """These are the slides of a company's investor presentation.
List every claim on them that states a number someone could check against company documents
(amounts, percentages, counts, years). Skip the terms of the proposed transaction.

For each claim return: slide (the page number), quote (the exact sentence from the slide),
metric (a short name), value (the number only), unit ("%", "$M", "count" or "year"),
period (for example "FY2025", or "" if none).

Return JSON: {{"claims": [{{"slide": 0, "quote": "", "metric": "", "value": 0, "unit": "", "period": ""}}]}}

{rules}

Slides:
{passages}
"""

EVIDENCE_V1 = """A slide claims: "{quote}"
Metric: {metric}. Value: {value} {unit}. Period: {period}.

Find, in the passages below, every passage that states this metric for this period, or the
figures needed to compute it. Do not judge whether the slide is right.

For each evidence item return: unit_id, quote, value (number), unit ("%", "$M", "count", "year"),
period, and role:
- "direct": the passage states the metric itself.
- "operand": a figure used to compute the metric (then fill computation).
- "context": a passage that explains the figure but holds no value for it (value null).

computation: null, or {{"op": "ratio_pct", "numerator": <index in evidence>, "denominator": <index>}}
when the metric is a share or a rate computed from two figures.

Return JSON: {{"evidence": [...], "computation": null}}. If nothing relevant: {{"evidence": [], "computation": null}}.

{rules}

Passages:
{passages}
"""

EVIDENCE_V2 = EVIDENCE_V1.replace(
    "figures needed to compute it. Do not judge whether the slide is right.",
    "figures needed to compute it. Do not judge whether the slide is right.\n\n"
    "Report the data room's figure for this metric even when it differs from the slide: a different\n"
    "number is evidence too. If the period is \"none\", use the most recent period in the passages.",
)

FLAGS_V1 = """You are reviewing one file from a company's data room, before an investment.
Run each check below over every passage. Report only what the text states.

Checks:
{checks}

For each finding return: check_id, observation (one factual sentence, no advice), unit_id, quote.
A finding can cite only one passage. If a check finds nothing in this file, return nothing for it.

Return JSON: {{"findings": [...]}}

{rules}

File {file}:
{passages}
"""

FLAGS_V2 = FLAGS_V1.replace(
    "Run each check below over every passage. Report only what the text states.",
    "Run each check below over every passage. Report only what the text states.\n"
    "Do not report the terms of the proposed transaction itself (buyer, stake, price): the investor\n"
    "already knows them. Report what those terms trigger elsewhere.",
)

PAGEINDEX = """You are navigating a data room by its table of contents.
A slide makes this claim: "{quote}" (metric: {metric}, period: {period}).

Pick the sections most likely to contain the figure, or the figures needed to compute it.
Pick at most {n}. Return JSON: {{"section_ids": ["..."]}}

Table of contents:
{outline}
"""

EVIDENCE_V3 = EVIDENCE_V2.replace(
    "period, and role:",
    "period (only when the passage or its section heading states it, otherwise \"\"), and role:",
)

RAG_V1 = {"top_k": 6, "max_per_file": None}
RAG_V3 = {"top_k": 8, "max_per_file": 2}
HYBRID_V3 = {"files": 3}  # method D, added 2026-10-05 with no tuning

VERSIONS = {
    "v1": {"claims": CLAIMS, "evidence": EVIDENCE_V1, "flags": FLAGS_V1, "pageindex": PAGEINDEX, "rag": RAG_V1},
    "v2": {"claims": CLAIMS, "evidence": EVIDENCE_V2, "flags": FLAGS_V2, "pageindex": PAGEINDEX, "rag": RAG_V1},
    "v3": {"claims": CLAIMS, "evidence": EVIDENCE_V3, "flags": FLAGS_V2, "pageindex": PAGEINDEX, "rag": RAG_V3,
           "hybrid": HYBRID_V3},
}
CURRENT = "v3"
