// TypeScript mirror of backend/src/schemas.py. Keep these in sync; any change
// here MUST be reflected there and vice versa.

export type Confidence = "high" | "med" | "low"
export type Status = "complete" | "insufficient_data" | "failed"

export type TranscriptLocator = {
  kind: "transcript"
  file: string
  line_start: number
  line_end: number
  timestamp: string
}

export type UsageLocator = {
  kind: "usage"
  column: string
}

export type EmailLocator = {
  kind: "email"
  file: string
  line_start: number
  line_end: number
}

export type Locator = TranscriptLocator | UsageLocator | EmailLocator

export type Evidence = {
  id: string
  source: "transcript" | "usage" | "email"
  locator: Locator
  quote: string
  context_before?: string | null
  context_after?: string | null
}

export type Goal = {
  id: string
  statement: string
  category: string
  confidence: Confidence
  evidence_ids: string[]
}

export type WorkingItem = {
  feature: string
  summary: string
  signal: string
  confidence: Confidence
  evidence_ids: string[]
}

export type Gap = {
  id: string
  feature: string
  severity: number
  goal_links: string[]
  summary: string
  recommended_action: string
  confidence: Confidence
  evidence_ids: string[]
}

export type Opportunity = {
  id: string
  product: string
  fit_score: number
  goal_links: string[]
  rationale: string
  signals: string[]
  confidence: Confidence
  evidence_ids: string[]
}

export type DeckOutline = {
  goals: string[]
  performance: string[]
  gaps: string[]
  recommendations: string[]
}

export type ConfidenceSummary = {
  high: number
  med: number
  low: number
}

export type ReviewBanner = {
  severity: "info" | "warning"
  message: string
}

export type Brief = {
  account_id: string
  account_name: string
  vertical: string
  run_id: string
  generated_at: string
  pipeline_version: string
  status: Status
  status_reason?: string | null
  review_banner?: ReviewBanner | null
  confidence_summary: ConfidenceSummary
  goals: Goal[]
  whats_working: WorkingItem[]
  gaps: Gap[]
  opportunities: Opportunity[]
  outline: DeckOutline
  evidence: Record<string, Evidence>
}

export type AccountSummary = {
  id: string
  name: string
  vertical: string
  status: Status | "not_run"
  last_run_at?: string | null
  error?: string | null
}

export type PipelineStage = {
  id: string
  name: string
  description: string
  artifact: string
  is_llm: boolean
  status: "ok" | "missing"
  data: unknown | null
  trace: {
    stage: string
    model: string
    system_prompt: string
    user_prompt: string
    user_prompt_chars: number
    raw_response: unknown
  } | null
}

export type PipelineSnapshot = {
  account_id: string
  stages: PipelineStage[]
}
