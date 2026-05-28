from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..ingest import ACCOUNTS, AccountInfo
from ..schemas import (
    Brief,
    ConfidenceSummary,
    DeckOutline,
    Evidence,
    Gap,
    Goal,
    Opportunity,
    UsageLocator,
    WorkingItem,
)
from ..store import OUTPUT_DIR, write_brief

PIPELINE_VERSION = "0.2.0"


def assemble_brief(account_id: str) -> Brief:
    # The problem is: the AM's UI consumes a single `brief.json` per account, but the
    # pipeline writes per-stage artifacts. We need a deterministic assembler that
    # composes those artifacts into the schema the UI validates against.
    # The way we solve this is: load each stage's artifact, project fields into the
    # Brief shape, synthesize the customer-facing outline from structured data
    # (no LLM call here in v0), merge all evidence maps under one set of stable IDs,
    # let pydantic's @model_validator catch any drift. The "is this a sales lead?"
    # decision is read from the corpus (no usage row → insufficient_data), so no
    # account-name literal lives anywhere in this file.
    # flow: graph.node_assemble_brief() -> assemble_brief() <-- HERE -> write_brief()
    info = ACCOUNTS[account_id]
    corpus = _load(account_id, "corpus.json")

    if corpus.get("usage") is None:
        return _insufficient_data_brief(info)

    goals_data = _load(account_id, "goals.json")
    usage_data = _load(account_id, "usage_facts.json")
    gaps_data = _load(account_id, "gaps.json")
    opps_data = _load(account_id, "opportunities.json")

    goals = [Goal(**g) for g in goals_data["goals"]]
    gaps = [Gap(**g) for g in gaps_data.get("gaps", [])]
    opportunities = [Opportunity(**o) for o in opps_data.get("opportunities", [])]

    whats_working, working_evidence = _whats_working_from_usage(usage_data, next_ev_id=1)

    evidence: dict[str, Evidence] = {
        **{eid: Evidence(**ev) for eid, ev in goals_data.get("evidence", {}).items()},
        **{eid: Evidence(**ev) for eid, ev in gaps_data.get("evidence", {}).items()},
        **{eid: Evidence(**ev) for eid, ev in opps_data.get("evidence", {}).items()},
        **working_evidence,
    }

    confidence_summary = _count_confidence(goals, whats_working, gaps, opportunities)
    outline = _synthesize_outline(goals, whats_working, gaps, opportunities)

    return Brief(
        account_id=account_id,
        account_name=info.display_name,
        vertical=info.vertical,
        run_id=str(uuid.uuid4()),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        pipeline_version=PIPELINE_VERSION,
        status="complete",
        review_banner=None,
        confidence_summary=confidence_summary,
        goals=goals,
        whats_working=whats_working,
        gaps=gaps,
        opportunities=opportunities,
        outline=outline,
        evidence=evidence,
    )


def write_brief_to_disk(brief: Brief) -> Path:
    # flow: pipeline.run_pipeline() -> assemble_brief() -> write_brief_to_disk() <-- HERE
    write_brief(brief.account_id, brief)
    return OUTPUT_DIR / brief.account_id / "brief.json"


def _load(account_id: str, filename: str) -> dict[str, Any]:
    path = OUTPUT_DIR / account_id / filename
    if not path.exists():
        raise FileNotFoundError(
            f"{filename} missing for {account_id!r}; earlier pipeline stage hasn't run."
        )
    return json.loads(path.read_text())


def _whats_working_from_usage(
    usage_data: dict[str, Any],
    next_ev_id: int,
) -> tuple[list[WorkingItem], dict[str, Evidence]]:
    # The problem is: "what's working" needs at-a-glance evidence that the agent is
    # giving credit where credit is due — not just calling out gaps.
    # The way we solve this is: every feature that is both owned AND active becomes
    # a WorkingItem, with the activity-column value as its cited evidence.
    items: list[WorkingItem] = []
    evidence: dict[str, Evidence] = {}
    counter = next_ev_id
    for feat_id, facts in usage_data["facts"].items():
        if not (facts["owned"] and facts["active"] is True):
            continue
        # Pick the first signal column with a usable value as the citation
        signal_col, signal_val = next(
            ((c, v) for c, v in facts["signals"].items() if v not in (None, "")),
            (None, None),
        )
        if signal_col is None:
            continue
        ev_id = f"ev_work_{counter:03d}"
        counter += 1
        evidence[ev_id] = Evidence(
            id=ev_id,
            source="usage",
            locator=UsageLocator(kind="usage", column=signal_col),
            quote=_render(signal_val),
        )
        items.append(WorkingItem(
            feature=facts["label"],
            summary=f"{facts['label']} is actively engaged in the last 30 days.",
            signal=f"{signal_col}: {_render(signal_val)}",
            confidence="high",
            evidence_ids=[ev_id],
        ))
    return items, evidence


def _render(v: Any) -> str:
    if v is None or v == "":
        return "(empty)"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _count_confidence(
    goals: list[Goal],
    working: list[WorkingItem],
    gaps: list[Gap],
    opps: list[Opportunity],
) -> ConfidenceSummary:
    counter: Counter[str] = Counter()
    for item in [*goals, *working, *gaps, *opps]:
        counter[item.confidence] += 1
    return ConfidenceSummary(
        high=counter.get("high", 0),
        med=counter.get("med", 0),
        low=counter.get("low", 0),
    )


def _synthesize_outline(
    goals: list[Goal],
    working: list[WorkingItem],
    gaps: list[Gap],
    opps: list[Opportunity],
) -> DeckOutline:
    # No LLM here in v0 — synthesize the customer-facing outline directly from the
    # structured findings. When goal/gap quality is good, swap to an LLM call.
    return DeckOutline(
        goals=[g.statement for g in goals[:4]],
        performance=[w.summary for w in working[:4]],
        gaps=[g.summary for g in gaps[:4]],
        recommendations=(
            [g.recommended_action for g in gaps[:3]]
            + [f"Pilot {o.product} this quarter." for o in opps[:3]]
        ),
    )


def _insufficient_data_brief(info: "AccountInfo") -> Brief:
    return Brief(
        account_id=info.id,
        account_name=info.display_name,
        vertical=info.vertical,
        run_id=str(uuid.uuid4()),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        pipeline_version=PIPELINE_VERSION,
        status="insufficient_data",
        status_reason=(
            f"{info.display_name} has no usage row on file — likely a sales lead. "
            "QBRs require an active customer relationship; there is nothing to review yet."
        ),
        confidence_summary=ConfidenceSummary(high=0, med=0, low=0),
        goals=[],
        whats_working=[],
        gaps=[],
        opportunities=[],
        outline=DeckOutline(goals=[], performance=[], gaps=[], recommendations=[]),
        evidence={},
    )
