"""
rules/r002.py
Rule R-002: Vehicle Speed > 0 while Gear Position is PARK.
Contradictory Signal Anomaly.
"""

from typing import Dict, Optional
from asc_parser import CANFrame
from signal_decoder import DecodedSignal
from signal_history import SignalHistory
from anomaly import Anomaly, AnomalyType
from rules.base_rule import BaseRule


class Rule002(BaseRule):
    """
    R-002: Contradictory Signal Rule.
    Detects when Vehicle_Speed is positive while Gear_Position indicates PARK (0).
    """

    def __init__(
        self,
        speed_threshold: float = 0.5,
        park_gear_val: int = 0,
        max_signal_skew_seconds: float = 0.05,
        min_trigger_interval_seconds: float = 0.05
    ):
        super().__init__(
            rule_id="R-002",
            name="Vehicle Moving while Gear PARK",
            anomaly_type=AnomalyType.CONTRADICTORY_SIGNAL.value,
            description="Vehicle is moving while transmission indicates PARK",
            is_enabled=True
        )
        self.speed_threshold = speed_threshold
        self.park_gear_val = park_gear_val
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

        # Check if the current frame updated Vehicle_Speed or Gear_Position
        if "Vehicle_Speed" not in decoded_signals and "Gear_Position" not in decoded_signals:
            return None

        # Retrieve latest values from history
        speed_obs = history.get_latest("Vehicle_Speed")
        gear_obs = history.get_latest("Gear_Position")

        if speed_obs is None or gear_obs is None:
            return None

        # Ensure signals were observed within a reasonable time window of each other
        if abs(speed_obs.timestamp - gear_obs.timestamp) > self.max_signal_skew_seconds:
            return None

        speed_val = speed_obs.value
        gear_val = int(round(gear_obs.value))

        # Condition: Vehicle speed > threshold while Gear is PARK (0)
        if speed_val > self.speed_threshold and gear_val == self.park_gear_val:
            # Debounce: prevent duplicate triggers within debounce window
            if self._last_trigger_timestamp is not None:
                if abs(frame.timestamp - self._last_trigger_timestamp) < self.min_trigger_interval_seconds:
                    return None
            self._last_trigger_timestamp = frame.timestamp

            return Anomaly(
                timestamp=frame.timestamp,
                rule_id=self.rule_id,
                anomaly_type=self.anomaly_type,
                signals=["Vehicle_Speed", "Gear_Position"],
                values={
                    "Vehicle_Speed": round(speed_val, 2),
                    "Gear_Position": gear_val
                },
                reason=f"Vehicle is moving ({speed_val:.2f} km/h) while transmission indicates PARK"
            )

        return None
