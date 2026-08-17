"""
rules/r007.py
Rule R-007: Brake Status vs Vehicle Speed Trend Correlation.
Signal Correlation Anomaly.
"""

from typing import Dict, Optional, List
from asc_parser import CANFrame
from signal_decoder import DecodedSignal
from signal_history import SignalHistory, SignalObservation
from anomaly import Anomaly, AnomalyType
from rules.base_rule import BaseRule


class Rule007(BaseRule):
    """
    R-007: Signal Correlation Rule.
    Evaluates physical consistency between Brake_Status and Vehicle_Speed trend over time.
    Flags an anomaly when Brake_Status is ON (1) while vehicle speed is actively and significantly increasing.
    """

    def __init__(
        self,
        time_window_seconds: float = 0.5,
        min_speed_increase_kmh: float = 5.0,
        min_acceleration_rate_kmh_s: float = 10.0,
        min_observations: int = 3
    ):
        super().__init__(
            rule_id="R-007",
            name="Brake Applied with Positive Speed Acceleration",
            anomaly_type=AnomalyType.SIGNAL_CORRELATION.value,
            description="Vehicle accelerates significantly while brake pedal status indicates ON (1)",
            is_enabled=True
        )
        self.time_window_seconds = time_window_seconds
        self.min_speed_increase_kmh = min_speed_increase_kmh
        self.min_acceleration_rate_kmh_s = min_acceleration_rate_kmh_s
        self.min_observations = min_observations

    def evaluate(
        self,
        frame: CANFrame,
        decoded_signals: Dict[str, DecodedSignal],
        history: SignalHistory
    ) -> Optional[Anomaly]:
        if not self.is_enabled:
            return None

        # Check if frame contains Brake_Status or Vehicle_Speed
        if "Brake_Status" not in decoded_signals and "Vehicle_Speed" not in decoded_signals:
            return None

        brake_obs = history.get_latest("Brake_Status")
        speed_obs = history.get_latest("Vehicle_Speed")

        if brake_obs is None or speed_obs is None:
            return None

        brake_val = int(round(brake_obs.value))
        current_speed = speed_obs.value

        # Only evaluate when Brake is pressed (1)
        if brake_val != 1:
            return None

        # Retrieve recent vehicle speed history anchored on evaluation frame timestamp
        recent_speeds: List[SignalObservation] = history.get_recent_history(
            "Vehicle_Speed",
            duration_seconds=self.time_window_seconds,
            as_of_timestamp=frame.timestamp
        )

        if len(recent_speeds) < self.min_observations:
            return None

        oldest_obs = recent_speeds[0]
        dt = speed_obs.timestamp - oldest_obs.timestamp
        if dt <= 0.05:  # Avoid division by near-zero interval
            return None

        delta_speed = current_speed - oldest_obs.value
        accel_rate = delta_speed / dt  # km/h per second

        # Check if vehicle is accelerating while brake is ON
        if delta_speed >= self.min_speed_increase_kmh and accel_rate >= self.min_acceleration_rate_kmh_s:
            if self._last_trigger_timestamp == frame.timestamp:
                return None
            self._last_trigger_timestamp = frame.timestamp

            return Anomaly(
                timestamp=frame.timestamp,
                rule_id=self.rule_id,
                anomaly_type=self.anomaly_type,
                signals=["Brake_Status", "Vehicle_Speed"],
                values={
                    "Brake_Status": brake_val,
                    "Vehicle_Speed": round(current_speed, 2),
                    "Delta_Speed_kmh": round(delta_speed, 2),
                    "Acceleration_Rate_kmh_s": round(accel_rate, 2)
                },
                reason=(
                    f"Temporal correlation violation: Vehicle speed accelerated by {delta_speed:.2f} km/h "
                    f"({accel_rate:.1f} km/h/s) over {dt:.2f}s while brake pedal status is ON (1)"
                ),
                context={
                    "start_speed_kmh": round(oldest_obs.value, 2),
                    "end_speed_kmh": round(current_speed, 2),
                    "time_window_s": round(dt, 3)
                }
            )

        return None
