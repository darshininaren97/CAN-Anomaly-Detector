"""Tests for rapid duplicate payload burst detection."""

import unittest
from timing_module.config import TimingConfig
from timing_module.models import AnomalyType, Frame, Severity
from timing_module.timing_analyzer import TimingAnalyzer


class TestDuplicateDetection(unittest.TestCase):
    """Unit tests for duplicate payload burst detection."""

    def setUp(self):
        self.config = TimingConfig(
            duplicate_max_interval_factor=0.30,
            duplicate_min_repeat_count=3,
            min_baseline_samples=5,
        )
        self.analyzer = TimingAnalyzer(config=self.config)

    def test_duplicate_payload_burst_detection(self):
        """Test detection of rapid repeated payload burst (replay injection)."""
        # Baseline frames (nominal 20ms = 0.020s)
        frames = [
            Frame(timestamp=i * 0.020, can_id=0x220, can_id_hex="0x220", data=f"PAYLOAD_{i:04X}", dlc=8, ecu="BCM")
            for i in range(10)
        ]
        self.analyzer.fit(frames)

        # Inject 6 duplicate frames with identical payload 'DEADBEEFCAFEBABE' spaced at 3ms (0.003s)
        t_start = 1.000
        burst_payload = "DEADBEEFCAFEBABE"
        dup_frames = [
            Frame(timestamp=t_start + i * 0.003, can_id=0x220, can_id_hex="0x220", data=burst_payload, dlc=8, ecu="BCM")
            for i in range(6)
        ]

        all_frames = frames + dup_frames
        anomalies = self.analyzer.analyze(all_frames)

        dup_events = [a for a in anomalies if a.anomaly_type == AnomalyType.DUPLICATE_BURST]
        self.assertEqual(len(dup_events), 1, f"Expected 1 duplicate burst event, got {len(dup_events)}")

        dup = dup_events[0]
        self.assertEqual(dup.can_id, "0x220")
        self.assertEqual(dup.ecu, "BCM")
        self.assertEqual(dup.abnormal_frame_count, 6)
        self.assertAlmostEqual(dup.start_time, t_start, places=3)
        self.assertAlmostEqual(dup.observed_period, 0.003, places=4)
        self.assertEqual(dup.evidence["payload"], burst_payload)
        self.assertEqual(dup.evidence["repeat_count"], 6)

    def test_normal_periodic_repeating_payload_not_flagged(self):
        """Test that static/repeating payloads at normal periodic intervals are NOT flagged as anomalies."""
        # 30 frames with the exact same payload at normal 100ms intervals
        same_payload = "0100000000000000"
        frames = [
            Frame(timestamp=i * 0.100, can_id=0x464, can_id_hex="0x464", data=same_payload, dlc=8, ecu="VSA")
            for i in range(30)
        ]
        self.analyzer.fit(frames)
        anomalies = self.analyzer.analyze(frames)

        # There should be 0 anomalies because the intervals are normal (0.100s)
        self.assertEqual(len(anomalies), 0, f"Normal repeating payloads should not trigger anomalies: {anomalies}")


if __name__ == "__main__":
    unittest.main()
