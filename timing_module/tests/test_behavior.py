"""
Behavioral, ECU profiling, Parser Adapter, Configuration validation, and End-to-End Integration Tests.
"""

import json
import tempfile
import unittest
from pathlib import Path

from timing_module.config import TimingConfig
from timing_module.models import AnomalyType, Frame, Severity
from timing_module.parser_adapter import (
    ParserAdapter,
    normalize_can_id,
    normalize_frame,
    parse_json_file,
    parse_records,
)
from timing_module.timing_analyzer import TimingAnalyzer


class TestBehaviorAndIntegration(unittest.TestCase):
    """Integration and behavioral profiling tests."""

    def test_package_import_public_api(self):
        """Test that public API symbols can be directly imported from the top-level package."""
        from timing_module import (
            AnomalyEvent,
            AnomalyType,
            BaselineProfile,
            ECUProfile,
            Frame,
            ParserAdapter,
            Severity,
            TimingAnalyzer,
            TimingConfig,
            normalize_can_id,
            normalize_frame,
            parse_json_file,
            parse_records,
        )
        self.assertIsNotNone(TimingAnalyzer)
        self.assertIsNotNone(ParserAdapter)

    def test_analyze_without_fit_raises_runtime_error(self):
        """Test that analyze() strictly requires fit() to prevent data leakage/contamination."""
        analyzer = TimingAnalyzer()
        frames = [
            Frame(timestamp=0.050, can_id=0x110, can_id_hex="0x110", data="AA", dlc=1, ecu="ECM")
        ]
        with self.assertRaises(RuntimeError) as ctx:
            analyzer.analyze(frames)
        self.assertIn("Baseline profiles have not been fitted", str(ctx.exception))

    def test_config_validation_rules(self):
        """Test that invalid config thresholds raise ValueError."""
        with self.assertRaises(ValueError):
            TimingConfig(flooding_ratio_threshold=1.5)  # Must be < 1.0

        with self.assertRaises(ValueError):
            TimingConfig(duplicate_max_interval_factor=-0.1)  # Must be > 0.0

        with self.assertRaises(ValueError):
            TimingConfig(timeout_multiplier=0.5)  # Must be > 1.0

        with self.assertRaises(ValueError):
            TimingConfig(relative_deviation_threshold=0.0)  # Must be > 0.0

    def test_ecu_fallback_resolution_from_baseline(self):
        """Test that frames with missing ecu field resolve ECU from fitted baseline."""
        # Baseline with ECU specified
        train_frames = [
            Frame(timestamp=i * 0.100, can_id=0x464, can_id_hex="0x464", data="01", dlc=1, ecu="VSA")
            for i in range(10)
        ]
        analyzer = TimingAnalyzer()
        analyzer.fit(train_frames)

        # Evaluation frames without ECU specified (ecu=None)
        eval_frames = [
            Frame(timestamp=i * 0.100, can_id=0x464, can_id_hex="0x464", data="01", dlc=1, ecu=None)
            for i in range(10)
        ]
        analyzer.analyze(eval_frames)

        # Verify ECU profile is attributed to VSA, not UNKNOWN
        self.assertIn("VSA", analyzer.ecu_profiles)
        self.assertNotIn("UNKNOWN", analyzer.ecu_profiles)
        self.assertEqual(analyzer.ecu_profiles["VSA"].message_count, 10)

    def test_can_id_normalization(self):
        """Test normalization of both hex and integer CAN ID inputs."""
        int_id, hex_id = normalize_can_id("0x464")
        self.assertEqual(int_id, 1124)
        self.assertEqual(hex_id, "0x464")

        int_id, hex_id = normalize_can_id("1124")
        self.assertEqual(int_id, 1124)
        self.assertEqual(hex_id, "0x464")

        int_id, hex_id = normalize_can_id(1124)
        self.assertEqual(int_id, 1124)
        self.assertEqual(hex_id, "0x464")

        int_id, hex_id = normalize_can_id(0x464)
        self.assertEqual(int_id, 1124)
        self.assertEqual(hex_id, "0x464")

    def test_parser_adapter_json_record(self):
        """Test parsing raw JSON records into normalized Frame objects."""
        raw_records = [
            {"timestamp": 1.250, "can_id": "0x464", "data": "01A2000000000000", "dlc": 8, "ecu": "VSA"},
            {"timestamp": 1.260, "can_id": 1124, "data": "01A2000000000000", "dlc": 8},
        ]
        adapter = ParserAdapter()
        frames = adapter.parse_records(raw_records)

        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0].can_id_hex, "0x464")
        self.assertEqual(frames[0].can_id, 1124)
        self.assertEqual(frames[0].ecu, "VSA")
        self.assertEqual(frames[1].can_id_hex, "0x464")
        self.assertIsNone(frames[1].ecu)

    def test_ecu_behavioral_profiling(self):
        """Test generation of ECU behavioral profiles across multiple ECUs."""
        frames = []
        for i in range(10):
            frames.append(Frame(timestamp=i * 0.050, can_id=0x110, can_id_hex="0x110", data=f"{i:02X}", dlc=1, ecu="ECM"))
        for i in range(10):
            frames.append(Frame(timestamp=i * 0.020, can_id=0x220, can_id_hex="0x220", data="AA", dlc=1, ecu="BCM"))

        analyzer = TimingAnalyzer()
        analyzer.fit(frames)
        analyzer.analyze(frames)

        profiles = analyzer.ecu_profiles
        self.assertIn("ECM", profiles)
        self.assertIn("BCM", profiles)

        ecm_profile = profiles["ECM"]
        self.assertEqual(ecm_profile.message_count, 10)
        self.assertIn("0x110", ecm_profile.can_ids)
        self.assertAlmostEqual(ecm_profile.nominal_frequency, 20.0, places=1)

    def test_end_to_end_pipeline(self):
        """
        Mandatory End-to-End Test:
        JSON input -> parser_adapter -> normalized frames -> TimingAnalyzer.fit()
        -> TimingAnalyzer.analyze() -> anomaly events -> JSON output report.
        """
        train_data = []
        # 10 baseline frames for 0x110 (50ms)
        for i in range(10):
            train_data.append({
                "timestamp": round(i * 0.050, 4),
                "can_id": "0x110",
                "data": "11223344",
                "dlc": 4,
                "ecu": "ECM",
            })

        # 10 baseline frames for 0x464 (100ms)
        for i in range(10):
            train_data.append({
                "timestamp": round(i * 0.100, 4),
                "can_id": "1124",
                "data": "AABBCCDD",
                "dlc": 4,
                "ecu": "VSA",
            })

        # Test evaluation stream with injected flooding and timeout
        eval_data = list(train_data)

        # Inject Flooding on 0x464 (10 frames at 2ms interval)
        for i in range(10):
            eval_data.append({
                "timestamp": round(2.000 + i * 0.002, 4),
                "can_id": "0x464",
                "data": "AABBCCDD",
                "dlc": 4,
                "ecu": "VSA",
            })

        # Inject Timeout on 0x110 (gap of 0.500s = 500ms after t=0.450 -> at t=0.950s)
        eval_data.append({
            "timestamp": 0.950,
            "can_id": "0x110",
            "data": "11223344",
            "dlc": 4,
            "ecu": "ECM",
        })

        with tempfile.TemporaryDirectory() as tmp_dir:
            train_file = Path(tmp_dir) / "train.json"
            eval_file = Path(tmp_dir) / "eval.json"
            output_file = Path(tmp_dir) / "output.json"

            with open(train_file, "w", encoding="utf-8") as f:
                json.dump(train_data, f)
            with open(eval_file, "w", encoding="utf-8") as f:
                json.dump(eval_data, f)

            # Step 1: Parse JSON
            adapter = ParserAdapter()
            train_frames = adapter.parse_json_file(train_file)
            eval_frames = adapter.parse_json_file(eval_file)

            # Step 2: Fit Baseline
            analyzer = TimingAnalyzer()
            analyzer.fit(train_frames)
            self.assertIn("0x110", analyzer.baseline_profiles)
            self.assertIn("0x464", analyzer.baseline_profiles)

            # Step 3: Analyze & Generate Report
            report = analyzer.generate_report(eval_frames)

            # Step 4: Write JSON output
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)

            self.assertTrue(output_file.exists())

            # Step 5: Read & Validate JSON Output
            with open(output_file, "r", encoding="utf-8") as f:
                loaded_report = json.load(f)

            self.assertIn("summary", loaded_report)
            self.assertIn("profiles", loaded_report)
            self.assertIn("anomalies", loaded_report)

            anomalies = loaded_report["anomalies"]
            self.assertGreaterEqual(len(anomalies), 2)

            # Validate standardized fields across all anomalies
            for anom in anomalies:
                self.assertIn("timestamp", anom)
                self.assertIn("start_time", anom)
                self.assertIn("end_time", anom)
                self.assertIn("observed_value", anom)
                self.assertIn("expected_value", anom)
                self.assertIn("deviation", anom)
                self.assertIn("nominal_period", anom)
                self.assertIn("observed_period", anom)
                self.assertIn("abnormal_frame_count", anom)

            anomaly_types = [a["anomaly_type"] for a in anomalies]
            self.assertIn(AnomalyType.TIMING_FLOODING.value, anomaly_types)
            self.assertIn(AnomalyType.TIMING_TIMEOUT.value, anomaly_types)

    def test_input_validation_errors(self):
        """Test that invalid payload characters, negative timestamps, and out of range IDs raise ValueError."""
        adapter = ParserAdapter()

        # Invalid hex character 'Z'
        with self.assertRaises(ValueError):
            adapter.normalize_record({"timestamp": 1.0, "can_id": "0x100", "data": "ZZZZ"})

        # Negative timestamp
        with self.assertRaises(ValueError):
            adapter.normalize_record({"timestamp": -0.5, "can_id": "0x100", "data": "1122"})

        # CAN ID out of 29-bit range
        with self.assertRaises(ValueError):
            adapter.normalize_record({"timestamp": 1.0, "can_id": 0x20000000, "data": "1122"})

    def test_cli_execution_and_missing_config_handling(self):
        """Test CLI run_cli function and error on missing config file."""
        from timing_module.__main__ import run_cli

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_report = Path(tmp_dir) / "report.json"
            tmp_parsed = Path(tmp_dir) / "parsed.json"

            # Run CLI on sample data
            ret = run_cli(
                input_path="examples/normal.json",
                output_path=str(tmp_report),
                parsed_output_path=str(tmp_parsed),
                allow_self_baseline=True,
            )
            self.assertEqual(ret, 0)
            self.assertTrue(tmp_report.exists())
            self.assertTrue(tmp_parsed.exists())

            # Missing config must return error code 1
            ret_err = run_cli(
                input_path="examples/normal.json",
                config_path="non_existent_config.json",
            )
            self.assertEqual(ret_err, 1)


if __name__ == "__main__":
    unittest.main()

