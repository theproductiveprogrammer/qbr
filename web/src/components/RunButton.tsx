import { Play, Loader2, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { RunStatus } from "@/lib/useRunPipeline"

export function RunButton({
  status,
  hasBrief,
  onRun,
}: {
  status: RunStatus
  hasBrief: boolean
  onRun: () => void
}) {
  // The problem is: the button needs to reflect run state (idle / running /
  // complete / failed) and dispatch a new run on click, but the streaming state
  // itself lives in useRunPipeline up in ResultsPane.
  // The way we solve this is: stay presentational — take status + onRun, render
  // the right label + icon, disable while running.
  // flow: ResultsPane.Header -> RunButton <-- HERE -> useRunPipeline.start()
  const isRunning = status === "running"
  const Icon = isRunning ? Loader2 : hasBrief ? RefreshCw : Play
  const label = isRunning
    ? "Running pipeline…"
    : hasBrief
    ? "Re-run pipeline"
    : "Run pipeline"

  return (
    <Button onClick={onRun} disabled={isRunning} size="sm">
      <Icon className={isRunning ? "animate-spin" : ""} />
      {label}
    </Button>
  )
}
