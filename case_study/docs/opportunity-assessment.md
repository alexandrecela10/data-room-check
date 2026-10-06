# Data Room Check: Opportunity Analysis

**Date:** 2026-10-04
**Owner:** Alexandre Cela
**Status:** Go (approved by Alex 2026-10-04)

## Problem Statement

A family office (a company that invests one family's money) must decide on a deal in 2 to 3 weeks. A wrong number in the seller's slides, or a risk in an unopened file, can change that decision. Today, nobody may notice either one.

## Current Situation

The seller shares a folder of documents, called the data room. An analyst reads it by hand and notes findings in a spreadsheet. They often rely on the lead investor's summary, and that investor wants the deal to close.

**A concrete case (made up for the demo).** Fintech A's slides say its largest customer is 12% of revenue. The customer list in the data room shows 31%. If that customer leaves, almost a third of revenue goes. Today, the analyst catches this only if they open that file.

## Proposed Solution

An AI checker for the data room. A language model (an AI that reads and writes text) does the reading. Code checks its work.
1. **Verifies every slide claim.** The AI finds the matching figure in the data room. It marks each claim confirmed, contradicted or not found.
2. **Hunts for every listed red flag in every file.** The list is fixed: change of owner clauses, legal claims, contracts ending soon and more. The AI also notes other unusual facts.
3. **Shows the lineage of every result.** Each result carries its file, page and an exact quote. Code confirms the quote is on that page, and the numbers match, before the result is shown. Results that fail are labelled unverified.

**The bar it must meet:** 100% of results with verified lineage, and at least 95% of flags real. Below either, it doesn't ship.

It states facts and never recommends. The analyst and the associate (who signs off the analyst's work) decide.

## Expected Impact: money

The family office makes money by paying the right price and avoiding losses it could have seen. Every number below is made up for this example.

- **Paying the right price.** The slides say revenue of $38.0M. The audited accounts say $36.2M. At a price of 4 times revenue, that gap is $7.2M of value paid for but not there. On a 10% stake, the family overpays $0.72M.
- **Asking for protection before signing.** A $2.1M legal claim, and a loan that must be repaid if owners change, surface before the deal closes. The family can ask for a lower price or for the seller to cover those costs.
- **Fewer hours per deal.** Analyst and associate hours fall, so the same team can review more deals. The hours saved are unobserved.

## Problems, hypotheses and success

One row per atomic problem: one job, one hypothesis, one metric. "Today" values and impacts are assumed, not measured.

| # | Problem | Today | Hypothesis | Success metric | Expected impact |
|---|---|---|---|---|---|
| 1 | Wrong numbers in the slides reach the decision | Only numbers the analyst has time for get checked | If every slide number is checked against the data room, then wrong ones get caught, because each mismatch shows both pages | Planted wrong slide numbers flagged: 100% | Fewer deal decisions made on a wrong number. Analyst hours re-checking slides: down (unobserved) |
| 2 | Risks sit in files nobody opened | Only opened files get read | If one warning-sign list runs over every file, then fewer risks are missed, because no file waits for the analyst's time | Planted risks found: 100%, including 2 or 3 not on the list | Fewer risks discovered after the deal closes. Files skipped for lack of time: 0 |
| 3 | The associate can't see what was checked | Spreadsheet notes, no page links | If every result shows its page and a quote that code matched to that page, then the associate trusts it without re-reading, because checking is one click | Results whose quote is found on the cited page: 100% | Associate sign-off becomes spot-checks, not a re-read. Sign-off time: down (unobserved) |

**Must not get worse:** claims shown as fact that failed the check: 0.

**Not tackled here:**
- **Retyping numbers for the financial model:** needs a set list of fields.
- **Trusting the lead investor's summary:** needs a sample summary to check.
- **Asking any free question:** a search can't prove a fact is absent, so it can't support "nothing was missed."
- **Turning findings into a lower price:** this is the investor's judgment.

## How It Could Be Delivered

- **Data:** made up. Fintech A as an older company with loans: 10 slides, 13 files, 9 known issues in an answer key.
- **Finding evidence for a claim, three ways compared:** one model call with the whole data room; RAG (search passages by meaning, then answer); PageIndex (the AI walks each file's table of contents). The red flag hunt reads every page, with no search.
- **Results** are computed once and stored, so the demo runs free. Details are in the PRD.

## Value Equation (Hormozi)

| Factor | Analyst (uses it) | Associate (signs off) |
|---|---|---|
| **Dream outcome** | "I checked everything and I can prove it." | "I can sign off without redoing the work." |
| **Perceived likelihood** | Low to medium. Investors distrust AI answers they can't check. | Low. They'll trust it only after spot-checking pages. |
| **Time delay** | Results minutes after the folder loads (unobserved). | Same day as the analyst's run. |
| **Effort & sacrifice** | Upload the folder, review flagged rows, learn one new screen. | Click through flagged rows instead of reading files. |

**Verdict.** Belief is the weak factor for both. The cheapest lever is to show the source page and quote beside every result. Another is to say "not found" instead of guessing. The outcome doesn't need improving.

## Recommendation

**Go, as a portfolio prototype.** The problem is plausible, the demo needs only fake data, and it adds a trust story Deck Rank and BDC Footnote Tape don't show. A user test with 2 analysts would make it a product case, not just a demo.

Sources: conversation with Alex 2026-10-04 (brief confirmed), `~/Documents/Company Tracker/company_scorer/demo/make_sample_decks.py`, `outputs/portfolio/deck-rank/linkedin.md`, `outputs/portfolio/bdc-footnotes/linkedin.md`
