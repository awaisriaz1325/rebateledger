"""Eligibility filters (SPEC §4.4.3).

Semantics, applied per line:
1. If any rule needs an attribute the line lacks → ATTRIBUTE_MISSING.
2. If any exclude rule matches → EXCLUDED_BY_RULE (exclude wins over include).
3. Include rules are grouped by field (flags grouped per flag name). Within a group
   a line must match at least one value; across groups every group must match →
   otherwise NOT_INCLUDED.
4. ``min_line_amount`` compares the absolute line amount, so a return of a
   qualifying-size purchase still nets against the measure (ADR 0010).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.engine.models import (
    EligibilityRule,
    ExclusionReason,
    PurchaseLine,
    RuleAction,
    RuleField,
)


@dataclass(frozen=True, slots=True)
class Decision:
    eligible: bool
    reason: ExclusionReason | None = None
    rule_id: str | None = None


ELIGIBLE = Decision(True)


def _attribute(line: PurchaseLine, rule: EligibilityRule) -> str | bool | None:
    if rule.field is RuleField.SKU:
        return line.sku
    if rule.field is RuleField.CATEGORY:
        return line.category
    if rule.field is RuleField.BRANCH:
        return line.branch
    if rule.field is RuleField.FLAG:
        assert rule.flag is not None
        return line.flag(rule.flag)
    return "amount"  # min_line_amount: amount is always present


def _matches(line: PurchaseLine, rule: EligibilityRule, value: str | bool) -> bool:
    if rule.field is RuleField.FLAG:
        return value is True
    if rule.field is RuleField.MIN_LINE_AMOUNT:
        assert rule.min_amount is not None
        return abs(line.amount) >= rule.min_amount
    assert isinstance(value, str)
    return value in rule.values


def _group_key(rule: EligibilityRule) -> str:
    if rule.field is RuleField.FLAG:
        return f"flag:{rule.flag}"
    return rule.field.value


def evaluate(line: PurchaseLine, rules: tuple[EligibilityRule, ...]) -> Decision:
    if not rules:
        return ELIGIBLE
    # Rules are evaluated in id order so the reported rule is deterministic.
    ordered = sorted(rules, key=lambda r: r.id)
    values: dict[str, str | bool] = {}
    for rule in ordered:
        value = _attribute(line, rule)
        if value is None or value == "":
            return Decision(False, ExclusionReason.ATTRIBUTE_MISSING, rule.id)
        values[rule.id] = value

    for rule in ordered:
        if rule.action is RuleAction.EXCLUDE and _matches(line, rule, values[rule.id]):
            return Decision(False, ExclusionReason.EXCLUDED_BY_RULE, rule.id)

    groups: dict[str, list[EligibilityRule]] = {}
    for rule in ordered:
        if rule.action is RuleAction.INCLUDE:
            groups.setdefault(_group_key(rule), []).append(rule)
    for key in sorted(groups):
        group = groups[key]
        if not any(_matches(line, r, values[r.id]) for r in group):
            reason = (
                ExclusionReason.BELOW_MIN_LINE_AMOUNT
                if key == RuleField.MIN_LINE_AMOUNT.value
                else ExclusionReason.NOT_INCLUDED
            )
            return Decision(False, reason, group[0].id)
    return ELIGIBLE
