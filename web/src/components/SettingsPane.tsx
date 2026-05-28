import { useEffect, useState, type ComponentType, type ReactNode } from "react"
import {
  SlidersHorizontal,
  ArrowRight,
  Users,
  Layers,
  FolderOpen,
  Check,
  AlertTriangle,
  KeyRound,
  Sparkles,
  FileSpreadsheet,
} from "lucide-react"

import { Card, CardContent } from "@/components/ui/card"
import { getSettings } from "@/lib/api"
import { cn } from "@/lib/utils"
import type { SettingsSnapshot } from "@/types"

export function SettingsPane() {
  // The problem is: the AM and any reviewer needs one screen to see what the pipeline
  // is configured with — the alias mapping, what the xlsx resolves to, which features
  // the agent considers, which models are wired up, and whether the API key is set.
  // The way we solve this is: a single GET /settings call returns a structured
  // snapshot; this component renders it as sectioned reference tables — dev-tool
  // density, no marketing flourish.
  // flow: App (view=settings) -> SettingsPane <-- HERE -> GET /settings
  const [settings, setSettings] = useState<SettingsSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getSettings()
      .then(setSettings)
      .catch(err => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return <div className="p-10 text-sm text-muted-foreground">Loading settings…</div>
  }
  if (error || !settings) {
    return <div className="p-10 text-sm text-destructive">Couldn't load settings: {error}</div>
  }

  return (
    <div className="mx-auto max-w-4xl space-y-10 px-6 py-12 sm:px-10">
      <header className="space-y-2">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          System configuration
        </div>
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">Settings</h1>
        <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
          Read-only view of the pipeline's configuration and source-of-truth mappings.
          Everything below is derived from <Code>data/input/</Code> + the running process —
          edit the files and restart the backend to apply changes.
        </p>
      </header>

      <Section icon={SlidersHorizontal} title="Configuration">
        <KeyValueCard>
          <KeyValue
            label="OpenAI API key"
            icon={KeyRound}
            value={
              settings.configuration.openai_key_set ? (
                <StatusPill tone="ok">set</StatusPill>
              ) : (
                <span className="inline-flex items-center gap-2">
                  <StatusPill tone="warn">missing</StatusPill>
                  <span className="text-xs text-muted-foreground">
                    add <Code>OPENAI_API_KEY=…</Code> to <Code>backend/.env</Code>
                  </span>
                </span>
              )
            }
          />
          <KeyValue
            label="Pipeline version"
            icon={Sparkles}
            value={<Code>{settings.configuration.pipeline_version}</Code>}
          />
          <KeyValue
            label="Extraction model"
            value={<Code>{settings.configuration.models.extraction}</Code>}
          />
          <KeyValue
            label="Narrative model"
            value={<Code>{settings.configuration.models.narrative}</Code>}
          />
        </KeyValueCard>
      </Section>

      <Section
        icon={ArrowRight}
        title="Aliases"
        description={<>Folder ↔ xlsx organization-name bridge. Source: <Code>{settings.discovery.aliases_path}</Code></>}
      >
        <DataTable
          headers={["Folder", "", "Organization in xlsx"]}
          rows={Object.entries(settings.discovery.aliases).map(([folder, org]) => [
            <Code key="f">{folder}</Code>,
            <ArrowRight key="a" className="h-3.5 w-3.5 text-muted-foreground" />,
            <span key="o" className="font-medium text-foreground">{org}</span>,
          ])}
          emptyMessage="No aliases declared — folder names must slug-match the xlsx."
          columnWidths={["35%", "1%", "auto"]}
        />
      </Section>

      <Section
        icon={Users}
        title="Resolved accounts"
        description="What discovery produced after applying aliases + slug fallback against the xlsx."
      >
        <DataTable
          headers={["ID", "Display name (xlsx)", "Vertical", "Transcripts", "Emails", "Status"]}
          rows={settings.discovery.accounts.map(a => [
            <Code key="id">{a.id}</Code>,
            <span key="dn" className="text-foreground">{a.display_name}</span>,
            <span key="v" className="text-muted-foreground">{a.vertical}</span>,
            <span key="tc" className="font-mono tabular-nums text-foreground">{a.transcript_count}</span>,
            <span key="ec" className="font-mono tabular-nums text-muted-foreground">{a.email_count}</span>,
            a.is_lead ? (
              <StatusPill key="s" tone="warn">sales lead</StatusPill>
            ) : (
              <StatusPill key="s" tone="ok">linked</StatusPill>
            ),
          ])}
        />
      </Section>

      <Section
        icon={Layers}
        title="Feature catalog"
        description={`${settings.feature_catalog.length} Podium features the agent considers when detecting gaps and opportunities.`}
      >
        <DataTable
          headers={["Feature", "Goal categories", "Ownership", "Activity signal"]}
          rows={settings.feature_catalog.map(f => [
            <span key="l" className="font-medium text-foreground">{f.label}</span>,
            <div key="g" className="flex flex-wrap gap-1">
              {f.goal_categories.map(c => (
                <CategoryChip key={c}>{c}</CategoryChip>
              ))}
            </div>,
            <Code key="o" wrap>{f.ownership_rule}</Code>,
            <Code key="a" wrap>{f.active_signal}</Code>,
          ])}
        />
      </Section>

      <Section icon={FolderOpen} title="Data sources">
        <KeyValueCard>
          <KeyValue
            label="Accounts xlsx"
            icon={FileSpreadsheet}
            value={
              <span className="inline-flex items-baseline gap-2">
                <Code>{settings.discovery.xlsx.path}</Code>
                <span className="text-xs text-muted-foreground">
                  {settings.discovery.xlsx.row_count} row{settings.discovery.xlsx.row_count === 1 ? "" : "s"}
                </span>
              </span>
            }
          />
          <KeyValue label="Input root" value={<Code>{settings.data_paths.input}</Code>} />
          <KeyValue label="Output root" value={<Code>{settings.data_paths.output}</Code>} />
        </KeyValueCard>
      </Section>
    </div>
  )
}

