import { Target, TrendingUp, AlertTriangle, CheckCircle2 } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import type { DeckOutline as DeckOutlineType } from "@/types"

const SECTIONS = [
  { key: "goals" as const, title: "Goals", icon: Target },
  { key: "performance" as const, title: "Current performance", icon: CheckCircle2 },
  { key: "gaps" as const, title: "Gaps", icon: AlertTriangle },
  { key: "recommendations" as const, title: "Recommendations", icon: TrendingUp },
]

export function DeckOutline({
  outline,
  accountName,
}: {
  outline: DeckOutlineType
  accountName: string
}) {
  // The problem is: the customer-facing view is a different audience than the internal
  // brief — same source data, different framing (positive, action-oriented, no
  // confidence noise).
  // The way we solve this is: render outline-shaped bullets in QBR section order.
  // flow: ResultsPane (view=customer) -> DeckOutline <-- HERE
  return (
    <Card>
      <CardContent className="space-y-8 p-8">
        <div className="text-center">
          <div className="text-xs font-medium uppercase tracking-wider text-violet-600">
            Quarterly Business Review
          </div>
          <div className="mt-2 text-2xl font-semibold text-slate-900">{accountName}</div>
        </div>
        <div className="space-y-6">
          {SECTIONS.map(section => {
            const items = outline[section.key]
            if (items.length === 0) return null
            const Icon = section.icon
            return (
              <div key={section.key} className="space-y-3">
                <div className="flex items-center gap-2">
                  <Icon className="h-4 w-4 text-violet-600" />
                  <h3 className="font-semibold text-slate-900">{section.title}</h3>
                </div>
                <ul className="list-disc space-y-2 pl-6 text-slate-700">
                  {items.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
