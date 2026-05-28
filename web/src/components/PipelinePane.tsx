import { useEffect, useState } from "react"
import { CheckCircle2, Circle, ChevronRight, Sparkles, FileJson, MessageSquare } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { getPipeline } from "@/lib/api"
import { cn } from "@/lib/utils"
import type { PipelineSnapshot, PipelineStage } from "@/types"

export function PipelinePane({ accountId }: { accountId: string }) {
  // The problem is: the AM (and reviewers) need to see what the agent actually did —
  // which stages ran, what each stage emitted, and for LLM stages what was sent and
  // received. Without this the pipeline is a black box producing a brief.
  // The way we solve this is: one bundled fetch returns every per-stage artifact
  // from disk; render each as a card with status, summary, and an expandable JSON
  // viewer (plus prompt + raw response for LLM stages).
  // flow: ResultsPane (view=pipeline) -> PipelinePane <-- HERE -> GET /pipeline
  const [snapshot, setSnapshot] = useState<PipelineSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setSnapshot(null)
    getPipeline(accountId)
      .then(s => { if (!cancelled) setSnapshot(s) })
      .catch(err => { if (!cancelled) setError(err instanceof Error ? err.message : String(err)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [accountId])

  if (loading) {
    return <div className="p-2 text-sm text-muted-foreground">Loading pipeline trace…</div>
  }
  if (error || !snapshot) {
    return <div className="p-2 text-sm text-destructive">Couldn't load pipeline trace: {error}</div>
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span className="font-semibold uppercase tracking-wider">Pipeline trace</span>
        <span>·</span>
        <span>
          {snapshot.stages.filter(s => s.status === "ok").length} of {snapshot.stages.length} stages ran
        </span>
      </div>
      <ol className="space-y-3">
        {snapshot.stages.map(stage => (
          <StageCard key={stage.id} stage={stage} />
        ))}
      </ol>
    </div>
  )
}

function StageCard({ stage }: { stage: PipelineStage }) {
  const ok = stage.status === "ok"
  const Icon = ok ? CheckCircle2 : Circle
  return (
    <li>
      <Card className={cn(!ok && "opacity-60")}>
        <CardContent className="space-y-3 p-5">
          <div className="flex items-start gap-3">
            <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted text-[12px] font-mono font-semibold tabular-nums text-foreground">
              {stage.id}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 font-semibold text-foreground">
                  {stage.name}
                  {stage.is_llm && (
                    <Badge variant="outline" className="gap-1">
                      <Sparkles className="h-3 w-3" />
                      LLM
                    </Badge>
                  )}
                </div>
                <div className="flex items-center gap-1.5">
                  <Icon className={cn("h-4 w-4", ok ? "text-emerald-500" : "text-slate-300")} />
                  <span className={cn("text-xs", ok ? "text-emerald-700" : "text-muted-foreground")}>
                    {ok ? "ok" : "not run"}
                  </span>
                </div>
              </div>
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{stage.description}</p>
              <div className="mt-1.5 inline-flex items-center gap-1 font-mono text-[11px] text-muted-foreground">
                <FileJson className="h-3 w-3" />
                data/output/&lt;account&gt;/{stage.artifact}
              </div>
            </div>
          </div>

          {stage.trace && (
            <Disclosure label="LLM trace" icon={MessageSquare} count={`${stage.trace.user_prompt_chars.toLocaleString()} chars in · ${stage.trace.model}`}>
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

          {ok && stage.data !== null && (
            <Disclosure label="Artifact JSON" icon={FileJson}>
              <JsonBlock data={stage.data} />
            </Disclosure>
          )}
        </CardContent>
      </Card>
    </li>
  )
}

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

function PromptBlock({ text, maxLines }: { text: string; maxLines?: number }) {
  const lines = text.split("\n")
  const needsClip = maxLines !== undefined && lines.length > maxLines
  if (!needsClip) {
    return (
      <pre className="max-h-[400px] overflow-auto rounded-md border border-border bg-slate-50 p-3 text-[12px] leading-relaxed text-slate-700">
        {text}
      </pre>
    )
  }
  const preview = lines.slice(0, maxLines).join("\n") + "\n…"
  return (
    <details className="group">
      <summary className="cursor-pointer text-[11px] text-muted-foreground transition-colors hover:text-foreground">
        <span className="group-open:hidden">Show full ({lines.length.toLocaleString()} lines)</span>
        <span className="hidden group-open:inline">Collapse to preview</span>
      </summary>
      <pre className="mt-2 max-h-[300px] overflow-auto rounded-md border border-border bg-slate-50 p-3 text-[12px] leading-relaxed text-slate-700 group-open:hidden">
        {preview}
      </pre>
      <pre className="mt-2 max-h-[600px] overflow-auto rounded-md border border-border bg-slate-50 p-3 text-[12px] leading-relaxed text-slate-700 hidden group-open:block">
        {text}
      </pre>
    </details>
  )
}

function JsonBlock({ data }: { data: unknown }) {
  return (
    <pre className="max-h-[480px] overflow-auto rounded-md border border-border bg-slate-50 p-3 font-mono text-[12px] leading-relaxed text-slate-800">
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}
