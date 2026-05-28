import type { AccountSummary, Brief, PipelineSnapshot, SettingsSnapshot } from "@/types"

async function jsonOrThrow<T>(res: Response): Promise<T> {
  // The problem is: silent non-2xx responses would render as empty UI without explaining
  // why nothing came back.
  // The way we solve this is: surface the status + body in the thrown Error so the
  // caller can show something meaningful.
  if (!res.ok) {
    const body = await res.text().catch(() => "")
    throw new Error(`${res.status} ${res.statusText}: ${body || "(no body)"}`)
  }
  return res.json() as Promise<T>
}

export async function listAccounts(): Promise<AccountSummary[]> {
  // flow: UI mounts -> App.useEffect -> listAccounts() <-- HERE -> GET /accounts
  return jsonOrThrow(await fetch("/accounts"))
}

export async function getBrief(accountId: string): Promise<Brief> {
  // flow: UI account-select -> ResultsPane.useEffect -> getBrief() <-- HERE -> GET /brief
  return jsonOrThrow(await fetch(`/accounts/${accountId}/brief`))
}

export async function getSettings(): Promise<SettingsSnapshot> {
  // flow: UI Settings tab -> SettingsPane.useEffect -> getSettings() <-- HERE -> GET /settings
  return jsonOrThrow(await fetch("/settings"))
}

export async function getPipeline(accountId: string): Promise<PipelineSnapshot> {
  // flow: UI Pipeline tab -> PipelinePane.useEffect -> getPipeline() <-- HERE -> GET /pipeline
  return jsonOrThrow(await fetch(`/accounts/${accountId}/pipeline`))
}

export async function runAccount(accountId: string): Promise<Brief> {
  // The problem is: the Run button needs to trigger the pipeline and block until the
  // brief is fresh.
  // The way we solve this is: synchronous POST that returns the completed brief — the
  // UI just awaits it with a spinner.
  // flow: UI Run button -> RunButton.onClick -> runAccount() <-- HERE -> POST /run
  return jsonOrThrow(
    await fetch(`/accounts/${accountId}/run`, { method: "POST" })
  )
}
