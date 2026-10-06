"""Write the 13 Fintech A data room PDFs from data/facts.yaml.

Every page uses the same layout: a large bold document title, then sections,
each with a bold heading. The heading font size is what ingestion uses to
rebuild the section tree, so keep HEADING_SIZE distinct from BODY_SIZE.

Run: .venv/bin/python scripts/make_data_room.py
"""

from pathlib import Path

import yaml
from fpdf import FPDF

ROOT = Path(__file__).resolve().parent.parent
FACTS = yaml.safe_load((ROOT / "data" / "facts.yaml").read_text())
OUT = ROOT / "data" / "room"

TITLE_SIZE = 18
HEADING_SIZE = 13
BODY_SIZE = 10


def money(x: float) -> str:
    return f"${x:.1f}M"


class Doc:
    """A document is a list of pages; a page is a list of blocks."""

    def __init__(self, title: str, landscape: bool = False):
        self.title = title
        self.pdf = FPDF(orientation="L" if landscape else "P", format="A4")
        self.pdf.set_auto_page_break(auto=False)
        self.pdf.set_margins(20, 18, 20)

    def page(self, *blocks):
        pdf = self.pdf
        pdf.add_page()
        pdf.set_font("Helvetica", "B", TITLE_SIZE)
        pdf.multi_cell(0, 9, self.title, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
        for kind, content in blocks:
            if kind == "h":
                pdf.ln(2)
                pdf.set_font("Helvetica", "B", HEADING_SIZE)
                pdf.multi_cell(0, 7, content, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(1)
            elif kind == "p":
                pdf.set_font("Helvetica", "", BODY_SIZE)
                pdf.multi_cell(0, 5.2, content, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(2)
            elif kind == "t":
                self._table(content)
        return self

    def _table(self, rows):
        pdf = self.pdf
        pdf.set_font("Helvetica", "", BODY_SIZE)
        with pdf.table(first_row_as_headings=True, line_height=6) as table:
            for row in rows:
                r = table.row()
                for cell in row:
                    r.cell(str(cell))
        pdf.ln(3)

    def save(self, name: str, path: Path | None = None):
        self.pdf.output(str(path or OUT / name))


def h(text):
    return ("h", text)


def p(text):
    return ("p", text)


def t(rows):
    return ("t", rows)


# ---------------------------------------------------------------- documents


def deck(numbers: dict | None = None, path: Path | None = None):
    """The seller's deck. `numbers` overrides FACTS["deck"] (the demo's slide editor)."""
    c, deal = FACTS["company"], FACTS["deal"]
    d = {**FACTS["deck"], **(numbers or {})}
    doc = Doc("Fintech A: Investor Presentation", landscape=True)
    doc.page(h("Payments and reconciliation for mid-size retailers"),
             p(f"Confidential. Prepared for prospective co-investors. {deal['date']}."))
    doc.page(h("Company"),
             p(f"Founded in {d['incorporated']}."),
             p(f"{d['offices']} offices: {', '.join(c['offices'])}."))
    doc.page(h("The problem we solve"),
             p("Mid-size retailers run payments and reconciliation in separate tools. "
               "Finance teams close the month by matching card settlements to orders by hand."))
    doc.page(h("Financials"),
             p(f"Revenue FY2025: {money(d['revenue_fy2025'])}."),
             p("Profitable and growing."))
    doc.page(h("Unit economics"),
             p(f"Gross margin: {d['gross_margin_pct']}%."),
             p(f"Net revenue retention: {d['revenue_kept_pct']}%."))
    doc.page(h("Customers"),
             p(f"{d['customers']} customers across the UK and Ireland."),
             p(f"Largest customer: {d['largest_customer_pct']}% of revenue."))
    doc.page(h("Product"),
             p(f"{d['products']} products: {', '.join(c['products'])}."))
    doc.page(h("Team"),
             p(f"{d['employees']} employees."),
             p(f"Led by CEO {c['ceo']} and CFO {c['cfo']}."))
    doc.page(h("Financing"),
             p(f"Senior term loan: {money(d['loan_musd'])}."))
    doc.page(h("The transaction"),
             p(f"{deal['lead_investor']} is acquiring a {deal['stake_sold_pct']}% stake for "
               f"{money(deal['equity_raise_musd'])}. Co-investment is available."))
    doc.save("01_investor_presentation.pdf", path)


def audited(year: str, fname: str):
    c, f = FACTS["company"], FACTS[year]
    rev = f.get("revenue_audited", f.get("revenue"))
    yr = year[2:]
    doc = Doc(f"Fintech A Ltd: Audited Financial Statements FY{yr}")
    doc.page(h("Directors' report"),
             p(f"The company was incorporated in England in {c['incorporated']}. Its principal activity is "
               f"{c['activity']}. The company sells three products: {', '.join(c['products'])}."),
             p(f"The company operates from {len(c['offices'])} offices in {', '.join(c['offices'])}. "
               + (f"The average number of employees during the year was {c['employees_avg_fy2025']}."
                  if year == "fy2025" else "")))
    doc.page(h("Independent auditor's report"),
             p(f"In our opinion the financial statements give a true and fair view of the state of the "
               f"company's affairs for the year ended 31 December {yr}. Signed: Pell & Rowe LLP, Chartered Accountants."))
    doc.page(h("Income statement"),
             t([["Line ($M)", f"FY{yr}"],
                ["Revenue", f"{rev:.1f}"],
                ["Cost of sales", f"({f['cost_of_sales']:.1f})"],
                ["Gross profit", f"{f['gross_profit']:.1f}"],
                ["Operating expenses before depreciation", f"({f['operating_expenses']:.1f})"],
                ["EBITDA", f"{f['ebitda']:.1f}"]]))
    if year == "fy2025":
        doc.page(h("Note 3: Key ratios"),
                 p(f"Gross margin for FY{yr} was {f['gross_margin_pct']:.1f}%."),
                 h("Note 4: Revenue recognition"),
                 p(f"An implementation fee of {money(f['one_off_fee'])} invoiced to Halden Retail Group in "
                   f"December 2025 relates to services delivered in 2026. It has been deferred and is not "
                   f"included in FY{yr} revenue."))
    doc.save(fname)


def monthly():
    f = FACTS["fy2025"]
    doc = Doc("Fintech A Ltd: Management Accounts FY2025")
    months = ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]
    # Spread the year's recurring revenue evenly, then add the one-off fee in December.
    recurring = f["revenue_audited"] / 12
    running = 0.0
    for i, m in enumerate(months):
        month_rev = recurring + (f["one_off_fee"] if m == "December" else 0)
        running += month_rev
        blocks = [h(f"{m} 2025"),
                  t([["Line ($M)", "Month", "Year to date"],
                     ["Revenue", f"{month_rev:.2f}", f"{running:.2f}"]])]
        if m == "December":
            blocks += [h("Full year summary"),
                       p(f"Total revenue FY2025: {money(f['revenue_management'])}, including a one-off "
                         f"implementation fee of {money(f['one_off_fee'])} from Halden Retail Group."),
                       h("Loan covenant check"),
                       p(f"Net debt to EBITDA at 31 December 2025: {f['leverage_x']:.1f}x. "
                         f"Covenant limit: {f['leverage_limit_x']:.1f}x. The company is in compliance.")]
        doc.page(*blocks)
    doc.save("04_management_accounts_fy2025.pdf")


def customer_list():
    cu, f = FACTS["customers"], FACTS["fy2025"]
    doc = Doc("Fintech A Ltd: Customer Revenue Analysis FY2024 to FY2025")
    doc.page(h("Summary"),
             p(f"Active customers at 31 December 2025: {cu['active_end_fy2025']}."),
             t([["Cohort: customers active on 1 January 2025", "Value"],
                ["Number of customers", str(cu["cohort_start_fy2025"])],
                ["Their revenue FY2024 ($M)", f"{cu['cohort_revenue_fy2024']:.1f}"],
                ["Their revenue FY2025 ($M)", f"{cu['cohort_revenue_fy2025']:.1f}"]]))
    top = [[cu["largest"]["name"], cu["largest"]["revenue_fy2025"]]] + cu["others_top"]
    rest = f["revenue_audited"] - sum(r for _, r in top)
    rows = [["Customer", "Revenue FY2025 ($M)"]]
    rows += [[n, f"{r:.2f}"] for n, r in top]
    rows += [[f"Other {cu['active_end_fy2025'] - len(top)} customers", f"{rest:.2f}"],
             ["Total", f"{f['revenue_audited']:.2f}"]]
    doc.page(h("Top 10 customers by revenue"), t(rows))
    doc.page(h("Basis of preparation"),
             p("Revenue is audited revenue, allocated to customers from the billing system. "
               "Customers are counted once per legal entity."))
    doc.save("05_customer_revenue_analysis.pdf")


def contract(fname, customer, start, end, fee, extra=None):
    doc = Doc(f"Master Services Agreement: Fintech A Ltd and {customer}")
    doc.page(h("1. Parties"),
             p(f"This agreement is between Fintech A Ltd (the Supplier) and {customer} (the Customer)."),
             h("2. Services"),
             p("The Supplier provides FinPay and FinRecon to the Customer's stores and head office."))
    blocks = [h("3. Term"),
              p(f"This agreement starts on {start} and ends on {end}. "
                "Either party may give 90 days' written notice not to renew.")]
    if extra:
        blocks.append(p(extra))
    blocks += [h("4. Fees"), p(f"Annual subscription fee: {fee}, invoiced quarterly in advance.")]
    doc.page(*blocks)
    doc.page(h("5. Termination"),
             p("Either party may terminate for material breach not remedied within 30 days."),
             h("6. Governing law"),
             p("This agreement is governed by the laws of England and Wales."))
    doc.save(fname)


def loan():
    l, f = FACTS["loan"], FACTS["fy2025"]
    doc = Doc(f"Senior Facility Agreement: Fintech A Ltd and {l['lender']}")
    doc.page(h("1. The facility"),
             p(f"The Lender makes available a term loan facility of {money(l['facility_musd'])}."),
             h("2. Interest"),
             p(f"Interest accrues at {l['margin']} per year, payable quarterly."))
    doc.page(h("3. Repayment"),
             p(f"The Borrower repays the loan in full on {l['maturity']}."),
             h("4. Financial covenant"),
             p(f"Net debt to EBITDA must not exceed {f['leverage_limit_x']:.1f}x, tested each 31 December."))
    doc.page(h("5. Representations"),
             p("The Borrower confirms it has paid all taxes when due and is not party to any material litigation "
               "other than as disclosed to the Lender in writing."))
    doc.page(h("14. Mandatory prepayment"),
             p("14.2 Change of control. If any person or group acting together acquires more than 25% of the "
               "shares in the Borrower, the Borrower must repay the loan in full, with accrued interest, within "
               "30 days of that change of control."))
    doc.page(h("22. Signatures"),
             p(f"Signed for and on behalf of Fintech A Ltd and {l['lender']}."))
    doc.save("09_senior_facility_agreement.pdf")


def ownership():
    c, deal = FACTS["company"], FACTS["deal"]
    doc = Doc("Fintech A Ltd: Shareholder Register")
    doc.page(h("Shareholders at 30 September 2026"),
             t([["Shareholder", "Ordinary shares", "% held"],
                [c["ceo"], "4,200,000", "42.0"],
                ["Founding team (4 people)", "2,300,000", "23.0"],
                ["Employee share scheme", "1,000,000", "10.0"],
                ["Seed and Series A investors", "2,500,000", "25.0"],
                ["Total", "10,000,000", "100.0"]]),
             h("Proposed transaction"),
             p(f"{deal['lead_investor']} proposes to acquire {deal['stake_sold_pct']}% of the shares."))
    doc.save("10_shareholder_register.pdf")


def board_minutes():
    c = FACTS["company"]
    doc = Doc("Fintech A Ltd: Board Minutes")
    meetings = [
        ("Meeting of 12 December 2025",
         "The board approved the FY2026 budget. The CEO reported that the Halden Retail Group implementation "
         "was complete."),
        ("Meeting of 20 March 2026",
         "The board reviewed the FY2025 audited accounts and approved them for signature."),
        ("Meeting of 18 June 2026",
         f"The board approved the appointment of advisers for a sale of a minority stake. "
         f"{c['chair']} chaired the meeting."),
        ("Meeting of 24 September 2026",
         f"The board noted the resignation of {c['cfo']}, Chief Financial Officer, effective 30 September 2026. "
         "The search for a replacement has started. The Financial Controller will act as interim CFO."),
    ]
    for title, text in meetings:
        doc.page(h(title), p(f"Present: {c['chair']} (Chair), {c['ceo']} (CEO), {c['cfo']} (CFO), "
                             "two non-executive directors."), p(text))
    doc.save("11_board_minutes.pdf")


def law_letter():
    lc = FACTS["legal_claim"]
    doc = Doc(f"Letter from {lc['law_firm']}")
    doc.page(h("Re: Claim by " + lc["claimant"]),
             p(f"We act for {lc['claimant']}, a former reseller of Fintech A Ltd. Our client claims "
               f"{money(lc['amount_musd'])} in unpaid commission and damages for the termination of its "
               "reseller agreement in 2025."),
             p("Unless the claim is settled within 60 days, we have instructions to issue proceedings."))
    doc.page(h("Basis of claim"),
             p("Our client introduced 41 customers between 2021 and 2024. Commission on their revenue was "
               "payable for the life of each customer relationship."))
    doc.save("12_letter_hollis_grant.pdf")


def lease():
    le = FACTS["lease"]
    doc = Doc("Lease: " + le["premises"])
    doc.page(h("1. Parties"),
             p(f"Landlord: {le['landlord']}. Tenant: Fintech A Ltd."),
             h("2. Premises"),
             p(f"{le['premises']}, approximately {le['area_sqft']:,} square feet."))
    doc.page(h("3. Rent"),
             p(f"The rent is ${le['rent_per_sqft']} per square foot per year, fixed for 10 years."),
             h("4. Term"),
             p("The lease runs for 10 years from 1 January 2024 with no break clause."))
    doc.page(h("Schedule 2: Landlord details and rent valuation"),
             p(f"{le['landlord']} is wholly owned by {le['landlord_owner']}."),
             p(f"An independent agent valued the market rent for comparable space at "
               f"${le['market_rent_per_sqft']} per square foot per year in December 2023."))
    doc.save("13_office_lease.pdf")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.pdf"):
        old.unlink()
    cu = FACTS["customers"]
    deck()
    audited("fy2024", "02_audited_accounts_fy2024.pdf")
    audited("fy2025", "03_audited_accounts_fy2025.pdf")
    monthly()
    customer_list()
    contract("06_contract_halden_retail.pdf", cu["largest"]["name"], "1 March 2022",
             cu["largest"]["contract_end"], "$11.2M",
             extra="No renewal has been agreed at the date of this copy.")
    contract("07_contract_corvo_home.pdf", "Corvo Home Stores", "1 July 2023", "30 June 2028", "$1.4M")
    contract("08_contract_pellam_outdoor.pdf", "Pellam Outdoor", "1 January 2024", "31 December 2028", "$1.2M")
    loan()
    ownership()
    board_minutes()
    law_letter()
    lease()
    print(f"wrote {len(list(OUT.glob('*.pdf')))} files to {OUT}")


if __name__ == "__main__":
    main()
