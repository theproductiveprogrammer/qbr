import { cn } from "@/lib/utils"

const PALETTE = [
  "bg-blue-500 text-white",
  "bg-violet-500 text-white",
  "bg-pink-500 text-white",
  "bg-emerald-500 text-white",
  "bg-amber-500 text-amber-950",
  "bg-rose-500 text-white",
  "bg-cyan-500 text-white",
] as const

function colorFor(seed: string): string {
  // The problem is: each account needs a consistent identifying color across visits so
  // the AM builds visual recognition for "their" accounts.
  // The way we solve this is: deterministic hash of the account id mod palette length.
  let hash = 0
  for (let i = 0; i < seed.length; i++) {
    hash = (hash * 31 + seed.charCodeAt(i)) >>> 0
  }
  return PALETTE[hash % PALETTE.length]
}

export function AccountAvatar({
  id,
  name,
  size = "md",
  variant = "round",
  className,
}: {
  id: string
  name: string
  size?: "sm" | "md" | "lg"
  variant?: "round" | "square"
  className?: string
}) {
  const initial = (name.trim()[0] ?? "?").toUpperCase()
  const sizeCls =
    size === "lg" ? "h-12 w-12 text-base" : size === "sm" ? "h-7 w-7 text-[11px]" : "h-9 w-9 text-sm"
  const radius = variant === "square" ? "rounded-md" : "rounded-full"
  return (
    <div
      aria-hidden
      className={cn(
        "flex shrink-0 items-center justify-center font-semibold",
        sizeCls,
        radius,
        colorFor(id),
        className
      )}
    >
      {initial}
    </div>
  )
}
