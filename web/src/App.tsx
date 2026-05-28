import { useEffect, useState } from "react"
import { AccountList } from "@/components/AccountList"
import { AccountsPane } from "@/components/AccountsPane"
import { ResultsPane } from "@/components/ResultsPane"
import { SettingsPane } from "@/components/SettingsPane"
import { SplashPane } from "@/components/SplashPane"
import { TopBar, type TopLevelView } from "@/components/TopBar"
import { listAccounts } from "@/lib/api"
import type { AccountSummary } from "@/types"

export function App() {
  // The problem is: the app shell routes between three top-level surfaces
  // (briefs, accounts, settings) and within briefs between splash (no selection)
  // and the per-account results pane.
  // The way we solve this is: a `view` state for the top-level tab + a
  // `selectedId` for the account selection inside briefs. Both live here so
  // TopBar, AccountList, and the right-pane components stay dumb. The sidebar
  // appears only on the briefs view — accounts and settings are full-width.
  // flow: page mount -> App <-- HERE -> TopBar + (AccountList + (SplashPane | ResultsPane) | AccountsPane | SettingsPane)
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
    // Selecting an account always implies the briefs view — that's where the
    // brief actually renders. Works from sidebar click AND AccountsPane row click.
    setView("briefs")
    setSelectedId(id)
  }

  return (
    <div className="flex h-screen flex-col bg-background">
      <TopBar view={view} onViewChange={setView} />
      <div className="flex flex-1 overflow-hidden">
        {(view === "briefs" || view === "accounts") && (
          <>
            <aside className="w-[320px] shrink-0 border-r border-border bg-card">
              <AccountList
                accounts={accounts}
                selectedId={view === "briefs" ? selectedId : null}
                onSelect={handleSelectAccount}
                onOpenInventory={() => setView("accounts")}
              />
            </aside>
            <main className="flex-1 overflow-y-auto">
              {error ? (
                <div className="p-8 text-sm text-destructive">
                  Couldn't load accounts: {error}
                </div>
              ) : view === "accounts" ? (
                <AccountsPane accounts={accounts} onSelectAccount={handleSelectAccount} />
              ) : selectedId ? (
                <ResultsPane
                  accountId={selectedId}
                  account={accounts.find(a => a.id === selectedId)}
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
