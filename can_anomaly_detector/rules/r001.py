"""
rules/r001.py
Rule R-001: Vehicle Speed > 0 while Engine Status is OFF.
Contradictory Signal Anomaly.
"""

from typing import Dict, Optional
from asc_parser import CANFrame
from signal_decoder import DecodedSignal
from signal_history import SignalHistory
from anomaly import Anomaly, AnomalyType
from rules.base_rule import BaseRule


class Rule001(BaseRule):
    """
    R-001: Contradictory Signal Rule.
    Detects when Vehicle_Speed is positive while Engine_Status indicates OFF (0).
    """

    def __init__(
        self,
        speed_threshold: float = 0.5,
        max_signal_skew_seconds: float = 0.15,
        min_trigger_interval_seconds: float = 0.05
    ):
        super().__init__(
            rule_id="R-001",
            name="Vehicle Moving while Engine OFF",
            anomaly_type=AnomalyType.CONTRADICTORY_SIGNAL.value,
            description="Vehicle speed is greater than zero while engine status indicates OFF",
            is_enabled=True
        )
        self.speed_threshold = speed_threshold
        self.max_signal_skew_seconds = max_signal_skew_seconds
        self.min_trigger_interval_seconds = min_trigger_interval_seconds

    def evaluate(
        self,
        frame: CANFrame,
        decoded_signals: Dict[str, DecodedSignal],
        history: SignalHistory
    ) -> Optional[Anomaly]:
        if not self.is_enabled:
            return None

        # Check if the current frame updated Vehicle_Speed or Engine_Status
        if "Vehicle_Speed" not in decoded_signals and "Engine_Status" not in decoded_signals:
            return None

        # Retrieve latest values from history
        speed_obs = history.get_latest("Vehicle_Speed")
        engine_obs = history.get_latest("Engine_Status")
        rpm_obs = history.get_latest("Engine_RPM")

        if speed_obs is None or engine_obs is None:
            return None

        # Ensure signals were observed within a reasonable time window of each other
        if abs(speed_obs.timestamp - engine_obs.timestamp) > self.max_signal_skew_seconds:
            return None

        speed_val = speed_obs.value
        engine_val = int(round(engine_obs.value))
        rpm_val = rpm_obs.value if rpm_obs is not None else 0.0

        # Moving while engine is confirmed OFF
        is_engine_off = (engine_val == 0) and (rpm_obs is None or rpm_val <= 0.0)

        # Condition: Vehicle speed > threshold while Engine is OFF
        if speed_val > self.speed_threshold and is_engine_off:
            # Debounce: prevent duplicate triggers within debounce window
            if self._last_trigger_timestamp is not None:
                if abs(frame.timestamp - self._last_trigger_timestamp) < self.min_trigger_interval_seconds:
                    return None
            self._last_trigger_timestamp = frame.timestamp

            return Anomaly(
                timestamp=frame.timestamp,
                rule_id=self.rule_id,
                anomaly_type=self.anomaly_type,
                signals=["Vehicle_Speed", "Engine_Status"],
                values={
                    "Vehicle_Speed": round(speed_val, 2),
                    "Engine_Status": engine_val
                },
                reason=f"Vehicle speed is greater than zero ({speed_val:.2f} km/h) while engine status is OFF"
            )

        return None
