import { FileText, Database, Mail, ChevronRight } from "lucide-react"
import type { Evidence } from "@/types"

export function EvidenceRail({
  evidenceIds,
  evidence,
}: {
  evidenceIds: string[]
  evidence: Record<string, Evidence>
}) {
  // The problem is: every claim in the brief needs its source visible alongside, not
  // hidden behind a tooltip. The AM should verify a claim in one eye-movement.
  // The way we solve this is: a vertical rail of evidence items pinned to the right
  // column of each claim card — source icon, locator (file:line@timestamp or usage
  // column), verbatim quote, expandable context.
  // flow: ResultsPane.ClaimCard -> EvidenceRail <-- HERE (right column of each card)
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
          return <EvidenceItem key={id} ev={ev} />
        })}
      </ul>
    </div>
  )
}

function EvidenceItem({ ev }: { ev: Evidence }) {
  const Icon =
    ev.source === "usage" ? Database : ev.source === "email" ? Mail : FileText
  const locator = formatLocator(ev)
  const hasContext = ev.context_before || ev.context_after

  return (
    <li className="space-y-1.5 text-sm">
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        <span className="truncate font-mono" title={locator}>
          {locator}
        </span>
      </div>
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
