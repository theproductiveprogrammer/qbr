from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from .store import INPUT_DIR, OUTPUT_DIR

ACCOUNTS_XLSX_FILE = "accounts.xlsx"
ALIASES_FILE = "aliases.json"

ORG_NAME_COL = "ORGANIZATION NAME"
VERTICAL_COL = "ORGANIZATION VERTICAL"
SUBVERTICAL_COL = "ORGANIZATION SUB-VERTICAL"

TURN_HEADER_RE = re.compile(r"^(\d+:\d+)\s*\|\s*(.+?)\s*$")
RECORDED_DATE_RE = re.compile(r"Recorded on\s+([A-Za-z]+\s+\d+,\s*\d{4})")


@dataclass(frozen=True)
class AccountInfo:
    # Identity used internally + in URLs (= the on-disk directory name)
    id: str
    # Human-facing name. xlsx ORGANIZATION NAME when available, else title-cased dir.
    display_name: str
    # "VERTICAL / SUB-VERTICAL" from xlsx, or "Sales lead" when no xlsx row.
    vertical: str
    # The xlsx ORGANIZATION NAME this account resolves to. None = no usage row (lead).
    xlsx_org_name: str | None


@dataclass
class Turn:
    line_start: int
    line_end: int
    timestamp: str
    speaker: str
    text: str


@dataclass
class TranscriptParse:
    n_lines: int
    recorded_date: str | None
    turns: list[Turn]


def parse_recorded_date(content: str) -> str | None:
    # The problem is: transcripts must be processed in chronological order so the LLM
    # sees how customer goals evolved over the relationship, but the filenames carry
    # no date — only the "Recorded on Mon DD, YYYY" line in each file's header.
    # The way we solve this is: regex the date from the first ~30 lines and normalize
    # to ISO (YYYY-MM-DD) so sort is just string-sort.
    # flow: parse_transcript() -> parse_recorded_date() <-- HERE
    head = "\n".join(content.splitlines()[:30])
    m = RECORDED_DATE_RE.search(head)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1).strip(), "%b %d, %Y")
        return dt.date().isoformat()
    except ValueError:
        return None


def parse_transcript(path: Path) -> TranscriptParse:
    # The problem is: each transcript file needs to surface three things downstream —
    # its turns (for quoting), its line count (for stats), and its recorded date (for
    # chronological ordering across calls).
    # The way we solve this is: single read of the file, extract all three, return a
    # TranscriptParse so the caller doesn't re-read.
    # flow: build_corpus() -> parse_transcript() <-- HERE
    content = path.read_text()
    lines = content.splitlines()
    return TranscriptParse(
        n_lines=len(lines),
        recorded_date=parse_recorded_date(content),
        turns=_parse_turns(lines),
    )


def _parse_turns(lines: list[str]) -> list[Turn]:
    # Scan line-by-line for `MM:SS | Speaker` headers, accumulate content until the
    # next header, emit a Turn with the header line as line_start and the last
    # non-blank content line as line_end.
    turns: list[Turn] = []
    cur: dict[str, Any] | None = None

    def finalize(c: dict[str, Any]) -> Turn:
        return Turn(
            line_start=c["line_start"],
            line_end=c["last_content_line"],
            timestamp=c["timestamp"],
            speaker=c["speaker"],
            text="\n".join(c["text_lines"]).strip(),
        )

    for i, line in enumerate(lines, start=1):
        m = TURN_HEADER_RE.match(line)
        if m:
            if cur is not None:
                turns.append(finalize(cur))
            cur = {
                "line_start": i,
                "last_content_line": i,
                "timestamp": m.group(1),
                "speaker": m.group(2),
                "text_lines": [],
            }
        elif cur is not None and line.strip():
            cur["text_lines"].append(line.strip())
            cur["last_content_line"] = i

    if cur is not None:
        turns.append(finalize(cur))
    return turns


# ─────────────────────────── account discovery ───────────────────────────


