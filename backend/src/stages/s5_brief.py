from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..config import load_pipeline_config
from ..feature_catalog import CATALOG, RuleColumnCheck
from ..ingest import ACCOUNTS, AccountInfo
from ..llm import parse_structured
from ..schemas import (
    Brief,
    ConfidenceSummary,
    DeckOutline,
    Evidence,
    Gap,
    Goal,
    Opportunity,
    ReviewBanner,
    UsageLocator,
    WorkingItem,
)
from ..store import OUTPUT_DIR, write_brief

PIPELINE_VERSION = "0.2.0"

NARRATE_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "narrate_findings.md"


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

    # Narrate gap summaries / recommended actions and opportunity rationales
    # via one LLM call. Rules-detected items are not re-decided here — the
    # LLM only fills in the prose fields. See narrate_findings() for the
    # constraints + failure-mode handling.
    gaps, opportunities, narration_banner = _narrate_findings(
        info, goals, gaps, opportunities, evidence, usage_data["facts"],
    )

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
        review_banner=narration_banner,
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
    # The customer outline slices already-narrated fields (no second LLM call
    # and no hardcoded "Pilot X this quarter" templates). Both gap and opp
    # recommended_action are filled by s5 narration upstream — if narration
    # failed they read as "[narration failed]" which surfaces the issue
    # explicitly rather than hiding behind a generic phrase.
    return DeckOutline(
        goals=[g.statement for g in goals[:4]],
        performance=[w.summary for w in working[:4]],
        gaps=[g.summary for g in gaps[:4]],
        recommendations=(
            [g.recommended_action for g in gaps[:3]]
            + [o.recommended_action for o in opps[:3]]
        ),
    )


# ────────────────────────── narration ──────────────────────────


class _NarratedGap(BaseModel):
    id: str
    summary: str
    recommended_action: str


class _NarratedOpportunity(BaseModel):
    id: str
    rationale: str
    recommended_action: str


class _NarrationResponse(BaseModel):
    gaps: list[_NarratedGap]
    opportunities: list[_NarratedOpportunity]


def _narrate_findings(
    info: "AccountInfo",
    goals: list[Goal],
    gaps: list[Gap],
    opps: list[Opportunity],
    evidence: dict[str, Evidence],
    usage_facts: dict[str, Any],
) -> tuple[list[Gap], list[Opportunity], ReviewBanner | None]:
    # The problem is: rules detect WHAT counts as a gap or opportunity, but the
    # prose for an AM-facing brief should reference the customer's own words and
    # specific usage numbers — not generic templates.
    # The way we solve this is: one LLM call that takes the structured findings
    # (with each item denormalized so the LLM has linked goals + customer quotes
    # + trigger numbers per item) and returns id-keyed narrations. Pydantic
    # validates the shape; we additionally check that every input id is narrated
    # exactly once. On any failure (timeout, validation, id-mismatch), the
    # brief still ships — gaps/opps keep their "[narration pending]" placeholders
    # and a review_banner alerts the AM.
    # flow: assemble_brief() -> _narrate_findings() <-- HERE -> OpenAI
    if not gaps and not opps:
        return gaps, opps, None  # nothing to narrate

    config = load_pipeline_config()
    packet = _build_narration_packet(info, goals, gaps, opps, evidence, usage_facts)
    user_content = json.dumps(packet, indent=2, default=str)
    system_prompt = NARRATE_PROMPT_PATH.read_text()

    try:
        response = parse_structured(
            model=config.narration_model,
            system_prompt=system_prompt,
            user_content=user_content,
            response_format=_NarrationResponse,
            temperature=config.narration_temperature,
        )
        narrated_gaps, narrated_opps = _apply_narrations(gaps, opps, response)
        return narrated_gaps, narrated_opps, None
    except Exception as exc:
        # The narration is the polish step, not the data. If it fails (rate
        # limit, refusal, id mismatch), ship the brief with [narration failed]
        # in every narrated field — that way the customer outline + internal
        # brief surface the failure explicitly instead of leaking the mid-
        # pipeline "[narration pending]" string OR a hardcoded fallback that
        # would hide the issue.
        narration_failed = "[narration failed]"
        failed_gaps = [
            gap.model_copy(update={
                "summary": narration_failed,
                "recommended_action": narration_failed,
            })
            for gap in gaps
        ]
        failed_opps = [
            opp.model_copy(update={
                "rationale": narration_failed,
                "recommended_action": narration_failed,
            })
            for opp in opps
        ]
        banner = ReviewBanner(
            severity="warning",
            message=(
                "Narration LLM call failed — gap summaries, recommended actions, and "
                f"opportunity rationales show as '[narration failed]'. Underlying rules "
                f"+ evidence are unaffected. ({exc!s})"
            ),
        )
        return failed_gaps, failed_opps, banner


