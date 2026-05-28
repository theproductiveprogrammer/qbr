from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..feature_catalog import CATALOG
from ..schemas import Evidence, Opportunity, UsageLocator
from ..store import OUTPUT_DIR


class OpportunitiesStageOutput(BaseModel):
    account_id: str
    opportunities: list[Opportunity]
    evidence: dict[str, Evidence]
    warnings: list[str] = Field(default_factory=list)


def detect_opportunities(account_id: str) -> OpportunitiesStageOutput:
    # The problem is: surfacing upsell candidates that won't feel forced — products
    # the account doesn't have, that align with a goal the customer actually stated.
    # The way we solve this is: rules-only candidate generation for v0. For each
    # feature NOT owned by the account, check whether its goal_categories overlap
    # with any extracted goal; if yes, emit an Opportunity. LLM-written rationale is
    # deferred until s1 goal quality is tight enough to trust as input.
    # flow: pipeline.run_pipeline() -> detect_opportunities() <-- HERE -> write
    usage_data = _load(account_id, "usage_facts.json")
    goals_data = _load(account_id, "goals.json")

    goals_by_category: dict[str, list[str]] = defaultdict(list)
    goal_statements: dict[str, str] = {}
    goals_by_id: dict[str, dict[str, Any]] = {}
    for g in goals_data.get("goals", []):
        goals_by_category[g["category"]].append(g["id"])
        goal_statements[g["id"]] = g["statement"]
        goals_by_id[g["id"]] = g

    opps: list[Opportunity] = []
    evidence: dict[str, Evidence] = {}
    warnings: list[str] = []
    ev_counter = 1

    for feat_id, facts in usage_data["facts"].items():
        feature = CATALOG.get(feat_id)
        if feature is None or facts["owned"]:
            continue

        linked: set[str] = set()
        for cat in facts["goal_categories"]:
            linked.update(goals_by_category.get(cat, []))
        if not linked:
            continue  # no goal alignment — not a credible opportunity in v0

        # Evidence: every signal column we have for this feature, showing not-owned
        ev_ids: list[str] = []
        for col, val in facts["signals"].items():
            ev_id = f"ev_opp_{ev_counter:03d}"
            ev_counter += 1
            evidence[ev_id] = Evidence(
                id=ev_id,
                source="usage",
                locator=UsageLocator(kind="usage", column=col),
                quote=_render_quote(val),
            )
            ev_ids.append(ev_id)

        # The problem is: opportunity cards need to show both the usage signals proving
        # the product isn't owned AND the customer's own words motivating the pitch.
        # The way we solve this is: prepend the linked goals' transcript evidence IDs
        # to the opportunity's evidence list (deduped). The brief assembler merges
        # everything into one evidence map at write time.
        goal_evidence_ids: list[str] = []
        seen: set[str] = set()
        for goal_id in sorted(linked):
            goal = goals_by_id.get(goal_id)
            if not goal:
                continue
            for goal_ev_id in goal.get("evidence_ids", []):
                if goal_ev_id not in seen:
                    seen.add(goal_ev_id)
                    goal_evidence_ids.append(goal_ev_id)

        opps.append(Opportunity(
            id=f"opp_{len(opps) + 1:03d}",
            product=facts["label"],
            fit_score=_score_fit(facts, len(linked)),
            goal_links=sorted(linked),
            rationale=_rationale(facts, [goal_statements[gid] for gid in sorted(linked)]),
            signals=_signal_bullets(facts),
            confidence="med",  # rules-only confidence cap until LLM rationale lands
            evidence_ids=goal_evidence_ids + ev_ids,
        ))

    opps.sort(key=lambda o: o.fit_score, reverse=True)
    return OpportunitiesStageOutput(
        account_id=account_id, opportunities=opps, evidence=evidence, warnings=warnings,
    )


def write_opportunities(output: OpportunitiesStageOutput) -> Path:
    path = OUTPUT_DIR / output.account_id / "opportunities.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(output.model_dump_json(indent=2))
    tmp.replace(path)
    return path


def _load(account_id: str, filename: str) -> dict[str, Any]:
    path = OUTPUT_DIR / account_id / filename
    if not path.exists():
        raise FileNotFoundError(
            f"{filename} missing for {account_id!r}; earlier pipeline stage hasn't run."
        )
    return json.loads(path.read_text())


def _render_quote(v: Any) -> str:
    if v is None or v == "":
        return "(empty)"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _score_fit(facts: dict[str, Any], n_linked_goals: int) -> int:
    # Mirrors s3._score_severity shape. Base 55, +10 per linked goal up to a cap.
    return min(55 + min(20, n_linked_goals * 10), 90)


def _rationale(facts: dict[str, Any], goal_statements: list[str]) -> str:
    label = facts["label"]
    if not goal_statements:
        return f"{label} aligns with goals the customer has stated this quarter."
    joined = " and ".join(f"“{s}”" for s in goal_statements[:2])
    return (
        f"{label} is not currently active for this account but aligns with stated "
        f"customer goals — including {joined}."
    )


def _signal_bullets(facts: dict[str, Any]) -> list[str]:
    bullets: list[str] = []
    for col, val in facts["signals"].items():
        bullets.append(f"{col}: {_render_quote(val)}")
    return bullets
