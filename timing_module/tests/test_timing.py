"""Tests for baseline calculation and timing deviation detection."""

import unittest
from timing_module.config import TimingConfig
from timing_module.models import AnomalyType, Frame, Severity
from timing_module.timing_analyzer import TimingAnalyzer


class TestTimingAnalyzer(unittest.TestCase):
    """Unit tests for timing intervals, baseline fitting, and jitter detection."""

    def setUp(self):
        self.config = TimingConfig(
            relative_deviation_threshold=0.20,
            z_score_threshold=3.0,
            min_baseline_samples=5,
        )
        self.analyzer = TimingAnalyzer(config=self.config)

    def test_normal_periodic_traffic(self):
        """Test that perfectly regular periodic traffic yields zero anomalies."""
        frames = [
            Frame(timestamp=i * 0.100, can_id=0x464, can_id_hex="0x464", data="01A2000000000000", dlc=8, ecu="VSA")
            for i in range(20)
        ]
        self.analyzer.fit(frames)
        profiles = self.analyzer.baseline_profiles
        self.assertIn("0x464", profiles)
        self.assertAlmostEqual(profiles["0x464"].median_interval, 0.100, places=4)
        self.assertAlmostEqual(profiles["0x464"].frames_per_second, 10.0, places=1)

        anomalies = self.analyzer.analyze(frames)
        self.assertEqual(len(anomalies), 0)

    def test_small_timing_variation_within_threshold(self):
        """Test that small realistic jitter (<2%) does not produce false positives."""
        # 100ms nominal +/- 1ms jitter
        jitters = [0.000, 0.001, -0.001, 0.0008, -0.0009, 0.0005, -0.0006, 0.000, 0.001, -0.001]
        frames = []
        t = 0.0
        for j in jitters:
            t += 0.100 + j
            frames.append(Frame(timestamp=t, can_id=0x110, can_id_hex="0x110", data="0011223344556677", dlc=8, ecu="ECM"))

        self.analyzer.fit(frames)
        profile = self.analyzer.baseline_profiles["0x110"]
        self.assertAlmostEqual(profile.median_interval, 0.100, places=3)

        anomalies = self.analyzer.analyze(frames)
        self.assertEqual(len(anomalies), 0, f"Expected 0 anomalies for small jitter, got: {anomalies}")

    def test_large_timing_deviation(self):
        """Test detection of significant timing deviation (+80% delay)."""
        # Baseline frames
        frames = [
            Frame(timestamp=i * 0.050, can_id=0x110, can_id_hex="0x110", data="1122334455667788", dlc=8, ecu="ECM")
            for i in range(10)
        ]
        self.analyzer.fit(frames)

        # Append anomalous frame with 90ms interval (nominal 50ms -> 80% deviation)
        t_last = frames[-1].timestamp
        anom_frame = Frame(timestamp=t_last + 0.090, can_id=0x110, can_id_hex="0x110", data="1122334455667788", dlc=8, ecu="ECM")
        all_frames = frames + [anom_frame]

        anomalies = self.analyzer.analyze(all_frames)
        timing_anoms = [a for a in anomalies if a.anomaly_type == AnomalyType.TIMING_DEVIATION]

        self.assertEqual(len(timing_anoms), 1)
        anom = timing_anoms[0]
        self.assertEqual(anom.can_id, "0x110")
        self.assertAlmostEqual(anom.observed_value, 0.090, places=4)
        self.assertAlmostEqual(anom.expected_value, 0.050, places=4)
        self.assertAlmostEqual(anom.deviation, 0.80, places=2)
        self.assertIn("nominal_period", anom.evidence)
        self.assertIn("observed_period", anom.evidence)

    def test_constant_interval_zero_std(self):
        """Test baseline fitting and anomaly detection when std is exactly 0.0 (no division by zero)."""
        frames = [
            Frame(timestamp=i * 0.100, can_id=0x500, can_id_hex="0x500", data="FFFFFFFF", dlc=4, ecu="GATEWAY")
            for i in range(10)
        ]
        self.analyzer.fit(frames)
        profile = self.analyzer.baseline_profiles["0x500"]
        self.assertEqual(profile.std_interval, 0.0)
        self.assertEqual(profile.coefficient_of_variation, 0.0)

        # Now test with anomalous frame (150ms instead of 100ms)
        anom_frames = frames + [
            Frame(timestamp=frames[-1].timestamp + 0.150, can_id=0x500, can_id_hex="0x500", data="FFFFFFFF", dlc=4, ecu="GATEWAY")
        ]
        anomalies = self.analyzer.analyze(anom_frames)
        timing_anoms = [a for a in anomalies if a.anomaly_type == AnomalyType.TIMING_DEVIATION]
        self.assertEqual(len(timing_anoms), 1)
        self.assertEqual(timing_anoms[0].evidence["z_score"], "N/A (std=0)")

    def test_single_frame_can_id(self):
        """Test handling of single-frame CAN ID without exceptions."""
        frames = [
            Frame(timestamp=1.000, can_id=0x7DF, can_id_hex="0x7DF", data="02010D0000000000", dlc=8, ecu="DIAG")
        ]
        self.analyzer.fit(frames)
        profile = self.analyzer.baseline_profiles["0x7DF"]
        self.assertEqual(profile.sample_count, 1)
        self.assertEqual(profile.median_interval, 0.0)

        anomalies = self.analyzer.analyze(frames)
        self.assertEqual(len(anomalies), 0)

    def test_unsorted_timestamps(self):
        """Test that unsorted input timestamps are properly ordered chronologically."""
        # Unsorted sequence of 50ms intervals
        raw_timestamps = [0.200, 0.050, 0.150, 0.000, 0.100, 0.300, 0.250]
        frames = [
            Frame(timestamp=ts, can_id=0x123, can_id_hex="0x123", data="00", dlc=1, ecu="TEST")
            for ts in raw_timestamps
        ]
        self.analyzer.fit(frames)
        profile = self.analyzer.baseline_profiles["0x123"]
        self.assertAlmostEqual(profile.median_interval, 0.050, places=4)

        anomalies = self.analyzer.analyze(frames)
        self.assertEqual(len(anomalies), 0)

    def test_multiple_can_ids(self):
        """Test baseline fitting and independent tracking for multiple CAN IDs."""
        frames = []
        # CAN ID 1: 20ms
        for i in range(10):
            frames.append(Frame(timestamp=i * 0.020, can_id=0x100, can_id_hex="0x100", data="A1", dlc=1, ecu="ECU1"))
        # CAN ID 2: 100ms
        for i in range(10):
            frames.append(Frame(timestamp=i * 0.100, can_id=0x200, can_id_hex="0x200", data="B2", dlc=1, ecu="ECU2"))

        self.analyzer.fit(frames)
        self.assertIn("0x100", self.analyzer.baseline_profiles)
        self.assertIn("0x200", self.analyzer.baseline_profiles)
        self.assertAlmostEqual(self.analyzer.baseline_profiles["0x100"].median_interval, 0.020, places=4)
        self.assertAlmostEqual(self.analyzer.baseline_profiles["0x200"].median_interval, 0.100, places=4)

    def test_insufficient_baseline(self):
        """Test that CAN IDs with fewer than min_baseline_samples do not generate false alerts."""
        frames = [
            Frame(timestamp=0.000, can_id=0x999, can_id_hex="0x999", data="00", dlc=1),
            Frame(timestamp=0.010, can_id=0x999, can_id_hex="0x999", data="00", dlc=1),
            Frame(timestamp=0.080, can_id=0x999, can_id_hex="0x999", data="00", dlc=1),
        ]
        # Only 3 samples vs min 5
        self.analyzer.fit(frames)
        anomalies = self.analyzer.analyze(frames)
        self.assertEqual(len(anomalies), 0)


if __name__ == "__main__":
    unittest.main()
