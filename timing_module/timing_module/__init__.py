"""
CAN Bus Temporal, Timing, and Behavioral Anomaly Detection Module.

A modular, deterministic, offline engine for detecting timing deviations,
CAN flooding bursts, duplicate payload bursts, and communication timeouts.
"""

from timing_module.config import TimingConfig
from timing_module.models import (
    AnomalyEvent,
    AnomalyType,
    BaselineProfile,
    ECUProfile,
    Frame,
    Severity,
)
from timing_module.parser_adapter import (
    ParserAdapter,
    normalize_can_id,
    normalize_frame,
    parse_json_file,
    parse_records,
)
from timing_module.timing_analyzer import TimingAnalyzer

__version__ = "1.0.0"

__all__ = [
    "TimingAnalyzer",
    "Frame",
    "BaselineProfile",
    "AnomalyEvent",
    "ECUProfile",
    "TimingConfig",
    "Severity",
    "AnomalyType",
    "ParserAdapter",
    "normalize_can_id",
    "normalize_frame",
    "parse_records",
    "parse_json_file",
]
