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
  // Temporal trail derived from linked evidence in stage 1
  mentioned_in_files?: string[]
  first_mentioned_date?: string | null
  last_mentioned_date?: string | null
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
  node: string
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
  // Merged evidence map from brief.json — lets the UI resolve cross-stage
  // evidence_ids (e.g. s4 referencing s1's transcript quotes).
  merged_evidence: Record<string, Evidence>
}

export type SettingsAccount = {
  id: string
  display_name: string
  vertical: string
  xlsx_org_name: string | null
  is_lead: boolean
  transcript_count: number
  email_count: number
}

export type SettingsFeature = {
  id: string
  label: string
  goal_categories: string[]
  ownership_rule: string
  active_signal: string
  // Optional copy from the catalog JSON. When set, these strings flow straight
  // into the brief instead of the templated fallback.
  gap_message: string | null
  recommended_action: string | null
  opportunity_message: string | null
}

export type SettingsSnapshot = {
  configuration: {
    openai_key_set: boolean
    pipeline_version: string
    models: {
      extraction: string
      narrative: string
    }
    max_extraction_tokens: number
    extraction_temperature: number
    extraction_seed: number | null
    config_file: string
  }
  discovery: {
    aliases: Record<string, string>
    aliases_path: string
    xlsx: {
      path: string
      exists: boolean
      row_count: number
    }
    accounts: SettingsAccount[]
  }
  feature_catalog: SettingsFeature[]
  data_paths: {
    input: string
    output: string
  }
}
