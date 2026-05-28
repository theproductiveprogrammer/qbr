import { Check, Circle, Loader2, Minus, X } from "lucide-react"
import type { ComponentType } from "react"

import { cn } from "@/lib/utils"
import type { RunStatus } from "@/lib/useRunPipeline"

// Display-only labels for the LangGraph node ids. Keep in sync with backend
// PIPELINE_NODES in api.py.
const STAGE_LABEL: Record<string, string> = {
  ingest: "Ingest",
  extract_goals: "Goals",
  analyze_usage: "Usage",
  detect_gaps: "Gaps",
  detect_opportunities: "Opps",
  generate_narrative: "Narrative",
}

type ChipState = "pending" | "running" | "complete" | "skipped" | "failed"

export function RunProgress({
  stages,
  completed,
  status,
  error,
}: {
  stages: string[]
  completed: string[]
  status: RunStatus
  error: string | null
}) {
  // The problem is: the user clicks Run and stares at a spinner for 30-90s with no
  // sense of progress. Without a per-stage indicator, the system feels like a black
  // box even though we're streaming events.
  // The way we solve this is: GitHub-Actions-style chip strip. One chip per stage,
  // state derived from (run status, completed list, my position relative to next-up).
  // flow: ResultsPane (status !== "idle") -> RunProgress <-- HERE
  if (stages.length === 0 && status === "idle") return null

  // Use the server-provided stage list once we have it; otherwise show the known
  // canonical 6-stage list as scaffolding so the strip doesn't pop in mid-run.
  const list = stages.length > 0 ? stages : Object.keys(STAGE_LABEL)
  const nextUp = nextRunningStage(list, completed, status)

  return (
    <div
      className={cn(
        "splash-fade-up flex flex-wrap items-center gap-2 rounded-lg border px-4 py-3",
        status === "failed"
          ? "border-rose-200 bg-rose-50/60"
          : status === "complete"
          ? "border-emerald-200 bg-emerald-50/40"
          : "border-primary/20 bg-primary/5",
      )}
    >
      <div className="mr-1 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-foreground/75">
        <Loader2
          className={cn(
            "h-3.5 w-3.5",
            status === "running" && "animate-spin text-primary",
            status === "complete" && "text-emerald-600",
            status === "failed" && "text-rose-600",
          )}
        />
        Pipeline {status}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {list.map((node, i) => {
          const state = chipStateFor(node, completed, status, nextUp)
          return (
            <div key={node} className="flex items-center">
              <StageChip node={node} state={state} />
              {i < list.length - 1 && (
                <span
                  aria-hidden
                  className={cn(
                    "mx-1 h-px w-3",
                    completed.includes(node)
                      ? "bg-foreground/30"
                      : "bg-foreground/10",
                  )}
                />
              )}
            </div>
          )
        })}
      </div>
      {status === "failed" && error && (
        <div className="w-full pt-1 text-xs text-rose-700">{error}</div>
      )}
    </div>
  )
}

function chipStateFor(
  node: string,
  completed: string[],
  status: RunStatus,
  nextUp: string | null,
): ChipState {
  if (completed.includes(node)) return "complete"
  if (status === "running" && node === nextUp) return "running"
  if (status === "complete" || status === "failed") {
    // The run finished but this node didn't fire — it was conditionally skipped
    // (e.g. the apex / sales-lead branch jumps from ingest straight to brief).
    return "skipped"
  }
  return "pending"
}

function nextRunningStage(
  list: string[],
  completed: string[],
  status: RunStatus,
): string | null {
  if (status !== "running") return null
  for (const node of list) {
    if (!completed.includes(node)) return node
  }
  return null
}

function StageChip({ node, state }: { node: string; state: ChipState }) {
  const label = STAGE_LABEL[node] ?? node
  const meta = CHIP_META[state]
  const Icon = meta.icon
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
        meta.classes,
      )}
      title={`${label} — ${state}`}
    >
      <Icon className={cn("h-3 w-3", state === "running" && "animate-spin")} />
      {label}
    </span>
  )
}

const CHIP_META: Record<
  ChipState,
  { icon: ComponentType<{ className?: string }>; classes: string }
> = {
  pending: {
    icon: Circle,
    classes: "border-border bg-card text-muted-foreground",
  },
  running: {
    icon: Loader2,
    classes: "border-primary/40 bg-primary/10 text-primary",
  },
  complete: {
    icon: Check,
    classes: "border-emerald-200 bg-emerald-50 text-emerald-700",
  },
  skipped: {
    icon: Minus,
    classes: "border-dashed border-border bg-card text-muted-foreground/70",
  },
  failed: {
    icon: X,
    classes: "border-rose-200 bg-rose-50 text-rose-700",
  },
}
