import { useEffect, useState } from "react"
import {
  Check,
  Circle,
  ChevronRight,
  FileJson,
  Loader2,
  MessageSquare,
  Minus,
  Quote,
  Sparkles,
  X,
} from "lucide-react"

import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { EvidenceRail } from "@/components/EvidenceRail"
import { getPipeline } from "@/lib/api"
import { cn } from "@/lib/utils"
import type { RunState } from "@/lib/useRunPipeline"
import type { Evidence, PipelineSnapshot, PipelineStage } from "@/types"

// Visual state of a single stage card. Derived from (liveRun, snapshot).
type StageVisualState = "pending" | "running" | "complete" | "skipped" | "failed" | "missing"

// Canonical 6-stage shape used as a scaffold while we haven't fetched the snapshot
// yet (e.g. user clicks Run before this component has mounted).
const CANONICAL_NODES = [
  { id: "s0", node: "ingest", name: "Ingest", is_llm: false },
  { id: "s1", node: "extract_goals", name: "Goal extraction", is_llm: true },
  { id: "s2", node: "analyze_usage", name: "Usage analysis", is_llm: false },
  { id: "s3", node: "detect_gaps", name: "Gap detection", is_llm: false },
  { id: "s4", node: "detect_opportunities", name: "Opportunity mapping", is_llm: false },
  { id: "s5", node: "assemble_brief", name: "Brief assembly", is_llm: false },
] as const

