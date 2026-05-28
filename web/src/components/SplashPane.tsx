import ReactMarkdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"
import { Sparkles } from "lucide-react"

import readmeContent from "../../../README.md?raw"
import type { AccountSummary } from "@/types"

// React-markdown component map. Explicit components beat fighting Tailwind prose
// specificity for the kind of editorial typography this splash needs.
const COMPONENTS: Components = {
  h1: ({ children }) => (
    <h1 className="mt-0 mb-6 font-display text-[56px] font-normal leading-[1.02] tracking-[-0.015em] text-foreground sm:text-[68px]">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="mt-16 mb-5 flex items-center gap-3 text-[26px] font-semibold tracking-tight text-foreground">
      <span
        aria-hidden
        className="inline-block h-2.5 w-2.5 shrink-0 rounded-[3px] bg-primary"
      />
      <span>{children}</span>
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="mt-10 mb-3 text-[12px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
      {children}
    </h3>
  ),
  p: ({ children }) => (
    <p className="my-5 text-[17px] leading-[1.7] text-foreground/85">{children}</p>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold text-foreground">{children}</strong>
  ),
  em: ({ children }) => <em className="italic text-foreground">{children}</em>,
  a: ({ children, href }) => (
    <a
      href={href}
      className="text-primary underline-offset-4 transition-colors hover:underline"
    >
      {children}
    </a>
  ),
  ul: ({ children }) => (
    <ul className="my-5 list-disc space-y-2.5 pl-6 marker:text-primary/50">
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="my-5 list-decimal space-y-2.5 pl-6 marker:font-mono marker:font-semibold marker:text-primary">
      {children}
    </ol>
  ),
  li: ({ children }) => (
    <li className="pl-1 text-[17px] leading-[1.7] text-foreground/85">{children}</li>
  ),
  code: ({ children, className }) => {
    // Fenced blocks come with a language-* className OR with newline content (fenced
    // without a language tag, like the README's Project layout block). Either way
    // they're block — let the parent <pre> handle styling. Only single-line untagged
    // strings get the inline chip.
    const text = String(children ?? "")
    const isBlock = !!className || text.includes("\n")
    if (isBlock) {
      return <code className={className}>{children}</code>
    }
    return (
      <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.88em] font-medium text-foreground">
        {children}
      </code>
    )
  },
  pre: ({ children }) => (
    <pre className="my-7 overflow-x-auto rounded-lg border border-slate-800 bg-slate-900 p-5 text-[13.5px] leading-[1.65] text-slate-100 shadow-sm">
      {children}
    </pre>
  ),
  blockquote: ({ children }) => (
    <blockquote className="my-6 border-l-2 border-primary pl-5 text-foreground/75 [&>p]:italic">
      {children}
    </blockquote>
  ),
  hr: () => (
    <hr className="my-12 h-px border-0 bg-gradient-to-r from-transparent via-border to-transparent" />
  ),
  table: ({ children }) => (
    <div className="my-8 overflow-x-auto rounded-lg border border-border">
      <table className="w-full border-collapse text-[15px]">{children}</table>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="border-b border-border bg-muted/40">{children}</thead>
  ),
  tr: ({ children }) => (
    <tr className="border-b border-border last:border-b-0">{children}</tr>
  ),
  th: ({ children }) => (
    <th className="px-4 py-3 text-left text-[12px] font-semibold uppercase tracking-wider text-muted-foreground">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="px-4 py-3 align-top text-foreground/85">{children}</td>
  ),
}

export function SplashPane({
  accounts: _accounts,
  onSelectAccount: _onSelectAccount,
}: {
  accounts: AccountSummary[]
  onSelectAccount: (id: string) => void
}) {
  // The problem is: when the app opens with no account selected, the reviewer should
  // see the project README — that way editing README.md propagates to the splash
  // without a code change, keeping one source of truth.
  // The way we solve this is: Vite `?raw` import of /README.md rendered through
  // react-markdown with explicit component mappings tuned to editorial typography:
  // Instrument Serif display H1, blue-square H2 markers, restrained prose body.
  // Account navigation stays in the left pane — splash is content-only.
  // flow: App (selectedId === null) -> SplashPane <-- HERE
  return (
    <div className="mx-auto max-w-3xl px-6 pb-24 pt-16 sm:px-10">
      <div
        className="splash-fade-up mb-12 inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-primary"
        style={{ animationDelay: "0ms" }}
      >
        <Sparkles className="h-3 w-3" />
        Podium AI GTM Engineer Case Study
      </div>
      <article
        className="splash-fade-up"
        style={{ animationDelay: "80ms" }}
      >
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
          {readmeContent}
        </ReactMarkdown>
      </article>
    </div>
  )
}
