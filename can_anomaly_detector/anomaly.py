"""
anomaly.py
Defines the structured Anomaly object and related types.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Dict, Any
import json


class AnomalyType(str, Enum):
    CONTRADICTORY_SIGNAL = "Contradictory Signal"
    SIGNAL_CORRELATION = "Signal Correlation"


@dataclass
class Anomaly:
    """Represents a structured anomaly detection event."""
    timestamp: float
    rule_id: str
    anomaly_type: str
    signals: List[str]
    values: Dict[str, Any]
    reason: str
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert anomaly object to dictionary for JSON serialization."""
        d = {
            "timestamp": round(self.timestamp, 6),
            "rule_id": self.rule_id,
            "anomaly_type": self.anomaly_type,
            "signals": self.signals,
            "values": self.values,
            "reason": self.reason
        }
        if self.context:
            d["context"] = self.context
        return d

    def to_json(self, indent: int = 2) -> str:
        """Convert anomaly object to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
