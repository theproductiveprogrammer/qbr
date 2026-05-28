import { CheckCircle2, AlertCircle, Circle, XCircle, ExternalLink } from "lucide-react"
import type { AccountSummary } from "@/types"
import { AccountAvatar } from "@/components/AccountAvatar"
import { cn } from "@/lib/utils"

const STATUS_META = {
  complete: { icon: CheckCircle2, label: "Reviewed", color: "text-emerald-500" },
  insufficient_data: { icon: AlertCircle, label: "No data", color: "text-amber-500" },
  failed: { icon: XCircle, label: "Failed", color: "text-rose-500" },
  not_run: { icon: Circle, label: "Not run", color: "text-slate-300" },
} as const

export function AccountList({
  accounts,
  selectedId,
  onSelect,
  onOpenInventory,
}: {
  accounts: AccountSummary[]
  selectedId: string | null
  onSelect: (id: string) => void
  onOpenInventory: () => void
}) {
  // The problem is: the AM needs a Podium-shaped sidebar that reads like the rest of
  // the suite — colored avatar thumbnails, dense rows, solid-blue selection state.
  // The header doubles as a navigation gesture to the full Accounts inventory.
  // The way we solve this is: tight row layout with the account avatar on the left,
  // name + vertical stacked, status icon on the right; selected row gets primary-blue
  // background + white foreground per the Podium "All Conversations" pattern. The
  // "Accounts" header is a button — hover reveals an arrow hint that clicking opens
  // the inventory view.
  // flow: App renders -> AccountList <-- HERE (left pane below top bar)
  return (
    <div className="flex h-full flex-col">
      <button
        type="button"
        onClick={onOpenInventory}
        className="group flex items-center justify-between px-4 pb-3 pt-5 text-left transition-colors hover:text-primary"
        title="Open full inventory"
      >
        <span className="inline-flex items-center gap-1.5">
          <h1 className="text-[15px] font-semibold tracking-tight text-foreground group-hover:text-primary">
            Accounts
          </h1>
          <ExternalLink className="h-3 w-3 text-muted-foreground/60 opacity-0 transition-opacity group-hover:opacity-100" />
        </span>
        <span className="text-[11px] font-medium tabular-nums text-muted-foreground">
          {accounts.length}
        </span>
      </button>

      <SectionLabel>Active reviews</SectionLabel>
      <ul className="px-2">
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
                  "flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-left transition-colors",
                  isSelected
                    ? "bg-primary text-primary-foreground"
                    : "text-foreground hover:bg-muted"
                )}
              >
                <AccountAvatar id={account.id} name={account.name} size="md" variant="round" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{account.name}</div>
                  <div
                    className={cn(
                      "truncate text-xs",
                      isSelected ? "text-primary-foreground/80" : "text-muted-foreground"
                    )}
                  >
                    {account.vertical}
                  </div>
                </div>
                <Icon
                  className={cn(
                    "h-4 w-4 shrink-0",
                    isSelected ? "text-primary-foreground/90" : meta.color
                  )}
                  aria-label={meta.label}
                />
              </button>
            </li>
          )
        })}
        {accounts.length === 0 && (
          <li className="px-3 py-3 text-xs text-muted-foreground">No accounts yet.</li>
        )}
      </ul>

      <div className="mt-auto border-t border-border bg-muted/50 px-4 py-3">
        <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Pipeline
        </div>
        <div className="mt-1 flex items-center justify-between text-xs">
          <span className="text-foreground">v0.1.0</span>
          <span className="font-mono text-muted-foreground">gpt-5.5</span>
        </div>
      </div>
    </div>
  )
}

function SectionLabel({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        "px-4 pb-1.5 pt-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground",
        className
      )}
    >
      {children}
    </div>
  )
}

