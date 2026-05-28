import { FileText, Database, Mail, ChevronRight, ExternalLink } from "lucide-react"
import type { Evidence } from "@/types"

export function EvidenceRail({
  evidenceIds,
  evidence,
  accountId,
}: {
  evidenceIds: string[]
  evidence: Record<string, Evidence>
  accountId: string
}) {
  // The problem is: every claim in the brief needs its source visible alongside, not
  // hidden behind a tooltip. The AM should verify a claim in one eye-movement —
  // and be able to jump to the full transcript when 4 lines of quote isn't enough.
  // The way we solve this is: render each evidence item inline next to its claim
  // (source icon, locator, verbatim quote). For transcript evidence the locator
  // itself becomes a link that opens the full file in a new tab with the cited
  // range highlighted + auto-scrolled.
  // flow: ResultsPane.ClaimCard / PipelinePane.StageCard -> EvidenceRail <-- HERE
  if (evidenceIds.length === 0) return null

  return (
    <div className="space-y-3 border-l border-primary/30 pl-4">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-primary">
        Evidence ({evidenceIds.length})
      </div>
      <ul className="space-y-3">
        {evidenceIds.map(id => {
          const ev = evidence[id]
          if (!ev) return null
          return <EvidenceItem key={id} ev={ev} accountId={accountId} />
        })}
      </ul>
    </div>
  )
}

function EvidenceItem({ ev, accountId }: { ev: Evidence; accountId: string }) {
  const Icon =
    ev.source === "usage" ? Database : ev.source === "email" ? Mail : FileText
  const locator = formatLocator(ev)
  const hasContext = ev.context_before || ev.context_after

  return (
    <li className="space-y-1.5 text-sm">
      <LocatorRow ev={ev} accountId={accountId} icon={Icon} text={locator} />
      <blockquote className="border-l-2 border-border pl-3 text-[13px] italic leading-relaxed text-foreground/85">
        &ldquo;{ev.quote}&rdquo;
      </blockquote>
      {hasContext && (
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer select-none list-none">
            <span className="inline-flex items-center gap-1 transition-colors hover:text-foreground">
              <ChevronRight className="h-3 w-3" />
              Surrounding context
            </span>
          </summary>
          <div className="mt-2 space-y-1.5 pl-4 text-[12px]">
            {ev.context_before && <div className="text-muted-foreground">… {ev.context_before}</div>}
            <div className="text-foreground/80">… {ev.quote}</div>
            {ev.context_after && <div className="text-muted-foreground">… {ev.context_after}</div>}
          </div>
        </details>
      )}
    </li>
  )
}

function LocatorRow({
  ev,
  accountId,
  icon: Icon,
  text,
}: {
  ev: Evidence
  accountId: string
  icon: typeof FileText
  text: string
}) {
  // The problem is: the locator should be both a glanceable label AND an
  // affordance to open the full file. Transcript evidence has a real source we
  // can link to; usage evidence is just a column reference.
  // The way we solve this is: for transcript locators, render as an <a target="_blank">
  // to the HTML transcript view (with the cited range highlighted server-side).
  // For usage/email, render as plain text.
  if (ev.locator.kind === "transcript") {
    const params = new URLSearchParams({
      cited_start: String(ev.locator.line_start),
      cited_end: String(ev.locator.line_end),
    })
    const href = `/accounts/${accountId}/transcripts/${encodeURIComponent(ev.locator.file)}?${params.toString()}`
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="group inline-flex max-w-full items-center gap-1.5 text-[11px] text-muted-foreground transition-colors hover:text-primary"
        title={`Open ${text} in a new tab`}
      >
        <Icon className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate font-mono">{text}</span>
        <ExternalLink className="h-3 w-3 shrink-0 opacity-0 transition-opacity group-hover:opacity-100" />
      </a>
    )
  }

  return (
    <div className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
      <Icon className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate font-mono" title={text}>
        {text}
      </span>
    </div>
  )
}

function formatLocator(ev: Evidence): string {
  switch (ev.locator.kind) {
    case "transcript": {
      const range =
        ev.locator.line_end !== ev.locator.line_start
          ? `L${ev.locator.line_start}-${ev.locator.line_end}`
          : `L${ev.locator.line_start}`
      return `${ev.locator.file} : ${range} @ ${ev.locator.timestamp}`
    }
    case "usage":
      return `usage.${ev.locator.column}`
    case "email":
      return `${ev.locator.file} : L${ev.locator.line_start}-${ev.locator.line_end}`
  }
}
