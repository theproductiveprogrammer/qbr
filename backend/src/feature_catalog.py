from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Goal categories must match the enum in stages/s1_goals.py — keep in sync.
# A feature's `goal_categories` is the join key used by stage 3 (gaps) and stage 4
# (opportunities) to align Podium features with customer-stated goals.

OwnershipRule = str  # "always" | "any_lifetime" | "gt_0" | "contains" | "equals"


@dataclass(frozen=True)
class Feature:
    id: str
    label: str
    goal_categories: list[str]
    ownership_rule: OwnershipRule
    ownership_col: str | None = None        # None for "always" rule (built-in features)
    ownership_value: Any = None             # for contains/equals rules
    active_col: str | None = None           # column that signals L30 activity
    active_threshold: float = 1.0           # ≥ this counts as "active"


def is_owned(feature: Feature, usage: dict[str, Any] | None) -> bool:
    # The problem is: each feature has its own way of being "owned" — Reviews is built-in,
    # Webchat is owned once installed (lifetime activity proves it), AI products show up
    # in a comma-list column, Paid Phones has a status string. A single check function
    # has to handle them all without exploding.
    # The way we solve this is: small DSL of ownership rules ("always", "any_lifetime",
    # "gt_0", "contains", "equals"); each rule is one cheap branch.
    # flow: stages/s2_usage.py -> is_owned() <-- HERE (per feature, per account)
    rule = feature.ownership_rule
    if rule == "always":
        return True
    if usage is None or feature.ownership_col is None:
        return False
    val = usage.get(feature.ownership_col)
    if val is None:
        return False
    if rule == "any_lifetime" or rule == "gt_0":
        try:
            return float(val) > 0
        except (TypeError, ValueError):
            return False
    if rule == "contains":
        return str(feature.ownership_value).lower() in str(val).lower()
    if rule == "equals":
        return str(val).strip().lower() == str(feature.ownership_value).strip().lower()
    return False


def is_active(feature: Feature, usage: dict[str, Any] | None) -> bool | None:
    # The problem is: some features have a clear "active in L30" signal (Reviews, Webchat,
    # Messaging) but others don't (Paid Phones is just provisioning, Phones AI is a
    # subscription state without a unified usage counter in this dataset).
    # The way we solve this is: return None when there's no engagement signal, so the
    # gap detector knows it can't say either way and skips the feature.
    if feature.active_col is None or usage is None:
        return None
    val = usage.get(feature.active_col)
    if val is None:
        return False
    try:
        return float(val) >= feature.active_threshold
    except (TypeError, ValueError):
        return bool(val)


def relevant_columns(feature: Feature) -> list[str]:
    cols: list[str] = []
    if feature.ownership_col:
        cols.append(feature.ownership_col)
    if feature.active_col and feature.active_col not in cols:
        cols.append(feature.active_col)
    return cols


CATALOG: dict[str, Feature] = {
    "reviews": Feature(
        id="reviews",
        label="Reviews",
        goal_categories=["reviews"],
        ownership_rule="always",
        active_col="REVIEW INVITES LAST 30DAYS",
        active_threshold=1.0,
    ),
    "messaging": Feature(
        id="messaging",
        label="Messaging",
        goal_categories=["messaging", "lead_response"],
        ownership_rule="always",
        active_col="RECEIVED MESSAGES LAST 30DAYS",
        active_threshold=1.0,
    ),
    "webchat": Feature(
        id="webchat",
        label="Webchat",
        goal_categories=["lead_response", "lead_integration"],
        ownership_rule="any_lifetime",
        ownership_col="WEBCHAT LEADS RECEIVED LAST 30DAYS",
        active_col="WEBCHAT LEADS RECEIVED LAST 30DAYS",
        active_threshold=10.0,  # under 10 webchat leads/month treated as underused
    ),
    "text_ai": Feature(
        id="text_ai",
        label="Text AI",
        goal_categories=["ai_adoption", "lead_response", "messaging", "reviews"],
        ownership_rule="contains",
        ownership_col="AI PRODUCT NAMES",
        ownership_value="Text AI",
        active_col="AI Conversations L28 Days",
        active_threshold=1.0,
    ),
    "phones_ai_voice": Feature(
        id="phones_ai_voice",
        label="Phones AI (Voice)",
        goal_categories=["call_capture", "ai_adoption"],
        ownership_rule="contains",
        ownership_col="AI PRODUCT NAMES",
        ownership_value="Phones AI",
    ),
    "paid_phones": Feature(
        id="paid_phones",
        label="Paid Phones",
        goal_categories=["call_capture", "lead_response"],
        ownership_rule="equals",
        ownership_col="PHONES PRODUCT STATUS",
        ownership_value="Paid Phones",
    ),
    "payments": Feature(
        id="payments",
        label="Payments",
        goal_categories=["payments"],
        ownership_rule="gt_0",
        ownership_col="PROCESSED AMOUNT ALL TIME",
        active_col="PROCESSED AMOUNT LAST 30 DAYS",
        active_threshold=1.0,
    ),
    "campaigns": Feature(
        id="campaigns",
        label="Campaigns",
        goal_categories=["messaging", "lead_response"],
        ownership_rule="gt_0",
        ownership_col="LOCATION CAMPAIGNS SUBSCRIBER LIMIT",
        active_col="CAMPAIGN MESSAGES SENT LAST 30 DAYS",
        active_threshold=1.0,
    ),
}