def _build_narration_packet(
    info: "AccountInfo",
    goals: list[Goal],
    gaps: list[Gap],
    opps: list[Opportunity],
    evidence: dict[str, Evidence],
    usage_facts: dict[str, Any],
) -> dict[str, Any]:
    # Denormalize: linked goals carry their statement + customer quotes inline,
    # and each gap carries the specific column/value/threshold that fired the
    # rule. The LLM gets everything it needs per item — no need to send the
    # full catalog or all account-level usage data.
    goals_by_id = {g.id: g for g in goals}

    def linked_goals(goal_ids: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for gid in goal_ids:
            g = goals_by_id.get(gid)
            if g is None:
                continue
            quotes = [
                evidence[eid].quote
                for eid in g.evidence_ids
                if eid in evidence and evidence[eid].source == "transcript"
            ]
            out.append({
                "id": g.id,
                "statement": g.statement,
                "customer_quotes": quotes,
            })
        return out

    return {
        "account": {"name": info.display_name, "vertical": info.vertical},
        "gaps": [
            {
                "id": gap.id,
                "feature": gap.feature,
                "severity": gap.severity,
                "linked_goals": linked_goals(gap.goal_links),
                "trigger_signal": _trigger_signal_for_gap(gap, usage_facts),
            }
            for gap in gaps
        ],
        "opportunities": [
            {
                "id": opp.id,
                "product": opp.product,
                "fit_score": opp.fit_score,
                "linked_goals": linked_goals(opp.goal_links),
            }
            for opp in opps
        ],
    }


def _trigger_signal_for_gap(gap: Gap, usage_facts: dict[str, Any]) -> dict[str, Any] | None:
    # Lookup the catalog rule that triggered this gap so we can hand the LLM
    # the specific column/value/threshold (e.g. "WEBCHAT LEADS = 5, < 10").
    feature_id = _feature_id_for_label(gap.feature)
    if feature_id is None:
        return None
    feature = CATALOG[feature_id]
    rule = feature.underused_when
    if not isinstance(rule, RuleColumnCheck):
        return None
    value = usage_facts.get(feature_id, {}).get("signals", {}).get(rule.col)
    return {
        "field": rule.col,
        "value": value,
        "trigger": _format_rule_trigger(rule),
    }


def _feature_id_for_label(label: str) -> str | None:
    for fid, feature in CATALOG.items():
        if feature.label == label:
            return fid
    return None


def _format_rule_trigger(rule: RuleColumnCheck) -> str:
    op_words = {"lt": "<", "gt": ">", "ever_gt": "ever >", "equals": "==", "contains": "contains"}
    op = op_words.get(rule.op, rule.op)
    return f"{op} {rule.value} (underused threshold)"


def _apply_narrations(
    gaps: list[Gap],
    opps: list[Opportunity],
    response: _NarrationResponse,
) -> tuple[list[Gap], list[Opportunity]]:
    # Pydantic already validated the shape — here we check id-match (the LLM
    # could return the right number of items but with mismatched ids).
    gap_narr = {n.id: n for n in response.gaps}
    opp_narr = {n.id: n for n in response.opportunities}

    expected_gap_ids = {g.id for g in gaps}
    expected_opp_ids = {o.id for o in opps}
    if set(gap_narr) != expected_gap_ids or set(opp_narr) != expected_opp_ids:
        raise ValueError(
            f"Narration id mismatch — expected gaps={sorted(expected_gap_ids)}, "
            f"got {sorted(gap_narr)}; expected opps={sorted(expected_opp_ids)}, "
            f"got {sorted(opp_narr)}"
        )

    new_gaps = [
        gap.model_copy(update={
            "summary": gap_narr[gap.id].summary,
            "recommended_action": gap_narr[gap.id].recommended_action,
        })
        for gap in gaps
    ]
    new_opps = [
        opp.model_copy(update={
            "rationale": opp_narr[opp.id].rationale,
            "recommended_action": opp_narr[opp.id].recommended_action,
        })
        for opp in opps
    ]
    return new_gaps, new_opps


# ────────────────────────── insufficient data ──────────────────────────


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
