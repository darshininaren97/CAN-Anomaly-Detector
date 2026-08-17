"""
tests/test_asc_parser.py
Unit tests for the ASCParser module.
"""

import unittest
import tempfile
import os
from asc_parser import ASCParser, CANFrame


class TestASCParser(unittest.TestCase):

    def setUp(self):
        self.asc_content = """begin asc log
date Thu Apr 15 00:00:00 2025
base hex timestamps absolute
internal events logged
// Test comment header
   0.000000 1  0C9  Rx  d 8  10 00 28 33 00 00 00 00
   0.100000 1  1A0  Rx  d 8  D0 07 00 00 00 00 00 00
   // Mid log comment
   4.023000 1  1B0  Rx  d 8  00 3C 00 00 00 00 00 00
   6.700000 1  0C9  Rx  d 0
end asc log
"""
        self.temp_file = tempfile.NamedTemporaryFile("w", delete=False, suffix=".log.txt", encoding="utf-8")
        self.temp_file.write(self.asc_content)
        self.temp_file.close()

    def tearDown(self):
        if os.path.exists(self.temp_file.name):
            os.remove(self.temp_file.name)

    def test_parse_frames(self):
        parser = ASCParser(self.temp_file.name)
        frames = parser.load_all_frames()

        self.assertEqual(len(frames), 4)

        # Frame 1
        f1 = frames[0]
        self.assertAlmostEqual(f1.timestamp, 0.000000)
        self.assertEqual(f1.channel, 1)
        self.assertEqual(f1.can_id, 0x0C9)
        self.assertEqual(f1.direction, "Rx")
        self.assertEqual(f1.dlc, 8)
        self.assertEqual(f1.data, bytes.fromhex("10 00 28 33 00 00 00 00"))

        # Frame 2
        f2 = frames[1]
        self.assertAlmostEqual(f2.timestamp, 0.100000)
        self.assertEqual(f2.can_id, 0x1A0)
        self.assertEqual(f2.data, bytes.fromhex("D0 07 00 00 00 00 00 00"))

        # Frame 3
        f3 = frames[2]
        self.assertAlmostEqual(f3.timestamp, 4.023000)
        self.assertEqual(f3.can_id, 0x1B0)
        self.assertEqual(f3.data, bytes.fromhex("00 3C 00 00 00 00 00 00"))

        # Frame 4 (DLC=0)
        f4 = frames[3]
        self.assertAlmostEqual(f4.timestamp, 6.700000)
        self.assertEqual(f4.can_id, 0x0C9)
        self.assertEqual(f4.dlc, 0)
        self.assertEqual(f4.data, b"")


if __name__ == "__main__":
    unittest.main()
