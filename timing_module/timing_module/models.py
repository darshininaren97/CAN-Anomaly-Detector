"""Data models for temporal, timing, and behavioral CAN bus anomaly detection."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class Severity(str, Enum):
    """Anomaly severity levels."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AnomalyType(str, Enum):
    """Categorized timing and behavioral anomaly types."""
    TIMING_DEVIATION = "TIMING_DEVIATION"
    TIMING_FLOODING = "TIMING_FLOODING"
    DUPLICATE_BURST = "DUPLICATE_BURST"
    TIMING_TIMEOUT = "TIMING_TIMEOUT"
    ECU_BEHAVIOR_DEVIATION = "ECU_BEHAVIOR_DEVIATION"


@dataclass
class Frame:
    """Normalized CAN bus frame."""
    timestamp: float
    can_id: int
    can_id_hex: str
    data: str
    dlc: int
    ecu: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert frame to dictionary representation."""
        result: Dict[str, Any] = {
            "timestamp": self.timestamp,
            "can_id": self.can_id_hex,
            "can_id_int": self.can_id,
            "data": self.data,
            "dlc": self.dlc,
        }
        if self.ecu is not None:
            result["ecu"] = self.ecu
        return result


@dataclass
class BaselineProfile:
    """Baseline timing characteristics for a CAN ID."""
    can_id: str
    can_id_int: int
    sample_count: int
    median_interval: float  # Primary nominal period
    mean_interval: float
    std_interval: float
    min_interval: float
    max_interval: float
    frames_per_second: float
    coefficient_of_variation: float
    ecu: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert profile to serializable dictionary."""
        return {
            "can_id": self.can_id,
            "can_id_int": self.can_id_int,
            "ecu": self.ecu or "UNKNOWN",
            "sample_count": self.sample_count,
            "nominal_period": round(self.median_interval, 6),
            "mean_period": round(self.mean_interval, 6),
            "std_period": round(self.std_interval, 6),
            "min_period": round(self.min_interval, 6),
            "max_period": round(self.max_interval, 6),
            "frames_per_second": round(self.frames_per_second, 2),
            "coefficient_of_variation": round(self.coefficient_of_variation, 4),
        }


@dataclass
class AnomalyEvent:
    """Standardized anomaly event structure with consistent temporal and value attributes."""
    anomaly_type: Union[AnomalyType, str]
    severity: Union[Severity, str]
    can_id: str
    diagnosis: str
    possible_causes: List[str]
    evidence: Dict[str, Any]
    timestamp: float
    start_time: float
    end_time: float
    observed_value: float
    expected_value: float
    deviation: float
    ecu: Optional[str] = None
    abnormal_frame_count: int = 1
    nominal_period: Optional[float] = None
    observed_period: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to clean, stable JSON-serializable dictionary."""
        anom_type = self.anomaly_type.value if isinstance(self.anomaly_type, AnomalyType) else str(self.anomaly_type)
        sev = self.severity.value if isinstance(self.severity, Severity) else str(self.severity)
        nom_p = self.nominal_period if self.nominal_period is not None else self.expected_value
        obs_p = self.observed_period if self.observed_period is not None else self.observed_value

        return {
            "timestamp": round(self.timestamp, 6),
            "start_time": round(self.start_time, 6),
            "end_time": round(self.end_time, 6),
            "can_id": self.can_id,
            "ecu": self.ecu or "UNKNOWN",
            "anomaly_type": anom_type,
            "severity": sev,
            "abnormal_frame_count": self.abnormal_frame_count,
            "observed_value": round(self.observed_value, 6),
            "expected_value": round(self.expected_value, 6),
            "deviation": round(self.deviation, 4),
            "nominal_period": round(nom_p, 6),
            "observed_period": round(obs_p, 6),
            "diagnosis": self.diagnosis,
            "possible_causes": self.possible_causes,
            "evidence": self.evidence,
        }


@dataclass
class ECUProfile:
    """Behavioral profile for an Electronic Control Unit (ECU)."""
    ecu: str
    message_count: int
    can_ids: List[str]
    nominal_frequency: float
    timing_variance: float
    duplicate_rate: float
    timeout_occurrences: int
    timing_anomaly_count: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert ECU profile to serializable dictionary."""
        return {
            "ecu": self.ecu,
            "message_count": self.message_count,
            "can_ids": self.can_ids,
            "nominal_frequency": round(self.nominal_frequency, 2),
            "timing_variance": round(self.timing_variance, 6),
            "duplicate_rate": round(self.duplicate_rate, 4),
            "timeout_occurrences": self.timeout_occurrences,
            "timing_anomaly_count": self.timing_anomaly_count,
        }
