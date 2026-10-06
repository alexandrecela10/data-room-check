"""A deterministic stand-in for the model, so tests run offline and free.

It answers like a careful model would on this data room, and only cites
passages it was actually shown. That lets the tests exercise retrieval (a
method that hides the right passage gets "not found"), the code checks and
the scoring, without a network call.
"""

import hashlib
import math
import re

CLAIMS = [
    {"slide": 2, "quote": "Founded in 2014.", "metric": "year founded", "value": 2014, "unit": "year", "period": ""},
    {"slide": 2, "quote": "3 offices: London, Manchester, Dublin.", "metric": "offices", "value": 3, "unit": "count", "period": ""},
    {"slide": 4, "quote": "Revenue FY2025: $38.0M.", "metric": "revenue", "value": 38.0, "unit": "$M", "period": "FY2025"},
    {"slide": 5, "quote": "Gross margin: 68%.", "metric": "gross margin", "value": 68, "unit": "%", "period": ""},
    {"slide": 5, "quote": "Net revenue retention: 115%.", "metric": "net revenue retention", "value": 115, "unit": "%", "period": ""},
    {"slide": 6, "quote": "410 customers across the UK and Ireland.", "metric": "customers", "value": 410, "unit": "count", "period": ""},
    {"slide": 6, "quote": "Largest customer: 12% of revenue.", "metric": "largest customer share", "value": 12, "unit": "%", "period": ""},
    {"slide": 7, "quote": "3 products: FinPay, FinRecon, FinInsights.", "metric": "products", "value": 3, "unit": "count", "period": ""},
    {"slide": 8, "quote": "240 employees.", "metric": "employees", "value": 240, "unit": "count", "period": ""},
    {"slide": 9, "quote": "Senior term loan: $25.0M.", "metric": "loan", "value": 25.0, "unit": "$M", "period": ""},
]

# claim metric -> (evidence items, computation)
EVIDENCE = {
    "year founded": ([("03_audited_accounts_fy2025:p1:u1", "The company was incorporated in England in 2014.", 2014, "year", "", "direct")], None),
    "offices": ([("03_audited_accounts_fy2025:p1:u1", "The company operates from 3 offices in London, Manchester, Dublin.", 3, "count", "", "direct")], None),
    "revenue": ([("03_audited_accounts_fy2025:p3:u1", "Revenue | 36.2", 36.2, "$M", "FY2025", "direct"),
                 ("04_management_accounts_fy2025:p12:u2", "Total revenue FY2025: $38.0M", 38.0, "$M", "FY2025", "direct")], None),
    "gross margin": ([("03_audited_accounts_fy2025:p4:u1", "Gross margin for FY2025 was 68.0%.", 68.0, "%", "FY2025", "direct")], None),
    "net revenue retention": ([("05_customer_revenue_analysis:p1:u2", "Their revenue FY2025 ($M) | 30.6", 30.6, "$M", "FY2025", "operand"),
                               ("05_customer_revenue_analysis:p1:u2", "Their revenue FY2024 ($M) | 29.4", 29.4, "$M", "FY2024", "operand")],
                              {"op": "ratio_pct", "numerator": 0, "denominator": 1}),
    "customers": ([("05_customer_revenue_analysis:p1:u1", "Active customers at 31 December 2025: 372.", 372, "count", "", "direct")], None),
    "largest customer share": ([("05_customer_revenue_analysis:p2:u1", "Halden Retail Group | 11.22", 11.22, "$M", "FY2025", "operand"),
                                ("05_customer_revenue_analysis:p2:u1", "Total | 36.20", 36.20, "$M", "FY2025", "operand")],
                               {"op": "ratio_pct", "numerator": 0, "denominator": 1}),
    "products": ([("03_audited_accounts_fy2025:p1:u1", "The company sells three products: FinPay, FinRecon, FinInsights.", 3, "count", "", "direct")], None),
    "employees": ([("03_audited_accounts_fy2025:p1:u1", "The average number of employees during the year was 240.", 240, "count", "", "direct")], None),
    "loan": ([("09_senior_facility_agreement:p1:u1", "The Lender makes available a term loan facility of $25.0M.", 25.0, "$M", "", "direct")], None),
}

