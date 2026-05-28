import { useEffect, useState, type ComponentType, type ReactNode } from "react"
import { Target, CheckCircle2, AlertTriangle, TrendingUp, Info, Sparkles, Calendar } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ConfidenceBadge } from "@/components/ConfidenceBadge"
import { EvidenceRail } from "@/components/EvidenceRail"
import { RunButton } from "@/components/RunButton"
import { DeckOutline } from "@/components/DeckOutline"
import { AccountAvatar } from "@/components/AccountAvatar"
import { PipelinePane } from "@/components/PipelinePane"
import { getBrief } from "@/lib/api"
import { useRunPipeline } from "@/lib/useRunPipeline"
import { cn } from "@/lib/utils"
import type {
  AccountSummary,
  Brief,
  Confidence,
  ConfidenceSummary as ConfidenceSummaryT,
  Evidence,
  ReviewBanner as ReviewBannerT,
} from "@/types"

type View = "customer" | "internal" | "pipeline"

// Order matters — this is the ViewToggle's left-to-right order. Reads as a
// drill-down: customer-facing → AM working brief → raw pipeline trace.
const VIEW_ORDER: readonly View[] = ["customer", "internal", "pipeline"] as const

const VIEW_LABELS: Record<View, string> = {
  customer: "Customer outline",
  internal: "Internal brief",
  pipeline: "Pipeline",
}

