"""Tests for CAN message timeout and missing frame detection."""

import unittest
from timing_module.config import TimingConfig
from timing_module.models import AnomalyType, Frame, Severity
from timing_module.timing_analyzer import TimingAnalyzer


class TestTimeoutDetection(unittest.TestCase):
    """Unit tests for timeout detection and missed message calculations."""

    def setUp(self):
        self.config = TimingConfig(
            timeout_multiplier=2.5,
            min_baseline_samples=5,
        )
        self.analyzer = TimingAnalyzer(config=self.config)

    def test_timeout_detection_and_missed_message_count(self):
        """Test detection of transmission timeout and calculation of missed frames."""
        # 10 baseline frames at 100ms (0.100s)
        frames = [
            Frame(timestamp=i * 0.100, can_id=0x330, can_id_hex="0x330", data="0F40", dlc=2, ecu="TCU")
            for i in range(10)
        ]
        self.analyzer.fit(frames)

        # Gap of 1.200s (expected 0.100s -> missed_messages = floor(1.2 / 0.1) - 1 = 11)
        t_last = frames[-1].timestamp
        t_resume = t_last + 1.200
        anom_frames = frames + [
            Frame(timestamp=t_resume, can_id=0x330, can_id_hex="0x330", data="0F40", dlc=2, ecu="TCU")
        ]

        anomalies = self.analyzer.analyze(anom_frames)
        timeout_events = [a for a in anomalies if a.anomaly_type == AnomalyType.TIMING_TIMEOUT]

        self.assertEqual(len(timeout_events), 1, f"Expected 1 timeout event, got {len(timeout_events)}")

        to_event = timeout_events[0]
        self.assertEqual(to_event.can_id, "0x330")
        self.assertEqual(to_event.ecu, "TCU")
        self.assertAlmostEqual(to_event.observed_value, 1.200, places=3)
        self.assertAlmostEqual(to_event.expected_value, 0.100, places=3)
        self.assertEqual(to_event.evidence["missed_messages"], 11)
        self.assertAlmostEqual(to_event.evidence["last_seen_timestamp"], t_last, places=3)
        self.assertAlmostEqual(to_event.evidence["resumed_timestamp"], t_resume, places=3)

    def test_timeout_with_insufficient_baseline_safety(self):
        """Test that single/insufficient frames do not trigger spurious timeout crashes."""
        # Single frame
        frames = [
            Frame(timestamp=1.000, can_id=0x111, can_id_hex="0x111", data="11", dlc=1)
        ]
        self.analyzer.fit(frames)
        anomalies = self.analyzer.analyze(frames)
        self.assertEqual(len(anomalies), 0)


if __name__ == "__main__":
    unittest.main()
