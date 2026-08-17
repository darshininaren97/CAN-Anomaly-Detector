"""
detector.py
Coordinates DBC parsing, CAN frame parsing, signal decoding, signal history tracking,
and rule engine evaluation to detect contradictory signal and correlation anomalies.
"""

from typing import List, Optional
import os
from dbc_parser import DBCDatabase, DBCParser
from asc_parser import ASCParser, CANFrame
from signal_decoder import SignalDecoder
from signal_history import SignalHistory
from anomaly import Anomaly
from rules import BaseRule, create_all_rules


class AnomalyDetector:
    """
    Main engine for detecting CAN bus contradictory signals and correlation anomalies.
    """

    def __init__(
        self,
        db: Optional[DBCDatabase] = None,
        rules: Optional[List[BaseRule]] = None,
        max_history: int = 200,
        history_window_seconds: float = 5.0
    ):
        self.db: Optional[DBCDatabase] = db
        self.decoder = SignalDecoder(db)
        self.history = SignalHistory(
            max_history_per_signal=max_history,
            time_window_seconds=history_window_seconds
        )
        self.detected_anomalies: List[Anomaly] = []

        # Ensure isolated rule state per detector instance
        if rules is not None:
            self.rules: List[BaseRule] = list(rules)
            for rule in self.rules:
                rule.reset()
        else:
            self.rules = create_all_rules()

    def set_database(self, db: DBCDatabase):
        """
        Update DBC database definition and keep decoder in full synchronization.
        """
        if not isinstance(db, DBCDatabase):
            raise TypeError(f"Expected DBCDatabase instance, got {type(db).__name__}")
        self.db = db
        self.decoder.set_database(db)

    def load_dbc(self, dbc_path: str) -> DBCDatabase:
        """
        Parse and load DBC from file path with comprehensive safety and existence checks.
        
        :param dbc_path: Path to automotive DBC file
        :return: Parsed DBCDatabase instance
        """
        if not isinstance(dbc_path, str) or not dbc_path.strip():
            raise ValueError("Invalid DBC filepath provided.")
        if not os.path.exists(dbc_path):
            raise FileNotFoundError(f"DBC definition file not found at: {dbc_path}")

        parser = DBCParser()
        db = parser.parse(dbc_path)
        if db is None or not isinstance(db, DBCDatabase):
            raise ValueError(f"Failed to parse valid DBC database from: {dbc_path}")

        self.set_database(db)
        return db

    def reset(self):
        """Reset internal history, detected anomalies, and all rule states."""
        self.history.clear()
        self.detected_anomalies.clear()
        for rule in self.rules:
            rule.reset()

    def process_frame(self, frame: CANFrame) -> List[Anomaly]:
        """
        Process a single CAN frame through decoding, history update, and rule evaluation.
        
        :param frame: Timestamped CANFrame
        :return: List of Anomaly instances detected in this frame
        """
        if self.db is None:
            raise ValueError("DBC database must be loaded before processing frames.")

        msg_def = self.db.get_message_by_id(frame.can_id)
        if msg_def is None:
            # Message not recognized in DBC — ignored (belongs to other modules / unmapped)
            return []

        # Decode signals from payload
        decoded_signals = self.decoder.decode_frame(frame)
        if not decoded_signals:
            return []

        # Record decoded signals in temporal history
        self.history.record(frame, msg_def.name, decoded_signals)

        # Evaluate all rules against updated state
        frame_anomalies: List[Anomaly] = []
        for rule in self.rules:
            if not rule.is_enabled:
                continue
            anomaly = rule.evaluate(frame, decoded_signals, self.history)
            if anomaly is not None:
                frame_anomalies.append(anomaly)
                self.detected_anomalies.append(anomaly)

        return frame_anomalies

    def process_log(self, log_path: str) -> List[Anomaly]:
        """
        Stream and process an entire Vector ASC CAN log file with upfront DBC verification,
        file validation, and comprehensive error handling.
        
        :param log_path: Path to CAN.log.txt
        :return: List of all detected anomalies
        """
        # Validate that DBC is configured BEFORE opening the log file or resetting state
        if self.db is None:
            raise ValueError("DBC database must be set or loaded before processing a CAN log.")

        if not isinstance(log_path, str) or not log_path.strip():
            raise ValueError("Invalid CAN log filepath provided.")
        if not os.path.exists(log_path):
            raise FileNotFoundError(f"CAN log file not found at: {log_path}")

        self.reset()
        try:
            parser = ASCParser(log_path)
            for frame in parser.parse_frames():
                self.process_frame(frame)
        except (OSError, ValueError, TypeError) as e:
            raise RuntimeError(f"Error occurred while processing log file '{log_path}': {e}") from e

        return self.detected_anomalies
