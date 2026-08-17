"""
rules/__init__.py
Rule registry and exports for all contradictory and correlation anomaly rules.
"""

from typing import List
from rules.base_rule import BaseRule
from rules.r001 import Rule001
from rules.r002 import Rule002
from rules.r003 import Rule003
from rules.r004 import Rule004
from rules.r005 import Rule005
from rules.r006 import Rule006
from rules.r007 import Rule007


def create_all_rules() -> List[BaseRule]:
    """Instantiate and return the complete suite of 7 anomaly rules."""
    return [
        Rule001(),
        Rule002(),
        Rule003(),
        Rule004(),
        Rule005(),
        Rule006(),
        Rule007(),
    ]


__all__ = [
    "BaseRule",
    "Rule001",
    "Rule002",
    "Rule003",
    "Rule004",
    "Rule005",
    "Rule006",
    "Rule007",
    "create_all_rules"
]
