from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..feature_catalog import CATALOG
from ..schemas import Evidence, Gap, UsageLocator
from ..store import OUTPUT_DIR

NARRATION_PENDING = "[narration pending]"


class GapsStageOutput(BaseModel):
    account_id: str
    gaps: list[Gap]
    evidence: dict[str, Evidence]
    warnings: list[str] = Field(default_factory=list)


def detect_gaps(account_id: str) -> GapsStageOutput:
    # The problem is: identifying which Podium features the account owns but has
    # stopped using AND that map back to a stated customer goal — the heart of an
    # adoption gap.
    # The way we solve this is: rules over (usage_facts × goals × feature_catalog).
    # No LLM call here — the catalog's `goal_categories` is the join key, and the
    # ownership / activity flags from stage 2 are the truth values. The LLM never
    # decides what counts as a gap.
    # flow: pipeline.run_pipeline() -> detect_gaps() <-- HERE -> write_gaps()
    usage_data = _load(account_id, "usage_facts.json")
    goals_data = _load(account_id, "goals.json")

    goals_by_category: dict[str, list[str]] = defaultdict(list)
    goals_by_id: dict[str, dict[str, Any]] = {}
    for g in goals_data.get("goals", []):
        goals_by_category[g["category"]].append(g["id"])
        goals_by_id[g["id"]] = g

    gaps: list[Gap] = []
    evidence: dict[str, Evidence] = {}
    warnings: list[str] = []
    ev_counter = 1

    for feat_id, facts in usage_data["facts"].items():
        feature = CATALOG.get(feat_id)
        if feature is None:
            continue  # catalog drift; safe to skip
        if not facts["owned"]:
            continue
        if facts["active"] is True or facts["active"] is None:
            continue  # active or unknowable — not a gap

        linked: set[str] = set()
        for cat in facts["goal_categories"]:
            linked.update(goals_by_category.get(cat, []))
        if not linked:
            warnings.append(
                f"{facts['label']} is owned-but-inactive but no stated goal maps to it; "
                f"deferred as a usage-driven gap (not emitted in v0)."
            )
            continue

        ev_id = f"ev_gap_{ev_counter:03d}"
        ev_counter += 1
        # The underused-when rule names the column we cite as gap evidence. If a
        # feature has no underused rule (e.g. paid_phones), it can't surface a
        # gap (s2 returns active=None for it), so we never reach this branch.
        active_col = _underused_column(feature) or ""
        signal_value = facts["signals"].get(active_col)
        evidence[ev_id] = Evidence(
            id=ev_id,
            source="usage",
            locator=UsageLocator(kind="usage", column=active_col),
            quote=_render_quote(signal_value),
        )

        # The problem is: a gap card with only the usage signal as evidence forces the
        # AM to mentally connect "feature underused" → "customer goal this blocks". They
        # need both halves visible side by side.
        # The way we solve this is: prepend each linked goal's transcript evidence IDs
        # to this gap's evidence list (deduped). The brief assembler merges all stage
        # evidence into one map, so these IDs resolve in the UI without any extra work.
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

        gaps.append(Gap(
            id=f"gap_{len(gaps) + 1:03d}",
            feature=facts["label"],
            severity=_score_severity(facts, len(linked)),
            goal_links=sorted(linked),
            # Prose is filled in by s5 narration. The placeholder keeps the
            # schema valid mid-pipeline and surfaces clearly in the UI if the
            # narration call fails after retries.
            summary=NARRATION_PENDING,
            recommended_action=NARRATION_PENDING,
            confidence="high",
            evidence_ids=goal_evidence_ids + [ev_id],
        ))

    gaps.sort(key=lambda g: g.severity, reverse=True)

    return GapsStageOutput(account_id=account_id, gaps=gaps, evidence=evidence, warnings=warnings)


def write_gaps(output: GapsStageOutput) -> Path:
    path = OUTPUT_DIR / output.account_id / "gaps.json"
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
    if v is None:
        return "(empty)"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _score_severity(facts: dict[str, Any], n_linked_goals: int) -> int:
    # The problem is: gaps need a ranking so the top-of-page recommendations are the
    # ones the AM should lead with.
    # The way we solve this is: simple additive heuristic — base 60, +10 per linked
    # goal (capped), +10 if the signal is literally zero (vs just below threshold).
    # We can replace this with a learned ranker later; for now it just needs to be
    # defensible.
    score = 60 + min(20, n_linked_goals * 10)
    return min(score, 95)


def _underused_column(feature: Any) -> str | None:
    # The column the underused_when rule checks. Used as the gap's evidence locator.
    rule = feature.underused_when
    if rule is None:
        return None
    col = getattr(rule, "col", None)
    return col if isinstance(col, str) else None


