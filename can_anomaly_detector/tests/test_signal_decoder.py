"""
tests/test_signal_decoder.py
Unit tests for the SignalDecoder module.
"""

import unittest
from dbc_parser import CANSignalDef, CANMessageDef, DBCDatabase
from asc_parser import CANFrame
from signal_decoder import SignalDecoder


class TestSignalDecoder(unittest.TestCase):

    def setUp(self):
        self.decoder = SignalDecoder()

        # Build sample DBC database
        self.db = DBCDatabase()

        # EngineData
        msg_engine = CANMessageDef(id=0x0C9, raw_id=201, name="EngineData", dlc=8, transmitter="Engine_ECU")
        msg_engine.signals["Engine_RPM"] = CANSignalDef(
            name="Engine_RPM", start_bit=0, length=16, byte_order=1, is_signed=False,
            factor=0.25, offset=0.0, min_val=0.0, max_val=8000.0, unit="RPM"
        )
        msg_engine.signals["Coolant_Temp"] = CANSignalDef(
            name="Coolant_Temp", start_bit=16, length=8, byte_order=1, is_signed=False,
            factor=1.0, offset=-40.0, min_val=-40.0, max_val=215.0, unit="degC"
        )
        msg_engine.signals["Engine_Status"] = CANSignalDef(
            name="Engine_Status", start_bit=24, length=1, byte_order=1, is_signed=False,
            factor=1.0, offset=0.0, min_val=0.0, max_val=1.0, unit="",
            enums={0: "OFF", 1: "RUNNING"}
        )

        # VehicleSpeed
        msg_speed = CANMessageDef(id=0x1A0, raw_id=416, name="VehicleSpeed", dlc=8, transmitter="ABS_ECU")
        msg_speed.signals["Vehicle_Speed"] = CANSignalDef(
            name="Vehicle_Speed", start_bit=0, length=16, byte_order=1, is_signed=False,
            factor=0.01, offset=0.0, min_val=0.0, max_val=300.0, unit="km/h"
        )
        msg_speed.signals["Brake_Status"] = CANSignalDef(
            name="Brake_Status", start_bit=16, length=1, byte_order=1, is_signed=False,
            factor=1.0, offset=0.0, min_val=0.0, max_val=1.0, unit="",
            enums={0: "OFF", 1: "ON"}
        )
        msg_speed.signals["Wheel_Speed_FL"] = CANSignalDef(
            name="Wheel_Speed_FL", start_bit=19, length=13, byte_order=1, is_signed=False,
            factor=0.01, offset=0.0, min_val=0.0, max_val=300.0, unit="km/h"
        )
        msg_speed.signals["Wheel_Speed_FR"] = CANSignalDef(
            name="Wheel_Speed_FR", start_bit=32, length=13, byte_order=1, is_signed=False,
            factor=0.01, offset=0.0, min_val=0.0, max_val=300.0, unit="km/h"
        )

        # TransmissionData
        msg_trans = CANMessageDef(id=0x1B0, raw_id=432, name="TransmissionData", dlc=8, transmitter="Transmission_ECU")
        msg_trans.signals["Gear_Position"] = CANSignalDef(
            name="Gear_Position", start_bit=0, length=4, byte_order=1, is_signed=False,
            factor=1.0, offset=0.0, min_val=0.0, max_val=8.0, unit="",
            enums={0: "PARK", 1: "REVERSE", 2: "NEUTRAL", 3: "DRIVE"}
        )

        self.db.messages[0x0C9] = msg_engine
        self.db.messages[0x1A0] = msg_speed
        self.db.messages[0x1B0] = msg_trans
        self.decoder.set_database(self.db)

    def test_extract_intel_raw_values(self):
        # 0x2EE0 = 12000 -> 120.0 km/h
        data = bytes.fromhex("E0 2E 00 00 00 00 00 00")
        raw = SignalDecoder.extract_raw_value(data, start_bit=0, length=16, byte_order=1, is_signed=False)
        self.assertEqual(raw, 12000)

    def test_extract_motorola_with_boundaries(self):
        # Vector Motorola: start_bit=7 (MSB of byte 0), length=16 -> spans Byte 0 and Byte 1
        # Data: 0x12, 0x34 -> raw should be 0x1234 = 4660
        data = bytes([0x12, 0x34])
        raw = SignalDecoder.extract_raw_value(data, start_bit=7, length=16, byte_order=0, is_signed=False)
        self.assertEqual(raw, 0x1234)

        # Boundary test: length extending past payload should not crash
        raw_overflow = SignalDecoder.extract_raw_value(data, start_bit=7, length=32, byte_order=0, is_signed=False)
        self.assertIsInstance(raw_overflow, int)

    def test_enum_lookup_with_scaled_factor(self):
        # Signal with factor=0.5 and enum on integer raw values
        sig = CANSignalDef(
            name="TestMode", start_bit=0, length=8, byte_order=1, is_signed=False,
            factor=0.5, offset=0.0, min_val=0.0, max_val=100.0, unit="",
            enums={1: "MODE_A", 2: "MODE_B"}
        )
        data = bytes([0x01])  # raw=1, physical=0.5
        decoded = self.decoder.decode_signal(data, sig)
        self.assertEqual(decoded.raw_value, 1)
        self.assertEqual(decoded.physical_value, 0.5)
        self.assertEqual(decoded.enum_name, "MODE_A")

    def test_decode_vehicle_speed(self):
        data = bytes.fromhex("E0 2E 00 00 00 00 00 00")
        frame = CANFrame(timestamp=4.023, channel=1, can_id=0x1A0, direction="Rx", frame_type="d", dlc=8, data=data)
        decoded = self.decoder.decode_frame(frame)

        self.assertIn("Vehicle_Speed", decoded)
        self.assertAlmostEqual(decoded["Vehicle_Speed"].physical_value, 120.00)
        self.assertEqual(decoded["Vehicle_Speed"].unit, "km/h")

    def test_decode_gear_enums(self):
        # Gear = PARK (0)
        data = bytes.fromhex("00 3C 00 00 00 00 00 00")
        frame = CANFrame(timestamp=4.023, channel=1, can_id=0x1B0, direction="Rx", frame_type="d", dlc=8, data=data)
        decoded = self.decoder.decode_frame(frame)
        self.assertIn("Gear_Position", decoded)
        self.assertEqual(decoded["Gear_Position"].physical_value, 0)
        self.assertEqual(decoded["Gear_Position"].enum_name, "PARK")

        # Gear = DRIVE (3)
        data_drive = bytes.fromhex("03 3C 00 00 00 00 00 00")
        frame_drive = CANFrame(timestamp=1.0, channel=1, can_id=0x1B0, direction="Rx", frame_type="d", dlc=8, data=data_drive)
        decoded_drive = self.decoder.decode_frame(frame_drive)
        self.assertEqual(decoded_drive["Gear_Position"].physical_value, 3)
        self.assertEqual(decoded_drive["Gear_Position"].enum_name, "DRIVE")

    def test_decode_wheel_speeds(self):
        data = bytes([0x00, 0x00, 0x00, 0xFA, 0x00, 0x00, 0x00, 0x00])
        sig_fl = self.db.messages[0x1A0].signals["Wheel_Speed_FL"]
        decoded_fl = self.decoder.decode_signal(data, sig_fl)
        self.assertAlmostEqual(decoded_fl.physical_value, 80.00, places=1)


if __name__ == "__main__":
    unittest.main()
