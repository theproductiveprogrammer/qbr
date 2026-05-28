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

export async function getBrief(accountId: string): Promise<Brief | null> {
  // The problem is: an account that exists but has never been run returns 404
  // from /brief — that's a normal state, not an error. Throwing on 404 made the
  // UI show "404 Not Found" instead of an empty-state with a Run button.
  // The way we solve this is: 404 → null. Real errors (5xx, network) still throw.
  // flow: UI account-select -> ResultsPane.useEffect -> getBrief() <-- HERE -> GET /brief
  const res = await fetch(`/accounts/${accountId}/brief`)
  if (res.status === 404) return null
  return jsonOrThrow(res)
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
  // The problem is: callers that don't need streaming (CLI / scripts) still want a
  // simple awaitable that returns the final brief.
  // The way we solve this is: synchronous POST that returns the completed brief.
  // flow: callers -> runAccount() <-- HERE -> POST /run
  return jsonOrThrow(
    await fetch(`/accounts/${accountId}/run`, { method: "POST" })
  )
}

// ── SSE streaming run ──────────────────────────────────────────────────

export type PipelineRunEvent =
  | { type: "start"; data: { account_id: string; stages: string[] } }
  | { type: "stage"; data: { node: string; completed: string[] } }
  | { type: "done"; data: Brief }
  | { type: "error"; data: { message: string; completed: string[] } }

export async function runAccountStreamed(
  accountId: string,
  onEvent: (event: PipelineRunEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  // The problem is: the UI wants live stage-by-stage progress while the LangGraph
  // pipeline runs (~30-90s for a real account). EventSource only supports GET; we
  // need POST. Solution: fetch() with streaming response body + a small SSE parser.
  // The way we solve this is: read the body as chunks via ReadableStream, accumulate
  // into a buffer, split on \n\n (the SSE event terminator), parse each event, and
  // hand it to onEvent.
  // flow: RunButton onClick -> useRunPipeline.start() -> runAccountStreamed() <-- HERE
  const res = await fetch(`/accounts/${accountId}/run/stream`, {
    method: "POST",
    signal,
  })
  if (!res.ok || !res.body) {
    const body = await res.text().catch(() => "")
    throw new Error(`${res.status} ${res.statusText}: ${body || "(no body)"}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      let sepIdx: number
      while ((sepIdx = buffer.indexOf("\n\n")) !== -1) {
        const chunk = buffer.slice(0, sepIdx)
        buffer = buffer.slice(sepIdx + 2)
        const parsed = parseSSEChunk(chunk)
        if (parsed) onEvent(parsed as PipelineRunEvent)
      }
    }
  } finally {
    reader.releaseLock()
  }
}

function parseSSEChunk(chunk: string): { type: string; data: unknown } | null {
  // Per SSE spec: lines starting with `event:` set the type; lines starting with
  // `data:` are concatenated (newline-separated) and parsed as JSON.
  let type = "message"
  const dataLines: string[] = []
  for (const line of chunk.split("\n")) {
    if (line.startsWith("event:")) type = line.slice(6).trim()
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim())
  }
  if (dataLines.length === 0) return null
  try {
    return { type, data: JSON.parse(dataLines.join("\n")) }
  } catch {
    return null
  }
}
