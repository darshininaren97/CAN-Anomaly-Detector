"""
tests/test_integration.py
End-to-end integration tests using the actual CAN.dbc and CAN.log.txt files.
Verifies exact detection of the logic contradictions at t=4.023000
and verifies ZERO false positives on non-target anomalies (flood, timeouts, data corruption, RPM out-of-range).
"""

import unittest
import os
from dbc_parser import DBCParser
from detector import AnomalyDetector
from anomaly import AnomalyType


class TestCANIntegration(unittest.TestCase):

    def setUp(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.dbc_path = os.path.join(self.base_dir, "CAN.dbc")
        self.log_path = os.path.join(self.base_dir, "CAN.log.txt")

    def test_integration_full_log(self):
        self.assertTrue(os.path.exists(self.dbc_path), f"DBC file missing at {self.dbc_path}")
        self.assertTrue(os.path.exists(self.log_path), f"Log file missing at {self.log_path}")

        dbc = DBCParser(self.dbc_path).db
        detector = AnomalyDetector(db=dbc)
        anomalies = detector.process_log(self.log_path)

        # 1. Total anomalies detected must be exactly 2 (R-001 and R-002 at t=4.023000)
        self.assertEqual(len(anomalies), 2, f"Expected 2 anomalies, found {len(anomalies)}: {anomalies}")

        # 2. Check R-001 anomaly
        r001_anomalies = [a for a in anomalies if a.rule_id == "R-001"]
        self.assertEqual(len(r001_anomalies), 1)
        a1 = r001_anomalies[0]
        self.assertAlmostEqual(a1.timestamp, 4.023000, places=5)
        self.assertEqual(a1.anomaly_type, AnomalyType.CONTRADICTORY_SIGNAL.value)
        self.assertEqual(a1.values["Vehicle_Speed"], 120.0)
        self.assertEqual(a1.values["Engine_Status"], 0)

        # 3. Check R-002 anomaly
        r002_anomalies = [a for a in anomalies if a.rule_id == "R-002"]
        self.assertEqual(len(r002_anomalies), 1)
        a2 = r002_anomalies[0]
        self.assertAlmostEqual(a2.timestamp, 4.023000, places=5)
        self.assertEqual(a2.anomaly_type, AnomalyType.CONTRADICTORY_SIGNAL.value)
        self.assertEqual(a2.values["Vehicle_Speed"], 120.0)
        self.assertEqual(a2.values["Gear_Position"], 0)

        # 4. Verify ZERO false positives on non-target anomalies
        # Flood @ t=2.010-2.100
        flood_anomalies = [a for a in anomalies if 2.0 <= a.timestamp <= 2.2]
        self.assertEqual(len(flood_anomalies), 0, "False positive detected during timing flood section")

        # Missing timeout @ t=8.0-18.0
        timeout_anomalies = [a for a in anomalies if 8.0 <= a.timestamp <= 18.0]
        self.assertEqual(len(timeout_anomalies), 0, "False positive detected during missing message section")

        # Data corruption @ t=6.5-6.75
        corruption_anomalies = [a for a in anomalies if 6.4 <= a.timestamp <= 6.8]
        self.assertEqual(len(corruption_anomalies), 0, "False positive detected during data corruption section")


if __name__ == "__main__":
    unittest.main()
