import { CheckCircle2, AlertCircle, Circle, XCircle } from "lucide-react"
import type { AccountSummary } from "@/types"
import { cn } from "@/lib/utils"

const STATUS_META = {
  complete: { icon: CheckCircle2, label: "Reviewed", color: "text-emerald-600" },
  insufficient_data: { icon: AlertCircle, label: "No data", color: "text-amber-600" },
  failed: { icon: XCircle, label: "Failed", color: "text-rose-600" },
  not_run: { icon: Circle, label: "Not run", color: "text-slate-400" },
} as const

export function AccountList({
  accounts,
  selectedId,
  onSelect,
}: {
  accounts: AccountSummary[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  // The problem is: the AM needs a glanceable index of which accounts have been reviewed
  // and which still need attention.
  // The way we solve this is: render a vertical list with each account's status icon
  // visible at the row level, selection state on the active item.
  // flow: App renders -> AccountList <-- HERE (left pane)
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-slate-200 px-5 py-5">
        <div className="text-xs font-medium uppercase tracking-wider text-violet-600">
          QBR Agent
        </div>
        <h1 className="mt-1 text-lg font-semibold text-slate-900">Accounts</h1>
      </div>
      <ul className="flex-1 overflow-y-auto py-2">
        {accounts.map(account => {
          const meta = STATUS_META[account.status]
          const Icon = meta.icon
          const isSelected = account.id === selectedId
          return (
            <li key={account.id}>
              <button
                type="button"
                onClick={() => onSelect(account.id)}
                className={cn(
                  "flex w-full flex-col items-start gap-1 border-l-2 border-transparent px-5 py-3 text-left transition-colors hover:bg-slate-50",
                  isSelected && "border-violet-600 bg-violet-50/60 hover:bg-violet-50/60"
                )}
              >
                <div className="flex w-full items-center justify-between gap-2">
                  <span
                    className={cn(
                      "text-sm font-medium text-slate-900",
                      isSelected && "text-violet-900"
                    )}
                  >
                    {account.name}
                  </span>
                  <Icon className={cn("h-4 w-4", meta.color)} aria-label={meta.label} />
                </div>
                <span className="text-xs text-slate-500">{account.vertical}</span>
              </button>
            </li>
          )
        })}
        {accounts.length === 0 && (
          <li className="px-5 py-3 text-xs text-slate-400">No accounts yet.</li>
        )}
      </ul>
    </div>
  )
}
