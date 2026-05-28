import { useEffect, useState } from "react"
import { AccountList } from "@/components/AccountList"
import { ResultsPane } from "@/components/ResultsPane"
import { SettingsPane } from "@/components/SettingsPane"
import { SplashPane } from "@/components/SplashPane"
import { TopBar, type TopLevelView } from "@/components/TopBar"
import { listAccounts } from "@/lib/api"
import type { AccountSummary } from "@/types"

export function App() {
  // The problem is: the app shell routes between two top-level surfaces (briefs +
  // settings) and within briefs between splash (no selection) and the per-account
  // results pane.
  // The way we solve this is: a `view` state for the top-level tab + a `selectedId`
  // for the account selection inside briefs. Both live here so TopBar, AccountList,
  // and the right-pane components stay dumb.
  // flow: page mount -> App <-- HERE -> TopBar + (AccountList + (SplashPane | ResultsPane) | SettingsPane)
  const [view, setView] = useState<TopLevelView>("briefs")
  const [accounts, setAccounts] = useState<AccountSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listAccounts()
      .then(setAccounts)
      .catch(err => setError(err instanceof Error ? err.message : String(err)))
  }, [refreshKey])

  function handleSelectAccount(id: string) {
    // Selecting an account always implies the briefs view.
    setView("briefs")
    setSelectedId(id)
  }

  return (
    <div className="flex h-screen flex-col bg-background">
      <TopBar view={view} onViewChange={setView} />
      <div className="flex flex-1 overflow-hidden">
        {view === "briefs" && (
          <>
            <aside className="w-[320px] shrink-0 border-r border-border bg-card">
              <AccountList
                accounts={accounts}
                selectedId={selectedId}
                onSelect={handleSelectAccount}
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
                <SplashPane accounts={accounts} onSelectAccount={handleSelectAccount} />
              )}
            </main>
          </>
        )}
        {view === "settings" && (
          <main className="flex-1 overflow-y-auto">
            <SettingsPane />
          </main>
        )}
      </div>
    </div>
  )
}
