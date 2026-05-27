import { useEffect, useState } from "react"
import { AccountList } from "@/components/AccountList"
import { ResultsPane } from "@/components/ResultsPane"
import { listAccounts } from "@/lib/api"
import type { AccountSummary } from "@/types"

export function App() {
  // The problem is: the top-level app needs to keep the account list in sync with the
  // backend and pass the current selection into the results pane.
  // The way we solve this is: fetch /accounts on mount and whenever a pipeline run
  // completes (refreshKey bump); default the selection to the first account.
  // flow: page mount -> App <-- HERE -> AccountList + ResultsPane
  const [accounts, setAccounts] = useState<AccountSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listAccounts()
      .then(setAccounts)
      .catch(err => setError(err instanceof Error ? err.message : String(err)))
  }, [refreshKey])

  useEffect(() => {
    if (!selectedId && accounts.length > 0) {
      setSelectedId(accounts[0].id)
    }
  }, [accounts, selectedId])

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="mx-auto flex h-screen max-w-[1400px]">
        <aside className="w-[300px] shrink-0 border-r border-slate-200 bg-white">
          <AccountList
            accounts={accounts}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </aside>
        <main className="flex-1 overflow-y-auto">
          {error ? (
            <div className="p-8 text-sm text-rose-600">
              Couldn't load accounts: {error}
            </div>
          ) : selectedId ? (
            <ResultsPane
              accountId={selectedId}
              onRunComplete={() => setRefreshKey(k => k + 1)}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-slate-400">
              Pick an account to begin
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
