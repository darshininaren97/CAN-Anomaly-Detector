"""
tests/test_detector_robustness.py
Tests specifically validating error handling, DBC loading safety, database synchronization,
rule state isolation across multiple detector instances, upfront DBC verification, and unhandled file operations.
"""

import unittest
import os
import tempfile
from dbc_parser import DBCParser, DBCDatabase
from asc_parser import ASCParser, CANFrame
from detector import AnomalyDetector
from signal_decoder import SignalDecoder, DecodedSignal
from rules import Rule001, Rule002, create_all_rules


class TestDetectorRobustness(unittest.TestCase):

    def setUp(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.dbc_path = os.path.join(self.base_dir, "CAN.dbc")
        self.log_path = os.path.join(self.base_dir, "CAN.log.txt")

    def test_signal_decoder_init_with_none(self):
        # Ensure SignalDecoder can be initialized with None without AttributeError
        decoder = SignalDecoder(None)
        self.assertIsNone(decoder.db)
        
        # Calling decode_frame on None db should raise ValueError
        frame = CANFrame(0.0, 1, 0x1A0, "Rx", "d", 8, b"\x00" * 8)
        with self.assertRaises(ValueError):
            decoder.decode_frame(frame)

    def test_process_log_deferred_dbc_check(self):
        # When detector is created without DBC, process_log must fail upfront
        detector = AnomalyDetector()
        self.assertIsNone(detector.db)

        with self.assertRaises(ValueError) as ctx:
            detector.process_log(self.log_path)
        self.assertIn("DBC database must be set or loaded", str(ctx.exception))

    def test_load_dbc_safety(self):
        detector = AnomalyDetector()
        self.assertIsNone(detector.db)

        # 1. Invalid path type / empty
        with self.assertRaises(ValueError):
            detector.load_dbc("")

        # 2. Non-existent file
        with self.assertRaises(FileNotFoundError):
            detector.load_dbc("non_existent_file.dbc")

        # 3. Valid load
        db = detector.load_dbc(self.dbc_path)
        self.assertIsNotNone(detector.db)
        self.assertIs(detector.db, db)
        self.assertIs(detector.decoder.db, db)

    def test_set_database_sync(self):
        detector = AnomalyDetector()
        db1 = DBCParser(self.dbc_path).db
        detector.set_database(db1)
        self.assertIs(detector.db, db1)
        self.assertIs(detector.decoder.db, db1)

        # Test setting a new database updates decoder simultaneously
        db2 = DBCDatabase()
        detector.set_database(db2)
        self.assertIs(detector.db, db2)
        self.assertIs(detector.decoder.db, db2)

        # Invalid type check
        with self.assertRaises(TypeError):
            detector.set_database("not_a_database")

    def test_process_log_file_handling(self):
        detector = AnomalyDetector()
        detector.load_dbc(self.dbc_path)

        # 1. Empty / invalid path
        with self.assertRaises(ValueError):
            detector.process_log("")

        # 2. Missing log file
        with self.assertRaises(FileNotFoundError):
            detector.process_log("missing_log.txt")

    def test_rule_state_isolation_between_instances(self):
        # Create two independent detectors
        d1 = AnomalyDetector()
        d2 = AnomalyDetector()

        self.assertEqual(len(d1.rules), 7)
        self.assertEqual(len(d2.rules), 7)

        # Ensure rule instances are unique objects
        self.assertIsNot(d1.rules[0], d2.rules[0])
        self.assertIsNot(d1.rules[1], d2.rules[1])

        # Mutate internal state on d1 rule
        d1.rules[0]._last_trigger_timestamp = 100.0
        self.assertEqual(d1.rules[0]._last_trigger_timestamp, 100.0)
        self.assertIsNone(d2.rules[0]._last_trigger_timestamp)

        # Test reset on d1 clears its state
        d1.reset()
        self.assertIsNone(d1.rules[0]._last_trigger_timestamp)


if __name__ == "__main__":
    unittest.main()
