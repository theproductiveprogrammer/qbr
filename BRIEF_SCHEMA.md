# `brief.json` Schema

The contract between the backend pipeline and the React UI. One file per account at `backend/output/<account>/brief.json`. The UI renders entirely from this; the pipeline writes entirely to this.

TypeScript types are the canonical form. Pydantic models in `backend/src/schemas.py` will mirror them 1:1.

## Top-level shape

```typescript
type Brief = {
  // ── Identity & versioning ────────────────────────────────────────────
  account_id: string;                       // canonical id, e.g. "meridian"
  account_name: string;                     // display name
  vertical: string;                         // "Retail / Furniture"
  run_id: string;                           // UUID v4, one per pipeline run
  generated_at: string;                     // ISO 8601, UTC
  pipeline_version: string;                 // semver — UI warns on mismatch

  // ── State (handles Apex empty case) ──────────────────────────────────
  status: "complete" | "insufficient_data" | "failed";
  status_reason?: string;                   // required when status !== "complete"

  // ── Trust signals ────────────────────────────────────────────────────
  review_banner?: {                         // optional banner at top of UI
    severity: "info" | "warning";
    message: string;                        // e.g. "Mostly low-confidence claims — review recommended"
  };
  confidence_summary: { high: number; med: number; low: number };

  // ── Core findings ────────────────────────────────────────────────────
  goals: Goal[];                            // unordered
  whats_working: WorkingItem[];             // unordered
  gaps: Gap[];                              // sorted desc by severity
  opportunities: Opportunity[];             // sorted desc by fit_score

  // ── Customer-facing view ─────────────────────────────────────────────
  outline: DeckOutline;

  // ── Evidence registry ────────────────────────────────────────────────
  evidence: Record<EvidenceId, Evidence>;   // every claim references ids in here
};
```

## Sub-types

```typescript
type EvidenceId = string;                   // "ev_001", "ev_002", ...
type Confidence = "high" | "med" | "low";

type Evidence = {
  id: EvidenceId;
  source: "transcript" | "usage" | "email";
  locator:
    | { kind: "transcript"; file: string; line_start: number; line_end: number; timestamp: string; date?: string }
    | { kind: "usage"; column: string }
    | { kind: "email"; file: string; line_start: number; line_end: number; date: string; sender: string };
  quote: string;                            // exact text from source
  context_before?: string;                  // ~3 surrounding lines for the rail expansion
  context_after?: string;
};

type Goal = {
  id: string;                               // "g_001"
  statement: string;                        // "Increase Google reviews"
  category: string;                         // feature_catalog goal-type, e.g. "reviews"
  confidence: Confidence;
  evidence_ids: EvidenceId[];
  // Temporal trail — derived deterministically by s1 from the dates on linked
  // transcript evidence (deduped by file, ordered chronologically). Lets the UI
  // surface whether a goal is recurring (multiple touchpoints across months) or
  // a one-off mention.
  mentioned_in_files?: string[];
  first_mentioned_date?: string;            // ISO YYYY-MM-DD
  last_mentioned_date?: string;             // ISO YYYY-MM-DD
};

type WorkingItem = {
  feature: string;                          // "Messaging"
  summary: string;                          // "Heavy sustained inbound message volume"
  signal: string;                           // "4,675 inbound messages lifetime, 351 L30"
  confidence: Confidence;
  evidence_ids: EvidenceId[];
};

type Gap = {
  id: string;                               // "gap_001"
  feature: string;                          // "Reviews"
  severity: number;                         // 0–100; drives ranking
  goal_links: string[];                     // goal.id values this gap blocks
  summary: string;                          // narrative for the UI card
  recommended_action: string;               // one short sentence for the AM
  confidence: Confidence;
  evidence_ids: EvidenceId[];
};

type Opportunity = {
  id: string;                               // "opp_001"
  product: string;                          // "Webchat"
  fit_score: number;                        // 0–100; drives ranking
  goal_links: string[];                     // goal.id values this addresses
  rationale: string;                        // LLM-written; quoted from evidence only
  signals: string[];                        // 1–3 short bullets pointing to fit
  confidence: Confidence;
  evidence_ids: EvidenceId[];
};

type DeckOutline = {                        // customer-facing QBR structure
  goals: string[];
  performance: string[];
  gaps: string[];
  recommendations: string[];
};
```

## Design choices (and why)

- **Evidence registry, not inline.** Every claim points to evidence by id; evidence lives once in `brief.evidence`. Lets one transcript line back multiple claims without duplication. UI gets an "all citations" view for free. Trade-off: renderer does a lookup. Cheap.
- **Confidence as `high | med | low`, not a 0–1 float.** LLMs emit categorical labels more reliably under structured output than calibrated probabilities. The UI bucket is the user-facing thing anyway.
- **Severity / fit_score as 0–100.** Numeric so we can rank; the UI buckets into low/med/high pills. More granular than 1–5 without becoming false-precision.
- **`status` at the top level.** One field tells the UI whether to render the results pane or the empty state. Apex sets `status: "insufficient_data"` and most arrays empty.
- **`pipeline_version` is semver.** If the schema breaks compatibly, minor bump; if it breaks, major bump and the UI shows a "regenerate this brief" prompt. Cheap insurance.
- **`goal_links` use ids, not statements.** Renaming a goal won't break cross-references; UI can highlight linked goals on hover.
- **`outline` is structured sections, not free-form markdown.** The customer-facing view renders as cards; structure lets us swap renderers (slides export later) without re-prompting.

## Concrete example (Meridian, abbreviated)

