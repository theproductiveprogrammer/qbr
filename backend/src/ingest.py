from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import openpyxl

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
ORG_NAME_COL = "ORGANIZATION NAME"


@dataclass
class Turn:
    line_start: int
    line_end: int
    timestamp: str
    speaker: str
    text: str


def parse_transcript(path: Path) -> list[Turn]:
    # The problem is: transcripts are walls of text with timestamp+speaker headers and
    # multi-line content blocks, and the pipeline needs line-anchored quoteable chunks
    # so downstream evidence locators line up with what the AM sees in the file.
    # The way we solve this is: scan line-by-line for the `MM:SS | Speaker` header
    # pattern, accumulate content until the next header, emit a Turn with the header
    # line as line_start and the last non-blank content line as line_end.
    # flow: pipeline -> build_corpus() -> parse_transcript() <-- HERE
    turns: list[Turn] = []
    lines = path.read_text().splitlines()
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
    # specific account, normalized to a {column: value} dict.
    # The way we solve this is: stream rows looking for ORGANIZATION NAME match,
    # zip with headers, return None if not found (so Apex flows through cleanly).
    # flow: pipeline -> build_corpus() -> load_usage() <-- HERE
    if org_name is None:
        return None
    wb = openpyxl.load_workbook(INPUT_DIR / "accounts.xlsx", data_only=True)
    ws = wb.active
    if ws is None:
        raise RuntimeError("accounts.xlsx has no active worksheet")
    rows = ws.iter_rows(values_only=True)
    headers = [str(h) if h is not None else "" for h in next(rows)]
    name_idx = headers.index(ORG_NAME_COL)
    for row in rows:
        if row[name_idx] == org_name:
            out: dict[str, Any] = {}
            for i, h in enumerate(headers):
                if h:
                    out[h] = row[i]
            return out
    return None


def build_corpus(account_id: str) -> dict[str, Any]:
    # The problem is: each downstream stage needs a single canonical "this is everything
    # we know about this account" artifact rather than re-parsing transcripts each time.
    # The way we solve this is: bundle parsed transcripts + the usage row into one
    # JSON blob keyed by account_id.
    # flow: pipeline.run_pipeline() -> build_corpus() <-- HERE -> write_corpus()
    if account_id not in ACCOUNTS:
        raise ValueError(f"Unknown account: {account_id!r}. Known: {list(ACCOUNTS)}")
    cfg = ACCOUNTS[account_id]

    transcripts = []
    for path in sorted(INPUT_DIR.glob(cfg["transcript_glob"])):
        turns = parse_transcript(path)
        transcripts.append({
            "file": path.name,
            "n_lines": len(path.read_text().splitlines()),
            "turns": [asdict(t) for t in turns],
        })

    usage = load_usage(cfg["usage_org_name"])

    return {
        "account_id": account_id,
        "account_name": cfg["name"],
        "vertical": cfg["vertical"],
        "transcripts": transcripts,
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
