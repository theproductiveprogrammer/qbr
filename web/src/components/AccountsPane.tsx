import {
  CheckCircle2,
  AlertCircle,
  Circle,
  XCircle,
  ChevronRight,
  FileText,
  Mail,
  ArrowRight,
} from "lucide-react"

import { AccountAvatar } from "@/components/AccountAvatar"
import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import type { AccountSummary, Status } from "@/types"

export function AccountsPane({
  accounts,
  onSelectAccount,
}: {
  accounts: AccountSummary[]
  onSelectAccount: (id: string) => void
}) {
  // The problem is: the account inventory is the operational surface — it tells
  // you what's been reviewed, what hasn't, and how much source data each
  // account has. Burying it in the Briefs splash made it transient (gone the
  // moment you picked an account).
  // The way we solve this is: a dedicated full-width top-level view. Click any
  // row to jump to that account's brief; click "Accounts" in the top nav (or
  // the sidebar header) to come back.
  // flow: TopBar click "Accounts" -> App view=accounts -> AccountsPane <-- HERE
  const linkedCount = accounts.filter(a => !a.is_lead).length
  const leadCount = accounts.filter(a => a.is_lead).length
  const reviewedCount = accounts.filter(a => a.status === "complete").length

  return (
    <div className="mx-auto max-w-4xl px-6 py-10 sm:px-10">
      <header className="mb-6 flex items-end justify-between gap-4">
        <div className="space-y-1">
          <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
            Inventory
          </div>
          <h1 className="text-[22px] font-semibold tracking-tight text-foreground">
            Accounts
          </h1>
        </div>
        <div className="flex items-center gap-1.5 text-xs">
          <StatPill label={`${accounts.length} total`} />
          {reviewedCount > 0 && (
            <StatPill label={`${reviewedCount} reviewed`} tone="ok" />
          )}
          {leadCount > 0 && (
            <StatPill label={`${leadCount} lead${leadCount === 1 ? "" : "s"}`} tone="warn" />
          )}
        </div>
      </header>

      <p className="mb-6 max-w-2xl text-[13px] leading-relaxed text-muted-foreground">
        Discovered from <Code>data/input/</Code>
        {linkedCount > 0 && (
          <>
            {" "}· {linkedCount} linked to <Code>accounts.xlsx</Code>
          </>
        )}
        . Click any row to open its brief.
      </p>

      {accounts.length === 0 ? (
        <EmptyState />
      ) : (
        <Card>
          <CardContent className="p-0">
            <ul className="divide-y divide-border">
              {accounts.map(a => (
                <AccountRow
                  key={a.id}
                  account={a}
                  onClick={() => onSelectAccount(a.id)}
                />
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

// ─────────────────────────── account row ───────────────────────────

const STATUS_META: Record<
  Status | "not_run",
  { label: string; icon: typeof Circle; pill: string }
> = {
  complete: {
    label: "Reviewed",
    icon: CheckCircle2,
    pill: "text-emerald-700 ring-emerald-200",
  },
  insufficient_data: {
    label: "Sales lead",
    icon: AlertCircle,
    pill: "text-amber-700 ring-amber-200",
  },
  failed: {
    label: "Failed",
    icon: XCircle,
    pill: "text-rose-700 ring-rose-200",
  },
  not_run: {
    label: "Not run",
    icon: Circle,
    pill: "text-slate-600 ring-slate-200",
  },
}

function AccountRow({
  account,
  onClick,
}: {
  account: AccountSummary
  onClick: () => void
}) {
  const status = STATUS_META[account.status]
  const StatusIcon = status.icon
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className="group flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary"
      >
        <AccountAvatar id={account.id} name={account.name} size="md" variant="round" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-semibold text-foreground">
              {account.name}
            </span>
            {account.is_lead && (
              <span className="rounded-full px-1.5 py-0 text-[10px] font-medium leading-4 text-amber-700 ring-1 ring-inset ring-amber-200">
                lead
              </span>
            )}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12px] text-muted-foreground">
            <span className="truncate">{account.vertical}</span>
            <Sep />
            <SourceCount icon={FileText} count={account.transcript_count} label="transcript" />
            {account.email_count > 0 && (
              <>
                <Sep />
                <SourceCount icon={Mail} count={account.email_count} label="email" />
              </>
            )}
          </div>
        </div>
        <span
          className={cn(
            "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset",
            status.pill,
          )}
        >
          <StatusIcon className="h-3 w-3" />
          {status.label}
        </span>
        <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/60 transition-all group-hover:translate-x-0.5 group-hover:text-primary" />
      </button>
    </li>
  )
}

function Sep() {
  return <span aria-hidden className="text-foreground/20">·</span>
}

function SourceCount({
  icon: Icon,
  count,
  label,
}: {
  icon: typeof FileText
  count: number
  label: string
}) {
  return (
    <span className="inline-flex items-center gap-1">
      <Icon className="h-3 w-3" />
      <span className="font-mono tabular-nums text-foreground/75">{count}</span>
      <span>{label}{count === 1 ? "" : "s"}</span>
    </span>
  )
}

function StatPill({ label, tone }: { label: string; tone?: "ok" | "warn" }) {
  const styles =
    tone === "ok"
      ? "text-emerald-700 ring-emerald-200"
      : tone === "warn"
      ? "text-amber-700 ring-amber-200"
      : "text-foreground/70 ring-border"
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 font-medium ring-1 ring-inset",
        styles,
      )}
    >
      {label}
    </span>
  )
}

function EmptyState() {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-3 px-6 py-12 text-center">
        <div className="rounded-full bg-muted p-3">
          <ArrowRight className="h-5 w-5 text-muted-foreground" />
        </div>
        <div className="space-y-1">
          <div className="text-sm font-semibold text-foreground">No accounts discovered</div>
          <p className="text-xs text-muted-foreground">
            Drop a folder under{" "}
            <Code>data/input/&lt;account&gt;/transcripts/</Code> and restart the backend.
          </p>
        </div>
      </CardContent>
    </Card>
  )
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[12px] font-medium text-foreground">
      {children}
    </code>
  )
}
