"""
tests/test_rules.py
Unit tests for anomaly detection rules R-001 through R-007.
Tests both positive detection conditions and normal negative baseline conditions.
"""

import unittest
from asc_parser import CANFrame
from signal_decoder import DecodedSignal
from signal_history import SignalHistory
from anomaly import AnomalyType
from rules import (
    Rule001, Rule002, Rule003, Rule004, Rule005, Rule006, Rule007
)


class TestRules(unittest.TestCase):

    def setUp(self):
        self.history = SignalHistory()

    def test_r001_positive_moving_while_engine_off(self):
        rule = Rule001(speed_threshold=0.5)

        # 1. Record Engine_Status = OFF (0) at t=4.0
        f_engine = CANFrame(timestamp=4.0, channel=1, can_id=0x0C9, direction="Rx", frame_type="d", dlc=8, data=b"")
        self.history.record(f_engine, "EngineData", {
            "Engine_Status": DecodedSignal("Engine_Status", raw_value=0, physical_value=0.0, unit="", enum_name="OFF")
        })

        # 2. Record Vehicle_Speed = 120.0 km/h at t=4.0
        f_speed = CANFrame(timestamp=4.0, channel=1, can_id=0x1A0, direction="Rx", frame_type="d", dlc=8, data=b"")
        decoded_speed = {
            "Vehicle_Speed": DecodedSignal("Vehicle_Speed", raw_value=12000, physical_value=120.0, unit="km/h")
        }
        self.history.record(f_speed, "VehicleSpeed", decoded_speed)

        # Evaluate rule
        anomaly = rule.evaluate(f_speed, decoded_speed, self.history)
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly.rule_id, "R-001")
        self.assertEqual(anomaly.anomaly_type, AnomalyType.CONTRADICTORY_SIGNAL.value)
        self.assertEqual(anomaly.values["Vehicle_Speed"], 120.0)
        self.assertEqual(anomaly.values["Engine_Status"], 0)

    def test_r001_negative_moving_while_engine_running(self):
        rule = Rule001(speed_threshold=0.5)

        # Record Engine_Status = RUNNING (1)
        f_engine = CANFrame(timestamp=1.0, channel=1, can_id=0x0C9, direction="Rx", frame_type="d", dlc=8, data=b"")
        self.history.record(f_engine, "EngineData", {
            "Engine_Status": DecodedSignal("Engine_Status", raw_value=1, physical_value=1.0, unit="", enum_name="RUNNING")
        })

        # Record Vehicle_Speed = 50.0 km/h
        f_speed = CANFrame(timestamp=1.0, channel=1, can_id=0x1A0, direction="Rx", frame_type="d", dlc=8, data=b"")
        decoded_speed = {
            "Vehicle_Speed": DecodedSignal("Vehicle_Speed", raw_value=5000, physical_value=50.0, unit="km/h")
        }
        self.history.record(f_speed, "VehicleSpeed", decoded_speed)

        anomaly = rule.evaluate(f_speed, decoded_speed, self.history)
        self.assertIsNone(anomaly)

    def test_r001_negative_stopped_while_engine_off(self):
        rule = Rule001(speed_threshold=0.5)

        # Record Engine_Status = OFF (0), Speed = 0.0 km/h
        f_frame = CANFrame(timestamp=0.0, channel=1, can_id=0x0C9, direction="Rx", frame_type="d", dlc=8, data=b"")
        self.history.record(f_frame, "EngineData", {
            "Engine_Status": DecodedSignal("Engine_Status", raw_value=0, physical_value=0.0, unit="", enum_name="OFF")
        })
        self.history.record(f_frame, "VehicleSpeed", {
            "Vehicle_Speed": DecodedSignal("Vehicle_Speed", raw_value=0, physical_value=0.0, unit="km/h")
        })

        anomaly = rule.evaluate(f_frame, {"Engine_Status": DecodedSignal("Engine_Status", 0, 0.0, "")}, self.history)
        self.assertIsNone(anomaly)

    def test_r002_positive_moving_while_gear_park(self):
        rule = Rule002(speed_threshold=0.5)

        # 1. Record Gear_Position = PARK (0) at t=4.0
        f_gear = CANFrame(timestamp=4.0, channel=1, can_id=0x1B0, direction="Rx", frame_type="d", dlc=8, data=b"")
        self.history.record(f_gear, "TransmissionData", {
            "Gear_Position": DecodedSignal("Gear_Position", raw_value=0, physical_value=0.0, unit="", enum_name="PARK")
        })

        # 2. Record Vehicle_Speed = 120.0 km/h at t=4.0
        f_speed = CANFrame(timestamp=4.0, channel=1, can_id=0x1A0, direction="Rx", frame_type="d", dlc=8, data=b"")
        decoded_speed = {
            "Vehicle_Speed": DecodedSignal("Vehicle_Speed", raw_value=12000, physical_value=120.0, unit="km/h")
        }
        self.history.record(f_speed, "VehicleSpeed", decoded_speed)

        anomaly = rule.evaluate(f_speed, decoded_speed, self.history)
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly.rule_id, "R-002")
        self.assertEqual(anomaly.anomaly_type, AnomalyType.CONTRADICTORY_SIGNAL.value)
        self.assertEqual(anomaly.values["Gear_Position"], 0)
        self.assertEqual(anomaly.values["Vehicle_Speed"], 120.0)

    def test_r002_negative_moving_while_gear_drive(self):
        rule = Rule002(speed_threshold=0.5)

        # Record Gear_Position = DRIVE (3)
        f_gear = CANFrame(timestamp=1.0, channel=1, can_id=0x1B0, direction="Rx", frame_type="d", dlc=8, data=b"")
        self.history.record(f_gear, "TransmissionData", {
            "Gear_Position": DecodedSignal("Gear_Position", raw_value=3, physical_value=3.0, unit="", enum_name="DRIVE")
        })

        f_speed = CANFrame(timestamp=1.0, channel=1, can_id=0x1A0, direction="Rx", frame_type="d", dlc=8, data=b"")
        decoded_speed = {
            "Vehicle_Speed": DecodedSignal("Vehicle_Speed", raw_value=8000, physical_value=80.0, unit="km/h")
        }
        self.history.record(f_speed, "VehicleSpeed", decoded_speed)

        anomaly = rule.evaluate(f_speed, decoded_speed, self.history)
        self.assertIsNone(anomaly)

    def test_r003_r004_r005_framework(self):
        r3 = Rule003()
        r4 = Rule004()
        r5 = Rule005()

        f = CANFrame(timestamp=1.0, channel=1, can_id=0x1A0, direction="Rx", frame_type="d", dlc=8, data=b"")
        # By default, disabled and returns None without official spec
        self.assertFalse(r3.is_enabled)
        self.assertFalse(r4.is_enabled)
        self.assertFalse(r5.is_enabled)
        self.assertIsNone(r3.evaluate(f, {}, self.history))
        self.assertIsNone(r4.evaluate(f, {}, self.history))
        self.assertIsNone(r5.evaluate(f, {}, self.history))

    def test_r006_positive_wheel_speed_divergence(self):
        rule = Rule006(max_speed_diff_kmh=15.0, min_evaluation_speed_kmh=5.0)

        # Vehicle is at 100 km/h, but FL is at 100 km/h and FR is at 40 km/h (diff = 60 km/h > 15)
        f = CANFrame(timestamp=2.0, channel=1, can_id=0x1A0, direction="Rx", frame_type="d", dlc=8, data=b"")
        decoded = {
            "Vehicle_Speed": DecodedSignal("Vehicle_Speed", 10000, 100.0, "km/h"),
            "Wheel_Speed_FL": DecodedSignal("Wheel_Speed_FL", 10000, 100.0, "km/h"),
            "Wheel_Speed_FR": DecodedSignal("Wheel_Speed_FR", 4000, 40.0, "km/h")
        }
        self.history.record(f, "VehicleSpeed", decoded)

        anomaly = rule.evaluate(f, decoded, self.history)
        self.assertIsNotNone(anomaly)
        self.assertEqual(anomaly.rule_id, "R-006")
        self.assertEqual(anomaly.anomaly_type, AnomalyType.SIGNAL_CORRELATION.value)
        self.assertEqual(anomaly.values["Vehicle_Speed"], 100.0)
        self.assertEqual(anomaly.values["Wheel_Speed_FR"], 40.0)

    def test_r006_negative_correlated_wheel_speeds(self):
        rule = Rule006(max_speed_diff_kmh=15.0)

        f = CANFrame(timestamp=2.0, channel=1, can_id=0x1A0, direction="Rx", frame_type="d", dlc=8, data=b"")
        decoded = {
            "Vehicle_Speed": DecodedSignal("Vehicle_Speed", 8000, 80.0, "km/h"),
            "Wheel_Speed_FL": DecodedSignal("Wheel_Speed_FL", 8020, 80.2, "km/h"),
            "Wheel_Speed_FR": DecodedSignal("Wheel_Speed_FR", 7980, 79.8, "km/h")
        }
        self.history.record(f, "VehicleSpeed", decoded)

        anomaly = rule.evaluate(f, decoded, self.history)
        self.assertIsNone(anomaly)

    def test_r007_positive_accelerating_while_brake_on(self):
        rule = Rule007(
            time_window_seconds=0.5,
            min_speed_increase_kmh=5.0,
            min_acceleration_rate_kmh_s=10.0,
            min_observations=3
        )

        # Simulate vehicle accelerating from 20 km/h to 50 km/h in 0.3s while Brake_Status == 1
        timestamps = [1.0, 1.1, 1.2, 1.3]
        speeds = [20.0, 30.0, 40.0, 50.0]

        last_anomaly = None
        for t, s in zip(timestamps, speeds):
            f = CANFrame(timestamp=t, channel=1, can_id=0x1A0, direction="Rx", frame_type="d", dlc=8, data=b"")
            decoded = {
                "Vehicle_Speed": DecodedSignal("Vehicle_Speed", int(s * 100), s, "km/h"),
                "Brake_Status": DecodedSignal("Brake_Status", 1, 1.0, "", enum_name="ON")
            }
            self.history.record(f, "VehicleSpeed", decoded)
            last_anomaly = rule.evaluate(f, decoded, self.history)

        self.assertIsNotNone(last_anomaly)
        self.assertEqual(last_anomaly.rule_id, "R-007")
        self.assertEqual(last_anomaly.anomaly_type, AnomalyType.SIGNAL_CORRELATION.value)
        self.assertEqual(last_anomaly.values["Brake_Status"], 1)

    def test_r007_negative_decelerating_while_brake_on(self):
        rule = Rule007()

        # Decelerating from 60 to 30 km/h while Brake is ON
        timestamps = [1.0, 1.1, 1.2, 1.3]
        speeds = [60.0, 50.0, 40.0, 30.0]

        for t, s in zip(timestamps, speeds):
            f = CANFrame(timestamp=t, channel=1, can_id=0x1A0, direction="Rx", frame_type="d", dlc=8, data=b"")
            decoded = {
                "Vehicle_Speed": DecodedSignal("Vehicle_Speed", int(s * 100), s, "km/h"),
                "Brake_Status": DecodedSignal("Brake_Status", 1, 1.0, "", enum_name="ON")
            }
            self.history.record(f, "VehicleSpeed", decoded)
            anomaly = rule.evaluate(f, decoded, self.history)
            self.assertIsNone(anomaly)


if __name__ == "__main__":
    unittest.main()
