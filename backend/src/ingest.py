from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .store import INPUT_DIR, OUTPUT_DIR

ACCOUNTS: dict[str, dict[str, Any]] = {
    "meridian": {
        "name": "Meridian Furniture Group",
        "vertical": "Retail / Furniture",
        "transcript_glob": "call-transcript--meridian-furniture-*.txt",
        "usage_org_name": "Auscraft Furniture",
    },
    "northfield": {
        "name": "Northfield Electrical",
        "vertical": "Home Services / Electrical",
        "transcript_glob": "call-transcript--northfield-electrical-*.txt",
        "usage_org_name": "Mr Sparky",
    },
    "apex": {
        "name": "Apex",
        "vertical": "Sales lead — no usage data on file",
        "transcript_glob": "call-transcript--apex-*.txt",
        "usage_org_name": None,
    },
}

TURN_HEADER_RE = re.compile(r"^(\d+:\d+)\s*\|\s*(.+?)\s*$")
RECORDED_DATE_RE = re.compile(r"Recorded on\s+([A-Za-z]+\s+\d+,\s*\d{4})")
ORG_NAME_COL = "ORGANIZATION NAME"


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


def load_usage(org_name: str | None) -> dict[str, Any] | None:
    # The problem is: the xlsx has 100+ columns and we only want the row matching a
    # specific account, normalized to a JSON-serializable {column: value} dict.
    # The way we solve this is: pandas reads the whole sheet, we slice the row by
    # ORGANIZATION NAME, then convert numpy/pandas scalars to native Python types and
    # NaN to None so JSON serialization is clean downstream.
    # flow: pipeline -> build_corpus() -> load_usage() <-- HERE
    if org_name is None:
        return None
    df = pd.read_excel(INPUT_DIR / "accounts.xlsx")
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
        elif hasattr(val, "item"):  # numpy scalar → native Python
            out[col] = val.item()
        else:
            out[col] = val
    return out


def parse_emails(account_id: str) -> list[dict[str, Any]]:
    # The problem is: the brief lists "email threads" as an input, but the case-study
    # dataset ships with no emails. Downstream linking already supports them — we just
    # need a hook here so the corpus shape includes an `emails` list (empty for now).
    # The way we solve this is: return an empty list until real email data lands; when
    # it does, this is where the parser slots in.
    # flow: pipeline.run_pipeline() -> build_corpus() -> parse_emails() <-- HERE
    _ = account_id
    return []


def build_corpus(account_id: str) -> dict[str, Any]:
    # The problem is: each downstream stage needs a single canonical "this is everything
    # we know about this account" artifact rather than re-parsing source files each
    # time.
    # The way we solve this is: bundle parsed transcripts + emails + the usage row into
    # one JSON blob keyed by account_id.
    # flow: pipeline.run_pipeline() -> build_corpus() <-- HERE -> write_corpus()
    if account_id not in ACCOUNTS:
        raise ValueError(f"Unknown account: {account_id!r}. Known: {list(ACCOUNTS)}")
    cfg = ACCOUNTS[account_id]

    transcripts = []
    for path in sorted(INPUT_DIR.glob(cfg["transcript_glob"])):
        parsed = parse_transcript(path)
        transcripts.append({
            "file": path.name,
            "n_lines": parsed.n_lines,
            "recorded_date": parsed.recorded_date,
            "turns": [asdict(t) for t in parsed.turns],
        })

    # Chronological ordering — undated transcripts (shouldn't happen in this dataset)
    # sort last so they don't poison the LLM's read of the relationship arc.
    transcripts.sort(key=lambda t: t["recorded_date"] or "9999-12-31")

    emails = parse_emails(account_id)
    usage = load_usage(cfg["usage_org_name"])

    return {
        "account_id": account_id,
        "account_name": cfg["name"],
        "vertical": cfg["vertical"],
        "transcripts": transcripts,
        "emails": emails,
        "usage": usage,
    }


def write_corpus(account_id: str, corpus: dict[str, Any]) -> Path:
    # The problem is: writing partway through a long run would leave a half-corpus on
    # disk that downstream stages might try to parse.
    # The way we solve this is: write to a sibling .tmp file then atomic rename.
    # flow: pipeline.run_pipeline() -> build_corpus() -> write_corpus() <-- HERE
    path = OUTPUT_DIR / account_id / "corpus.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(corpus, indent=2, default=str))
    tmp.replace(path)
    return path


def main() -> None:
    # flow: CLI `mise run pipeline -- --only ingest` -> ingest.main() <-- HERE
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
