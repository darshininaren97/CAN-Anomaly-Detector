"""
tests/test_dbc_parser.py
Unit tests for the DBCParser module.
"""

import unittest
import tempfile
import os
from dbc_parser import DBCParser, CANSignalDef, CANMessageDef


class TestDBCParser(unittest.TestCase):

    def setUp(self):
        self.dbc_content = """
VERSION ""
NS_ :
BS_:
BU_: Engine_ECU ABS_ECU Transmission_ECU

BO_ 201 EngineData: 8 Engine_ECU
 SG_ Engine_RPM : 0|16@1+ (0.25,0) [0|8000] "RPM" Vector__XXX
 SG_ Coolant_Temp : 16|8@1+ (1,-40) [-40|215] "degC" Vector__XXX
 SG_ Engine_Status : 24|1@1+ (1,0) [0|1] "" Vector__XXX

BO_ 416 VehicleSpeed: 8 ABS_ECU
 SG_ Vehicle_Speed : 0|16@1+ (0.01,0) [0|300] "km/h" Vector__XXX
 SG_ Brake_Status : 16|1@1+ (1,0) [0|1] "" Vector__XXX
 SG_ Wheel_Speed_FL : 19|13@1+ (0.01,0) [0|300] "km/h" Vector__XXX
 SG_ Wheel_Speed_FR : 32|13@1+ (0.01,0) [0|300] "km/h" Vector__XXX

BO_ 432 TransmissionData: 8 Transmission_ECU
 SG_ Gear_Position : 0|4@1+ (1,0) [0|8] "" Vector__XXX

VAL_ 201 Engine_Status 0 "OFF" 1 "RUNNING" ;
VAL_ 416 Brake_Status 0 "OFF" 1 "ON" ;
VAL_ 432 Gear_Position 0 "PARK" 1 "REVERSE" 2 "NEUTRAL" 3 "DRIVE" ;

CM_ SG_ 201 Engine_RPM "Engine speed in RPM";
CM_ BO_ 201 "Engine data frame";
"""
        self.temp_file = tempfile.NamedTemporaryFile("w", delete=False, suffix=".dbc", encoding="utf-8")
        self.temp_file.write(self.dbc_content)
        self.temp_file.close()

    def tearDown(self):
        if os.path.exists(self.temp_file.name):
            os.remove(self.temp_file.name)

    def test_parse_messages(self):
        parser = DBCParser(self.temp_file.name)
        db = parser.db

        self.assertEqual(len(db.messages), 3)
        self.assertIn(201, db.messages)
        self.assertIn(416, db.messages)
        self.assertIn(432, db.messages)

        # Lookup by ID
        msg_engine = db.get_message_by_id(201)
        self.assertIsNotNone(msg_engine)
        self.assertEqual(msg_engine.name, "EngineData")
        self.assertEqual(msg_engine.dlc, 8)
        self.assertEqual(msg_engine.transmitter, "Engine_ECU")
        self.assertEqual(msg_engine.hex_id, "0x0C9")

        # Lookup by name
        msg_speed = db.get_message_by_name("VehicleSpeed")
        self.assertIsNotNone(msg_speed)
        self.assertEqual(msg_speed.id, 416)

    def test_parse_signals(self):
        parser = DBCParser(self.temp_file.name)
        db = parser.db
        msg = db.get_message_by_id(201)

        self.assertIn("Engine_RPM", msg.signals)
        rpm_sig = msg.signals["Engine_RPM"]
        self.assertEqual(rpm_sig.start_bit, 0)
        self.assertEqual(rpm_sig.length, 16)
        self.assertEqual(rpm_sig.byte_order, 1)
        self.assertFalse(rpm_sig.is_signed)
        self.assertEqual(rpm_sig.factor, 0.25)
        self.assertEqual(rpm_sig.offset, 0.0)
        self.assertEqual(rpm_sig.min_val, 0.0)
        self.assertEqual(rpm_sig.max_val, 8000.0)
        self.assertEqual(rpm_sig.unit, "RPM")

        temp_sig = msg.signals["Coolant_Temp"]
        self.assertEqual(temp_sig.factor, 1.0)
        self.assertEqual(temp_sig.offset, -40.0)
        self.assertEqual(temp_sig.unit, "degC")

    def test_val_table_enums(self):
        parser = DBCParser(self.temp_file.name)
        db = parser.db

        gear_sig = db.get_message_by_id(432).signals["Gear_Position"]
        self.assertEqual(gear_sig.enums[0], "PARK")
        self.assertEqual(gear_sig.enums[1], "REVERSE")
        self.assertEqual(gear_sig.enums[2], "NEUTRAL")
        self.assertEqual(gear_sig.enums[3], "DRIVE")

        eng_sig = db.get_message_by_id(201).signals["Engine_Status"]
        self.assertEqual(eng_sig.enums[0], "OFF")
        self.assertEqual(eng_sig.enums[1], "RUNNING")


if __name__ == "__main__":
    unittest.main()
