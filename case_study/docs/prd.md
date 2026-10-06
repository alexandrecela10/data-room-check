# Data Room Check

**Stage:** Team Kickoff (lightweight AI PRD)
**Last Updated:** 2026-10-04
**Owner:** Alexandre Cela
**Status:** Draft
**Opportunity analysis:** `outputs/opportunity-analyses/data-room-check-opportunity.md` (Go, 2026-10-04)

> **Disclaimer.** Fintech A, its data room, its people and every number in this document are fictional, created for this prototype.

---

## Hypothesis

A family office (a company that invests one family's money) has 2 to 3 weeks to decide on a deal. A wrong number in the seller's slides, or a risk in an unopened file, can change that decision. Today, nobody may notice either one.

**Atomic problems** (carried from the opportunity analysis). "Today" values and impacts are assumed, not measured.

| # | Problem | Today | Hypothesis | Success metric | Expected impact |
|---|---|---|---|---|---|
| 1 | Wrong numbers in the slides reach the decision | Only numbers the analyst has time for get checked | If every slide number is checked against the data room, then wrong ones get caught, because each mismatch shows both pages | Known wrong slide numbers flagged: 4 of 4 | Fewer deal decisions made on a wrong number. Analyst hours re-checking slides: down (unobserved) |
| 2 | Risks sit in files nobody opened | Only opened files get read | If one warning-sign list runs over every file, then fewer risks are missed, because no file waits for the analyst's time | Known risks found: 6 of 6, including 2 not on the list | Fewer risks discovered after the deal closes. Files skipped for lack of time: 0 |
| 3 | The associate can't see what was checked | Spreadsheet notes, no page links | If every result shows its page and a quote that code matched to that page, then the associate trusts it without re-reading, because checking is one click | Results whose quote is found on the cited page: 100% | Associate sign-off becomes spot-checks, not a re-read. Sign-off time: down (unobserved) |

**Must not get worse:** claims shown as fact that failed the check: 0.

**Supporting evidence:** none from users. The problem comes from how this kind of investing works. No analyst has confirmed it.

---

## Strategic Fit

**Why this.** Every result is checked by code before it's shown. Deck Rank ranks decks. BDC Footnote Tape turns lender reports into a spreadsheet. Neither one checks a seller's claims against evidence.

**Why now.** It extends the private capital AI offer to a new buyer: the family office, through its analyst and associate.

**Impact sizing.** Not done yet: no deal volume or time-per-deal data exists. Alternatives considered are in Appendix B.

---

## Expected Impact

If this ships, the analyst gets every slide number marked confirmed, contradicted or not found, and every file checked for the same warning signs, each with a page. The associate signs off from that record. If it doesn't ship, coverage still depends on which files the analyst had time to open. Time saved is unknown. A test with 2 analysts on one data room would measure it.

---

## Value Equation (carried from the opportunity analysis)

| Factor | Analyst (uses it) | Associate (signs off) |
|---|---|---|
| **Dream outcome** | "I checked everything and I can prove it." | "I can sign off without redoing the work." |
| **Perceived likelihood** | Low to medium. Investors distrust AI answers they can't check. | Low. They'll trust it only after spot-checking pages. |
| **Time delay** | Results minutes after the folder loads (unobserved). | Same day as the analyst's run. |
| **Effort & sacrifice** | Upload the folder, review flagged rows, learn one new screen. | Click through flagged rows instead of reading files. |

**Verdict.** Belief is the weak factor. The cheapest lever is to show the source page and quote beside every result. Another is to say "not found" instead of guessing.

---

## Non-Goals

- **Free questions about anything.** A search can't prove a fact is absent.
- **Advice or a lower price.** The decision is the investor's.
- **Hundreds of documents.** This data room has 13 files. Search is built and measured (see trade-offs), but behaviour at scale isn't tested.
- **Privacy controls and logins.** Out of scope for the prototype.

**Trade-offs made:**
- **Three ways to find evidence for a slide claim, compared on the same answer key.**
  - **A. One model call.** The whole data room goes to the model at once. No search. It can't skip a page, and it stops working at roughly a few hundred pages. This is the baseline.
  - **B. RAG (search, then answer).** Pages are cut into passages. Each passage is turned into numbers that capture its meaning (embeddings). For each claim, the closest passages by meaning and by keyword go to the model.
  - **C. PageIndex (follow the table of contents).** Each file becomes a tree of section headings. The model reads the headings and walks down to the pages that matter. No embeddings.
  - B and C are more than 13 files need. They're built to learn both methods and to measure what each misses against A.
- **The red flag hunt never uses search.** It reads every page of every file, because search can't prove a file was covered.
- **Checked once, stored.** Each data room is checked when it loads. Reopening shows stored results and costs nothing.

---

## Success Metrics

Targets are in the atomic problems table. Two extra metrics:
- **Correct slide numbers wrongly flagged:** 0 of 6.
- **Evidence pages found, per method:** the share of answer-key evidence pages that A, B and C each find, shown side by side. Each method also reports how many of the 4 known wrong slide numbers it flags.

The answer key lists every issue in the data room, from a full manual read before the first run. It's stored apart and never shown to the model.

**Kill criteria:** after 2 attempts to improve the AI's instructions, we stop and don't publish if either is true:
- **Lineage below 100%.** Some results lack a file, a page and a quote that code finds on that page.
- **Precision below 90%.** Of everything the tool flags (wrong slide numbers and red flags), fewer than 90% are real issues in the answer key. (Lowered from 95% by Alex on 2026-10-05.)
- **Recall below 100%.** The tool misses any of the 4 wrong slide numbers or 6 red flags in the answer key. (Added 2026-10-05.)

Why: an unverified result sends the associate back to the files, false flags teach the analyst to ignore flags, and a missed issue is the problem this tool exists to solve.

**Test set caveat:** the prompts were tuned on this one data room (3 revisions, all logged in Langfuse). A pass here shows the method works on what it was tuned on. A second data room the prompts have never seen is needed to show it generalises.

---

## Rollout Plan

1. **Data room and answer key.** Passing: 13 files load, and every known issue sits on a known page.
2. **Checks and scoring.** Passing: the metrics table is filled from a logged run, for A, B and C.
3. **Interface and case study.** Passing: the interface loads in a browser and `/portfolio-case-study` goals pass.

The PM reviews each step before the next one starts.

---

## AI Behavior Contract

**Principle:** the model reads and drafts, code checks and computes, the person decides.

| Dimension | Specification |
|---|---|
| **Primary tasks** | Extract slide numbers. Find the matching evidence. Run the warning-sign list. Note other unusual facts. |
| **Inputs** | Every page tagged with file name, page number and section heading. Slide claims: the pages found by method A, B or C. Red flags: every page of every file |
| **Model output** | A list of claims. Each has a value, unit, period, source page and an exact quote. |
| **Code checks** | The quote must appear on the cited page (close match). The number must appear in the quote with the same unit and period. Totals and shares are computed in code from cited rows. |
| **Labels** | Confirmed, contradicted, not found or unverified. Each fact is marked stated, computed or inferred. |
| **Never** | Recommend, rate the deal or guess. A claim that fails a check is shown as unverified, never as fact. |
| **Logged** | Every run: input files, model name, raw model output, check results |

**Behavior examples:**

| Case | Input | Expected output |
|---|---|---|
| Good | Slide 6: "Largest customer is 12% of revenue" | Contradicted. Computed 31% from the customer revenue list, p.2. Both pages linked. |
| Good | Slide 5: "Gross margin 68%" | Confirmed. Audited accounts FY2025, p.4, quote shown. |
| Edge | Slide 4: "Revenue FY2025 $38.0M". Monthly accounts say $38.0M. Audited accounts say $36.2M. | Conflict. Both sources shown with dates. No pick between them. |
| Edge | The model cites p.7 but the quote is on p.8 | Unverified. Shown apart from the facts. |
| Reject | "Should we invest?" | The relevant findings, then: "The decision is yours." No recommendation words. |

---

## Open Questions

- [ ] PDF reader library: decide at build step 2, with trade-offs shown. @Alex
- [ ] Embedding model for B. Use the open-source PageIndex library for C, or build a small version. Does the demo show A, B, C or all three? @Alex
- [ ] Public demo: stored results only, or live runs with the visitor's own model key? @Alex
- [ ] Final product name before the case study. @Alex

---

## Appendix A: Data room

**Fintech A:** payments software for mid-size retailers, founded 2014. A buyout fund leads the deal. The family office puts in money alongside it.

**Files (13):** pitch deck (10 slides) · audited accounts FY2024 · audited accounts FY2025 · monthly accounts FY2025 · customer revenue list FY2024 to FY2025 · top 3 customer contracts · loan agreement · ownership table · board minutes (last 4 meetings) · law firm letter · office lease.

**Answer key: known issues (9):**

| # | Type | Slide says | Data room shows | On the list? |
|---|---|---|---|---|
| V1 | Wrong number | Largest customer 12% of revenue | 31%, customer list | n/a |
| V2 | Wrong number | Revenue kept from last year's customers 115% | 104%, computed from customer list | n/a |
| V3 | Wrong number | 410 customers | 372, customer list | n/a |
| V4 | Conflict | Revenue FY2025 $38.0M | Audited $36.2M; monthly accounts $38.0M | n/a |
| D1 | Risk | | Loan must be repaid if owners change | Yes |
| D2 | Risk | | $2.1M claim from a former partner | Yes |
| D3 | Risk | | Largest customer's contract ends in 5 months | Yes |
| H1 | Risk | | CFO resigned, in board minutes | No |
| H2 | Risk | | Office rented from the CEO's company above market rent | No |

**Correct slide numbers (6):** gross margin, staff count, founding year, offices, loan size, products. They test that the tool doesn't flag correct numbers.

**Warning-sign list (7 checks):** change of owner clauses, legal claims, contracts ending within 12 months, unpaid taxes, loan covenant breaches (loan conditions broken), customer concentration over 20%, plus "other unusual facts."

---

## Appendix B: Alternatives and risks

**Alternatives considered:**
- **Open question box with search (RAG).** Not chosen: a search can't prove a fact is absent, so it can't support "nothing was missed."
- **Typed questions turned into database queries (text-to-SQL).** Not chosen: it adds a second way to be wrong.
- **Keep Fintech A as an early-stage startup.** Not chosen: older companies with loans are closer to typical family office deals.

**Risks and recovery:**

| Risk | Detection | Fallback |
|---|---|---|
| The AI misses the 2 issues the red flag list doesn't name | Neither found after 2 attempts to improve its instructions | Remove that check; state the tool only finds what the list names |
| B or C misses evidence pages, so a claim reads "not found" when the data room has it | Fewer evidence pages found than A on the answer key | Show A's result; report the gap in the case study |
| The known issues are too easy, so the result proves little | All 9 found on the first run with no prompt work | Add 2 harder ones and report both runs |
| The tool marks itself correct | Scoring reads the answer key only | Answer key is written first, stored apart, and never passed to the model |
| The model invents a quote | Quote not found on the cited page | Unverified label; counted in the guardrail |
