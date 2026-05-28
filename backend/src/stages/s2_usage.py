from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..feature_catalog import CATALOG, is_active, is_owned, relevant_columns
from ..store import OUTPUT_DIR


class FeatureFacts(BaseModel):
    feature_id: str
    label: str
    goal_categories: list[str]
    owned: bool
    active: bool | None  # None when no engagement signal is defined for the feature
    signals: dict[str, Any]


class UsageStageOutput(BaseModel):
    account_id: str
    facts: dict[str, FeatureFacts]


def analyze_usage(account_id: str) -> UsageStageOutput:
    # The problem is: 100+ usage columns mean nothing on their own — the AM needs them
    # interpreted through "which Podium features does this account own, and which of
    # those is it actually using."
    # The way we solve this is: walk the feature catalog, apply each feature's
    # ownership + activity rules against the account's usage row, snapshot the
    # relevant column values for citation downstream.
    # flow: pipeline.run_pipeline() -> analyze_usage() <-- HERE -> write_usage_facts()
    corpus_path = OUTPUT_DIR / account_id / "corpus.json"
    if not corpus_path.exists():
        raise FileNotFoundError(
            f"No corpus.json for '{account_id}'. Run ingest first."
        )
    corpus = json.loads(corpus_path.read_text())
    usage: dict[str, Any] | None = corpus.get("usage")

    facts: dict[str, FeatureFacts] = {}
    for feat_id, feature in CATALOG.items():
        signals: dict[str, Any] = {}
        if usage is not None:
            for col in relevant_columns(feature):
                signals[col] = usage.get(col)

        facts[feat_id] = FeatureFacts(
            feature_id=feat_id,
            label=feature.label,
            goal_categories=feature.goal_categories,
            owned=is_owned(feature, usage),
            active=is_active(feature, usage),
            signals=signals,
        )

    return UsageStageOutput(account_id=account_id, facts=facts)


def write_usage_facts(output: UsageStageOutput) -> Path:
    # flow: pipeline.run_pipeline() -> analyze_usage() -> write_usage_facts() <-- HERE
    path = OUTPUT_DIR / output.account_id / "usage_facts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(output.model_dump_json(indent=2))
    tmp.replace(path)
    return path