// ─────────────────────────── building blocks ───────────────────────────

function Section({
  icon: Icon,
  title,
  description,
  children,
}: {
  icon: ComponentType<{ className?: string }>
  title: string
  description?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-0.5">
          <h2 className="flex items-center gap-2 text-base font-semibold tracking-tight text-foreground">
            <Icon className="h-4 w-4 text-primary" />
            {title}
          </h2>
          {description && (
            <p className="text-sm leading-relaxed text-muted-foreground">{description}</p>
          )}
        </div>
      </div>
      {children}
    </section>
  )
}

function KeyValueCard({ children }: { children: ReactNode }) {
  return (
    <Card>
      <CardContent className="p-0">
        <dl className="divide-y divide-border">{children}</dl>
      </CardContent>
    </Card>
  )
}

function KeyValue({
  label,
  icon: Icon,
  value,
}: {
  label: string
  icon?: ComponentType<{ className?: string }>
  value: ReactNode
}) {
  return (
    <div className="grid grid-cols-[180px_1fr] items-center gap-4 px-5 py-3">
      <dt className="inline-flex items-center gap-2 text-sm text-muted-foreground">
        {Icon && <Icon className="h-3.5 w-3.5" />}
        <span>{label}</span>
      </dt>
      <dd className="text-sm text-foreground">{value}</dd>
    </div>
  )
}

function DataTable({
  headers,
  rows,
  columnWidths,
  emptyMessage,
}: {
  headers: string[]
  rows: ReactNode[][]
  columnWidths?: string[]
  emptyMessage?: string
}) {
  if (rows.length === 0) {
    return (
      <Card>
        <CardContent className="p-6 text-center text-sm text-muted-foreground">
          {emptyMessage ?? "No entries."}
        </CardContent>
      </Card>
    )
  }
  return (
    <Card>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            {columnWidths && (
              <colgroup>
                {columnWidths.map((w, i) => (
                  <col key={i} style={{ width: w }} />
                ))}
              </colgroup>
            )}
            <thead>
              <tr className="border-b border-border bg-muted/40">
                {headers.map((h, i) => (
                  <th
                    key={i}
                    className="px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, ri) => (
                <tr key={ri} className="border-b border-border last:border-b-0">
                  {row.map((cell, ci) => (
                    <td key={ci} className="px-4 py-3 align-top">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}

function StatusPill({
  tone,
  children,
}: {
  tone: "ok" | "warn" | "err"
  children: ReactNode
}) {
  const styles = {
    ok: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    warn: "bg-amber-50 text-amber-700 ring-amber-200",
    err: "bg-rose-50 text-rose-700 ring-rose-200",
  }[tone]
  const dot = {
    ok: "bg-emerald-500",
    warn: "bg-amber-500",
    err: "bg-rose-500",
  }[tone]
  const Icon = tone === "ok" ? Check : AlertTriangle
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        styles
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", dot)} />
      <Icon className="h-3 w-3" />
      {children}
    </span>
  )
}

function CategoryChip({ children }: { children: ReactNode }) {
  return (
    <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-foreground/80">
      {children}
    </span>
  )
}

function Code({ children, wrap = false }: { children: ReactNode; wrap?: boolean }) {
  return (
    <code
      className={cn(
        "rounded bg-muted px-1.5 py-0.5 font-mono text-[12.5px] font-medium text-foreground",
        wrap && "whitespace-normal break-words"
      )}
    >
      {children}
    </code>
  )
}
