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
  // The way we solve this is: render each evidence item inline next to its claim with
  // the locator (file:line@timestamp or usage column) and the verbatim quote.
  // flow: ResultsPane.ClaimCard -> EvidenceRail <-- HERE (right column of each card)
  if (evidenceIds.length === 0) return null

  return (
    <div className="space-y-3 border-l-2 border-violet-100 pl-4">
      <div className="text-xs font-medium uppercase tracking-wider text-violet-700">
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
      <div className="flex items-center gap-1.5 text-xs text-slate-500">
        <Icon className="h-3.5 w-3.5" />
        <span className="font-mono truncate" title={locator}>{locator}</span>
      </div>
      <blockquote className="border-l-2 border-slate-200 pl-3 italic text-slate-700">
        &ldquo;{ev.quote}&rdquo;
      </blockquote>
      {hasContext && (
        <details className="text-xs text-slate-500">
          <summary className="cursor-pointer select-none list-none">
            <span className="inline-flex items-center gap-1 hover:text-slate-700">
              <ChevronRight className="h-3 w-3" />
              Surrounding context
            </span>
          </summary>
          <div className="mt-2 space-y-1.5 pl-4">
            {ev.context_before && <div className="text-slate-500">… {ev.context_before}</div>}
            <div className="text-slate-700">… {ev.quote}</div>
            {ev.context_after && <div className="text-slate-500">… {ev.context_after}</div>}
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
