"""Loading the challenge deletion rules."""

from __future__ import annotations

import csv
from pathlib import Path

from ..errors import DatasetError
from .models import PolicyAction, PolicyRule

RULE_HEADERS = ("rule_id", "data_category", "condition", "required_action")


class PolicyRuleSet:
    """Typed, read-only view of ``deletion_rules.csv``."""

    def __init__(self, rules: tuple[PolicyRule, ...]) -> None:
        self.rules = rules
        self._by_category = {rule.data_category: rule for rule in rules}
        if len(self._by_category) != len(rules):
            raise DatasetError("Duplicate data_category in deletion_rules.csv")

    def for_category(self, category: str) -> PolicyRule | None:
        return self._by_category.get(category)

    def __len__(self) -> int:
        return len(self.rules)

    def __iter__(self):
        return iter(self.rules)


def load_policy_rules(path: str | Path) -> PolicyRuleSet:
    resolved = Path(path)
    if not resolved.is_file():
        raise DatasetError(f"Deletion rules file not found: {resolved}")
    rules: list[PolicyRule] = []
    with resolved.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        actual = tuple(reader.fieldnames or ())
        if actual != RULE_HEADERS:
            raise DatasetError(
                f"Unexpected deletion rules header: {actual!r}; expected {RULE_HEADERS!r}"
            )
        for row_number, raw in enumerate(reader, start=1):
            try:
                action = PolicyAction(raw["required_action"].strip())
            except ValueError as exc:
                raise DatasetError(
                    f"Unknown policy action on row {row_number}: {raw['required_action']!r}"
                ) from exc
            rules.append(
                PolicyRule(
                    rule_id=raw["rule_id"].strip(),
                    data_category=raw["data_category"].strip(),
                    condition=raw["condition"].strip(),
                    required_action=action,
                )
            )
    return PolicyRuleSet(tuple(rules))
