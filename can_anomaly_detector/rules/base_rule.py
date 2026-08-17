"""
rules/base_rule.py
Base class definition for all anomaly detection rules.
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional
from asc_parser import CANFrame
from signal_decoder import DecodedSignal
from signal_history import SignalHistory
from anomaly import Anomaly


class BaseRule(ABC):
    """Abstract base class for all CAN anomaly detection rules."""

    def __init__(
        self,
        rule_id: str,
        name: str,
        anomaly_type: str,
        description: str = "",
        is_enabled: bool = True
    ):
        self.rule_id = rule_id
        self.name = name
        self.anomaly_type = anomaly_type
        self.description = description
        self.is_enabled = is_enabled
        self._last_trigger_timestamp: Optional[float] = None

    @abstractmethod
    def evaluate(
        self,
        frame: CANFrame,
        decoded_signals: Dict[str, DecodedSignal],
        history: SignalHistory
    ) -> Optional[Anomaly]:
        """
        Evaluate rule against incoming CAN frame, decoded signals, and signal history.
        
        :param frame: The current CANFrame being processed
        :param decoded_signals: Decoded signals for the current frame
        :param history: SignalHistory containing past and present signal values
        :return: Anomaly instance if rule condition is satisfied, else None
        """
        pass

    def reset(self):
        """Reset internal rule state to prevent cross-run or cross-instance state pollution."""
        self._last_trigger_timestamp = None
