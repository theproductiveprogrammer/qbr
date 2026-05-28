import { Sparkles, HelpCircle, Settings } from "lucide-react"

export type TopLevelView = "briefs" | "settings"

export function TopBar({
  view,
  onViewChange,
}: {
  view: TopLevelView
  onViewChange: (next: TopLevelView) => void
}) {
  // The problem is: a Podium-family product needs an at-a-glance brand bar that says
  // "this lives inside the Podium ecosystem" rather than feeling like a side tool,
  // and it owns the top-level routing between the briefs surface and the settings
  // surface.
  // The way we solve this is: dark navy header with the brand mark on the left, two
  // nav tabs that drive top-level view state, and a minimal icon strip on the right.
  // flow: App mounts -> TopBar <-- HERE (above main layout, drives view state)
  return (
    <header className="flex h-14 shrink-0 items-center justify-between bg-navbar px-5 text-navbar-foreground">
      <div className="flex items-center gap-3">
        <BrandMark />
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-semibold tracking-tight">QBR Agent</span>
          <span className="hidden text-xs text-navbar-muted md:inline">
            Account Review &amp; Expansion
          </span>
        </div>
        <nav className="ml-8 hidden items-center gap-1 md:flex">
          <NavTab active={view === "briefs"} onClick={() => onViewChange("briefs")}>
            Briefs
          </NavTab>
          <NavTab active={view === "settings"} onClick={() => onViewChange("settings")}>
            Settings
          </NavTab>
        </nav>
      </div>

      <div className="flex items-center gap-1.5">
        <IconButton icon={HelpCircle} label="Help" />
        <IconButton
          icon={Settings}
          label="Settings"
          onClick={() => onViewChange("settings")}
        />
        <UserChip />
      </div>
    </header>
  )
}

function BrandMark() {
  return (
    <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/95 text-primary-foreground shadow-sm">
      <Sparkles className="h-4 w-4" />
    </div>
  )
}

function NavTab({
  children,
  active = false,
  onClick,
}: {
  children: React.ReactNode
  active?: boolean
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        active
          ? "relative px-3 py-2 text-sm font-medium text-white after:absolute after:inset-x-3 after:-bottom-[14px] after:h-[3px] after:rounded-full after:bg-primary"
          : "px-3 py-2 text-sm font-medium text-navbar-muted transition-colors hover:text-white"
      }
    >
      {children}
    </button>
  )
}

function IconButton({
  icon: Icon,
  label,
  onClick,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="rounded-md p-2 text-navbar-muted transition-colors hover:bg-white/5 hover:text-white"
    >
      <Icon className="h-4 w-4" />
    </button>
  )
}

function UserChip() {
  return (
    <div className="ml-1 flex h-8 w-8 items-center justify-center rounded-full bg-amber-300 text-xs font-semibold text-amber-900">
      CL
    </div>
  )
}
