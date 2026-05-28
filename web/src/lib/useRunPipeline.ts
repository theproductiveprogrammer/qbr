import { useCallback, useRef, useState } from "react"
import { runAccountStreamed, type PipelineRunEvent } from "@/lib/api"
import type { Brief } from "@/types"

export type RunStatus = "idle" | "running" | "complete" | "failed"

export type RunState = {
  // Status of the most recent (or in-progress) run for this account.
  status: RunStatus
  // The full stage list (sent by the server in the `start` event). Empty pre-run.
  stages: string[]
  // Stages the server has emitted a `stage` event for. Order matches arrival.
  completed: string[]
  // Fresh brief from the `done` event — null until the run finishes.
  brief: Brief | null
  // Set on `error` event or fetch failure.
  error: string | null
}

const INITIAL: RunState = {
  status: "idle",
  stages: [],
  completed: [],
  brief: null,
  error: null,
}

export function useRunPipeline(accountId: string) {
  // The problem is: the Run button and the progress strip both need the same
  // streaming-pipeline state, and the run lifecycle (start → many stage events →
  // done|error) doesn't fit into a single useEffect.
  // The way we solve this is: a hook that owns the state machine. start() opens
  // the SSE connection and pipes events into setState. Switching accounts mid-run
  // aborts the previous fetch via AbortController.
  // flow: ResultsPane / RunButton -> useRunPipeline(accountId) <-- HERE
  const [state, setState] = useState<RunState>(INITIAL)
  const abortRef = useRef<AbortController | null>(null)

  const start = useCallback(async () => {
    abortRef.current?.abort()
    const ac = new AbortController()
    abortRef.current = ac

    setState({ ...INITIAL, status: "running" })

    try {
      await runAccountStreamed(
        accountId,
        (event: PipelineRunEvent) => {
          if (event.type === "start") {
            setState(s => ({ ...s, stages: event.data.stages }))
          } else if (event.type === "stage") {
            setState(s => ({ ...s, completed: event.data.completed }))
          } else if (event.type === "done") {
            setState(s => ({ ...s, status: "complete", brief: event.data }))
          } else if (event.type === "error") {
            setState(s => ({
              ...s,
              status: "failed",
              error: event.data.message,
              completed: event.data.completed ?? s.completed,
            }))
          }
        },
        ac.signal,
      )
    } catch (err) {
      if (ac.signal.aborted) return
      setState(s => ({
        ...s,
        status: "failed",
        error: err instanceof Error ? err.message : String(err),
      }))
    }
  }, [accountId])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    setState(INITIAL)
  }, [])

  return { ...state, start, reset }
}
