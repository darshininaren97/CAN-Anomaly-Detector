"""Parser adapter for normalizing raw CAN log records into standardized Frame objects."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from timing_module.models import Frame

MAX_CAN_ID = 0x1FFFFFFF  # 29-bit extended CAN ID maximum


def normalize_can_id(val: Union[int, str]) -> Tuple[int, str]:
    """
    Normalize CAN ID from various representations (hex string, integer, decimal string)
    into a standardized (int_id, "0xHEX") tuple.

    Examples:
        0x464 -> (1124, "0x464")
        "0x464" -> (1124, "0x464")
        "464" (if hex-like) / 1124 -> (1124, "0x464")
        "1124" -> (1124, "0x464")
    """
    if isinstance(val, int):
        int_id = val
    elif isinstance(val, str):
        val_clean = val.strip()
        if val_clean.lower().startswith("0x"):
            int_id = int(val_clean, 16)
        elif any(c in "abcdefABCDEF" for c in val_clean):
            int_id = int(val_clean, 16)
        else:
            try:
                int_id = int(val_clean, 10)
            except ValueError:
                int_id = int(val_clean, 16)
    else:
        raise TypeError(f"Unsupported CAN ID type: {type(val)} (value: {val})")

    if not (0 <= int_id <= MAX_CAN_ID):
        raise ValueError(f"CAN ID out of valid range (0 to 0x{MAX_CAN_ID:X}): {int_id}")

    hex_id = f"0x{int_id:X}"
    return int_id, hex_id


def normalize_payload_data(val: Union[bytes, str, list, None]) -> str:
    """Normalize payload to uppercase hexadecimal string and validate characters."""
    if val is None:
        return ""
    if isinstance(val, bytes):
        return val.hex().upper()
    if isinstance(val, list):
        # List of integer byte values
        return "".join(f"{b:02X}" for b in val)
    if isinstance(val, str):
        val_clean = val.strip().replace(" ", "").replace("0x", "")
        # Validate hex characters
        if any(c not in "0123456789ABCDEFabcdef" for c in val_clean):
            raise ValueError(f"Invalid hexadecimal payload characters: {val}")
        return val_clean.upper()
    return str(val).upper()


class ParserAdapter:
    """
    Adapter to convert external CAN log dictionaries / JSON structures
    into normalized Frame instances with validation.
    """

    def __init__(self, key_mapping: Optional[Dict[str, str]] = None):
        """
        Initialize adapter with optional custom field name mapping.

        Default keys expected:
            timestamp -> 'timestamp'
            can_id -> 'can_id'
            data -> 'data'
            dlc -> 'dlc'
            ecu -> 'ecu'
        """
        self.key_mapping = {
            "timestamp": "timestamp",
            "can_id": "can_id",
            "data": "data",
            "dlc": "dlc",
            "ecu": "ecu",
        }
        if key_mapping:
            self.key_mapping.update(key_mapping)

    def normalize_record(self, record: Dict[str, Any]) -> Frame:
        """Convert a single record dictionary to a validated, normalized Frame."""
        if not isinstance(record, dict):
            raise TypeError(f"Expected dict record, got {type(record)}: {record}")

        ts_key = self.key_mapping["timestamp"]
        id_key = self.key_mapping["can_id"]
        data_key = self.key_mapping["data"]
        dlc_key = self.key_mapping["dlc"]
        ecu_key = self.key_mapping["ecu"]

        if ts_key not in record:
            raise KeyError(f"Record missing required timestamp key '{ts_key}': {record}")
        if id_key not in record:
            raise KeyError(f"Record missing required can_id key '{id_key}': {record}")

        try:
            timestamp = float(record[ts_key])
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid timestamp value '{record[ts_key]}': {e}") from e

        if timestamp < 0:
            raise ValueError(f"Timestamp cannot be negative: {timestamp}")

        can_id_int, can_id_hex = normalize_can_id(record[id_key])

        raw_data = record.get(data_key, "")
        data_hex = normalize_payload_data(raw_data)

        if dlc_key in record:
            dlc = int(record[dlc_key])
            if not (0 <= dlc <= 64):
                raise ValueError(f"DLC out of range (0-64): {dlc}")
        else:
            dlc = len(data_hex) // 2

        ecu = record.get(ecu_key)
        if ecu is not None:
            ecu = str(ecu).strip()
            if not ecu:
                ecu = None

        return Frame(
            timestamp=timestamp,
            can_id=can_id_int,
            can_id_hex=can_id_hex,
            data=data_hex,
            dlc=dlc,
            ecu=ecu,
        )

    def parse_records(self, records: Sequence[Dict[str, Any]]) -> List[Frame]:
        """Convert a sequence of record dictionaries to normalized Frame objects."""
        return [self.normalize_record(rec) for rec in records]

    def parse_json_file(self, file_path: Union[str, Path]) -> List[Frame]:
        """Load and parse a JSON file containing a list of CAN frame records."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"CAN log JSON file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                raise ValueError(f"Failed to decode JSON from {path}: {e}") from e

        if not isinstance(data, list):
            raise ValueError(f"Expected JSON array of frame objects in {path}, got {type(data)}")

        return self.parse_records(data)


# Module-level convenience functions
_default_adapter = ParserAdapter()


def normalize_frame(record: Dict[str, Any]) -> Frame:
    """Normalize a single frame dictionary using default adapter."""
    return _default_adapter.normalize_record(record)


def parse_records(records: Sequence[Dict[str, Any]]) -> List[Frame]:
    """Parse multiple frame dictionaries using default adapter."""
    return _default_adapter.parse_records(records)


def parse_json_file(file_path: Union[str, Path]) -> List[Frame]:
    """Parse a JSON file of frame dictionaries using default adapter."""
    return _default_adapter.parse_json_file(file_path)