export function PipelinePane({
  accountId,
  liveRun,
}: {
  accountId: string
  liveRun: RunState
}) {
  // The problem is: the AM needs to see WHAT the agent is doing in real time during
  // a run, AND inspect the artifacts each stage produced after it finishes. Those
  // two needs share the same UI surface (the Pipeline tab).
  // The way we solve this is: fetch the snapshot on mount + whenever liveRun
  // transitions out of "running" (so a completed run shows fresh artifacts). During
  // a run, derive each stage card's visual state from liveRun.completed and the
  // next-up node. After the run, fall back to the snapshot's per-stage status.
  // flow: ResultsPane (view=pipeline) -> PipelinePane <-- HERE
  const [snapshot, setSnapshot] = useState<PipelineSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (liveRun.status === "running") return // skip during run; refetch on completion
    let cancelled = false
    setLoading(true)
    setError(null)
    getPipeline(accountId)
      .then(s => { if (!cancelled) setSnapshot(s) })
      .catch(err => { if (!cancelled) setError(err instanceof Error ? err.message : String(err)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [accountId, liveRun.status])

  // Build the stage list to render. Prefer the snapshot (has data + traces).
  // While a run is in flight without a snapshot yet, fall back to the canonical
  // scaffolding so the tab isn't blank.
  const stages: PipelineStage[] = snapshot?.stages ?? CANONICAL_NODES.map(c => ({
    id: c.id,
    node: c.node,
    name: c.name,
    description: "",
    artifact: "",
    is_llm: c.is_llm,
    status: "missing",
    data: null,
    trace: null,
  }))

  const nextUpNode = nextRunningNode(liveRun)

  if (loading && !snapshot && liveRun.status === "idle") {
    return <div className="p-2 text-sm text-muted-foreground">Loading pipeline trace…</div>
  }
  if (error && !snapshot) {
    return <div className="p-2 text-sm text-destructive">Couldn't load pipeline trace: {error}</div>
  }

  const ranCount = stages.filter(s => stageVisualState(s, liveRun, nextUpNode) === "complete").length

  return (
    <div className="space-y-3">
      <PipelineHeader
        ran={ranCount}
        total={stages.length}
        liveRun={liveRun}
      />
      <ol className="space-y-2.5">
        {stages.map(stage => (
          <StageCard
            key={stage.id}
            stage={stage}
            visual={stageVisualState(stage, liveRun, nextUpNode)}
            mergedEvidence={snapshot?.merged_evidence ?? {}}
            accountId={accountId}
          />
        ))}
      </ol>
    </div>
  )
}

function PipelineHeader({
  ran,
  total,
  liveRun,
}: {
  ran: number
  total: number
  liveRun: RunState
}) {
  const tone =
    liveRun.status === "failed"
      ? "text-rose-700"
      : liveRun.status === "running"
      ? "text-primary"
      : liveRun.status === "complete"
      ? "text-emerald-700"
      : "text-muted-foreground"
  const StatusIcon =
    liveRun.status === "failed"
      ? X
      : liveRun.status === "running"
      ? Loader2
      : liveRun.status === "complete"
      ? Check
      : Circle

  return (
    <div className="flex items-center justify-between gap-2 text-xs">
      <div className={cn("inline-flex items-center gap-2 font-semibold uppercase tracking-wider", tone)}>
        <StatusIcon
          className={cn(
            "h-3.5 w-3.5",
            liveRun.status === "running" && "animate-spin",
          )}
        />
        {liveRun.status === "idle" ? "Pipeline trace" : `Pipeline ${liveRun.status}`}
      </div>
      <span className="text-muted-foreground">
        {ran} of {total} stages {liveRun.status === "running" ? "complete" : "ran"}
      </span>
    </div>
  )
}

function StageCard({
  stage,
  visual,
  mergedEvidence,
  accountId,
}: {
  stage: PipelineStage
  visual: StageVisualState
  mergedEvidence: Record<string, Evidence>
  accountId: string
}) {
  const meta = VISUAL_META[visual]
  const Icon = meta.icon
  const hasData = stage.data !== null
  // Walk this stage's data, collect every evidence_id it references, then resolve
  // each against the merged evidence map (handles cross-stage refs like s4
  // pointing at s1's transcript quotes).
  const referencedEvidenceIds = hasData ? collectEvidenceIds(stage.data) : []
  const resolvedEvidenceIds = referencedEvidenceIds.filter(id => id in mergedEvidence)

  // Drama: future stages fade well back, the running stage pops with a blue glow
  // + slight bloom, completed stages settle with a quiet emerald hairline, failed
  // stages get a red glow for visibility.
  const cardClass = cn(
    "transition-all duration-300 ease-out",
    visual === "pending" && "opacity-40 grayscale",
    visual === "missing" && "opacity-50",
    visual === "skipped" && "opacity-45 grayscale",
    visual === "running" && "scale-[1.015] ring-2 ring-primary shadow-lg shadow-primary/15",
    visual === "complete" && "ring-1 ring-emerald-200/70",
    visual === "failed" && "ring-2 ring-rose-300 shadow-lg shadow-rose-200/40",
  )

  return (
    <li>
      <Card className={cardClass}>
        <CardContent className="space-y-2.5 p-4">
          <div className="flex items-start gap-3">
            <div
              className={cn(
                "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md font-mono text-[11px] font-semibold tabular-nums transition-colors duration-300",
                visual === "running"
                  ? "bg-primary text-primary-foreground shadow-sm shadow-primary/30"
                  : visual === "complete"
                  ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200"
                  : visual === "failed"
                  ? "bg-rose-50 text-rose-700 ring-1 ring-rose-200"
                  : "bg-muted text-muted-foreground",
              )}
            >
              {stage.id}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  {stage.name}
                  {stage.is_llm && (
                    <Badge variant="outline" className="gap-1 text-[10.5px]">
                      <Sparkles className="h-3 w-3" />
                      LLM
                    </Badge>
                  )}
                </div>
                <div className={cn("inline-flex items-center gap-1.5 text-[11px]", meta.color)}>
                  <Icon className={cn("h-3.5 w-3.5", visual === "running" && "animate-spin")} />
                  <span>{meta.label}</span>
                </div>
              </div>
              {stage.description && (
                <p className="mt-0.5 text-[13px] leading-relaxed text-muted-foreground">{stage.description}</p>
              )}
              {stage.artifact && (
                <div className="mt-1.5 inline-flex items-center gap-1 font-mono text-[11px] text-muted-foreground">
                  <FileJson className="h-3 w-3" />
                  data/output/&lt;account&gt;/{stage.artifact}
                </div>
              )}
            </div>
          </div>

          {stage.trace && visual !== "running" && (
            <Disclosure
              label="LLM trace"
              icon={MessageSquare}
              count={`${stage.trace.user_prompt_chars.toLocaleString()} chars in · ${stage.trace.model}`}
            >
              <div className="space-y-3 text-sm">
                <div>
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">System prompt</div>
                  <PromptBlock text={stage.trace.system_prompt} />
                </div>
                <div>
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">User prompt (rendered corpus)</div>
                  <PromptBlock text={stage.trace.user_prompt} maxLines={20} />
                </div>
                <div>
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Raw LLM response (before linking)</div>
                  <JsonBlock data={stage.trace.raw_response} />
                </div>
              </div>
            </Disclosure>
          )}

          {resolvedEvidenceIds.length > 0 && visual !== "running" && (
            <Disclosure
              label="Resolved evidence"
              icon={Quote}
              count={
                referencedEvidenceIds.length === resolvedEvidenceIds.length
                  ? `${resolvedEvidenceIds.length} referenced`
                  : `${resolvedEvidenceIds.length} of ${referencedEvidenceIds.length} resolved`
              }
            >
              <EvidenceRail
                evidenceIds={resolvedEvidenceIds}
                evidence={mergedEvidence}
                accountId={accountId}
              />
            </Disclosure>
          )}

          {hasData && visual !== "running" && (
            <Disclosure label="Artifact JSON" icon={FileJson}>
              <JsonBlock data={stage.data} />
            </Disclosure>
          )}
        </CardContent>
      </Card>
    </li>
  )
}

// ─────────────────────────── helpers ───────────────────────────

function stageVisualState(
  stage: PipelineStage,
  liveRun: RunState,
  nextUpNode: string | null,
): StageVisualState {
  // No active run — use whatever the on-disk snapshot says.
  if (liveRun.status === "idle") {
    return stage.status === "ok" ? "complete" : "missing"
  }
  // A run is or was happening — derive from live events.
  if (liveRun.completed.includes(stage.node)) return "complete"
  if (liveRun.status === "running") {
    return stage.node === nextUpNode ? "running" : "pending"
  }
  if (liveRun.status === "failed") {
    // Stages that didn't complete during a failed run: the failing one shows
    // failed, downstream stages show pending (they never got a chance).
    return stage.node === nextUpNode ? "failed" : "pending"
  }
  // status === "complete" but this stage didn't fire = conditional skip
  return "skipped"
}

function nextRunningNode(liveRun: RunState): string | null {
  if (liveRun.status !== "running") return null
  const list = liveRun.stages.length > 0 ? liveRun.stages : CANONICAL_NODES.map(c => c.node)
  for (const node of list) {
    if (!liveRun.completed.includes(node)) return node
  }
  return null
}

const VISUAL_META: Record<
  StageVisualState,
  { label: string; color: string; icon: typeof Check }
> = {
  pending: { label: "pending", color: "text-muted-foreground", icon: Circle },
  running: { label: "running", color: "text-primary", icon: Loader2 },
  complete: { label: "complete", color: "text-emerald-700", icon: Check },
  skipped: { label: "skipped", color: "text-muted-foreground/70", icon: Minus },
  failed: { label: "failed", color: "text-rose-700", icon: X },
  missing: { label: "not run", color: "text-slate-400", icon: Circle },
}

// ─────────────────────────── disclosures ───────────────────────────

function Disclosure({
  label,
  icon: Icon,
  count,
  children,
}: {
  label: string
  icon: React.ComponentType<{ className?: string }>
  count?: string
  children: React.ReactNode
}) {
  return (
    <details className="group rounded-md border border-border bg-muted/30">
      <summary className="flex cursor-pointer select-none items-center gap-2 px-3 py-2 text-xs font-medium text-foreground transition-colors hover:bg-muted/60">
        <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
        <Icon className="h-3.5 w-3.5 text-muted-foreground" />
        <span>{label}</span>
        {count && <span className="ml-auto font-normal text-muted-foreground">{count}</span>}
      </summary>
      <div className="border-t border-border bg-card p-3">{children}</div>
    </details>
  )
}

// Shared <pre> base. whitespace-pre-wrap preserves newlines AND wraps long
// lines; break-words breaks unbroken tokens (URLs, long JSON string values) so
// they don't blow out the layout. Vertical scroll still kicks in past max-h.
const CODE_BLOCK_BASE =
  "overflow-y-auto rounded-md border border-border bg-slate-50 p-3 text-[12px] leading-relaxed whitespace-pre-wrap break-words"

function PromptBlock({ text, maxLines }: { text: string; maxLines?: number }) {
  const lines = text.split("\n")
  const needsClip = maxLines !== undefined && lines.length > maxLines
  if (!needsClip) {
    return <pre className={cn(CODE_BLOCK_BASE, "max-h-[400px] text-slate-700")}>{text}</pre>
  }
  const preview = lines.slice(0, maxLines).join("\n") + "\n…"
  return (
    <details className="group">
      <summary className="cursor-pointer text-[11px] text-muted-foreground transition-colors hover:text-foreground">
        <span className="group-open:hidden">Show full ({lines.length.toLocaleString()} lines)</span>
        <span className="hidden group-open:inline">Collapse to preview</span>
      </summary>
      <pre className={cn(CODE_BLOCK_BASE, "mt-2 max-h-[300px] text-slate-700 group-open:hidden")}>
        {preview}
      </pre>
      <pre className={cn(CODE_BLOCK_BASE, "mt-2 hidden max-h-[600px] text-slate-700 group-open:block")}>
        {text}
      </pre>
    </details>
  )
}

function JsonBlock({ data }: { data: unknown }) {
  return (
    <pre className={cn(CODE_BLOCK_BASE, "max-h-[480px] font-mono text-slate-800")}>
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}

function collectEvidenceIds(data: unknown): string[] {
  // The problem is: a stage's data contains evidence_ids arrays nested inside
  // goals/gaps/opportunities/whats_working. We don't want to special-case each
  // shape — the same key always means the same thing.
  // The way we solve this is: walk the tree generically, collect every string
  // value that appears inside an `evidence_ids` array. Stable ordered list,
  // deduped.
  const seen = new Set<string>()
  const ordered: string[] = []
  function walk(node: unknown): void {
    if (Array.isArray(node)) {
      for (const item of node) walk(item)
      return
    }
    if (typeof node !== "object" || node === null) return
    const rec = node as Record<string, unknown>
    for (const key of Object.keys(rec)) {
      if (key === "evidence_ids" && Array.isArray(rec[key])) {
        for (const id of rec[key] as unknown[]) {
          if (typeof id === "string" && !seen.has(id)) {
            seen.add(id)
            ordered.push(id)
          }
        }
        continue
      }
      walk(rec[key])
    }
  }
  walk(data)
  return ordered
}
