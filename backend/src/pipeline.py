from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .graph import PIPELINE_GRAPH
from .ingest import ACCOUNTS, build_corpus, write_corpus
from .stages.s1_goals import extract_goals, write_goals
from .stages.s2_usage import analyze_usage, write_usage_facts
from .stages.s3_gaps import detect_gaps, write_gaps
from .stages.s4_opportunities import detect_opportunities, write_opportunities
from .stages.s5_brief import assemble_brief, write_brief_to_disk

REPO_ROOT = Path(__file__).resolve().parents[2]

STAGES = ["ingest", "s1", "s2", "s3", "s4", "s5"]


def run_pipeline(account_id: str, *, only: str | None = None) -> None:
    # The problem is: developers want fast iteration on a single stage (`--only s1`)
    # while the production path needs the whole graph with retries + conditional
    # routing.
    # The way we solve this is: --only X bypasses the graph and calls the stage
    # function directly; no --only runs the compiled LangGraph end-to-end, which
    # gives us free retries on the LLM node and the apex/lead branch with zero
    # account-name literals.
    # flow: CLI `mise run pipeline -- --account meridian` -> run_pipeline() <-- HERE
    if only is not None:
        _run_single_stage(account_id, only)
        return

    _say(f"[graph] {account_id}  (LangGraph: ingest → s1 → s2 → s3 → s4 → s5)")
    for event in PIPELINE_GRAPH.stream({"account_id": account_id}, stream_mode="updates"):
        for node_name in event.keys():
            _say(f"  ✓ {node_name}")
    _say(f"[done] {account_id}  →  {_rel(REPO_ROOT / 'data' / 'output' / account_id / 'brief.json')}")


def _run_single_stage(account_id: str, stage: str) -> None:
    # Direct stage execution, used during dev iteration. Bypasses LangGraph so the
    # earlier stages don't need to re-run.
    if stage == "ingest":
        _stage("s0 ingest", account_id)
        corpus = build_corpus(account_id)
        path = write_corpus(account_id, corpus)
        n_t = len(corpus["transcripts"])
        n_turns = sum(len(t["turns"]) for t in corpus["transcripts"])
        _say(f"  → {_rel(path)}  ·  {n_t} transcripts, {n_turns} turns")
    elif stage == "s1":
        from .config import load_pipeline_config
        _stage("s1 goals", account_id, f" (OpenAI — {load_pipeline_config().extraction_model})")
        out = extract_goals(account_id)
        path = write_goals(out)
        _say(f"  → {_rel(path)}  ·  {len(out.goals)} goals, {len(out.evidence)} evidence, {len(out.warnings)} warnings")
        for g in out.goals:
            _say(f"    • [{g.confidence}] {g.statement}  ({g.category})")
    elif stage == "s2":
        _stage("s2 usage", account_id)
        out = analyze_usage(account_id)
        path = write_usage_facts(out)
        owned = sum(1 for f in out.facts.values() if f.owned)
        active = sum(1 for f in out.facts.values() if f.active is True)
        _say(f"  → {_rel(path)}  ·  {len(out.facts)} features, {owned} owned, {active} active")
    elif stage == "s3":
        _stage("s3 gaps", account_id)
        out = detect_gaps(account_id)
        path = write_gaps(out)
        _say(f"  → {_rel(path)}  ·  {len(out.gaps)} gaps")
    elif stage == "s4":
        _stage("s4 opportunities", account_id)
        out = detect_opportunities(account_id)
        path = write_opportunities(out)
        _say(f"  → {_rel(path)}  ·  {len(out.opportunities)} opportunities")
    elif stage == "s5":
        _stage("s5 narrative", account_id)
        brief = assemble_brief(account_id)
        path = write_brief_to_disk(brief)
        _say(f"  → {_rel(path)}  ·  status={brief.status}")


def _stage(label: str, account_id: str, suffix: str = "") -> None:
    _say(f"[{label}] {account_id}{suffix}")


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def _say(msg: str) -> None:
    print(msg, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(prog="pipeline", description="Run the QBR pipeline for one account")
    parser.add_argument("--account", required=True, choices=sorted(ACCOUNTS.keys()))
    parser.add_argument(
        "--only",
        choices=STAGES,
        help="Run only one stage (bypasses the LangGraph; earlier artifacts must exist)",
    )
    args = parser.parse_args()
    try:
        run_pipeline(args.account, only=args.only)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