def _slug(s: str) -> str:
    # Lowercase + non-alphanumeric runs collapsed to "-". Used for fuzzy folder ↔
    # xlsx-name matching so accounts whose folder is already named after the xlsx org
    # don't need an aliases.json entry.
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


@lru_cache(maxsize=1)
def _load_xlsx() -> pd.DataFrame:
    # The problem is: every discovery + usage lookup hits the xlsx; re-reading it
    # for each call wastes time when the file is the same.
    # The way we solve this is: lru_cache so we read once per process. If the file
    # changes the dev server restart will reset the cache.
    return pd.read_excel(INPUT_DIR / ACCOUNTS_XLSX_FILE)


@lru_cache(maxsize=1)
def _load_aliases() -> dict[str, str]:
    # The problem is: some on-disk folder names don't match any xlsx ORGANIZATION
    # NAME (e.g. transcripts call the customer "Meridian" but the xlsx row is
    # "Auscraft Furniture" — Podium-confirmed data drift).
    # The way we solve this is: optional aliases.json declares the bridge. Keys
    # starting with "_" are treated as comments.
    path = INPUT_DIR / ALIASES_FILE
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, str)}


def _resolve_xlsx_org(dir_name: str) -> str | None:
    # The problem is: given a folder name, find its xlsx ORGANIZATION NAME — first
    # via explicit aliases, then via slug fuzzy match, else give up (account is a
    # sales lead with no usage row).
    aliases = _load_aliases()
    if dir_name in aliases:
        return aliases[dir_name]

    df = _load_xlsx()
    org_names = [n for n in df[ORG_NAME_COL].dropna().unique() if isinstance(n, str)]
    dir_slug = _slug(dir_name)
    for org in org_names:
        if _slug(org) == dir_slug:
            return org
    return None


def _vertical_from_xlsx(row: dict[str, Any]) -> str:
    parts: list[str] = []
    v = row.get(VERTICAL_COL)
    sv = row.get(SUBVERTICAL_COL)
    if isinstance(v, str) and v.strip():
        parts.append(v.strip())
    if isinstance(sv, str) and sv.strip():
        parts.append(sv.strip())
    return " / ".join(parts) if parts else "(unknown vertical)"


def _is_account_dir(p: Path) -> bool:
    # An account directory has a transcripts/ or emails/ subfolder. This skips
    # accidental folders or future siblings (e.g. a future _archive/).
    return p.is_dir() and ((p / "transcripts").exists() or (p / "emails").exists())


def discover_accounts() -> dict[str, AccountInfo]:
    # The problem is: hard-coding the account list and per-account metadata in this
    # file means adding a new account requires a code change, and inevitably drifts
    # from the xlsx source of truth.
    # The way we solve this is: scan data/input/ for account directories, resolve
    # each one's xlsx row via aliases.json + slug fallback, pull display name and
    # vertical FROM the xlsx. No-xlsx-row folders become sales leads with no QBR.
    # flow: import-time -> discover_accounts() <-- HERE -> ACCOUNTS dict
    accounts: dict[str, AccountInfo] = {}
    for child in sorted(INPUT_DIR.iterdir()):
        if not _is_account_dir(child):
            continue
        dir_name = child.name
        xlsx_org = _resolve_xlsx_org(dir_name)
        if xlsx_org is not None:
            row = _xlsx_row(xlsx_org) or {}
            display_name = xlsx_org
            vertical = _vertical_from_xlsx(row)
        else:
            display_name = dir_name.replace("-", " ").replace("_", " ").title()
            vertical = "Sales lead"
        accounts[dir_name] = AccountInfo(
            id=dir_name,
            display_name=display_name,
            vertical=vertical,
            xlsx_org_name=xlsx_org,
        )
    return accounts


