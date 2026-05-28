from __future__ import annotations

import pytest

from src.feature_catalog import (
    CATALOG,
    Feature,
    RuleAlways,
    RuleColumnCheck,
    _eval_rule,
    _parse_rule,
    describe_activity,
    describe_ownership,
    is_active,
    is_owned,
    relevant_columns,
)


# ────────────────────────── parser ──────────────────────────


def test_parse_rule_always_string() -> None:
    assert _parse_rule("always") == RuleAlways()


@pytest.mark.parametrize(
    "spec,expected_op,expected_value",
    [
        ({"col": "X", "gt": 0}, "gt", 0),
        ({"col": "X", "lt": 10}, "lt", 10),
        ({"col": "X", "ever_gt": 0}, "ever_gt", 0),
        ({"col": "X", "equals": "Yes"}, "equals", "Yes"),
        ({"col": "X", "contains": "Text AI"}, "contains", "Text AI"),
    ],
)
def test_parse_rule_column_check_each_operator(spec, expected_op, expected_value) -> None:
    rule = _parse_rule(spec)
    assert isinstance(rule, RuleColumnCheck)
    assert rule.col == "X"
    assert rule.op == expected_op
    assert rule.value == expected_value


def test_parse_rule_rejects_non_string_non_dict() -> None:
    with pytest.raises(ValueError):
        _parse_rule(42)


def test_parse_rule_rejects_missing_col() -> None:
    with pytest.raises(ValueError, match="missing 'col'"):
        _parse_rule({"gt": 0})


def test_parse_rule_rejects_unknown_operator() -> None:
    with pytest.raises(ValueError, match="must specify one of"):
        _parse_rule({"col": "X", "approximately": 5})


# ────────────────────────── evaluator ──────────────────────────


def test_eval_always_returns_true_regardless_of_usage() -> None:
    assert _eval_rule(RuleAlways(), None) is True
    assert _eval_rule(RuleAlways(), {}) is True


def test_eval_gt_lt_handle_numeric_strings() -> None:
    assert _eval_rule(_parse_rule({"col": "X", "gt": 0}), {"X": "5"}) is True
    assert _eval_rule(_parse_rule({"col": "X", "lt": 10}), {"X": 7}) is True
    assert _eval_rule(_parse_rule({"col": "X", "lt": 5}), {"X": 7}) is False


def test_eval_contains_substring_match() -> None:
    rule = _parse_rule({"col": "AI PRODUCT NAMES", "contains": "Text AI"})
    assert _eval_rule(rule, {"AI PRODUCT NAMES": '["Text AI", "Webchat AI"]'}) is True
    assert _eval_rule(rule, {"AI PRODUCT NAMES": '["Phones AI"]'}) is False


def test_eval_equals_normalizes_case_and_whitespace() -> None:
    rule = _parse_rule({"col": "STATUS", "equals": "Paid Phones"})
    assert _eval_rule(rule, {"STATUS": "paid phones "}) is True
    assert _eval_rule(rule, {"STATUS": "Free Phones"}) is False


def test_eval_returns_false_for_missing_column() -> None:
    rule = _parse_rule({"col": "X", "gt": 0})
    assert _eval_rule(rule, {}) is False
    assert _eval_rule(rule, {"X": None}) is False


def test_eval_returns_false_for_non_numeric_when_op_is_numeric() -> None:
    rule = _parse_rule({"col": "X", "gt": 0})
    assert _eval_rule(rule, {"X": "not a number"}) is False


# ────────────────────────── catalog load ──────────────────────────


def test_catalog_loads_and_has_expected_features() -> None:
    # The problem is: a broken or missing feature_catalog.json would silently
    # break gap detection. The catalog load should be loud + correct.
    expected = {"reviews", "messaging", "webchat", "text_ai", "phones_ai_voice", "paid_phones", "payments", "campaigns"}
    assert expected.issubset(set(CATALOG.keys()))


def test_catalog_features_are_immutable_dataclasses() -> None:
    for f in CATALOG.values():
        assert isinstance(f, Feature)
        with pytest.raises(Exception):  # frozen dataclass blocks mutation
            f.label = "NOPE"  # type: ignore[misc]


def test_reviews_is_always_owned() -> None:
    f = CATALOG["reviews"]
    assert is_owned(f, None) is True
    assert is_owned(f, {}) is True


def test_text_ai_owned_only_when_product_names_contains_it() -> None:
    f = CATALOG["text_ai"]
    assert is_owned(f, {"AI PRODUCT NAMES": '["Text AI"]'}) is True
    assert is_owned(f, {"AI PRODUCT NAMES": '["Phones AI"]'}) is False
    assert is_owned(f, {"AI PRODUCT NAMES": ""}) is False


def test_paid_phones_has_no_activity_signal() -> None:
    f = CATALOG["paid_phones"]
    assert is_active(f, {"PHONES PRODUCT STATUS": "Paid Phones"}) is None


def test_describe_ownership_returns_readable_string() -> None:
    assert "always" in describe_ownership(CATALOG["reviews"]).lower()
    assert "AI PRODUCT NAMES" in describe_ownership(CATALOG["text_ai"])


def test_describe_activity_returns_readable_or_no_signal() -> None:
    assert "REVIEW INVITES" in describe_activity(CATALOG["reviews"])
    assert "no" in describe_activity(CATALOG["paid_phones"]).lower()


def test_relevant_columns_drops_duplicates() -> None:
    # Webchat uses the same column for ownership + underused — should appear once.
    cols = relevant_columns(CATALOG["webchat"])
    assert cols.count("WEBCHAT LEADS RECEIVED LAST 30DAYS") == 1
