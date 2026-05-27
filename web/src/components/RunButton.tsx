import { useState } from "react"
import { Play, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { runAccount } from "@/lib/api"

export function RunButton({
  accountId,
  hasBrief,
  onComplete,
}: {
  accountId: string
  hasBrief: boolean
  onComplete: () => void
}) {
  // The problem is: triggering the pipeline is a slow synchronous request — UI needs to
  // show running state and surface failures without locking the rest of the app.
  // The way we solve this is: local loading state during the await, and an inline error
  // line if it fails. The button itself is the only thing that goes into a busy state.
  // flow: ResultsPane.Header -> RunButton <-- HERE -> POST /accounts/{id}/run
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleRun() {
    setRunning(true)
    setError(null)
    try {
      await runAccount(accountId)
      onComplete()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="flex items-center gap-3">
      <Button onClick={handleRun} disabled={running} size="sm">
        {running ? (
          <>
            <Loader2 className="animate-spin" />
            Running pipeline…
          </>
        ) : (
          <>
            <Play />
            {hasBrief ? "Re-run pipeline" : "Run pipeline"}
          </>
        )}
      </Button>
      {error && <span className="text-sm text-rose-600">{error}</span>}
    </div>
  )
}
