"""
rules/r003.py
Rule R-003: Contradictory Signal Rule Framework.
[PENDING OFFICIAL SPECIFICATION]
This rule interface is established for project expansion.
Do not fabricate logic without official project definitions.
"""

from typing import Dict, Optional, Callable
from asc_parser import CANFrame
from signal_decoder import DecodedSignal
from signal_history import SignalHistory
from anomaly import Anomaly, AnomalyType
from rules.base_rule import BaseRule


class Rule003(BaseRule):
    """
    R-003: Contradictory Signal Rule Framework.
    
    NOTE: As per project specification, R-003 logic is reserved for official project definition.
    A custom condition callback can be injected or configured when official specifications are provided.
    """

    def __init__(self, condition_fn: Optional[Callable[[CANFrame, Dict[str, DecodedSignal], SignalHistory], Optional[Anomaly]]] = None):
        super().__init__(
            rule_id="R-003",
            name="Contradictory Signal Rule 003 [Pending Specification]",
            anomaly_type=AnomalyType.CONTRADICTORY_SIGNAL.value,
            description="Framework for R-003 contradiction rule. Requires official project specification.",
            is_enabled=False  # Disabled by default until official specification is configured
        )
        self.condition_fn = condition_fn
        if condition_fn is not None:
            self.is_enabled = True

    def evaluate(
        self,
        frame: CANFrame,
        decoded_signals: Dict[str, DecodedSignal],
        history: SignalHistory
    ) -> Optional[Anomaly]:
        if not self.is_enabled:
            return None

        if self.condition_fn is not None:
            return self.condition_fn(frame, decoded_signals, history)

        # Official condition required
        return None
