# AI Account Review & Expansion Agent

Pipeline that turns one account's call transcripts + usage data into a QBR-ready brief and a customer-facing deck.

Built for the Podium AI GTM Engineer case study. Design rationale lives in [`DESIGN.md`](./DESIGN.md).

## What it does

For each account, the pipeline produces:

1. **`qbr_brief.md`** — internal AM brief: goals, what's working, top adoption gaps, top upsell opportunities, evidence inline, confidence labels.
2. **`qbr_deck.md`** — customer-facing QBR outline: goals → performance → gaps → recommendations.
3. **Structured intermediates** (`goals.json`, `usage_facts.json`, `gaps.json`, `opportunities.json`) so each stage is auditable.

## How it works (one paragraph)

A five-stage prompt chain over structured JSON.
1. **Goal extraction** runs map-reduce over the transcripts and produces a list of customer goals with transcript-line citations.
2. **Usage analysis** is a deterministic transform of the spreadsheet row into per-feature facts (owned / active / usage / benchmark).
3. **Gap detection** is a rule pass — features that are owned-but-underused AND map to a stated goal.
4. **Opportunity mapping** is rules-driven candidate generation with LLM-written rationales.
5. **Narrative generation** writes the brief and deck from those four artifacts; it cannot invent claims because it only quotes from evidence the prior stages collected.

## Quickstart

```bash
# 1. install
mise setup

# 2. set the API key
export OPENAI_API_KEY=sk-...

# 3. ingest source data into data/
python -m src.ingest

# 4. run the pipeline for one account
python -m src.pipeline --account meridian
python -m src.pipeline --account northfield

# 5. read the output
open output/meridian/qbr_brief.md
```

`--account all` runs every account; `--stage s1` runs a single stage; `--from s3` resumes from a stage if earlier artifacts already exist.

## Project layout

```
data/                source transcripts, usage.xlsx, feature_catalog.json
src/                 ingest, stages/, schemas, llm wrapper, pipeline orchestrator
prompts/             one .md per LLM-driven stage
output/<account>/    all generated artifacts for that account
tests/               schema + evidence smoke tests
DESIGN.md            architecture, decisions, eval approach
```

## The accounts in the dataset

| Transcript name      | Usage-row name      | Vertical             | Transcripts | Notes |
|----------------------|---------------------|----------------------|-------------|-------|
| Meridian Furniture   | Auscraft Furniture  | Retail / Furniture   | 11          | Full lifecycle: onboarding → AI setup → phones → 3 account reviews |
| Northfield Electrical| Mr Sparky           | Home Services / Electrical | 8     | Sales → onboarding → AI setup → upgrade review |
| Apex                 | —                   | —                    | 1 (intro)   | Sales lead, not a customer — pipeline returns "insufficient data" |

Transcript-name ↔ usage-row mapping is in `data/account_map.json`.

## Design principles (short version)

- **JSON is the contract between stages.** Prose only at the final step.
- **Every claim cites evidence.** Transcript line+timestamp or specific usage column.
- **Rules judge, the LLM writes.** Gaps and opportunities are surfaced by deterministic rules over usage + goals + the feature catalog. The LLM narrates what the rules surface — it does not decide what counts.
- **Confidence labels everywhere.** Low-confidence claims surface in a "needs AM review" section, not the main brief.

Full reasoning in [`DESIGN.md`](./DESIGN.md).

## Status

Design document complete. Implementation in progress.

## Known gaps vs the brief

- **No email parsing** — the dataset contains no email threads. The ingest stage supports them but isn't exercised on this submission.
- **"Top 3" cutoff** — we rank and score, then take top-3. Variable-length output is available behind a flag.
- **Deck rendering** — output is markdown. PPTX/PDF render is out of scope for the timebox.
