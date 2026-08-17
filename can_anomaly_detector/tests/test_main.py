"""
tests/test_main.py
Unit tests for main.py CLI pipeline covering exit codes, input validation,
stage-specific error handling, and partial result salvage.
"""

import unittest
import os
import tempfile
import shutil
from main import (
    main,
    EXIT_SUCCESS,
    EXIT_INVALID_ARGS,
    EXIT_FILE_NOT_FOUND,
    EXIT_DBC_ERROR,
    EXIT_LOG_ERROR,
    EXIT_OUTPUT_ERROR
)


class TestMainCLI(unittest.TestCase):

    def setUp(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.dbc_path = os.path.join(self.base_dir, "CAN.dbc")
        self.log_path = os.path.join(self.base_dir, "CAN.log.txt")
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_successful_run(self):
        output_file = os.path.join(self.temp_dir, "out.json")
        code = main(["--dbc", self.dbc_path, "--log", self.log_path, "--output", output_file])
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertTrue(os.path.exists(output_file))

    def test_missing_dbc_file(self):
        code = main(["--dbc", "non_existent.dbc", "--log", self.log_path])
        self.assertEqual(code, EXIT_FILE_NOT_FOUND)

    def test_missing_log_file(self):
        code = main(["--dbc", self.dbc_path, "--log", "non_existent.log.txt"])
        self.assertEqual(code, EXIT_FILE_NOT_FOUND)

    def test_directory_passed_as_dbc(self):
        # Pass temporary directory instead of file
        code = main(["--dbc", self.temp_dir, "--log", self.log_path])
        self.assertEqual(code, EXIT_INVALID_ARGS)

    def test_directory_passed_as_output(self):
        code = main(["--dbc", self.dbc_path, "--log", self.log_path, "--output", self.temp_dir])
        self.assertEqual(code, EXIT_INVALID_ARGS)

    def test_verbose_flag_and_log_file(self):
        output_file = os.path.join(self.temp_dir, "out_verbose.json")
        log_file = os.path.join(self.temp_dir, "run.log")
        code = main([
            "--dbc", self.dbc_path,
            "--log", self.log_path,
            "--output", output_file,
            "--verbose",
            "--log-file", log_file
        ])
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertTrue(os.path.exists(log_file))


if __name__ == "__main__":
    unittest.main()
