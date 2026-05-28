from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .ingest import ACCOUNTS, build_corpus, write_corpus
from .stages.s1_goals import extract_goals, write_goals
from .stages.s2_usage import analyze_usage, write_usage_facts
from .stages.s3_gaps import detect_gaps, write_gaps
from .stages.s4_opportunities import detect_opportunities, write_opportunities
from .stages.s5_brief import assemble_brief, write_brief_to_disk

REPO_ROOT = Path(__file__).resolve().parents[2]

STAGES = ["ingest", "s1", "s2", "s3", "s4", "s5"]


def run_pipeline(account_id: str, *, only: str | None = None) -> None:
    # The problem is: the AM wants to kick off the QBR pipeline for one account and
    # see what each stage produced — with the ability to re-run from any single stage.
    # The way we solve this is: linear orchestration with an `only` filter; Apex
    # short-circuits to an insufficient-data brief after ingest (it's a sales lead,
    # not a customer).
    # flow: CLI `mise run pipeline -- --account meridian` -> run_pipeline() <-- HERE
    if only is None or only == "ingest":
        _stage("s0 ingest", account_id)
        corpus = build_corpus(account_id)
        path = write_corpus(account_id, corpus)
        n_t = len(corpus["transcripts"])
        n_lines = sum(t["n_lines"] for t in corpus["transcripts"])
        n_turns = sum(len(t["turns"]) for t in corpus["transcripts"])
        _say(f"  → {_rel(path)}  ·  {n_t} transcripts, {n_lines} lines, {n_turns} turns")

    if account_id == "apex":
        # Sales lead — write the insufficient_data brief, no s1..s4
        _stage("apex insufficient-data", account_id)
        brief = assemble_brief(account_id)
        path = write_brief_to_disk(brief)
        _say(f"  → {_rel(path)}  ·  status={brief.status}")
        return

    if only is None or only == "s1":
        _stage("s1 goals", account_id, " (OpenAI — gpt-5.4-mini)")
        stage_out = extract_goals(account_id)
        path = write_goals(stage_out)
        _say(
            f"  → {_rel(path)}  ·  {len(stage_out.goals)} goals, "
            f"{len(stage_out.evidence)} evidence, {len(stage_out.warnings)} warnings"
        )
        for g in stage_out.goals:
            cites = f"{len(g.evidence_ids)} citation{'' if len(g.evidence_ids) == 1 else 's'}"
            _say(f"    • [{g.confidence}] {g.statement}  ({g.category}, {cites})")

    if only is None or only == "s2":
        _stage("s2 usage", account_id)
        usage_out = analyze_usage(account_id)
        path = write_usage_facts(usage_out)
        owned = sum(1 for f in usage_out.facts.values() if f.owned)
        active = sum(1 for f in usage_out.facts.values() if f.active is True)
        _say(f"  → {_rel(path)}  ·  {len(usage_out.facts)} features, {owned} owned, {active} active")

    if only is None or only == "s3":
        _stage("s3 gaps", account_id)
        gaps_out = detect_gaps(account_id)
        path = write_gaps(gaps_out)
        _say(
            f"  → {_rel(path)}  ·  {len(gaps_out.gaps)} gaps, "
            f"{len(gaps_out.warnings)} warnings"
        )
        for g in gaps_out.gaps:
            goals = ", ".join(g.goal_links)
            _say(f"    • [{g.severity}] {g.feature}  → goals[{goals}]")

    if only is None or only == "s4":
        _stage("s4 opportunities", account_id)
        opps_out = detect_opportunities(account_id)
        path = write_opportunities(opps_out)
        _say(f"  → {_rel(path)}  ·  {len(opps_out.opportunities)} opportunities")
        for o in opps_out.opportunities:
            goals = ", ".join(o.goal_links)
            _say(f"    • [{o.fit_score}] {o.product}  → goals[{goals}]")

    if only is None or only == "s5":
        _stage("s5 brief", account_id)
        brief = assemble_brief(account_id)
        path = write_brief_to_disk(brief)
        _say(
            f"  → {_rel(path)}  ·  status={brief.status}, "
            f"{len(brief.goals)} goals, {len(brief.whats_working)} working, "
            f"{len(brief.gaps)} gaps, {len(brief.opportunities)} opps, "
            f"{len(brief.evidence)} evidence items"
        )


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
    parser.add_argument("--account", required=True, choices=list(ACCOUNTS.keys()))
    parser.add_argument(
        "--only",
        choices=STAGES,
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
