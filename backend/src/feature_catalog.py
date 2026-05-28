from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from .store import DATA_DIR

CATALOG_FILENAME = "feature_catalog.json"

# Rule operators the JSON DSL supports. Adding a new one means adding a branch
# to _parse_rule + _eval_rule + _describe_rule, plus updating the JSON schema
# section in the catalog file's _comment.
_RULE_OPS = ("ever_gt", "gt", "lt", "equals", "contains")


@dataclass(frozen=True)
class RuleAlways:
    """Sentinel for built-in features (Reviews, Messaging) that ship enabled."""


@dataclass(frozen=True)
class RuleColumnCheck:
    col: str
    op: str  # one of _RULE_OPS
    value: Any


Rule = RuleAlways | RuleColumnCheck


@dataclass(frozen=True)
class Feature:
    id: str
    label: str
    goal_categories: list[str]
    owned_when: Rule
    underused_when: Rule | None = None


# ────────────────────────── rule parser ──────────────────────────


def _parse_rule(spec: Any) -> Rule:
    # The problem is: the catalog JSON expresses rules in two shapes —
    # `"always"` for built-ins and `{col, OP: value}` for column checks.
    # The way we solve this is: a tiny interpreter that returns one of the two
    # dataclasses. Validation errors raise with clear messages so a broken
    # catalog fails loudly at load time, not in the middle of a pipeline run.
    # flow: _load_catalog_from_json() -> _parse_rule() <-- HERE
    if spec == "always":
        return RuleAlways()
    if not isinstance(spec, dict):
        raise ValueError(f"Rule must be 'always' or an object, got {spec!r}")
    col = spec.get("col")
    if not isinstance(col, str) or not col:
        raise ValueError(f"Rule object missing 'col' string field: {spec!r}")
    for op in _RULE_OPS:
        if op in spec:
            return RuleColumnCheck(col=col, op=op, value=spec[op])
    raise ValueError(
        f"Rule object must specify one of {list(_RULE_OPS)} operators; got {spec!r}"
    )


def _eval_rule(rule: Rule, usage: dict[str, Any] | None) -> bool:
    if isinstance(rule, RuleAlways):
        return True
    if usage is None:
        return False
    val = usage.get(rule.col)
    if val is None:
        return False
    op = rule.op
    if op in ("ever_gt", "gt"):
        try:
            return float(val) > float(rule.value)
        except (TypeError, ValueError):
            return False
    if op == "lt":
        try:
            return float(val) < float(rule.value)
        except (TypeError, ValueError):
            return False
    if op == "equals":
        return str(val).strip().lower() == str(rule.value).strip().lower()
    if op == "contains":
        return str(rule.value).lower() in str(val).lower()
    return False


def _describe_rule(rule: Rule) -> str:
    # Human-friendly rendering used by the /settings endpoint so the Settings
    # page can show what each rule actually checks.
    if isinstance(rule, RuleAlways):
        return "always (built-in)"
    op_words = {
        "ever_gt": "ever >",
        "gt": ">",
        "lt": "<",
        "equals": "==",
        "contains": "contains",
    }
    op_word = op_words.get(rule.op, rule.op)
    if rule.op == "contains":
        return f'{rule.col} contains "{rule.value}"'
    if rule.op == "equals":
        return f'{rule.col} == "{rule.value}"'
    return f"{rule.col} {op_word} {rule.value}"


# ────────────────────────── feature checks ──────────────────────────


def is_owned(feature: Feature, usage: dict[str, Any] | None) -> bool:
    # flow: stages/s2_usage.py -> is_owned() <-- HERE (per feature, per account)
    return _eval_rule(feature.owned_when, usage)


def is_active(feature: Feature, usage: dict[str, Any] | None) -> bool | None:
    # Semantic complement of `underused_when`: a feature is "active" when its
    # underused-when rule does NOT fire. Returns None for features without an
    # underused rule (provisioning-style features like Paid Phones, Voice AI).
    # flow: stages/s2_usage.py -> is_active() <-- HERE
    if feature.underused_when is None:
        return None
    return not _eval_rule(feature.underused_when, usage)


def describe_ownership(feature: Feature) -> str:
    return _describe_rule(feature.owned_when)


def describe_activity(feature: Feature) -> str:
    if feature.underused_when is None:
        return "(no activity signal defined)"
    # Invert the description: underused_when's lt=N → "active when ≥ N"
    rule = feature.underused_when
    if isinstance(rule, RuleColumnCheck) and rule.op == "lt":
        return f"{rule.col} ≥ {rule.value}"
    return f"NOT ({_describe_rule(rule)})"


def relevant_columns(feature: Feature) -> list[str]:
    cols: list[str] = []
    if isinstance(feature.owned_when, RuleColumnCheck):
        cols.append(feature.owned_when.col)
    if isinstance(feature.underused_when, RuleColumnCheck) and feature.underused_when.col not in cols:
        cols.append(feature.underused_when.col)
    return cols


# ────────────────────────── catalog loader ──────────────────────────


@lru_cache(maxsize=1)
def _load_catalog_from_json() -> dict[str, Feature]:
    # The problem is: the feature catalog is the spine of gap detection +
    # opportunity mapping. A non-engineer Podium operator should be able to add
    # a feature, tune a threshold, or rewrite gap copy without touching Python.
    # The way we solve this is: load + parse the JSON at import time, build
    # immutable Feature dataclasses, cache for the process lifetime. Restart
    # the backend to pick up edits. Keys starting with "_" are treated as
    # comments and skipped.
    # flow: import-time -> _load_catalog_from_json() <-- HERE -> CATALOG
    path = DATA_DIR / CATALOG_FILENAME
    if not path.exists():
        raise FileNotFoundError(
            f"feature_catalog.json not found at {path}. The pipeline needs "
            f"this file to know which Podium features to consider."
        )
    raw = json.loads(path.read_text())
    catalog: dict[str, Feature] = {}
    for fid, spec in raw.items():
        if fid.startswith("_") or not isinstance(spec, dict):
            continue
        if "label" not in spec or "owned_when" not in spec:
            raise ValueError(
                f"Feature {fid!r} missing required fields (label, owned_when): {spec}"
            )
        catalog[fid] = Feature(
            id=fid,
            label=str(spec["label"]),
            goal_categories=list(spec.get("goal_categories", [])),
            owned_when=_parse_rule(spec["owned_when"]),
            underused_when=(
                _parse_rule(spec["underused_when"])
                if "underused_when" in spec
                else None
            ),
        )
    if not catalog:
        raise ValueError(f"feature_catalog.json at {path} produced 0 features")
    return catalog


# Resolve once at import; reuse the same instances across the process.
CATALOG: dict[str, Feature] = _load_catalog_from_json()
