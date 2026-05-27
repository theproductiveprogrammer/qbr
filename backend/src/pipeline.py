from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .ingest import ACCOUNTS, build_corpus, write_corpus
from .stages.s1_goals import extract_goals, write_goals

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_pipeline(account_id: str, *, only: str | None = None) -> None:
    # The problem is: the AM wants to kick off the full pipeline for one account and
    # see what each stage produced, ideally with the ability to re-run from a stage.
    # The way we solve this is: linear orchestration with `only` filter for re-runs;
    # Apex short-circuits after ingest because it's a sales lead, not a customer.
    # flow: CLI `mise run pipeline -- --account meridian` -> run_pipeline() <-- HERE
    if only is None or only == "ingest":
        _say(f"[s0 ingest] {account_id}")
        corpus = build_corpus(account_id)
        path = write_corpus(account_id, corpus)
        n_t = len(corpus["transcripts"])
        n_lines = sum(t["n_lines"] for t in corpus["transcripts"])
        n_turns = sum(len(t["turns"]) for t in corpus["transcripts"])
        _say(f"  → {_rel(path)}  ·  {n_t} transcripts, {n_lines} lines, {n_turns} turns")

    if account_id == "apex":
        _say(f"[apex] sales lead — skipping s1+ (no usage data on file)")
        return

    if only is None or only == "s1":
        _say(f"[s1 goals] {account_id}  (OpenAI call — gpt-5.4-mini)")
        stage_out = extract_goals(account_id)
        path = write_goals(stage_out)
        _say(f"  → {_rel(path)}  ·  {len(stage_out.goals)} goals, {len(stage_out.evidence)} evidence items")
        for g in stage_out.goals:
            cites = f"{len(g.evidence_ids)} citation{'' if len(g.evidence_ids) == 1 else 's'}"
            _say(f"    • [{g.confidence}] {g.statement}  ({g.category}, {cites})")


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def _say(msg: str) -> None:
    print(msg, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pipeline",
        description="Run the QBR pipeline for one account",
    )
    parser.add_argument("--account", required=True, choices=list(ACCOUNTS.keys()))
    parser.add_argument(
        "--only",
        choices=["ingest", "s1"],
        help="Run only one stage (others must already have artifacts on disk)",
    )
    args = parser.parse_args()
    try:
        run_pipeline(args.account, only=args.only)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
