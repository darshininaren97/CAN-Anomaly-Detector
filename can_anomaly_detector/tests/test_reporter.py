"""
tests/test_reporter.py
Unit tests for AnomalyReporter covering Enum normalization, directory creation,
console formatting, and JSON export.
"""

import unittest
import os
import tempfile
import json
import shutil
from anomaly import Anomaly, AnomalyType
from reporter import AnomalyReporter


class TestAnomalyReporter(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_enum_comparison_normalization(self):
        # Create anomalies where one uses raw string and one uses Enum instance
        a1 = Anomaly(
            timestamp=4.0,
            rule_id="R-001",
            anomaly_type="Contradictory Signal",  # raw string
            signals=["Vehicle_Speed", "Engine_Status"],
            values={"Vehicle_Speed": 120.0, "Engine_Status": 0},
            reason="Speed > 0 with Engine OFF"
        )
        a2 = Anomaly(
            timestamp=4.0,
            rule_id="R-002",
            anomaly_type=AnomalyType.CONTRADICTORY_SIGNAL,  # Enum instance
            signals=["Vehicle_Speed", "Gear_Position"],
            values={"Vehicle_Speed": 120.0, "Gear_Position": 0},
            reason="Speed > 0 with Gear PARK"
        )
        a3 = Anomaly(
            timestamp=5.0,
            rule_id="R-006",
            anomaly_type=AnomalyType.SIGNAL_CORRELATION,  # Enum instance
            signals=["Vehicle_Speed", "Wheel_Speed_FL"],
            values={"Vehicle_Speed": 100.0, "Wheel_Speed_FL": 40.0},
            reason="Wheel speed deviation"
        )

        summary = AnomalyReporter.calculate_summary([a1, a2, a3])
        self.assertEqual(summary["contradictory_anomalies"], 2)
        self.assertEqual(summary["correlation_anomalies"], 1)
        self.assertEqual(summary["total_anomalies"], 3)

    def test_export_json_nested_directory_creation(self):
        nested_output_path = os.path.join(self.temp_dir, "nested", "subfolder", "report.json")
        self.assertFalse(os.path.exists(os.path.dirname(nested_output_path)))

        anomaly = Anomaly(
            timestamp=4.023,
            rule_id="R-001",
            anomaly_type=AnomalyType.CONTRADICTORY_SIGNAL,
            signals=["Vehicle_Speed", "Engine_Status"],
            values={"Vehicle_Speed": 120.0, "Engine_Status": 0},
            reason="Speed > 0 with Engine OFF"
        )

        AnomalyReporter.export_json([anomaly], nested_output_path)
        self.assertTrue(os.path.exists(nested_output_path))

        with open(nested_output_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["summary"]["contradictory_anomalies"], 1)
        self.assertEqual(data["summary"]["total_anomalies"], 1)
        self.assertEqual(len(data["anomalies"]), 1)

    def test_console_report_format(self):
        anomaly = Anomaly(
            timestamp=4.023,
            rule_id="R-001",
            anomaly_type="Contradictory Signal",
            signals=["Vehicle_Speed", "Engine_Status"],
            values={"Vehicle_Speed": 120.0, "Engine_Status": 0},
            reason="Vehicle is moving while engine status indicates OFF."
        )

        report = AnomalyReporter.format_console_report([anomaly])
        self.assertIn("CAN CONTRADICTORY / CORRELATION ANOMALY REPORT", report)
        self.assertIn("Rule: R-001", report)
        self.assertIn("Vehicle_Speed = 120.00 km/h", report)
        self.assertIn("Engine_Status = OFF", report)
        self.assertIn("Contradictory anomalies: 1", report)
        self.assertIn("Total anomalies:         1", report)


if __name__ == "__main__":
    unittest.main()
