import { useEffect, useState, type ComponentType, type ReactNode } from "react"
import { Target, CheckCircle2, AlertTriangle, TrendingUp, Info } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { ConfidenceBadge } from "@/components/ConfidenceBadge"
import { EvidenceRail } from "@/components/EvidenceRail"
import { RunButton } from "@/components/RunButton"
import { DeckOutline } from "@/components/DeckOutline"
import { getBrief } from "@/lib/api"
import { cn } from "@/lib/utils"
import type {
  Brief,
  Confidence,
  ConfidenceSummary as ConfidenceSummaryT,
  Evidence,
  ReviewBanner as ReviewBannerT,
} from "@/types"

type View = "internal" | "customer"

export function ResultsPane({
  accountId,
  onRunComplete,
}: {
  accountId: string
  onRunComplete: () => void
}) {
  // The problem is: the right pane has to swap between three states (loading, no-brief,
  // brief) and across two views (internal brief / customer outline) without flicker.
  // The way we solve this is: fetch on accountId change with a clear loading/error
  // gate, then branch on brief.status for the empty/insufficient case.
  // flow: App.selectedId -> ResultsPane <-- HERE -> GET /accounts/{id}/brief
  const [brief, setBrief] = useState<Brief | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<View>("internal")

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setBrief(null)
    getBrief(accountId)
      .then(b => { if (!cancelled) setBrief(b) })
      .catch(err => { if (!cancelled) setError(err instanceof Error ? err.message : String(err)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [accountId])

  if (loading) {
    return <div className="p-8 text-sm text-slate-400">Loading…</div>
  }

  if (error || !brief) {
    return (
      <div className="space-y-4 p-8">
        <div className="text-sm text-slate-700">No brief yet for this account.</div>
        <RunButton accountId={accountId} hasBrief={false} onComplete={onRunComplete} />
        {error && <div className="text-sm text-rose-600">{error}</div>}
      </div>
    )
  }

  if (brief.status === "insufficient_data") {
    return (
      <div className="mx-auto max-w-3xl space-y-6 p-8">
        <Header brief={brief} onRunComplete={onRunComplete} />
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Info className="h-5 w-5 text-amber-600" />
              <CardTitle>Insufficient data for a QBR</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="text-sm text-slate-700">
            {brief.status_reason}
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-8">
      <Header brief={brief} onRunComplete={onRunComplete} />
      <ViewToggle view={view} onChange={setView} />
      {brief.review_banner && <ReviewBannerCard banner={brief.review_banner} />}
      {view === "internal" ? (
        <InternalView brief={brief} />
      ) : (
        <DeckOutline outline={brief.outline} accountName={brief.account_name} />
      )}
    </div>
  )
}

function Header({ brief, onRunComplete }: { brief: Brief; onRunComplete: () => void }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <h2 className="text-2xl font-semibold text-slate-900">{brief.account_name}</h2>
        <div className="mt-1 flex items-center gap-2 text-sm text-slate-500">
          <span>{brief.vertical}</span>
          <span>·</span>
          <span>Generated {formatDate(brief.generated_at)}</span>
        </div>
      </div>
      <RunButton accountId={brief.account_id} hasBrief={true} onComplete={onRunComplete} />
    </div>
  )
}

function ViewToggle({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  return (
    <div className="inline-flex rounded-md border border-slate-200 bg-white p-1">
      {(["internal", "customer"] as const).map(v => (
        <button
          key={v}
          type="button"
          onClick={() => onChange(v)}
          className={cn(
            "rounded px-3 py-1.5 text-sm font-medium transition-colors",
            view === v
              ? "bg-violet-100 text-violet-900"
              : "text-slate-600 hover:text-slate-900"
          )}
        >
          {v === "internal" ? "Internal brief" : "Customer outline"}
        </button>
      ))}
    </div>
  )
}

function ReviewBannerCard({ banner }: { banner: ReviewBannerT }) {
  const Icon = banner.severity === "warning" ? AlertTriangle : Info
  const color =
    banner.severity === "warning"
      ? "border-amber-300 bg-amber-50"
      : "border-violet-200 bg-violet-50"
  return (
    <div className={cn("flex items-start gap-3 rounded-lg border p-4", color)}>
      <Icon
        className={cn(
          "mt-0.5 h-5 w-5 shrink-0",
          banner.severity === "warning" ? "text-amber-700" : "text-violet-700"
        )}
      />
      <div className="text-sm text-slate-800">{banner.message}</div>
    </div>
  )
}

function InternalView({ brief }: { brief: Brief }) {
  return (
    <div className="space-y-6">
      <ConfidenceSummaryStrip summary={brief.confidence_summary} />

      <Section icon={Target} title="Customer goals">
        <div className="space-y-4">
          {brief.goals.map(goal => (
            <ClaimCard
              key={goal.id}
              title={goal.statement}
              meta={<span className="capitalize">{goal.category.replace(/_/g, " ")}</span>}
              confidence={goal.confidence}
              evidenceIds={goal.evidence_ids}
              evidence={brief.evidence}
            />
          ))}
        </div>
      </Section>

      <Section icon={CheckCircle2} title="What's working">
        <div className="space-y-4">
          {brief.whats_working.map((w, i) => (
            <ClaimCard
              key={i}
              title={w.feature}
              body={w.summary}
              meta={<span className="font-mono text-xs">{w.signal}</span>}
              confidence={w.confidence}
              evidenceIds={w.evidence_ids}
              evidence={brief.evidence}
            />
          ))}
        </div>
      </Section>

      <Section icon={AlertTriangle} title="Adoption gaps">
        <div className="space-y-4">
          {brief.gaps.map(gap => (
            <ClaimCard
              key={gap.id}
              title={gap.feature}
              body={gap.summary}
              footer={gap.recommended_action}
              footerLabel="Recommended action"
              meta={<Badge variant="outline">severity {gap.severity}</Badge>}
              confidence={gap.confidence}
              evidenceIds={gap.evidence_ids}
              evidence={brief.evidence}
            />
          ))}
        </div>
      </Section>

      <Section icon={TrendingUp} title="Upsell opportunities">
        <div className="space-y-4">
          {brief.opportunities.map(opp => (
            <ClaimCard
              key={opp.id}
              title={opp.product}
              body={opp.rationale}
              footer={opp.signals.join(" · ")}
              footerLabel="Signals"
              meta={<Badge variant="outline">fit {opp.fit_score}</Badge>}
              confidence={opp.confidence}
              evidenceIds={opp.evidence_ids}
              evidence={brief.evidence}
            />
          ))}
        </div>
      </Section>
    </div>
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
  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-slate-500" />
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          {title}
        </h3>
      </div>
      {children}
    </section>
  )
}

function ClaimCard({
  title,
  body,
  meta,
  footer,
  footerLabel,
  confidence,
  evidenceIds,
  evidence,
}: {
  title: string
  body?: string
  meta?: ReactNode
  footer?: string
  footerLabel?: string
  confidence: Confidence
  evidenceIds: string[]
  evidence: Record<string, Evidence>
}) {
  return (
    <Card>
      <CardContent className="p-5">
        <div className="grid gap-5 md:grid-cols-[1fr_minmax(260px,360px)]">
          <div className="space-y-3">
            <div className="flex items-start justify-between gap-3">
              <div className="font-medium text-slate-900">{title}</div>
              <ConfidenceBadge confidence={confidence} />
            </div>
            {body && <p className="text-sm text-slate-700">{body}</p>}
            {meta && <div className="text-xs text-slate-500">{meta}</div>}
            {footer && footerLabel && (
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm">
                <div className="mb-1 text-xs font-medium uppercase tracking-wider text-slate-500">
                  {footerLabel}
                </div>
                <div className="text-slate-700">{footer}</div>
              </div>
            )}
          </div>
          <EvidenceRail evidenceIds={evidenceIds} evidence={evidence} />
        </div>
      </CardContent>
    </Card>
  )
}

function ConfidenceSummaryStrip({ summary }: { summary: ConfidenceSummaryT }) {
  const total = summary.high + summary.med + summary.low
  if (total === 0) return null
  return (
    <div className="flex items-center gap-2 text-xs text-slate-500">
      <span className="font-medium uppercase tracking-wider">Confidence:</span>
      <Badge variant="success">{summary.high} high</Badge>
      <Badge variant="warning">{summary.med} med</Badge>
      {summary.low > 0 && <Badge variant="destructive">{summary.low} low</Badge>}
    </div>
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
