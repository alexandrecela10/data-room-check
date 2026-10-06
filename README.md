# Data Room Check

An AI checker for an investment data room. It verifies every number in the seller's slides against the data room, hunts for listed red flags in every file, and shows the file, page and quote behind every result.

> Fintech A, its data room, its people and every number here are fictional, created for this prototype.

## Status

Steps 1 to 3 built: data room and answer key, four search methods with code checks and scoring, and the demo.
Prompt v3 passes on all four methods: precision 100%, recall 100%, lineage 100% (answer key in `eval/`).
Tuned on this one data room: an unseen second data room is the next test.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Step 1: verify it yourself

```bash
.venv/bin/python scripts/make_data_room.py   # writes 13 PDFs to data/room/ from data/facts.yaml
.venv/bin/python -m dataroom.ingest          # splits them into units, saves data/dataroom.duckdb
.venv/bin/python -m dataroom.show_key        # every answer-key item with FOUND/MISSING per quote
.venv/bin/python -m pytest -q                # 42 tests
```

## Run the demo (no key needed)

```bash
.venv/bin/streamlit run app.py      # replays case_study/data/snapshot.json
```

## Run the checks yourself (needs keys in .env)

```bash
# .env: GEMINI_API_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL
.venv/bin/python -m eval.experiment --version v3            # 4 methods, scored, sent to Langfuse
.venv/bin/python -m eval.experiment --version v3 --bench    # fresh cache: fair cost and time
.venv/bin/python -m case_study.export_snapshot              # freeze results for the demo
```

## The four search methods

| | How it picks what the AI reads |
|---|---|
| A. One model call | Every passage in the data room |
| B. RAG | Top 8 passages by meaning and keywords, at most 2 per file |
| C. PageIndex | The AI reads section headings and picks up to 6 sections |
| D. RAG + PageIndex | RAG keeps the 3 best files, then PageIndex inside them |

The red flag hunt never searches: it reads every page of every file.

## Layout

| Path | What it is |
|---|---|
| `data/facts.yaml` | Every Fintech A number. All 13 files are generated from it. The deck's claims sit under `deck:` |
| `scripts/make_data_room.py` | Writes the 13 PDFs |
| `data/room/` | The data room |
| `dataroom/ingest.py` | PDF to units: ID, file, SHA-256, page, section path, kind, text. Tables stay whole |
| `config/red_flags.yaml` | The 7 red flag checks |
| `eval/answer_key.yaml` | 10 slide claims (4 wrong, 6 correct) and 6 red flags (2 not on the list). Only scoring code reads it |
| `tests/test_step1.py` | Lineage, tables, sections, and every answer-key quote found on its page |
| `dataroom/prompts.py` | Every prompt version (v1 to v3) with a change log |
| `dataroom/retrieve.py` | Methods A to D |
| `dataroom/verify.py` | Code checks: quote on page, number in quote, unit and period, arithmetic, status |
| `dataroom/pipeline.py` | Claims, evidence, red flags; traced to Langfuse when keys are set |
| `dataroom/tracing.py` | Langfuse trace structure and names |
| `eval/score.py`, `eval/experiment.py` | Scoring against the answer key; Langfuse experiments |
| `case_study/export_snapshot.py` | Freezes scores, cost, time and trace trees for the demo |
| `app.py` | The demo |
