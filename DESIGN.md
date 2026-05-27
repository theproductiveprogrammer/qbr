# AI Account Review & Expansion Agent — System Design

## 1. Frame

**What it is.** A prompt-chained pipeline that takes one account's call transcripts + usage data and emits a QBR pack (internal brief + customer-facing deck).

**What it is not.** An agentic, tool-using thing. No vector DB, no CRM connector, no real-time sync. The brief explicitly excludes those.

**Operating definitions** (the brief doesn't pin these — we do):
- **Goal**: a stated customer objective with a verb + outcome, traceable to ≥1 transcript quote. ("Increase Google reviews", not "improve marketing".)
- **Adoption gap**: a Podium feature the account *owns or could enable* whose usage is materially below a benchmark, **AND** which maps to a stated goal.
- **Upsell opportunity**: a Podium product the account does *not* own, where stated goals + current behavior suggest fit.

These three definitions are the spine. Everything downstream depends on them holding.

## 2. Pipeline

```
                                                       ┌─────────────────────┐
transcripts/*.txt  ──┐                                  │  feature_catalog    │
emails/*.eml       ──┼──► (0) Ingest & Normalize ──►  account_corpus.json   │ (static)
usage.xlsx         ──┘                                  └─────────────────────┘
                                                                  │
                          ┌──────────────────────────┐            │
account_corpus.json ──►   │ (1) Goal Extraction       │ ──►  goals.json
                          │  map-reduce per transcript│      [{goal, evidence:[...]}]
                          └──────────────────────────┘
                          ┌──────────────────────────┐
account_corpus.json ──►   │ (2) Usage Analysis        │ ──►  usage_facts.json
+ feature_catalog   ──►   │  deterministic transform  │      {feature: {owned, active,
                          └──────────────────────────┘                  usage_pct, benchmark}}

goals.json          ──┐   ┌──────────────────────────┐
usage_facts.json    ──┼──►│ (3) Gap Detection         │ ──►  gaps.json
feature_catalog     ──┘   │  RULES, not LLM           │      [{feature, goal_link,
                          └──────────────────────────┘             severity, evidence}]

gaps.json           ──┐   ┌──────────────────────────┐
usage_facts.json    ──┼──►│ (4) Opportunity Mapping   │ ──►  opportunities.json
product_catalog     ──┘   │  rules + LLM rationale    │      [{product, rationale,
                          └──────────────────────────┘             fit_score, signals}]

ALL ARTIFACTS       ──►   ┌──────────────────────────┐ ──►  qbr_brief.md   (internal)
                          │ (5) Narrative Generation  │      qbr_deck.md   (customer)
                          └──────────────────────────┘
```

## 3. Design decisions (and why)

### 3.1 JSON profile as the contract
Every stage reads structured JSON and writes structured JSON. Prose only appears at the final narrative stage. This isolates hallucination risk to one place and makes each stage independently testable.

### 3.2 Evidence-first extraction
Every goal, gap, and opportunity carries `evidence: [{source, locator, quote}]` — transcript line+timestamp, or a specific usage-data column. The narrator quotes from evidence; it cannot invent. If a claim has no evidence, it's dropped.

### 3.3 Map-reduce on transcripts
Meridian has 11 transcripts (~5k lines total); Northfield has 8 (~6k lines). Naive concatenation explodes the prompt and degrades extraction. Per-transcript extract → per-account merge. Each step has a small, focused prompt.

### 3.4 Rules judge, LLM writes
Gap detection is a deterministic rule pass over `usage_facts × goals × feature_catalog`. The LLM does not decide what counts as a gap — it only narrates gaps the rules already surfaced. This is the single biggest hallucination-reduction lever.

Opportunity mapping is hybrid: rules generate candidates from owned-vs-unowned products + goal alignment; LLM writes the rationale and scores fit qualitatively.

### 3.5 Feature catalog is the project's spine
A hand-built JSON file (`feature_catalog.json`) maps:
- Podium product name (e.g. "Webchat")
- Usage columns it appears in (e.g. `WEBCHAT LEADS RECEIVED LAST 30DAYS`)
- The goal-types it typically serves (e.g. `lead-response`, `inbound-volume`)
- A baseline benchmark for "in use" vs "underused"

Without this, the agent can't reason. With it, half the pipeline is just lookups.

### 3.6 Two outputs from one substrate
Internal brief: frank, includes risks, shows evidence inline, calls out low-confidence claims.
Customer deck: positive framing, no evidence sidebar, action-oriented. Same JSON inputs → different prompt personas. Not different facts.

### 3.7 Confidence labels everywhere
Each extracted goal/gap/opportunity carries `confidence: high|med|low`. The internal brief surfaces low-confidence items in a separate "needs AM review" section. This addresses the "low trust in AI outputs" risk directly — the AM sees what the agent is unsure about.

## 4. Data realities (worth calling out)

- **No emails in the dataset.** Brief says "calls + emails", we have only calls. Pipeline supports emails (stage 0 normalizes both into the same `account_corpus.json` shape), but for this submission email parsing is unexercised.
- **Transcript names ≠ usage-data names.** Transcripts: Meridian Furniture, Northfield Electrical, Apex. Usage data: Auscraft Furniture, Mr Sparky, (no Apex). Verticals match — Meridian↔Auscraft (furniture/retail), Northfield↔Mr Sparky (electrical). We treat these as the same account under their transcript-side names and document the mapping in `data/account_map.json`. Worth flagging to the reviewer.
- **Apex has one intro call and no usage row.** Not a QBR candidate. The pipeline returns "insufficient data — sales lead, not a customer" rather than hallucinating a QBR.

## 5. File layout

```
podium-case-study/
├── data/
│   ├── transcripts/                 # copied from requirement/
│   ├── usage.xlsx
│   ├── feature_catalog.json         # hand-built
│   └── account_map.json             # transcript-name ↔ usage-row mapping
├── src/
│   ├── ingest.py                    # transcript parser, xlsx loader, mapper
│   ├── stages/
│   │   ├── s1_goals.py              # map-reduce LLM extraction
│   │   ├── s2_usage.py              # deterministic
│   │   ├── s3_gaps.py               # rules
│   │   ├── s4_opportunities.py      # rules + LLM rationale
│   │   └── s5_narrative.py          # LLM, brief + deck
│   ├── schemas.py                   # pydantic models for every artifact
│   ├── llm.py                       # Anthropic SDK wrapper, prompt caching
│   └── pipeline.py                  # orchestrator
├── prompts/
│   ├── goal_extract.md
│   ├── opportunity_rationale.md
│   ├── narrative_brief.md
│   └── narrative_deck.md
├── output/
│   └── <account>/
│       ├── account_corpus.json
│       ├── goals.json
│       ├── usage_facts.json
│       ├── gaps.json
│       ├── opportunities.json
│       ├── qbr_brief.md
│       └── qbr_deck.md
├── tests/
│   └── eval_spotcheck.py            # samples N claims, prints evidence for human review
├── DESIGN.md
└── README.md
```

## 6. Tech choices

- **Language**: Python — Anthropic SDK is first-class, ecosystem (pydantic, openpyxl) covers what we need.
- **Models**: Sonnet 4.6 for stage-1 extraction (high volume, structured, cheap), Opus 4.7 for stage-5 narrative (one call per account, quality matters).
- **Prompt caching**: account corpus is cached across stages — same transcripts read by stage 1 and stage 5.
- **No vector DB**: full corpus fits in context with caching at this scale.
- **No framework** (no LangChain, no DSPy): five stages of pure functions over JSON is clearer than a graph abstraction.

## 7. What we'll cut if the timebox bites

In priority order to drop:
1. Customer-facing deck (internal brief is the core deliverable).
2. Opportunity mapping LLM rationale (rules-only candidates with stub rationale).
3. Multi-transcript map-reduce (single concatenated prompt with caching — works at this scale but less robust).
4. Apex's "insufficient data" handler (just skip it).

Goal extraction → gap detection → internal brief is the must-ship path.

## 8. Eval & trust

- **Schema validation** at every stage boundary (pydantic). If JSON doesn't conform, the stage fails loudly, not silently.
- **Evidence verification**: a smoke test that picks N random claims from the final brief and checks each one against the cited transcript line.
- **Confidence audit**: count of high/med/low claims per account — if a brief is mostly low-confidence, the agent self-flags "this account needs human review."
- **Human spot-check rubric**: 5 questions the AM can answer in 2 minutes after reading the brief — goal accuracy, gap relevance, opportunity sanity, evidence holds up, would they send the deck.

## 9. Open questions for the reviewer

1. Is the Meridian↔Auscraft / Northfield↔Mr Sparky mapping intentional, or were transcripts meant to match usage names directly?
2. "Top 3" gaps/opportunities is a hard cutoff — is ranked + scored (variable length) acceptable, or strictly top-3?
3. The "QBR deck" — markdown is the lightest path. Is a rendered .pptx/.pdf expected, or is a structured outline enough for evaluation?
