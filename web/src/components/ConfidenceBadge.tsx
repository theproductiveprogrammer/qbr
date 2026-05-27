import { Badge } from "@/components/ui/badge"
import type { Confidence } from "@/types"

const VARIANT: Record<Confidence, "success" | "warning" | "destructive"> = {
  high: "success",
  med: "warning",
  low: "destructive",
}

const LABEL: Record<Confidence, string> = {
  high: "High confidence",
  med: "Medium confidence",
  low: "Low confidence",
}

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  return <Badge variant={VARIANT[confidence]}>{LABEL[confidence]}</Badge>
}
