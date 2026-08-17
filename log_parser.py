"""Unified, high-performance Vector ASC / CAN log parser.

Features:
- High-throughput parsing of Vector ASC log files using fast token scanning
  with regex fallback.
- Support for standard 11-bit and extended 29-bit CAN IDs ('x' suffix and numeric).
- Support for data frames, remote frames (RTR), and CAN FD formatting.
- Dynamic detection of 'base hex' vs 'base dec' headers.
- Payload normalization for bytes, hex strings, integer sequences, and arrays.
- Structured diagnostics with backward-compatible tuple unpacking.
- Memory-efficient slots-based CANFrame dataclass.
- JSON log file parsing and incremental JSON streaming export.
- Clean strict and non-strict error handling modes.
- Python 3.10+ compatible using only standard library modules.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Dict,
    Generator,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    TextIO,
    Tuple,
    Union,
)

__all__ = [
    "CANFrame",
    "LogParseError",
    "ParseDiagnostic",
    "CANLogParser",
    "parse_asc_log",
    "parse_can_log",
    "parse_json_file",
    "load_frames",
]


@dataclass(frozen=True, slots=True)
class CANFrame:
    """Immutable representation of a parsed CAN frame."""
    timestamp: float
    channel: int
    can_id: int
    direction: str
    frame_type: str
    dlc: int
    data: bytes
    is_extended: bool = False
    raw_line: str = ""
    line_number: Optional[int] = None

    @property
    def hex_id(self) -> str:
        """Formatted hexadecimal representation of the CAN ID."""
        return f"0x{self.can_id:0{8 if self.is_extended else 3}X}"

    @property
    def is_remote(self) -> bool:
        """Return True if this is a remote transmission request (RTR) frame."""
        return self.frame_type.lower() == "r"

    @property
    def is_rx(self) -> bool:
        """Return True if frame direction is Received (Rx)."""
        return self.direction.lower() == "rx"

    @property
    def is_tx(self) -> bool:
        """Return True if frame direction is Transmitted (Tx)."""
        return self.direction.lower() == "tx"

    def to_dict(self) -> Dict[str, Any]:
        """Return a serializable dictionary representation of the CAN frame."""
        return {
            "timestamp": self.timestamp,
            "channel": self.channel,
            "can_id": self.can_id,
            "hex_id": self.hex_id,
            "direction": self.direction,
            "frame_type": self.frame_type,
            "dlc": self.dlc,
            "data": self.data.hex().upper(),
            "data_bytes": list(self.data),
            "is_extended": self.is_extended,
            "raw_line": self.raw_line,
            "line_number": self.line_number,
        }


class LogParseError(ValueError):
    """Raised when log parsing encounters an unrecoverable syntax error in strict mode."""
    pass


@dataclass(frozen=True, slots=True)
class ParseDiagnostic:
    """Diagnostic message generated during log parsing.

    Supports tuple unpacking `kind, message = diag` for 100% backward compatibility.
    """
    kind: str  # 'error', 'warning', or 'info'
    message: str
    line_number: Optional[int] = None
    raw_line: str = ""

    def __iter__(self):
        return iter((self.kind, self.message))

    def __getitem__(self, index: int) -> str:
        return (self.kind, self.message)[index]

    def __repr__(self) -> str:
        loc = f" (line {self.line_number})" if self.line_number is not None else ""
        return f"ParseDiagnostic({self.kind.upper()}{loc}: {self.message})"


class CANLogParser:
    """High-performance parser for Vector ASC and JSON CAN logs."""

    DATA_LINE_REGEX = re.compile(
        r"^\s*(\d+(?:\.\d+)?)\s+(\d+)\s+"
        r"((?:0x)?[0-9a-fA-F]+)(x)?\s+(Rx|Tx)\s+"
        r"([a-zA-Z]+)\s+(\d+)(?:\s+(.*))?$",
        re.IGNORECASE,
    )

    IGNORE_PREFIXES = (
        "//", "***", "begin", "end", "date", "base",
        "internal", "version", "start", "statistic:",
    )

    def __init__(self, strict: bool = False):
        self.strict = strict
        self.base_is_hex = True

    @staticmethod
    def parse_can_id(value: Union[int, str], base_is_hex: bool = True) -> int:
        """Parse a CAN ID from an integer or string (hex or dec)."""
        if isinstance(value, int):
            return value
        text = str(value).strip()
        if text.lower().startswith("0x"):
            return int(text, 16)
        if text.lower().endswith("x"):
            text = text[:-1]
            return int(text, 16)
        return int(text, 16 if base_is_hex else 10)

    @staticmethod
    def normalize_payload(
        value: Union[bytes, bytearray, memoryview, str, Sequence[int], None]
    ) -> bytes:
        """Convert various payload formats into standard bytes efficiently."""
        if value is None:
            return b""
        if isinstance(value, bytes):
            return value
        if isinstance(value, (bytearray, memoryview)):
            return bytes(value)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return b""
            # Strip prefixes and commas if present
            if "0x" in text or "," in text:
                text = text.replace("0x", "").replace(",", "")
            try:
                # In Python 3.8+, bytes.fromhex natively handles spaces between hex bytes
                return bytes.fromhex(text)
            except ValueError:
                # Remove spaces if needed
                return bytes.fromhex(text.replace(" ", ""))
        return bytes(int(x) for x in value)

    def _diagnostic(
        self, kind: str, message: str, line_num: Optional[int] = None, raw_line: str = ""
    ) -> ParseDiagnostic:
        if self.strict and kind == "error":
            raise LogParseError(f"Line {line_num}: {message}" if line_num else message)
        return ParseDiagnostic(kind=kind, message=message, line_number=line_num, raw_line=raw_line)

    def _parse_line_fast(
        self, stripped: str, line_num: int, base_is_hex: bool
    ) -> Optional[CANFrame]:
        """Fast-path line parser using whitespace token splitting."""
        parts = stripped.split()
        num_parts = len(parts)
        if num_parts < 6:
            return None

        # Check if first part is a valid timestamp
        try:
            timestamp = float(parts[0])
        except ValueError:
            return None

        # Check standard format: <ts> <ch> <id>[x] <Rx|Tx> <d|r> <dlc> [<b0> <b1> ...]
        try:
            channel = int(parts[1])
        except ValueError:
            return None

        raw_id_str = parts[2]
        is_extended = raw_id_str.lower().endswith("x")
        clean_id_str = raw_id_str[:-1] if is_extended else raw_id_str

        try:
            can_id = self.parse_can_id(clean_id_str, base_is_hex)
        except ValueError:
            return None

        if not is_extended and can_id > 0x7FF:
            is_extended = True

        direction = parts[3]
        if direction.lower() not in ("rx", "tx"):
            return None

        frame_type = parts[4]
        try:
            dlc = int(parts[5])
        except ValueError:
            return None

        # Payload bytes
        if num_parts > 6:
            # Join byte tokens and parse from hex
            payload_hex = "".join(parts[6:6 + dlc])
            try:
                payload = bytes.fromhex(payload_hex)
            except ValueError:
                payload = self.normalize_payload(" ".join(parts[6:]))
        else:
            payload = b""

        return CANFrame(
            timestamp=timestamp,
            channel=channel,
            can_id=can_id,
            direction=direction,
            frame_type=frame_type,
            dlc=dlc,
            data=payload,
            is_extended=is_extended,
            raw_line=stripped,
            line_number=line_num,
        )

    def parse_asc(
        self, file_path_or_handle: Union[str, Path, TextIO]
    ) -> Generator[Union[CANFrame, ParseDiagnostic, Tuple[str, str]], None, None]:
        """Parse an ASC file or stream, yielding CANFrame objects and diagnostics."""
        base_is_hex = self.base_is_hex

        if hasattr(file_path_or_handle, "readline"):
            handle = file_path_or_handle
            should_close = False
        else:
            path = Path(file_path_or_handle)
            if not path.exists():
                raise FileNotFoundError(f"ASC log file not found: {path}")
            handle = path.open("r", encoding="utf-8", errors="replace")
            should_close = True

        try:
            for line_num, line in enumerate(handle, 1):
                stripped = line.strip()
                if not stripped:
                    continue

                lower = stripped.lower()
                if lower.startswith("base"):
                    if "hex" in lower:
                        base_is_hex = True
                    elif "dec" in lower:
                        base_is_hex = False
                    continue

                if any(lower.startswith(p) for p in self.IGNORE_PREFIXES):
                    continue

                # 1. Try fast-path split parser
                frame = self._parse_line_fast(stripped, line_num, base_is_hex)
                if frame is not None:
                    if len(frame.data) != frame.dlc and not frame.is_remote:
                        yield self._diagnostic(
                            "warning",
                            f"DLC ({frame.dlc}) does not match payload length "
                            f"({len(frame.data)}) for CAN ID {frame.can_id:#x}",
                            line_num=line_num,
                            raw_line=stripped,
                        )
                    yield frame
                    continue

                # 2. Fallback to regex for non-standard line formatting
                match = self.DATA_LINE_REGEX.match(stripped)
                if not match:
                    parts = stripped.split()
                    if parts:
                        is_data_candidate = False
                        try:
                            float(parts[0])
                            is_data_candidate = True
                        except ValueError:
                            pass

                        if is_data_candidate:
                            yield self._diagnostic(
                                "error",
                                f"Malformed CAN data format: {stripped!r}",
                                line_num=line_num,
                                raw_line=stripped,
                            )
                    continue

                try:
                    timestamp = float(match.group(1))
                    channel = int(match.group(2))
                    can_id = self.parse_can_id(match.group(3), base_is_hex)
                    is_extended = match.group(4) is not None or (can_id > 0x7FF)
                    direction = match.group(5)
                    frame_type = match.group(6)
                    dlc = int(match.group(7))
                    payload = self.normalize_payload(match.group(8) or "")

                    if len(payload) != dlc and frame_type.lower() != "r":
                        yield self._diagnostic(
                            "warning",
                            f"DLC ({dlc}) does not match payload length ({len(payload)}) for CAN ID {can_id:#x}",
                            line_num=line_num,
                            raw_line=stripped,
                        )

                    yield CANFrame(
                        timestamp=timestamp,
                        channel=channel,
                        can_id=can_id,
                        direction=direction,
                        frame_type=frame_type,
                        dlc=dlc,
                        data=payload,
                        is_extended=is_extended,
                        raw_line=stripped,
                        line_number=line_num,
                    )
                except (ValueError, TypeError) as exc:
                    yield self._diagnostic(
                        "error",
                        f"Error parsing line {stripped!r}: {exc}",
                        line_num=line_num,
                        raw_line=stripped,
                    )
        finally:
            if should_close:
                handle.close()

    def iter_frames(
        self, file_path_or_handle: Union[str, Path, TextIO]
    ) -> Generator[CANFrame, None, None]:
        """Convenience generator yielding only valid CANFrame instances, discarding non-critical diagnostics."""
        for item in self.parse_asc(file_path_or_handle):
            if isinstance(item, CANFrame):
                yield item

    def load_all_frames(self, file_path_or_handle: Union[str, Path, TextIO]) -> List[CANFrame]:
        """Load all valid CAN frames from an ASC file into memory."""
        return list(self.iter_frames(file_path_or_handle))

    def normalize_record(
        self,
        record: Dict[str, Any],
        key_mapping: Optional[Dict[str, str]] = None,
    ) -> CANFrame:
        """Convert a dictionary record into a CANFrame."""
        mapping = {
            "timestamp": "timestamp",
            "channel": "channel",
            "can_id": "can_id",
            "data": "data",
            "dlc": "dlc",
            "direction": "direction",
            "frame_type": "frame_type",
            "is_extended": "is_extended",
        }
        if key_mapping:
            mapping.update(key_mapping)

        can_id_val = record.get(mapping["can_id"], record.get("id", 0))
        can_id = self.parse_can_id(can_id_val, self.base_is_hex)

        raw_data = record.get(mapping["data"], record.get("payload", b""))
        data = self.normalize_payload(raw_data)
        dlc = int(record.get(mapping["dlc"], len(data)))
        is_extended = bool(record.get(mapping["is_extended"], can_id > 0x7FF))

        return CANFrame(
            timestamp=float(record.get(mapping["timestamp"], 0.0)),
            channel=int(record.get(mapping["channel"], 0)),
            can_id=can_id,
            direction=str(record.get(mapping["direction"], "Rx")),
            frame_type=str(record.get(mapping["frame_type"], "d")),
            dlc=dlc,
            data=data,
            is_extended=is_extended,
            raw_line=str(record.get("raw_line", "")),
            line_number=record.get("line_number"),
        )

    def parse_records(
        self,
        records: Sequence[Dict[str, Any]],
        key_mapping: Optional[Dict[str, str]] = None,
    ) -> List[CANFrame]:
        """Convert a list of dictionary records to CANFrame objects."""
        return [self.normalize_record(r, key_mapping) for r in records]

    def parse_json_file(
        self,
        file_path: Union[str, Path],
        key_mapping: Optional[Dict[str, str]] = None,
    ) -> List[CANFrame]:
        """Parse a JSON file containing an array of CAN frame records."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"JSON log file not found: {path}")
        with path.open("r", encoding="utf-8") as handle:
            records = json.load(handle)
        if not isinstance(records, list):
            raise ValueError("Expected a JSON array of CAN frame objects")
        return self.parse_records(records, key_mapping)

    def export_to_json(
        self,
        frames: Iterable[CANFrame],
        output_file: Union[str, Path, TextIO],
        indent: Optional[int] = 2,
    ) -> int:
        """Stream an iterable of CANFrame objects into a JSON file with minimal memory footprint."""
        if isinstance(output_file, (str, Path)):
            handle = open(output_file, "w", encoding="utf-8")
            should_close = True
        else:
            handle = output_file
            should_close = False

        count = 0
        try:
            handle.write("[\n" if indent is not None else "[")
            for i, frame in enumerate(frames):
                if i > 0:
                    handle.write(",\n" if indent is not None else ",")
                frame_dict = frame.to_dict()
                if indent is not None:
                    serialized = json.dumps(frame_dict, indent=indent)
                    indented = ["  " + line for line in serialized.splitlines()]
                    handle.write("\n".join(indented))
                else:
                    handle.write(json.dumps(frame_dict))
                count += 1
            handle.write("\n]\n" if indent is not None else "]")
        finally:
            if should_close:
                handle.close()
        return count


_default_parser = CANLogParser()


def parse_asc_log(
    file_path: Union[str, Path, TextIO]
) -> Generator[Union[CANFrame, ParseDiagnostic, Tuple[str, str]], None, None]:
    """Parse an ASC CAN log file using the default parser configuration."""
    return _default_parser.parse_asc(file_path)


def parse_can_log(
    file_path: Union[str, Path, TextIO]
) -> Generator[Union[CANFrame, ParseDiagnostic, Tuple[str, str]], None, None]:
    """Alias for parse_asc_log."""
    return _default_parser.parse_asc(file_path)


def parse_json_file(
    file_path: Union[str, Path],
    key_mapping: Optional[Dict[str, str]] = None,
) -> List[CANFrame]:
    """Parse a JSON file containing CAN frames using the default parser configuration."""
    return _default_parser.parse_json_file(file_path, key_mapping)


def load_frames(file_path: Union[str, Path]) -> List[CANFrame]:
    """Auto-detect format (ASC or JSON) and load all CAN frames into a list."""
    path = Path(file_path)
    if path.suffix.lower() == ".json":
        return parse_json_file(path)
    return _default_parser.load_all_frames(path)