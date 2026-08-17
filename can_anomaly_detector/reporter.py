"""
reporter.py
Generates human-readable console reports and JSON file exports for detected anomalies.
"""

import json
import os
from typing import List, Dict, Any
from anomaly import Anomaly, AnomalyType


class AnomalyReporter:
    """Formats and exports anomaly detection results."""

    @staticmethod
    def _normalize_anomaly_type(anomaly_type: Any) -> str:
        """Normalize anomaly type whether passed as an Enum instance or string."""
        if hasattr(anomaly_type, "value"):
            return str(anomaly_type.value)
        return str(anomaly_type)

    @classmethod
    def calculate_summary(cls, anomalies: List[Anomaly]) -> Dict[str, int]:
        """
        Calculate summary counts of contradictory, correlation, and total anomalies.
        Handles both Enum instances and raw string representations safely.
        """
        contradictory_count = sum(
            1 for a in anomalies
            if cls._normalize_anomaly_type(a.anomaly_type) == AnomalyType.CONTRADICTORY_SIGNAL.value
        )
        correlation_count = sum(
            1 for a in anomalies
            if cls._normalize_anomaly_type(a.anomaly_type) == AnomalyType.SIGNAL_CORRELATION.value
        )
        return {
            "contradictory_anomalies": contradictory_count,
            "correlation_anomalies": correlation_count,
            "total_anomalies": len(anomalies)
        }

    @classmethod
    def format_console_report(cls, anomalies: List[Anomaly]) -> str:
        """Generate human-readable console report matching required specifications."""
        lines = []
        lines.append("=" * 60)
        lines.append("CAN CONTRADICTORY / CORRELATION ANOMALY REPORT")
        lines.append("=" * 60)
        lines.append("")

        if not anomalies:
            lines.append("No contradictory or correlation anomalies detected.")
            lines.append("")
        else:
            for anomaly in anomalies:
                type_str = cls._normalize_anomaly_type(anomaly.anomaly_type)
                lines.append("[ANOMALY]")
                lines.append(f"Rule: {anomaly.rule_id}")
                lines.append(f"Type: {type_str}")
                lines.append(f"Timestamp: {anomaly.timestamp:.6f} s")
                lines.append("")

                for sig_name, val in anomaly.values.items():
                    if sig_name == "Engine_Status":
                        val_str = "OFF" if val == 0 else "RUNNING"
                        lines.append(f"{sig_name} = {val_str}")
                    elif sig_name == "Gear_Position":
                        gear_map = {0: "PARK", 1: "REVERSE", 2: "NEUTRAL", 3: "DRIVE"}
                        gear_str = gear_map.get(val, str(val))
                        lines.append(f"{sig_name} = {gear_str}")
                    elif sig_name == "Brake_Status":
                        val_str = "ON" if val == 1 else "OFF"
                        lines.append(f"{sig_name} = {val_str}")
                    elif "Speed" in sig_name and isinstance(val, (int, float)):
                        lines.append(f"{sig_name} = {val:.2f} km/h")
                    elif isinstance(val, float):
                        lines.append(f"{sig_name} = {val:.2f}")
                    else:
                        lines.append(f"{sig_name} = {val}")

                lines.append("")
                lines.append("Reason:")
                lines.append(anomaly.reason)
                lines.append("")
                lines.append("-" * 60)
                lines.append("")

        # Summary statistics via centralized helper
        summary = cls.calculate_summary(anomalies)

        lines.append("SUMMARY")
        lines.append(f"Contradictory anomalies: {summary['contradictory_anomalies']}")
        lines.append(f"Correlation anomalies:   {summary['correlation_anomalies']}")
        lines.append(f"Total anomalies:         {summary['total_anomalies']}")
        lines.append("=" * 60)

        return "\n".join(lines)

    @classmethod
    def print_console_report(cls, anomalies: List[Anomaly]):
        """Print the formatted console report."""
        print(cls.format_console_report(anomalies))

    @classmethod
    def export_json(cls, anomalies: List[Anomaly], output_path: str):
        """
        Export anomalies list to a JSON file, automatically creating parent directories if needed.
        """
        parent_dir = os.path.dirname(output_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        summary = cls.calculate_summary(anomalies)
        data = {
            "summary": summary,
            "anomalies": [a.to_dict() for a in anomalies]
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
