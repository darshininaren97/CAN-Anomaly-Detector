"""
tests/test_signal_history.py
Unit tests for SignalHistory validating:
1. Signal name collision protection across different CAN IDs / messages.
2. Time-window based retention vs sample count capping.
3. get_recent_history anchoring with as_of_timestamp.
4. Constructor parameter validation.
5. SignalObservation runtime type coercion and validation.
"""

import unittest
from asc_parser import CANFrame
from signal_decoder import DecodedSignal
from signal_history import SignalHistory, SignalObservation


class TestSignalHistory(unittest.TestCase):

    def test_constructor_validation(self):
        # 1. Invalid max_history_per_signal
        with self.assertRaises(ValueError):
            SignalHistory(max_history_per_signal=0)
        with self.assertRaises(ValueError):
            SignalHistory(max_history_per_signal=-10)
        with self.assertRaises(ValueError):
            SignalHistory(max_history_per_signal="invalid")

        # 2. Invalid time_window_seconds
        with self.assertRaises(ValueError):
            SignalHistory(time_window_seconds=0)
        with self.assertRaises(ValueError):
            SignalHistory(time_window_seconds=-5.0)
        with self.assertRaises(ValueError):
            SignalHistory(time_window_seconds="invalid")

    def test_signal_observation_runtime_type_coercion(self):
        obs = SignalObservation(
            timestamp="1.2345",      # string float
            value="45.67",           # string float
            raw_value="1234",        # string int
            can_id="416",            # string int
            message_name="VehicleSpeed",
            signal_name="Vehicle_Speed"
        )
        self.assertIsInstance(obs.timestamp, float)
        self.assertIsInstance(obs.value, float)
        self.assertIsInstance(obs.raw_value, int)
        self.assertIsInstance(obs.can_id, int)
        self.assertEqual(obs.raw_value, 1234)

    def test_signal_name_collision_protection(self):
        history = SignalHistory()

        # Two different messages (0x100 and 0x200) both defining a signal named "Status"
        f1 = CANFrame(timestamp=1.0, channel=1, can_id=0x100, direction="Rx", frame_type="d", dlc=8, data=b"")
        history.record(f1, "EngineMsg", {
            "Status": DecodedSignal(name="Status", raw_value=1, physical_value=1.0, unit="")
        })

        f2 = CANFrame(timestamp=1.5, channel=1, can_id=0x200, direction="Rx", frame_type="d", dlc=8, data=b"")
        history.record(f2, "TransmissionMsg", {
            "Status": DecodedSignal(name="Status", raw_value=3, physical_value=3.0, unit="")
        })

        # Explicit lookup by CAN ID
        obs_eng = history.get_latest("Status", can_id=0x100)
        obs_trans = history.get_latest("Status", can_id=0x200)

        self.assertIsNotNone(obs_eng)
        self.assertIsNotNone(obs_trans)
        self.assertEqual(obs_eng.value, 1.0)
        self.assertEqual(obs_eng.message_name, "EngineMsg")
        self.assertEqual(obs_trans.value, 3.0)
        self.assertEqual(obs_trans.message_name, "TransmissionMsg")

        # Explicit lookup by Message Name
        obs_eng_name = history.get_latest("Status", message_name="EngineMsg")
        self.assertEqual(obs_eng_name.value, 1.0)

        # Disjoint history lists
        hist_eng = history.get_history("Status", can_id=0x100)
        hist_trans = history.get_history("Status", can_id=0x200)
        self.assertEqual(len(hist_eng), 1)
        self.assertEqual(len(hist_trans), 1)

    def test_time_window_retention_high_frequency(self):
        # 1ms update rate over 3 seconds = 3000 samples
        history = SignalHistory(max_history_per_signal=5000, time_window_seconds=2.0)

        for i in range(3000):
            t = i * 0.001  # 0.000 to 2.999
            f = CANFrame(timestamp=t, channel=1, can_id=0x1A0, direction="Rx", frame_type="d", dlc=8, data=b"")
            history.record(f, "VehicleSpeed", {
                "Speed": DecodedSignal(name="Speed", raw_value=i, physical_value=float(i), unit="km/h")
            })

        # At t=2.999s with 2.0s time window, observations before t=0.999s should be pruned
        hist = history.get_history("Speed")
        self.assertGreater(len(hist), 1900)
        self.assertLessEqual(len(hist), 2050)
        self.assertGreaterEqual(hist[0].timestamp, 0.999 - 0.01)

    def test_get_recent_history_anchored_on_as_of_timestamp(self):
        history = SignalHistory(time_window_seconds=10.0)

        # Record Door_Status at t=1.0 and t=2.0 (does not update afterwards)
        for t in [1.0, 2.0]:
            f = CANFrame(timestamp=t, channel=1, can_id=0x1A0, direction="Rx", frame_type="d", dlc=8, data=b"")
            history.record(f, "VehicleSpeed", {
                "Door_Status": DecodedSignal(name="Door_Status", raw_value=0, physical_value=0.0, unit="")
            })

        # Query 1: as_of_timestamp = 2.5, duration = 1.0s -> window [1.5, 2.5] -> includes t=2.0
        recent_1 = history.get_recent_history("Door_Status", duration_seconds=1.0, as_of_timestamp=2.5)
        self.assertEqual(len(recent_1), 1)
        self.assertEqual(recent_1[0].timestamp, 2.0)

        # Query 2: as_of_timestamp = 8.0, duration = 1.0s -> window [7.0, 8.0] -> empty (Door_Status is stale)
        recent_2 = history.get_recent_history("Door_Status", duration_seconds=1.0, as_of_timestamp=8.0)
        self.assertEqual(len(recent_2), 0)


if __name__ == "__main__":
    unittest.main()
