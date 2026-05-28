import { cn } from "@/lib/utils"
import type { Confidence } from "@/types"

const STYLES: Record<Confidence, string> = {
  high: "text-emerald-700 ring-emerald-200",
  med: "text-amber-700 ring-amber-200",
  low: "text-rose-700 ring-rose-200",
}

const LABELS: Record<Confidence, string> = {
  high: "High confidence",
  med: "Medium confidence",
  low: "Low confidence",
}

const DOTS: Record<Confidence, string> = {
  high: "bg-emerald-500",
  med: "bg-amber-500",
  low: "bg-rose-500",
}

export function ConfidenceBadge({
  confidence,
  compact = false,
}: {
  confidence: Confidence
  compact?: boolean
}) {
  // The problem is: every claim needs a glanceable confidence chip that reads as a
  // "tag" in the Podium family — soft pill, dot indicator, low chrome.
  // The way we solve this is: dot-prefixed pill with a 1px ring instead of a hard
  // border, semantic color triplet per level.
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset",
        STYLES[confidence]
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", DOTS[confidence])} />
      {compact ? confidence : LABELS[confidence]}
    </span>
  )
}
