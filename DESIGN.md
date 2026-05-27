# AI Account Review & Expansion Agent — System Design

## 1. Frame

**What it is.** A local LangGraph pipeline that ingests one account's call transcripts + usage data and writes static JSON artifacts, plus a React UI that reads those artifacts and renders a QBR pack with confidence labels and click-through evidence on every claim.

**What it is not.** An agentic, tool-using thing. No CRM connector, no real-time sync, no DB, no auth. Local-only, single-user demo.

**Operating definitions** (the brief doesn't pin these — we do):
- **Goal**: a stated customer objective with a verb + outcome, traceable to ≥1 transcript quote.
- **Adoption gap**: a Podium feature the account owns/could enable whose usage is materially below benchmark **AND** which maps to a stated goal.
- **Upsell opportunity**: a Podium product the account does *not* own, where stated goals + current behavior suggest fit.

Output is ranked + scored, no fixed top-N cutoff — the UI handles whatever length is justified by the evidence.

## 2. Architecture

```
                ┌────────────────────────────────────────┐
                │   React UI                             │
                │   shadcn/ui · Tailwind · Lucide · Inter│
                │  ┌──────────┬──────────────────────┐   │
                │  │ Account  │  Results pane        │   │
                │  │ list     │  (evidence-first)    │   │
                │  └──────────┴──────────────────────┘   │
                └─────────────────┬──────────────────────┘
                                  │ 3 sync HTTP endpoints
                ┌─────────────────▼──────────────────────┐
                │   FastAPI (tiny, local)                │
                │   GET /accounts                        │
                │   POST /accounts/{id}/run  (blocks)    │
                │   GET /accounts/{id}/brief             │
                └─────────────────┬──────────────────────┘
                                  │ in-process call
                ┌─────────────────▼──────────────────────┐
                │   LangGraph pipeline                   │
                │   s1 → s2 → s3 → s4 → s5               │
                │   typed state · retries · branches     │
                └─────────────────┬──────────────────────┘
                                  │ writes
                ┌─────────────────▼──────────────────────┐
                │   output/<account>/*.json              │
                │   corpus · goals · usage_facts · gaps  │
                │   · opportunities · brief              │
                └────────────────────────────────────────┘
```

The five-stage pipeline:

```
transcripts/*.txt  ──┐
emails/*.eml       ──┼──► (0) Ingest & Normalize ──►  corpus.json
usage.xlsx         ──┘

(1) Goal Extraction         — LLM, map-reduce per transcript  ──►  goals.json
(2) Usage Analysis          — deterministic transform         ──►  usage_facts.json
(3) Gap Detection           — RULES, not LLM                  ──►  gaps.json
(4) Opportunity Mapping     — rules + LLM rationale           ──►  opportunities.json
(5) Narrative Generation    — LLM, brief + outline structure  ──►  brief.json
```

## 3. Design decisions (and why)

### 3.1 JSON files as the contract and the store
Every stage reads structured JSON and writes structured JSON. Prose only appears at the final narrative stage. No database — the filesystem is the database. Each artifact is a versioned file at `output/<account>/<artifact>.json`. The UI reads brief.json directly via the API; auditing means opening the per-stage files. Each artifact is independently inspectable, diffable, and re-runnable.

### 3.2 Evidence-first extraction
Every goal, gap, and opportunity carries `evidence: [{source, locator, quote}]` — transcript line+timestamp, or a specific usage-data column. The narrator quotes from evidence; it cannot invent. The UI is built around this: evidence isn't hidden behind a tooltip, it's a first-class element. Claims without evidence are dropped before they reach the UI.

### 3.3 Map-reduce on transcripts
Meridian has 11 transcripts (~5k lines); Northfield has 8 (~6k lines). Naive concatenation explodes the prompt and degrades extraction. Per-transcript extract → per-account merge, each step a small focused prompt.

### 3.4 Rules judge, LLM writes
Gap detection is a deterministic rule pass over `usage_facts × goals × feature_catalog`. The LLM does not decide what counts as a gap — it only narrates gaps the rules surface. Single biggest hallucination-reduction lever.

Opportunity mapping is hybrid: rules generate candidates from owned-vs-unowned products + goal alignment; the LLM writes the rationale and scores fit qualitatively.

### 3.5 Feature catalog is the project's spine
A hand-built `feature_catalog.json` maps:
- Podium product name (e.g. "Webchat")
- Usage columns it appears in (e.g. `WEBCHAT LEADS RECEIVED LAST 30DAYS`)
- Goal-types it typically serves (e.g. `lead-response`, `inbound-volume`)
- A baseline benchmark for "in use" vs "underused"

Without this, the agent can't reason. With it, half the pipeline is just lookups.

### 3.6 LangGraph for orchestration
LangGraph wraps the five stages as nodes in a typed state graph. What it buys us:
- **Retries with backoff** per node — transient OpenAI errors don't blow up the whole run.
- **Conditional branches** — Apex routes to an "insufficient data" terminal node instead of running the full pipeline.
- **Typed state** — the graph state is a single pydantic model; each node mutates a slice. Refactoring stages is safer.
- **Stage skipping** — if `goals.json` already exists for an account and the input hasn't changed, the node short-circuits. The JSON files on disk are the "checkpoint" — no LangGraph SqliteSaver needed.

Streaming/event emission is in LangGraph's toolkit but we're not using it in this build (see §3.7).

### 3.7 Synchronous run, no progress streaming
`POST /accounts/{id}/run` blocks for the duration of the pipeline (~30s–2min) and returns the brief on completion. The UI shows a loading state. No SSE, no polling — both add code and complexity for an experience the demo doesn't need at localhost latency. Trivially upgradable later if progress UX becomes important.

### 3.8 Two outputs from one substrate
Internal brief: frank, evidence inline, low-confidence claims surfaced.
Customer-facing outline: positive framing, structured headings (Goals → Performance → Gaps → Recommendations).
Same JSON inputs → different prompt personas. Both views rendered in the UI from the same `brief.json` — no separate file artifact.

### 3.9 Confidence labels everywhere
Each goal/gap/opportunity carries `confidence: high | med | low`. UI shows a colored badge next to every claim. Low-confidence claims are grouped under "needs AM review" at the bottom of each section. Addresses "low trust in AI outputs" directly — the AM sees what the agent is unsure about, and verification is one click away.

## 4. Data realities

- **No emails in the dataset.** Brief says "calls + emails"; we have only calls. Pipeline supports both (stage 0 normalizes into the same `corpus.json` shape), but email parsing is unexercised on this submission.
- **Account name normalization.** Transcripts say "Meridian Furniture" / "Northfield Electrical"; usage data says "Auscraft Furniture" / "Mr Sparky". Per Podium, this was a dataset error — they refer to the same accounts. Stage 0 normalizes to one canonical name per account.
- **Apex has one intro call and no usage row.** Not a QBR candidate. LangGraph routes Apex to an "insufficient data — sales lead, not a customer" terminal node, and the UI surfaces this clearly rather than hallucinating a QBR.

## 5. File layout

```
podium-case-study/
├── data/
│   ├── input/                       # raw transcripts + usage.xlsx (gitignored)
│   ├── output/
│   │   └── <account>/               # JSON artifacts, one dir per account
│   │       ├── corpus.json
│   │       ├── goals.json
│   │       ├── usage_facts.json
│   │       ├── gaps.json
│   │       ├── opportunities.json
│   │       └── brief.json
│   └── feature_catalog.json         # hand-built
├── backend/
│   ├── src/
│   │   ├── ingest.py                # transcript parser, xlsx loader, name normalizer
│   │   ├── stages/
│   │   │   ├── s1_goals.py          # map-reduce LLM extraction
│   │   │   ├── s2_usage.py          # deterministic
│   │   │   ├── s3_gaps.py           # rules
│   │   │   ├── s4_opportunities.py  # rules + LLM rationale
│   │   │   └── s5_narrative.py      # LLM, brief + outline
│   │   ├── graph.py                 # LangGraph state machine wiring s1..s5
│   │   ├── schemas.py               # pydantic models for every artifact
│   │   ├── llm.py                   # OpenAI wrapper, structured output
│   │   ├── store.py                 # JSON read/write helpers, atomic writes
│   │   └── api.py                   # FastAPI, 3 endpoints
│   ├── prompts/
│   │   ├── goal_extract.md
│   │   ├── opportunity_rationale.md
│   │   └── narrative.md
│   ├── tests/
│   └── pyproject.toml
├── web/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── AccountList.tsx       # left pane
│   │   │   ├── ResultsPane.tsx       # right pane: goals/gaps/opps/outline
│   │   │   ├── EvidenceRail.tsx      # evidence shown alongside claims, not behind tooltips
│   │   │   ├── ConfidenceBadge.tsx
│   │   │   ├── RunButton.tsx
│   │   │   └── DeckOutline.tsx       # customer-facing outline view
│   │   ├── lib/api.ts                # 3 fetch wrappers
│   │   └── types.ts                  # mirrors backend schemas
│   ├── package.json
│   └── vite.config.ts
├── DESIGN.md
└── README.md
```

## 6. API surface

Three endpoints. All synchronous. No auth.

| Method | Path                          | Returns                                                  |
|--------|-------------------------------|----------------------------------------------------------|
| GET    | `/accounts`                   | `[{id, name, vertical, has_brief, last_run_at}]`         |
| POST   | `/accounts/{id}/run`          | Blocks until pipeline finishes; returns `brief.json`     |
| GET    | `/accounts/{id}/brief`        | Reads and returns `output/{id}/brief.json` (incl. embedded evidence) |

Evidence is embedded inline in `brief.json` — no separate `/evidence/{id}` endpoint needed at this scale.

## 7. Tech choices

**Backend**
- Python, FastAPI, LangGraph, pydantic, openpyxl
- OpenAI: `gpt-5.4-mini` for stage-1 extraction and stage-4 opportunity rationale (high volume, structured output); `gpt-5.5` for stage-5 narrative (one call per account, quality matters). Configurable in `llm.py`.
- Storage: JSON files on disk. No database.
- Retries: LangGraph node-level, exponential backoff.

**Frontend**
- React + Vite + TypeScript
- Tailwind + shadcn/ui
- Lucide icons
- Inter font

**Visual style**
- White / light surfaces
- Rounded cards
- Muted borders
- Restrained purple accents (Podium-adjacent without aping it)
- Evidence-first layout: claims and their citations live side by side, not in a modal or tooltip. The AM should be able to scan a claim and its source line in one eye-movement.

## 8. What we'll cut if the timebox bites

In priority order:
1. Customer-facing outline view (internal brief is the core deliverable).
2. Opportunity LLM rationale (rules-only candidates with stub rationale).
3. Map-reduce on transcripts (single concatenated prompt — works at this scale, less robust).
4. Apex "insufficient data" routing (just skip it).

Ingest → goals → gaps → internal brief in the UI is the must-ship path.

## 9. Eval & trust

- **Schema validation** at every stage boundary (pydantic). If JSON doesn't conform, the LangGraph node retries, then fails the run loudly.
- **Evidence verification**: smoke test picks N random claims from `brief.json`, checks each against the cited transcript line.
- **Confidence audit**: count of high/med/low claims per account. If a brief is mostly low-confidence, the UI surfaces a "this account needs human review" banner at the top.
- **Traceability built into the UI**: every claim is rendered next to its evidence. Reviewers don't have to trust the agent — they can verify in one eye-movement.

## 10. Resolved questions

Per Podium:
- The transcript/usage name mismatch was a dataset error — they refer to the same accounts. Stage 0 normalizes.
- No fixed top-N cutoff — output is ranked + scored, length follows the evidence.
- Customer-facing deck is a structured outline rendered in the UI, not a separate file artifact.
