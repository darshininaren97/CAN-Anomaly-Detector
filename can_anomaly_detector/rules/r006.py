"""
rules/r006.py
Rule R-006: Wheel Speed vs Vehicle Speed Correlation.
Signal Correlation Anomaly.
"""

from typing import Dict, Optional
from asc_parser import CANFrame
from signal_decoder import DecodedSignal
from signal_history import SignalHistory
from anomaly import Anomaly, AnomalyType
from rules.base_rule import BaseRule


class Rule006(BaseRule):
    """
    R-006: Signal Correlation Rule.
    Evaluates physical consistency between Vehicle_Speed, Wheel_Speed_FL, and Wheel_Speed_FR.
    Flags an anomaly when active wheel speeds physically deviate from vehicle speed beyond tolerance.
    """

    def __init__(
        self,
        max_speed_diff_kmh: float = 15.0,
        min_evaluation_speed_kmh: float = 5.0,
        require_active_wheel_signals: bool = True
    ):
        super().__init__(
            rule_id="R-006",
            name="Wheel Speed vs Vehicle Speed Inconsistency",
            anomaly_type=AnomalyType.SIGNAL_CORRELATION.value,
            description="Wheel speeds (FL/FR) deviate significantly from vehicle speed",
            is_enabled=True
        )
        self.max_speed_diff_kmh = max_speed_diff_kmh
        self.min_evaluation_speed_kmh = min_evaluation_speed_kmh
        self.require_active_wheel_signals = require_active_wheel_signals

    def evaluate(
        self,
        frame: CANFrame,
        decoded_signals: Dict[str, DecodedSignal],
        history: SignalHistory
    ) -> Optional[Anomaly]:
        if not self.is_enabled:
            return None

        # Check if the current frame contains VehicleSpeed message signals
        if "Vehicle_Speed" not in decoded_signals:
            return None

        v_speed_sig = decoded_signals["Vehicle_Speed"]
        v_speed = v_speed_sig.physical_value

        fl_sig = decoded_signals.get("Wheel_Speed_FL")
        fr_sig = decoded_signals.get("Wheel_Speed_FR")

        if fl_sig is None or fr_sig is None:
            return None

        fl_speed = fl_sig.physical_value
        fr_speed = fr_sig.physical_value

        # If require_active_wheel_signals is True, skip evaluation when wheel speed signals
        # are unpopulated/zero while vehicle is moving (handling logs where wheel speeds are omitted)
        if self.require_active_wheel_signals:
            if fl_speed == 0.0 and fr_speed == 0.0:
                return None

        # Only evaluate above minimum speed to avoid standstill edge cases
        if v_speed < self.min_evaluation_speed_kmh and fl_speed < self.min_evaluation_speed_kmh and fr_speed < self.min_evaluation_speed_kmh:
            return None

        # Calculate deviations
        diff_fl = abs(v_speed - fl_speed)
        diff_fr = abs(v_speed - fr_speed)
        diff_wheels = abs(fl_speed - fr_speed)

        # Inconsistent if either wheel deviates from vehicle speed by more than tolerance
        if diff_fl > self.max_speed_diff_kmh or diff_fr > self.max_speed_diff_kmh:
            if self._last_trigger_timestamp == frame.timestamp:
                return None
            self._last_trigger_timestamp = frame.timestamp

            return Anomaly(
                timestamp=frame.timestamp,
                rule_id=self.rule_id,
                anomaly_type=self.anomaly_type,
                signals=["Vehicle_Speed", "Wheel_Speed_FL", "Wheel_Speed_FR"],
                values={
                    "Vehicle_Speed": round(v_speed, 2),
                    "Wheel_Speed_FL": round(fl_speed, 2),
                    "Wheel_Speed_FR": round(fr_speed, 2)
                },
                reason=(
                    f"Physical correlation violation: Vehicle speed ({v_speed:.2f} km/h) deviates from "
                    f"wheel speeds (FL={fl_speed:.2f} km/h, FR={fr_speed:.2f} km/h) "
                    f"beyond tolerance of {self.max_speed_diff_kmh:.1f} km/h"
                )
            )

        return None