FLAGS = {
    "09_senior_facility_agreement.pdf": [("change_of_control", "09_senior_facility_agreement:p4:u1",
        "If any person or group acting together acquires more than 25% of the shares in the Borrower, the Borrower must repay the loan in full",
        "The loan must be repaid if anyone acquires more than 25% of the shares.")],
    "12_letter_hollis_grant.pdf": [("legal_claims", "12_letter_hollis_grant:p1:u1",
        "Our client claims $2.1M in unpaid commission and damages", "A former reseller claims $2.1M.")],
    "06_contract_halden_retail.pdf": [("contracts_ending", "06_contract_halden_retail:p2:u1",
        "No renewal has been agreed at the date of this copy.", "The contract ends on 28 February 2027 with no renewal agreed.")],
    "05_customer_revenue_analysis.pdf": [("customer_concentration", "05_customer_revenue_analysis:p2:u1",
        "Halden Retail Group | 11.22", "Halden Retail Group is 31% of FY2025 revenue.")],
    "11_board_minutes.pdf": [("other", "11_board_minutes:p4:u1",
        "The board noted the resignation of Priya Raman, Chief Financial Officer, effective 30 September 2026.",
        "The CFO resigned effective 30 September 2026.")],
    "13_office_lease.pdf": [("other", "13_office_lease:p3:u1", "Calder Property Ltd is wholly owned by Daniel Okafor.",
        "The landlord is owned by the CEO.")],
}

HEADINGS_FOR = {
    "year founded": ["Directors' report"], "offices": ["Directors' report"], "products": ["Directors' report"],
    "employees": ["Directors' report"], "revenue": ["Income statement", "Full year summary"],
    "gross margin": ["Note 3: Key ratios"], "net revenue retention": ["Summary"], "customers": ["Summary"],
    "largest customer share": ["Top 10 customers by revenue"], "loan": ["1. The facility"],
}


class FakeLLM:
    name = "fake"

    def __init__(self, drop_units=()):
        self.drop_units = set(drop_units)  # simulate a model that ignores some passages

    def json(self, prompt: str):
        if "List every claim" in prompt:
            return {"claims": CLAIMS}
        if "table of contents" in prompt:
            metric = re.search(r"\(metric: (.*?), period", prompt).group(1)
            wanted = HEADINGS_FOR.get(metric, [])
            ids = re.findall(r"\[(\d\d\.s\d+)\] (.*?) \(p\.", prompt)
            files_ok = ("03.", "04.", "05.", "09.")
            return {"section_ids": [i for i, h in ids if h in wanted and i.startswith(files_ok)][:6]}
        if "A slide claims" in prompt:
            metric = re.search(r"Metric: (.*?)\. Value", prompt).group(1)
            items, comp = EVIDENCE.get(metric, ([], None))
            shown = set(re.findall(r"^\[(.+?)\]", prompt, re.M))
            ev = [{"unit_id": u, "quote": q, "value": v, "unit": un, "period": p, "role": r}
                  for u, q, v, un, p, r in items if u in shown and u not in self.drop_units]
            return {"evidence": ev, "computation": comp if len(ev) == len(items) else None}
        if "Run each check" in prompt:
            f = re.search(r"^File (.+?):$", prompt, re.M).group(1)
            return {"findings": [{"check_id": c, "unit_id": u, "quote": q, "observation": o}
                                 for c, u, q, o in FLAGS.get(f, [])]}
        raise AssertionError("unexpected prompt")

    def embed(self, texts):
        """Hashed bag of words: similar wording gives similar vectors."""
        out = []
        for t in texts:
            v = [0.0] * 64
            for w in re.findall(r"[a-z0-9]+", t.lower()):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1
            n = math.sqrt(sum(x * x for x in v)) or 1
            out.append([x / n for x in v])
        return out
