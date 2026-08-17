"""Configuration settings and threshold parameters for timing anomaly detection."""

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional, Union


@dataclass
class TimingConfig:
    """Configurable thresholds for timing and behavioral anomaly detection."""

    # Relative deviation from nominal period (e.g., 0.20 = 20% deviation)
    relative_deviation_threshold: float = 0.20

    # Z-score statistical threshold
    z_score_threshold: float = 3.0

    # Flooding burst criteria: observed interval <= flooding_ratio_threshold * nominal
    # (e.g., 0.25 means interval <= 25% of nominal period, i.e., >= 4x nominal frequency)
    flooding_ratio_threshold: float = 0.25

    # Minimum consecutive abnormal frames to qualify as a flooding burst
    flooding_min_burst_count: int = 5

    # Duplicate payload burst criteria: interval <= duplicate_max_interval_factor * nominal
    duplicate_max_interval_factor: float = 0.30

    # Minimum consecutive identical payloads to qualify as duplicate burst
    duplicate_min_repeat_count: int = 3

    # Timeout criteria: gap >= timeout_multiplier * nominal
    timeout_multiplier: float = 2.5

    # Minimum number of baseline frames required to establish nominal period
    min_baseline_samples: int = 5

    # Minimum standard deviation floor to prevent zero-division / oversensitivity
    min_std_floor_factor: float = 0.005

    # Severity deviation boundaries
    severity_low_deviation: float = 0.25
    severity_medium_deviation: float = 0.60
    severity_high_deviation: float = 1.20
    severity_critical_deviation: float = 3.00

    def __post_init__(self) -> None:
        """Validate threshold ranges to prevent logic inversion or illegal configs."""
        if not (0.0 < self.relative_deviation_threshold < 5.0):
            raise ValueError(
                f"relative_deviation_threshold must be between 0.0 and 5.0, got {self.relative_deviation_threshold}"
            )
        if not (0.0 < self.flooding_ratio_threshold < 1.0):
            raise ValueError(
                f"flooding_ratio_threshold must be a fraction in (0.0, 1.0) representing interval reduction, got {self.flooding_ratio_threshold}"
            )
        if not (0.0 < self.duplicate_max_interval_factor < 1.0):
            raise ValueError(
                f"duplicate_max_interval_factor must be a fraction in (0.0, 1.0), got {self.duplicate_max_interval_factor}"
            )
        if self.timeout_multiplier <= 1.0:
            raise ValueError(
                f"timeout_multiplier must be > 1.0, got {self.timeout_multiplier}"
            )
        if self.flooding_min_burst_count < 2:
            raise ValueError(
                f"flooding_min_burst_count must be >= 2, got {self.flooding_min_burst_count}"
            )
        if self.duplicate_min_repeat_count < 2:
            raise ValueError(
                f"duplicate_min_repeat_count must be >= 2, got {self.duplicate_min_repeat_count}"
            )
        if self.min_baseline_samples < 2:
            raise ValueError(
                f"min_baseline_samples must be >= 2, got {self.min_baseline_samples}"
            )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimingConfig":
        """Create TimingConfig from dictionary."""
        valid_keys = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)

    @classmethod
    def from_json_file(cls, path: Union[str, Path]) -> "TimingConfig":
        """Load configuration from a JSON file."""
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return asdict(self)