def _xlsx_row(org_name: str) -> dict[str, Any] | None:
    # The problem is: pandas iloc returns numpy scalars; the resulting dict must be
    # JSON-serializable so downstream stages can persist and the API can serve it.
    # The way we solve this is: convert numpy scalars to Python natives and NaN to
    # None at the boundary.
    # flow: load_usage / discover_accounts -> _xlsx_row() <-- HERE
    df = _load_xlsx()
    matches = df[df[ORG_NAME_COL] == org_name]
    if matches.empty:
        return None
    row = matches.iloc[0]
    out: dict[str, Any] = {}
    for col in df.columns:
        if not isinstance(col, str):
            continue
        val = row[col]
        if pd.isna(val):
            out[col] = None
        elif hasattr(val, "item"):
            out[col] = val.item()
        else:
            out[col] = val
    return out


# Resolve once at import time; downstream code uses this dict. Restart the process
# to pick up filesystem changes (new account folders, edited aliases.json).
ACCOUNTS: dict[str, AccountInfo] = discover_accounts()


# ─────────────────────────── corpus assembly ───────────────────────────


def load_usage(org_name: str | None) -> dict[str, Any] | None:
    if org_name is None:
        return None
    return _xlsx_row(org_name)


def parse_emails(account_dir: Path) -> list[dict[str, Any]]:
    # The problem is: the brief lists "email threads" as an input but the dataset
    # currently ships none. Downstream linking already supports them — we need a
    # hook here so corpus shape includes an `emails` list (empty for now).
    # The way we solve this is: glob the account's emails/ subfolder; return empty
    # until a real parser is wired up.
    emails_dir = account_dir / "emails"
    if not emails_dir.exists():
        return []
    return []


def build_corpus(account_id: str) -> dict[str, Any]:
    # The problem is: each downstream stage needs a single canonical "this is
    # everything we know about this account" artifact rather than re-parsing source
    # files each time.
    # The way we solve this is: bundle parsed transcripts + emails + the resolved
    # usage row into one JSON blob keyed by account_id.
    # flow: graph.node_ingest() -> build_corpus() <-- HERE -> write_corpus()
    if account_id not in ACCOUNTS:
        raise ValueError(f"Unknown account: {account_id!r}. Known: {list(ACCOUNTS)}")
    info = ACCOUNTS[account_id]
    account_dir = INPUT_DIR / info.id

    transcripts: list[dict[str, Any]] = []
    transcripts_dir = account_dir / "transcripts"
    if transcripts_dir.exists():
        for path in sorted(transcripts_dir.glob("*.txt")):
            parsed = parse_transcript(path)
            transcripts.append({
                "file": path.name,
                "n_lines": parsed.n_lines,
                "recorded_date": parsed.recorded_date,
                "turns": [asdict(t) for t in parsed.turns],
            })

    # Chronological ordering — undated transcripts sort last so they don't poison
    # the LLM's read of the relationship arc.
    transcripts.sort(key=lambda t: t["recorded_date"] or "9999-12-31")

    emails = parse_emails(account_dir)
    usage = load_usage(info.xlsx_org_name)

    return {
        "account_id": info.id,
        "account_name": info.display_name,
        "vertical": info.vertical,
        "transcripts": transcripts,
        "emails": emails,
        "usage": usage,
    }


def write_corpus(account_id: str, corpus: dict[str, Any]) -> Path:
    path = OUTPUT_DIR / account_id / "corpus.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(corpus, indent=2, default=str))
    tmp.replace(path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest transcripts + usage data for one account")
    parser.add_argument("--account", required=True, choices=list(ACCOUNTS.keys()))
    args = parser.parse_args()

    try:
        corpus = build_corpus(args.account)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    path = write_corpus(args.account, corpus)
    n_transcripts = len(corpus["transcripts"])
    n_turns = sum(len(t["turns"]) for t in corpus["transcripts"])
    n_lines = sum(t["n_lines"] for t in corpus["transcripts"])
    has_usage = corpus["usage"] is not None
    print(f"wrote {path}")
    print(f"  {n_transcripts} transcripts · {n_lines} lines · {n_turns} turns · usage={has_usage}")


if __name__ == "__main__":
    main()
