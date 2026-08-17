"""Tests for CAN flooding detection and event aggregation."""

import unittest
from timing_module.config import TimingConfig
from timing_module.models import AnomalyType, Frame, Severity
from timing_module.timing_analyzer import TimingAnalyzer


class TestFloodingDetection(unittest.TestCase):
    """Unit tests for flooding bursts and alert aggregation."""

    def setUp(self):
        self.config = TimingConfig(
            flooding_ratio_threshold=0.25,
            flooding_min_burst_count=5,
            min_baseline_samples=5,
        )
        self.analyzer = TimingAnalyzer(config=self.config)

    def test_flooding_burst_detection_and_aggregation(self):
        """Test that a burst of 30 rapid frames generates exactly ONE aggregated event."""
        # Establish baseline: 100ms period (0.100s)
        baseline_frames = [
            Frame(timestamp=i * 0.100, can_id=0x464, can_id_hex="0x464", data="01A2000000000000", dlc=8, ecu="VSA")
            for i in range(15)
        ]
        self.analyzer.fit(baseline_frames)

        # Inject flooding burst: 30 frames at 2ms interval (0.002s) starting at t=2.0s
        t_start = 2.000
        flooding_frames = []
        for i in range(30):
            flooding_frames.append(
                Frame(timestamp=round(t_start + i * 0.002, 6), can_id=0x464, can_id_hex="0x464", data="01A2000000000000", dlc=8, ecu="VSA")
            )

        # Resume normal traffic
        t_resume = flooding_frames[-1].timestamp + 0.100
        resume_frames = [
            Frame(timestamp=round(t_resume + i * 0.100, 6), can_id=0x464, can_id_hex="0x464", data="01A2000000000000", dlc=8, ecu="VSA")
            for i in range(5)
        ]

        all_frames = baseline_frames + flooding_frames + resume_frames
        anomalies = self.analyzer.analyze(all_frames)

        flooding_events = [a for a in anomalies if a.anomaly_type == AnomalyType.TIMING_FLOODING]

        # Must aggregate into exactly ONE event
        self.assertEqual(len(flooding_events), 1, f"Expected exactly 1 aggregated flooding event, got {len(flooding_events)}")

        flood = flooding_events[0]
        self.assertEqual(flood.can_id, "0x464")
        self.assertEqual(flood.ecu, "VSA")
        self.assertEqual(flood.abnormal_frame_count, 30)
        self.assertAlmostEqual(flood.nominal_period, 0.100, places=3)
        self.assertAlmostEqual(flood.observed_period, 0.002, places=4)
        self.assertAlmostEqual(flood.start_time, t_start, places=3)
        self.assertAlmostEqual(flood.end_time, flooding_frames[-1].timestamp, places=3)

        # Verify diagnosis and causes
        self.assertEqual(
            flood.diagnosis,
            "Abnormally high-frequency CAN transmission; possible flooding, replay-like activity, or ECU malfunction.",
        )
        self.assertIn("CAN flooding", flood.possible_causes)
        self.assertIn("Replay-like transmission", flood.possible_causes)
        self.assertIn("ECU malfunction", flood.possible_causes)

        # Verify evidence dictionary
        self.assertEqual(flood.evidence["repeat_count"], 30)
        self.assertAlmostEqual(flood.evidence["nominal_period"], 0.100, places=3)
        self.assertAlmostEqual(flood.evidence["observed_period"], 0.002, places=4)

    def test_flooding_persistence_requirement(self):
        """Test that short transient bursts below flooding_min_burst_count are not flagged as flooding."""
        # 10 baseline frames at 100ms
        frames = [
            Frame(timestamp=i * 0.100, can_id=0x464, can_id_hex="0x464", data="01A2000000000000", dlc=8, ecu="VSA")
            for i in range(10)
        ]
        self.analyzer.fit(frames)

        # Transient: only 2 rapid frames (below min burst count of 5)
        t_last = frames[-1].timestamp
        transient_frames = [
            Frame(timestamp=t_last + 0.005, can_id=0x464, can_id_hex="0x464", data="01A2000000000000", dlc=8, ecu="VSA"),
            Frame(timestamp=t_last + 0.010, can_id=0x464, can_id_hex="0x464", data="01A2000000000000", dlc=8, ecu="VSA"),
        ]

        # Normal continuation
        cont_frames = [
            Frame(timestamp=t_last + 0.010 + (i + 1) * 0.100, can_id=0x464, can_id_hex="0x464", data="01A2000000000000", dlc=8, ecu="VSA")
            for i in range(5)
        ]

        all_frames = frames + transient_frames + cont_frames
        anomalies = self.analyzer.analyze(all_frames)

        flooding_events = [a for a in anomalies if a.anomaly_type == AnomalyType.TIMING_FLOODING]
        self.assertEqual(len(flooding_events), 0, "Transient burst should not trigger a persistent flooding alert")


if __name__ == "__main__":
    unittest.main()