```json
{
  "account_id": "meridian",
  "account_name": "Meridian Furniture Group",
  "vertical": "Retail / Furniture",
  "run_id": "0193f7aa-b120-7be1-b358-3324a3815e28",
  "generated_at": "2026-05-27T04:12:31Z",
  "pipeline_version": "0.1.0",
  "status": "complete",
  "confidence_summary": { "high": 6, "med": 4, "low": 2 },

  "goals": [
    {
      "id": "g_001",
      "statement": "Increase Google reviews",
      "category": "reviews",
      "confidence": "high",
      "evidence_ids": ["ev_001", "ev_002"]
    },
    {
      "id": "g_002",
      "statement": "Improve response speed to inbound web leads",
      "category": "lead_response",
      "confidence": "high",
      "evidence_ids": ["ev_003"]
    }
  ],

  "whats_working": [
    {
      "feature": "Messaging",
      "summary": "Heavy, sustained inbound messaging — the team is responsive on the channel they've adopted.",
      "signal": "1,410 inbound msgs L30, 6,533 lifetime; 2,134 sent L30",
      "confidence": "high",
      "evidence_ids": ["ev_010"]
    }
  ],

  "gaps": [
    {
      "id": "gap_001",
      "feature": "Reviews",
      "severity": 78,
      "goal_links": ["g_001"],
      "summary": "Reviews stated as a top goal but invite volume is flat relative to messaging engagement. 38 invites L30 against 1,410 inbound messages — a fraction of natural ask points.",
      "recommended_action": "Enable automatic review invites on the messaging close-flow.",
      "confidence": "high",
      "evidence_ids": ["ev_001", "ev_011"]
    }
  ],

  "opportunities": [
    {
      "id": "opp_001",
      "product": "Webchat",
      "fit_score": 84,
      "goal_links": ["g_002"],
      "rationale": "Webchat is not enabled (0 L30 webchat leads), yet the team's stated goal is faster lead response. Their messaging volume shows the channel works for them — extending into webchat compounds an already-strong behavior.",
      "signals": [
        "0 webchat leads L30",
        "Stated goal: faster response to inbound leads (ev_003)",
        "High messaging fluency (ev_010) → low adoption friction"
      ],
      "confidence": "high",
      "evidence_ids": ["ev_003", "ev_010", "ev_012"]
    }
  ],

  "outline": {
    "goals": [
      "Increase Google reviews",
      "Improve response speed to inbound web leads"
    ],
    "performance": [
      "Strong messaging adoption: 1,410 inbound / 2,134 outbound L30"
    ],
    "gaps": [
      "Reviews invites flat relative to messaging engagement"
    ],
    "recommendations": [
      "Turn on automatic review invites in messaging close-flow",
      "Enable Webchat to extend messaging behavior to web visitors"
    ]
  },

  "evidence": {
    "ev_001": {
      "id": "ev_001",
      "source": "transcript",
      "locator": {
        "kind": "transcript",
        "file": "call-transcript--meridian-furniture-account-review.txt",
        "line_start": 142,
        "line_end": 145,
        "timestamp": "18:32"
      },
      "quote": "We really want to push our Google reviews up this quarter. We're sitting at 4.6 and we want to break 4.8 by end of Q2.",
      "context_before": "Customer: ...so for the quarter ahead our priorities are...",
      "context_after": "CSM: That tracks — let's look at where invites are coming from..."
    },
    "ev_003": {
      "id": "ev_003",
      "source": "transcript",
      "locator": {
        "kind": "transcript",
        "file": "call-transcript--meridian-furniture-onboarding-kickoff.txt",
        "line_start": 211,
        "line_end": 213,
        "timestamp": "23:04"
      },
      "quote": "If someone fills out a form on our site we want to be back to them within five minutes, ideally less.",
      "context_before": "CSM: How fast do you want to be replying to web leads?",
      "context_after": "Customer: Right now it can be hours and we lose them."
    },
    "ev_010": {
      "id": "ev_010",
      "source": "usage",
      "locator": { "kind": "usage", "column": "RECEIVED MESSAGES LAST 30DAYS" },
      "quote": "1410"
    },
    "ev_012": {
      "id": "ev_012",
      "source": "usage",
      "locator": { "kind": "usage", "column": "WEBCHAT LEADS RECEIVED LAST 30DAYS" },
      "quote": "8"
    }
  }
}
```

## Empty-state example (Apex)

```json
{
  "account_id": "apex",
  "account_name": "Apex",
  "vertical": "Unknown — sales lead only",
  "run_id": "0193f7aa-c211-...",
  "generated_at": "2026-05-27T04:14:02Z",
  "pipeline_version": "0.1.0",

  "status": "insufficient_data",
  "status_reason": "Apex is a sales lead (single intro call, no usage data). QBRs require an active customer relationship.",

  "confidence_summary": { "high": 0, "med": 0, "low": 0 },
  "goals": [],
  "whats_working": [],
  "gaps": [],
  "opportunities": [],
  "outline": { "goals": [], "performance": [], "gaps": [], "recommendations": [] },
  "evidence": {}
}
```

## Validation rules (enforced by pydantic on write)

- Every `evidence_ids` entry in any claim must exist as a key in `evidence`.
- Every `goal_links` entry in `gaps[]` and `opportunities[]` must reference an existing `goals[].id`.
- `gaps` is sorted by `severity` descending; `opportunities` by `fit_score` descending.
- `confidence_summary` counts must equal the total of confidence labels across `goals`, `whats_working`, `gaps`, `opportunities`.
- When `status !== "complete"`, `status_reason` is required and all finding arrays are empty.
- `pipeline_version` is valid semver.

The pipeline fails the run loudly if any of these don't hold rather than writing an inconsistent brief.
