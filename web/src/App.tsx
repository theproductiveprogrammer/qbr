import { useEffect, useState } from "react"
import { AccountList } from "@/components/AccountList"
import { ResultsPane } from "@/components/ResultsPane"
import { SplashPane } from "@/components/SplashPane"
import { TopBar } from "@/components/TopBar"
import { listAccounts } from "@/lib/api"
import type { AccountSummary } from "@/types"

export function App() {
  // The problem is: the app shell keeps the account list in sync with the backend and
  // routes between the splash (when nothing is selected) and a results pane (when an
  // account is picked).
  // The way we solve this is: fetch /accounts on mount and whenever a pipeline run
  // completes; selectedId stays null until the user clicks an account or a splash CTA.
  // flow: page mount -> App <-- HERE -> TopBar + AccountList + (SplashPane | ResultsPane)
  const [accounts, setAccounts] = useState<AccountSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listAccounts()
      .then(setAccounts)
      .catch(err => setError(err instanceof Error ? err.message : String(err)))
  }, [refreshKey])

  return (
    <div className="flex h-screen flex-col bg-background">
      <TopBar />
      <div className="flex flex-1 overflow-hidden">
        <aside className="w-[320px] shrink-0 border-r border-border bg-card">
          <AccountList
            accounts={accounts}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </aside>
        <main className="flex-1 overflow-y-auto">
          {error ? (
            <div className="p-8 text-sm text-destructive">
              Couldn't load accounts: {error}
            </div>
          ) : selectedId ? (
            <ResultsPane
              accountId={selectedId}
              onRunComplete={() => setRefreshKey(k => k + 1)}
            />
          ) : (
            <SplashPane accounts={accounts} onSelectAccount={setSelectedId} />
          )}
        </main>
      </div>
    </div>
  )
}