export function ResultsPane({
  accountId,
  account,
  onRunComplete,
}: {
  accountId: string
  account: AccountSummary | undefined
  onRunComplete: () => void
}) {
  // The problem is: the right pane has to coordinate three live concerns —
  // (1) hydrating the brief on account-select, (2) swapping between three views
  // (internal / customer / pipeline), (3) running the pipeline with live SSE
  // progress and consuming the fresh brief that comes back.
  // The way we solve this is: on accountId change, fetch the on-disk brief; on
  // Run click, useRunPipeline opens an SSE stream and on `done` we swap in its
  // brief in-place (no separate refetch). Account-list refresh is fired via
  // onRunComplete so the left-pane status icons update.
  // flow: App.selectedId -> ResultsPane <-- HERE -> getBrief / useRunPipeline
  const [brief, setBrief] = useState<Brief | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // Default to the customer-facing view — it's the highest-level surface and the
  // first thing an AM (or reviewer) wants to see; deeper views are drill-downs.
  const [view, setView] = useState<View>("customer")

  const run = useRunPipeline(accountId)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setBrief(null)
    run.reset()
    getBrief(accountId)
      .then(b => { if (!cancelled) setBrief(b) })
      .catch(err => { if (!cancelled) setError(err instanceof Error ? err.message : String(err)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId])

  // When a streamed run completes, swap in the fresh brief and let the parent
  // refresh the account list (status icons).
  useEffect(() => {
    if (run.status === "complete" && run.brief) {
      setBrief(run.brief)
      onRunComplete()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.status, run.brief])

  if (loading) {
    return <div className="p-10 text-sm text-muted-foreground">Loading brief…</div>
  }

  // Wrap run.start so clicking Run pops the user to the Pipeline tab — that's
  // where the live progress (and post-run artifacts) actually render.
  function handleRun() {
    setView("pipeline")
    run.start()
  }

  if (error) {
    // Real network/parse error (not a 404 — that's handled as brief=null below).
    return (
      <div className="space-y-4 p-10">
        <div className="text-sm text-destructive">Failed to load brief: {error}</div>
        <RunButton status={run.status} hasBrief={false} onRun={handleRun} />
      </div>
    )
  }

  if (!brief) {
    // The problem is: a freshly-discovered account (no output/<id>/brief.json
    // yet) needs to be runnable — and once the user clicks Run, they should see
    // the pipeline progress, not stay stuck on the empty state.
    // The way we solve this is: idle → empty state with Run; running/complete/
    // failed → render the Pipeline view directly so the user can watch stages
    // tick. handleRun() also sets view="pipeline" so this branch picks up.
    if (run.status === "idle") {
      return (
        <div className="mx-auto max-w-5xl space-y-5 p-8">
          <PendingHeader account={account} accountId={accountId} runStatus={run.status} onRun={handleRun} />
          <Card>
            <CardContent className="space-y-3 p-6">
              <div className="text-sm text-foreground">
                No brief yet for this account. Run the pipeline to generate one.
              </div>
              <div className="text-xs text-muted-foreground">
                Source data lives in <code className="font-mono">data/input/{accountId}/</code>.
                Outputs land in <code className="font-mono">data/output/{accountId}/</code>.
              </div>
            </CardContent>
          </Card>
        </div>
      )
    }
    return (
      <div className="mx-auto max-w-5xl space-y-5 p-8">
        <PendingHeader account={account} accountId={accountId} runStatus={run.status} onRun={handleRun} />
        <PipelinePane accountId={accountId} liveRun={run} />
      </div>
    )
  }

  if (brief.status === "insufficient_data") {
    return (
      <div className="mx-auto max-w-3xl space-y-5 p-8">
        <Header brief={brief} runStatus={run.status} onRun={handleRun} />
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Info className="h-5 w-5 text-amber-600" />
              <CardTitle>Insufficient data for a QBR</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="text-sm text-foreground/80">
            {brief.status_reason}
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-5xl">
      {/* The problem is: with the whole brief in one scroll, the account
          identity + view toggle scroll out of view as soon as the user reads
          past Customer goals — they lose context on which account they're in
          and lose the ability to switch views without scrolling back.
          The way we solve this is: sticky region pinned to the top of the
          main scroll container. It contains Header + ViewToggle always, plus
          the ConfidenceSummaryStrip when we're on Internal Brief (where the
          strip is contextual). bg-background occludes scrolling content. */}
      <div className="sticky top-0 z-20 space-y-4 border-b border-border/60 bg-background px-8 pb-4 pt-8">
        <Header brief={brief} runStatus={run.status} onRun={handleRun} />
        <ViewToggle view={view} onChange={setView} />
        {view === "internal" && (
          <ConfidenceSummaryStrip summary={brief.confidence_summary} />
        )}
      </div>

      <div className="space-y-5 px-8 pb-8 pt-5">
        {brief.review_banner && view !== "pipeline" && <ReviewBannerCard banner={brief.review_banner} />}
        {view === "internal" && <InternalView brief={brief} />}
        {view === "customer" && <DeckOutline outline={brief.outline} accountName={brief.account_name} />}
        {view === "pipeline" && <PipelinePane accountId={brief.account_id} liveRun={run} />}
      </div>
    </div>
  )
}

function Header({
  brief,
  runStatus,
  onRun,
}: {
  brief: Brief
  runStatus: import("@/lib/useRunPipeline").RunStatus
  onRun: () => void
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="flex items-start gap-4">
        <AccountAvatar id={brief.account_id} name={brief.account_name} size="lg" variant="round" />
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-[22px] font-semibold leading-tight text-foreground">
              {brief.account_name}
            </h2>
            <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium text-primary ring-1 ring-inset ring-primary/30">
              <Sparkles className="h-3 w-3" />
              QBR brief
            </span>
          </div>
          <div className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
            <span>{brief.vertical}</span>
            <span aria-hidden>·</span>
            <span>Generated {formatDate(brief.generated_at)}</span>
            <span aria-hidden>·</span>
            <span className="font-mono text-xs">v{brief.pipeline_version}</span>
          </div>
        </div>
      </div>
      <RunButton status={runStatus} hasBrief={true} onRun={onRun} />
    </div>
  )
}

function PendingHeader({
  account,
  accountId,
  runStatus,
  onRun,
}: {
  account: AccountSummary | undefined
  accountId: string
  runStatus: import("@/lib/useRunPipeline").RunStatus
  onRun: () => void
}) {
  // The problem is: the running/empty states need the same visual scaffolding
  // as a loaded brief (avatar + name + vertical + Run button) but without
  // brief-derived fields (generated_at, pipeline_version).
  // The way we solve this is: read identity from AccountSummary (which comes
  // from input-side discovery, so it's available before any run has happened)
  // and show a "Not run yet" pill in place of the QBR-brief pill.
  const name = account?.name ?? accountId
  const vertical = account?.vertical
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="flex items-start gap-4">
        <AccountAvatar id={accountId} name={name} size="lg" variant="round" />
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-[22px] font-semibold leading-tight text-foreground">
              {name}
            </h2>
            <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium text-muted-foreground ring-1 ring-inset ring-border">
              <Info className="h-3 w-3" />
              {runStatus === "idle" ? "Not run yet" : "Pipeline running"}
            </span>
          </div>
          {vertical && (
            <div className="mt-1 text-sm text-muted-foreground">{vertical}</div>
          )}
        </div>
      </div>
      <RunButton status={runStatus} hasBrief={false} onRun={onRun} />
    </div>
  )
}

function ViewToggle({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  return (
    <div className="inline-flex items-center rounded-md border border-border bg-card p-0.5 shadow-sm">
      {VIEW_ORDER.map(v => (
        <button
          key={v}
          type="button"
          onClick={() => onChange(v)}
          className={cn(
            "rounded px-2.5 py-1 text-[13px] font-medium transition-colors",
            view === v
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          {VIEW_LABELS[v]}
        </button>
      ))}
    </div>
  )
}

function ReviewBannerCard({ banner }: { banner: ReviewBannerT }) {
  const Icon = banner.severity === "warning" ? AlertTriangle : Info
  const tone =
    banner.severity === "warning"
      ? "border-amber-200 bg-amber-50 text-amber-900"
      : "border-primary/20 bg-primary/5 text-foreground"
  return (
    <div className={cn("flex items-start gap-3 rounded-lg border p-4", tone)}>
      <Icon
        className={cn(
          "mt-0.5 h-5 w-5 shrink-0",
          banner.severity === "warning" ? "text-amber-600" : "text-primary"
        )}
      />
      <div className="text-sm leading-relaxed">{banner.message}</div>
    </div>
  )
}

function InternalView({ brief }: { brief: Brief }) {
  // ConfidenceSummaryStrip is rendered by ResultsPane up in the sticky header
  // region — it should stay pinned with the view toggle as the user scrolls.
  return (
    <div className="space-y-7">
      <Section icon={Target} title="Customer goals">
        <ClaimGroup>
          {brief.goals.map(goal => (
            <ClaimRow
              key={goal.id}
              title={goal.statement}
              meta={<GoalMeta goal={goal} />}
              confidence={goal.confidence}
              evidenceIds={goal.evidence_ids}
              evidence={brief.evidence}
              accountId={brief.account_id}
            />
          ))}
        </ClaimGroup>
      </Section>

      <Section icon={CheckCircle2} title="What's working">
        <ClaimGroup>
          {brief.whats_working.map((w, i) => (
            <ClaimRow
              key={i}
              title={w.feature}
              body={w.summary}
              meta={
                <span className="font-mono text-[11px] text-muted-foreground">
                  {w.signal}
                </span>
              }
              confidence={w.confidence}
              evidenceIds={w.evidence_ids}
              evidence={brief.evidence}
              accountId={brief.account_id}
            />
          ))}
        </ClaimGroup>
      </Section>

      <Section icon={AlertTriangle} title="Adoption gaps">
        <ClaimGroup>
          {brief.gaps.map(gap => (
            <ClaimRow
              key={gap.id}
              title={gap.feature}
              body={gap.summary}
              footer={gap.recommended_action}
              footerLabel="Recommended action"
              meta={<ScoreChip label="severity" value={gap.severity} />}
              confidence={gap.confidence}
              evidenceIds={gap.evidence_ids}
              evidence={brief.evidence}
              accountId={brief.account_id}
            />
          ))}
        </ClaimGroup>
      </Section>

      <Section icon={TrendingUp} title="Upsell opportunities">
        <ClaimGroup>
          {brief.opportunities.map(opp => (
            <ClaimRow
              key={opp.id}
              title={opp.product}
              body={opp.rationale}
              footer={opp.recommended_action}
              footerLabel="Recommended action"
              meta={<ScoreChip label="fit" value={opp.fit_score} />}
              confidence={opp.confidence}
              evidenceIds={opp.evidence_ids}
              evidence={brief.evidence}
              accountId={brief.account_id}
            />
          ))}
        </ClaimGroup>
      </Section>
    </div>
  )
}

function ClaimGroup({ children }: { children: ReactNode }) {
  // Single card with divider rows — homogeneous lists (goals/gaps/etc.) read
  // as one group instead of a stack of disconnected cards.
  return (
    <Card>
      <CardContent className="p-0">
        <div className="divide-y divide-border">{children}</div>
      </CardContent>
    </Card>
  )
}

function Section({
  icon: Icon,
  title,
  children,
}: {
  icon: ComponentType<{ className?: string }>
  title: string
  children: ReactNode
}) {
  // The problem is: the old micro-cap headers (11px tracked uppercase) read as
  // category labels, not section dividers — the brief looked like one long page.
  // The way we solve this is: bump to a real section heading (17px regular) with
  // a primary-blue icon. The size + color contrast carries the sectioning weight
  // on its own without needing rules or background tints.
  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-primary" />
        <h3 className="text-[15px] font-semibold tracking-tight text-foreground">
          {title}
        </h3>
      </div>
      {children}
    </section>
  )
}

function ClaimRow({
  title,
  body,
  meta,
  footer,
  footerLabel,
  confidence,
  evidenceIds,
  evidence,
  accountId,
}: {
  title: string
  body?: string
  meta?: ReactNode
  footer?: string
  footerLabel?: string
  confidence: Confidence
  evidenceIds: string[]
  evidence: Record<string, Evidence>
  accountId: string
}) {
  return (
    <div className="p-4">
      <div className="grid gap-4 md:grid-cols-[1fr_minmax(260px,360px)]">
        <div className="space-y-2.5">
          <div className="text-sm font-semibold leading-snug text-foreground">{title}</div>
          {body && <p className="text-[13px] leading-relaxed text-foreground/80">{body}</p>}
          {meta && <div className="text-[11px] text-muted-foreground">{meta}</div>}
          <div>
            <ConfidenceBadge confidence={confidence} />
          </div>
          {footer && footerLabel && (
            <div className="rounded-md border border-border bg-muted/50 p-2.5 text-[13px]">
              <div className="mb-0.5 text-[10.5px] font-semibold uppercase tracking-wider text-muted-foreground">
                {footerLabel}
              </div>
              <div className="text-foreground/85">{footer}</div>
            </div>
          )}
        </div>
        <EvidenceRail evidenceIds={evidenceIds} evidence={evidence} accountId={accountId} />
      </div>
    </div>
  )
}

function GoalMeta({ goal }: { goal: import("@/types").Goal }) {
  // The problem is: a goal card needs to show its category AND (when available)
  // the temporal arc so the AM can see "this is a recurring theme across 5 calls
  // since Oct 2025" vs "mentioned once in March 2026".
  // The way we solve this is: a small chip line — category plus a Calendar-icon
  // badge showing date range and call count when the s1 linker populated them.
  const trail = formatGoalTimeline(goal)
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <span className="capitalize">{goal.category.replace(/_/g, " ")}</span>
      {trail && (
        <>
          <span aria-hidden className="text-foreground/30">·</span>
          <span className="inline-flex items-center gap-1 text-muted-foreground">
            <Calendar className="h-3 w-3" />
            {trail}
          </span>
        </>
      )}
    </div>
  )
}

function formatGoalTimeline(goal: import("@/types").Goal): string | null {
  if (!goal.first_mentioned_date) return null
  const n = goal.mentioned_in_files?.length ?? 0
  const first = new Date(goal.first_mentioned_date)
  const last = goal.last_mentioned_date ? new Date(goal.last_mentioned_date) : first
  const fmt = (d: Date) => d.toLocaleDateString(undefined, { month: "short", year: "numeric" })
  const firstStr = fmt(first)
  const lastStr = fmt(last)
  const callsLabel = `${n} call${n === 1 ? "" : "s"}`
  if (firstStr === lastStr) return `${firstStr} · ${callsLabel}`
  return `${firstStr} → ${lastStr} · ${callsLabel}`
}

function ScoreChip({ label, value }: { label: string; value: number }) {
  // The problem is: severity / fit scores need a glanceable chip that doesn't read as
  // a confidence pill (different semantic).
  // The way we solve this is: neutral chip with a tabular-numerals score, matching the
  // Podium tag treatment.
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-medium text-muted-foreground ring-1 ring-inset ring-border">
      <span className="uppercase tracking-wider">{label}</span>
      <span className="font-mono tabular-nums text-foreground">{value}</span>
    </span>
  )
}

function ConfidenceSummaryStrip({ summary }: { summary: ConfidenceSummaryT }) {
  const total = summary.high + summary.med + summary.low
  if (total === 0) return null
  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-card px-3.5 py-2 text-[11px]">
      <span className="font-semibold uppercase tracking-wider text-muted-foreground">
        Confidence
      </span>
      <div className="flex items-center gap-2">
        <SummaryDot count={summary.high} color="bg-emerald-500" label="high" />
        <SummaryDot count={summary.med} color="bg-amber-500" label="med" />
        {summary.low > 0 && <SummaryDot count={summary.low} color="bg-rose-500" label="low" />}
      </div>
      <span className="ml-auto text-muted-foreground">
        {total} claim{total === 1 ? "" : "s"} traced to evidence
      </span>
    </div>
  )
}

function SummaryDot({ count, color, label }: { count: number; color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn("h-2 w-2 rounded-full", color)} />
      <span className="font-mono tabular-nums text-foreground">{count}</span>
      <span className="text-muted-foreground">{label}</span>
    </span>
  )
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
    })
  } catch {
    return iso
  }
}
