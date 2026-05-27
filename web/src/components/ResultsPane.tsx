import { useEffect, useState, type ComponentType, type ReactNode } from "react"
import { Target, CheckCircle2, AlertTriangle, TrendingUp, Info, Sparkles } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ConfidenceBadge } from "@/components/ConfidenceBadge"
import { EvidenceRail } from "@/components/EvidenceRail"
import { RunButton } from "@/components/RunButton"
import { DeckOutline } from "@/components/DeckOutline"
import { AccountAvatar } from "@/components/AccountAvatar"
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
    return <div className="p-10 text-sm text-muted-foreground">Loading brief…</div>
  }

  if (error || !brief) {
    return (
      <div className="space-y-4 p-10">
        <div className="text-sm text-foreground">No brief yet for this account.</div>
        <RunButton accountId={accountId} hasBrief={false} onComplete={onRunComplete} />
        {error && <div className="text-sm text-destructive">{error}</div>}
      </div>
    )
  }

  if (brief.status === "insufficient_data") {
    return (
      <div className="mx-auto max-w-3xl space-y-6 p-10">
        <Header brief={brief} onRunComplete={onRunComplete} />
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
    <div className="mx-auto max-w-5xl space-y-6 p-10">
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
      <div className="flex items-start gap-4">
        <AccountAvatar id={brief.account_id} name={brief.account_name} size="lg" variant="round" />
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-[22px] font-semibold leading-tight text-foreground">
              {brief.account_name}
            </h2>
            <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
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
      <RunButton accountId={brief.account_id} hasBrief={true} onComplete={onRunComplete} />
    </div>
  )
}

function ViewToggle({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  return (
    <div className="inline-flex items-center rounded-md border border-border bg-card p-1 shadow-sm">
      {(["internal", "customer"] as const).map(v => (
        <button
          key={v}
          type="button"
          onClick={() => onChange(v)}
          className={cn(
            "rounded px-3 py-1.5 text-sm font-medium transition-colors",
            view === v
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground"
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
  return (
    <div className="space-y-6">
      <ConfidenceSummaryStrip summary={brief.confidence_summary} />

      <Section icon={Target} title="Customer goals">
        <div className="space-y-3">
          {brief.goals.map(goal => (
            <ClaimCard
              key={goal.id}
              title={goal.statement}
              meta={
                <span className="capitalize">
                  {goal.category.replace(/_/g, " ")}
                </span>
              }
              confidence={goal.confidence}
              evidenceIds={goal.evidence_ids}
              evidence={brief.evidence}
            />
          ))}
        </div>
      </Section>

      <Section icon={CheckCircle2} title="What's working">
        <div className="space-y-3">
          {brief.whats_working.map((w, i) => (
            <ClaimCard
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
            />
          ))}
        </div>
      </Section>

      <Section icon={AlertTriangle} title="Adoption gaps">
        <div className="space-y-3">
          {brief.gaps.map(gap => (
            <ClaimCard
              key={gap.id}
              title={gap.feature}
              body={gap.summary}
              footer={gap.recommended_action}
              footerLabel="Recommended action"
              meta={<ScoreChip label="severity" value={gap.severity} />}
              confidence={gap.confidence}
              evidenceIds={gap.evidence_ids}
              evidence={brief.evidence}
            />
          ))}
        </div>
      </Section>

      <Section icon={TrendingUp} title="Upsell opportunities">
        <div className="space-y-3">
          {brief.opportunities.map(opp => (
            <ClaimCard
              key={opp.id}
              title={opp.product}
              body={opp.rationale}
              footer={opp.signals.join(" · ")}
              footerLabel="Signals"
              meta={<ScoreChip label="fit" value={opp.fit_score} />}
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
        <Icon className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
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
    <Card className="transition-shadow hover:shadow-md">
      <CardContent className="p-5">
        <div className="grid gap-5 md:grid-cols-[1fr_minmax(260px,360px)]">
          <div className="space-y-3">
            <div className="flex items-start justify-between gap-3">
              <div className="text-[15px] font-semibold leading-snug text-foreground">{title}</div>
              <ConfidenceBadge confidence={confidence} />
            </div>
            {body && <p className="text-sm leading-relaxed text-foreground/80">{body}</p>}
            {meta && <div className="text-xs text-muted-foreground">{meta}</div>}
            {footer && footerLabel && (
              <div className="rounded-md border border-border bg-muted/50 p-3 text-sm">
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  {footerLabel}
                </div>
                <div className="text-foreground/85">{footer}</div>
              </div>
            )}
          </div>
          <EvidenceRail evidenceIds={evidenceIds} evidence={evidence} />
        </div>
      </CardContent>
    </Card>
  )
}

function ScoreChip({ label, value }: { label: string; value: number }) {
  // The problem is: severity / fit scores need a glanceable chip that doesn't read as
  // a confidence pill (different semantic).
  // The way we solve this is: neutral chip with a tabular-numerals score, matching the
  // Podium tag treatment.
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
      <span className="uppercase tracking-wider">{label}</span>
      <span className="font-mono tabular-nums text-foreground">{value}</span>
    </span>
  )
}

function ConfidenceSummaryStrip({ summary }: { summary: ConfidenceSummaryT }) {
  const total = summary.high + summary.med + summary.low
  if (total === 0) return null
  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-2.5 text-xs">
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
