# AI Account Review & Expansion Agent

A local LangGraph pipeline plus a React UI that turns one account's call transcripts + usage data into a QBR-ready brief and a customer-facing outline. Every claim sits next to its evidence — no tooltips, no hidden state.

Built for the Podium AI GTM Engineer case study. Design rationale lives in [`DESIGN.md`](./DESIGN.md).

## What it does

For each account, the pipeline produces:

1. **Internal AM brief** — goals, what's working, ranked adoption gaps, ranked upsell opportunities. Every claim carries a confidence label and inline evidence (transcript line + timestamp, or specific usage column).
2. **Customer-facing outline** — structured QBR headings (Goals → Performance → Gaps → Recommendations) rendered in the UI.
3. **Auditable intermediates** — `goals.json`, `usage_facts.json`, `gaps.json`, `opportunities.json`, `brief.json` written to `output/<account>/`. Each stage is independently inspectable and re-runnable.

The **React UI** is the primary surface:
- **Left pane**: list of accounts with run status.
- **Right pane**: results for the selected account — goals, gaps, opportunities, outline, each item with a confidence badge and its evidence rendered alongside.
- **Run button** triggers the backend pipeline synchronously and renders the brief on completion.

## How it works (one paragraph)

A five-stage prompt chain over structured JSON.
1. **Goal extraction** runs map-reduce over the transcripts and produces a list of customer goals with transcript-line citations.
2. **Usage analysis** is a deterministic transform of the spreadsheet row into per-feature facts (owned / active / usage / benchmark).
3. **Gap detection** is a rule pass — features that are owned-but-underused AND map to a stated goal.
4. **Opportunity mapping** is rules-driven candidate generation with LLM-written rationales.
5. **Narrative generation** writes the brief and deck from those four artifacts; it cannot invent claims because it only quotes from evidence the prior stages collected.

## Quickstart

```bash
# 1. install backend + frontend deps
mise setup
cd web && pnpm install && cd ..

# 2. set the API key
export OPENAI_API_KEY=sk-...

# 3. ingest source data into data/output/
cd backend && .venv/bin/python -m src.ingest

# 4. start the backend (FastAPI on :8000)
python -m src.api

# 5. start the frontend (separate terminal, Vite on :5173)
cd web && pnpm dev

# 6. open the UI and click "Run" on an account
open http://localhost:5173
```

CLI also works for headless runs:

```bash
python -m src.pipeline --account meridian
python -m src.pipeline --account all
python -m src.pipeline --account meridian --from s3   # resume from a stage
```

## Project layout

```
backend/
  data/              source transcripts, usage.xlsx, feature_catalog.json
  output/<account>/  JSON artifacts written by each pipeline stage
  src/               ingest, stages/, LangGraph wiring, schemas, llm, store, api
  prompts/           one .md per LLM-driven stage
  tests/             schema + evidence smoke tests
web/
  src/               React + Vite + TS — AccountList, ResultsPane, EvidenceRail, etc.
DESIGN.md            architecture, decisions, eval approach
```

**Stack**: FastAPI · LangGraph · pydantic · OpenAI (`gpt-5.5` narrative, `gpt-5.4-mini` extraction) · React · Vite · Tailwind · shadcn/ui · Lucide · Inter. No DB, no auth — JSON files on disk.

## The accounts in the dataset

| Account               | Vertical                    | Transcripts | Notes |
|-----------------------|-----------------------------|-------------|-------|
| Meridian Furniture    | Retail / Furniture          | 11          | Full lifecycle: onboarding → AI setup → phones → 3 account reviews |
| Northfield Electrical | Home Services / Electrical  | 8           | Sales → onboarding → AI setup → upgrade review |
| Apex                  | (sales lead)                | 1 (intro)   | Not a customer — pipeline routes to "insufficient data" terminal |

Transcripts use "Meridian / Northfield" and the usage spreadsheet uses "Auscraft / Mr Sparky". Per Podium, this was a dataset error — they refer to the same accounts. Stage 0 normalizes to one canonical name.

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
- **Deck rendering** — customer-facing deck is a structured outline rendered in the UI, not a PPTX/PDF export. Confirmed acceptable with Podium.
