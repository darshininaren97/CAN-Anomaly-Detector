"""Unified, high-performance DBC parser and CAN signal decoder.

Features:
- Full DBC parsing (BO_, SG_, VAL_, CM_, VERSION, global VAL_TABLE_).
- Multi-line DBC comments and multi-line value enum tables.
- O(1) integer-arithmetic bit extraction for both Intel (little-endian)
  and Motorola (big-endian/sequential) signals.
- Signed and unsigned signal scaling and offset calculation.
- Multiplexing support (standard multiplexers and multiplexed signals).
- Duplicate message ID and duplicate signal detection.
- Fast streaming JSON output for massive CAN logs with O(1) memory overhead.
- Clean, robust error handling with strict and non-strict modes.
- Python 3.10+ compatible using only standard library modules.
"""
from __future__ import annotations

import io
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Callable,
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
    "CANSignalDef",
    "CANMessageDef",
    "DBCDatabase",
    "DBCParser",
    "DBCDecoder",
    "DBCError",
    "DBCParseError",
    "DBCDecodeError",
    "StreamingJSONWriter",
    "parse_dbc_file",
    "decode_frames",
    "decode_file",
]


class DBCError(Exception):
    """Base exception for DBC errors."""
    pass


class DBCParseError(DBCError, ValueError):
    """Raised when parsing a DBC file fails due to invalid syntax or duplicates."""
    pass


class DBCDecodeError(DBCError, ValueError):
    """Raised when decoding a CAN frame fails in strict mode."""
    pass


@dataclass(frozen=True, slots=True)
class CANSignalDef:
    """Definition of a CAN signal within a DBC message."""
    name: str
    start_bit: int
    length: int
    byte_order: int  # 1 = Intel (little-endian), 0 = Motorola (big-endian)
    is_signed: bool
    factor: float
    offset: float
    min_val: Optional[float]
    max_val: Optional[float]
    unit: str
    receivers: List[str] = field(default_factory=list)
    enums: Dict[int, str] = field(default_factory=dict)
    comment: str = ""
    is_multiplexer: bool = False
    multiplexer_value: Optional[int] = None
    is_multiplexed_multiplexer: bool = False

    # Precomputed fields for O(1) bit extraction and bounds checking
    _mask: int = field(init=False, repr=False)
    _sign_bit: int = field(init=False, repr=False)
    _sign_sub: int = field(init=False, repr=False)
    _be_start: int = field(init=False, repr=False)
    _min_bytes: int = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.length <= 0:
            raise DBCParseError(f"Signal '{self.name}': signal length must be positive (got {self.length})")
        object.__setattr__(self, "_mask", (1 << self.length) - 1)
        object.__setattr__(self, "_sign_bit", 1 << (self.length - 1))
        object.__setattr__(self, "_sign_sub", 1 << self.length)
        if self.byte_order == 1:
            # Intel (little-endian)
            object.__setattr__(self, "_be_start", 0)
            object.__setattr__(self, "_min_bytes", (self.start_bit + self.length + 7) // 8)
        else:
            # Motorola (big-endian sequential)
            be_start = (self.start_bit // 8) * 8 + (7 - (self.start_bit % 8))
            object.__setattr__(self, "_be_start", be_start)
            object.__setattr__(self, "_min_bytes", (be_start + self.length + 7) // 8)

    @property
    def is_intel(self) -> bool:
        """Return True if the signal uses Intel (little-endian) byte order."""
        return self.byte_order == 1

    @property
    def is_motorola(self) -> bool:
        """Return True if the signal uses Motorola (big-endian) byte order."""
        return self.byte_order == 0

    def to_dict(self) -> Dict[str, Any]:
        """Return a serializable dictionary representation of the signal definition."""
        return {
            "name": self.name,
            "start_bit": self.start_bit,
            "length": self.length,
            "byte_order": "intel" if self.is_intel else "motorola",
            "is_signed": self.is_signed,
            "factor": self.factor,
            "offset": self.offset,
            "min_val": self.min_val,
            "max_val": self.max_val,
            "unit": self.unit,
            "receivers": list(self.receivers),
            "enums": dict(self.enums),
            "comment": self.comment,
            "is_multiplexer": self.is_multiplexer,
            "multiplexer_value": self.multiplexer_value,
        }


@dataclass(slots=True)
class CANMessageDef:
    """Definition of a CAN message in a DBC database."""
    id: int
    raw_id: int
    name: str
    dlc: int
    transmitter: str
    is_extended: bool = False
    signals: Dict[str, CANSignalDef] = field(default_factory=dict)
    comment: str = ""

    # Pre-partitioned signal lists for fast multiplexer-aware decoding
    _multiplexers: List[CANSignalDef] = field(default_factory=list, repr=False)
    _unmultiplexed: List[CANSignalDef] = field(default_factory=list, repr=False)
    _multiplexed: Dict[int, List[CANSignalDef]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.signals:
            self._rebuild_signal_cache()

    @property
    def hex_id(self) -> str:
        """Return the formatted hexadecimal CAN ID (e.g. 0x1F4 or 0x18FEF100)."""
        return f"0x{self.id:0{8 if self.is_extended else 3}X}"

    def get_signal(self, name: str) -> Optional[CANSignalDef]:
        """Retrieve a signal definition by name."""
        return self.signals.get(name)

    def add_signal(self, signal: CANSignalDef) -> None:
        """Add a signal definition and update internal decoding cache."""
        self.signals[signal.name] = signal
        if signal.is_multiplexer:
            self._multiplexers.append(signal)
        elif signal.multiplexer_value is not None:
            self._multiplexed.setdefault(signal.multiplexer_value, []).append(signal)
        else:
            self._unmultiplexed.append(signal)

    def _rebuild_signal_cache(self) -> None:
        """Rebuild internal partitioned lists for fast decoding."""
        self._multiplexers = []
        self._unmultiplexed = []
        self._multiplexed = {}
        for sig in self.signals.values():
            if sig.is_multiplexer:
                self._multiplexers.append(sig)
            elif sig.multiplexer_value is not None:
                self._multiplexed.setdefault(sig.multiplexer_value, []).append(sig)
            else:
                self._unmultiplexed.append(sig)

    def to_dict(self) -> Dict[str, Any]:
        """Return a serializable dictionary representation of the message."""
        return {
            "id": self.id,
            "raw_id": self.raw_id,
            "hex_id": self.hex_id,
            "name": self.name,
            "dlc": self.dlc,
            "transmitter": self.transmitter,
            "is_extended": self.is_extended,
            "comment": self.comment,
            "signals": {k: v.to_dict() for k, v in self.signals.items()},
        }


@dataclass(slots=True)
class DBCDatabase:
    """In-memory representation of a parsed DBC file."""
    version: str = ""
    messages: Dict[Tuple[int, bool], CANMessageDef] = field(default_factory=dict)
    messages_by_name: Dict[str, CANMessageDef] = field(default_factory=dict)
    val_tables: Dict[str, Dict[int, str]] = field(default_factory=dict)
    comments: Dict[str, str] = field(default_factory=dict)

    def get_message_by_id(
        self, can_id: int, is_extended: Optional[bool] = None
    ) -> Optional[CANMessageDef]:
        """Lookup a message definition by CAN ID and optional extended flag.

        If is_extended is None, first searches for standard (11-bit) then extended (29-bit).
        """
        normalized = can_id & 0x1FFFFFFF
        if is_extended is not None:
            return self.messages.get((normalized, bool(is_extended)))
        # Default lookup: check standard first, then extended
        msg = self.messages.get((normalized, False))
        if msg is not None:
            return msg
        return self.messages.get((normalized, True))

    def get_message_by_name(self, name: str) -> Optional[CANMessageDef]:
        """Lookup a message definition by name."""
        return self.messages_by_name.get(name)

    def __len__(self) -> int:
        return len(self.messages)

    def __iter__(self) -> Iterator[CANMessageDef]:
        return iter(self.messages.values())

    def __contains__(self, item: Any) -> bool:
        if isinstance(item, tuple) and len(item) == 2:
            norm = int(item[0]) & 0x1FFFFFFF
            return (norm, bool(item[1])) in self.messages
        if isinstance(item, int):
            norm = item & 0x1FFFFFFF
            return (norm, False) in self.messages or (norm, True) in self.messages
        if isinstance(item, str):
            return item in self.messages_by_name
        return False


class DBCParser:
    """High-performance DBC file parser supporting full Vector DBC syntax."""

    RE_VERSION = re.compile(r'^\s*VERSION\s+"([^"]*)"', re.MULTILINE)
    RE_MESSAGE = re.compile(r'^\s*BO_\s+(\d+)\s+([^\s:]+)\s*:\s*(\d+)\s+(\S+)')
    RE_SIGNAL = re.compile(
        r'^\s*SG_\s+(\S+)\s*(?:(M|m\d+M?))?\s*:\s*'
        r'(\d+)\|(\d+)@([01])([+-])\s*'
        r'\(([^,]+),([^)]+)\)'
        r'(?:\s*\[\s*([^|\]]*?)\s*\|\s*([^\]]*?)\s*\])?'
        r'\s*"([^"]*)"\s*(.*)$'
    )
    RE_VAL_BLOCK = re.compile(r'VAL_\s+(\d+)\s+(\S+)\s+(.*?);', re.DOTALL)
    RE_VAL_TABLE_BLOCK = re.compile(r'VAL_TABLE_\s+(\S+)\s+(.*?);', re.DOTALL)
    RE_VAL_ENTRY = re.compile(r'(-?\d+)\s+"([^"]*)"')
    RE_CM_BO_BLOCK = re.compile(r'CM_\s+BO_\s+(\d+)\s+"(.*?)"\s*;', re.DOTALL)
    RE_CM_SG_BLOCK = re.compile(r'CM_\s+SG_\s+(\d+)\s+(\S+)\s+"(.*?)"\s*;', re.DOTALL)
    RE_CM_GEN_BLOCK = re.compile(r'CM_\s+"(.*?)"\s*;', re.DOTALL)

    def __init__(self, filepath: Optional[Union[str, Path]] = None, strict: bool = True):
        self.filepath = str(filepath) if filepath else None
        self.strict = strict
        self.db = DBCDatabase()
        if filepath:
            self.parse(filepath)

    @staticmethod
    def _id(raw_id: int) -> Tuple[int, bool]:
        """Extract the 29-bit CAN ID and extended frame boolean flag from DBC raw ID."""
        can_id = raw_id & 0x1FFFFFFF
        is_extended = bool(raw_id & 0x80000000) or (raw_id > 0x7FF)
        return can_id, is_extended

    @staticmethod
    def _float_or_none(value: Optional[str]) -> Optional[float]:
        if value is None:
            return None
        s = value.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None

    def parse(self, filepath_or_text: Union[str, Path, TextIO]) -> DBCDatabase:
        """Parse a DBC file or DBC text content into a DBCDatabase object."""
        if hasattr(filepath_or_text, "read"):
            content = filepath_or_text.read()
            self.filepath = getattr(filepath_or_text, "name", None)
        else:
            path = Path(filepath_or_text)
            if path.exists() and path.is_file():
                self.filepath = str(path)
                with path.open("r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            else:
                # Treat as raw string content
                content = str(filepath_or_text)

        self.db = DBCDatabase()

        # 1. Parse Version
        version_match = self.RE_VERSION.search(content)
        if version_match:
            self.db.version = version_match.group(1)

        # 2. Parse Global Value Tables (VAL_TABLE_)
        for m in self.RE_VAL_TABLE_BLOCK.finditer(content):
            table_name = m.group(1)
            entries = {int(e.group(1)): e.group(2) for e in self.RE_VAL_ENTRY.finditer(m.group(2))}
            self.db.val_tables[table_name] = entries

        # 3. Parse Signal Value Descriptions (VAL_ <id> <sig> ...)
        val_tables: Dict[Tuple[int, bool], Dict[str, Dict[int, str]]] = {}
        for m in self.RE_VAL_BLOCK.finditer(content):
            raw_id = int(m.group(1))
            key = self._id(raw_id)
            sig_name = m.group(2)
            entries = {int(e.group(1)): e.group(2) for e in self.RE_VAL_ENTRY.finditer(m.group(3))}
            val_tables.setdefault(key, {})[sig_name] = entries

        # 4. Parse Multi-line Comments (CM_ BO_, CM_ SG_, CM_)
        msg_comments: Dict[Tuple[int, bool], str] = {}
        sig_comments: Dict[Tuple[int, bool], Dict[str, str]] = {}
        for m in self.RE_CM_BO_BLOCK.finditer(content):
            key = self._id(int(m.group(1)))
            msg_comments[key] = m.group(2).replace(r'\"', '"')

        for m in self.RE_CM_SG_BLOCK.finditer(content):
            key = self._id(int(m.group(1)))
            sig_comments.setdefault(key, {})[m.group(2)] = m.group(3).replace(r'\"', '"')

        for m in self.RE_CM_GEN_BLOCK.finditer(content):
            self.db.comments["database"] = m.group(1).replace(r'\"', '"')

        # 5. Parse Messages (BO_) and Signals (SG_) line by line
        current_msg: Optional[CANMessageDef] = None

        for line_num, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.startswith("BO_ "):
                m = self.RE_MESSAGE.match(stripped)
                if not m:
                    if self.strict:
                        raise DBCParseError(f"Line {line_num}: invalid BO_ syntax: {stripped!r}")
                    continue

                raw_id = int(m.group(1))
                can_id, is_extended = self._id(raw_id)
                key = (can_id, is_extended)

                if key in self.db.messages:
                    raise DBCParseError(
                        f"Line {line_num}: Duplicate DBC message ID 0x{can_id:X} "
                        f"(extended={is_extended}). Existing message '{self.db.messages[key].name}', "
                        f"new message '{m.group(2)}'."
                    )

                current_msg = CANMessageDef(
                    id=can_id,
                    raw_id=raw_id,
                    name=m.group(2),
                    dlc=int(m.group(3)),
                    transmitter=m.group(4),
                    is_extended=is_extended,
                    comment=msg_comments.get(key, ""),
                )
                self.db.messages[key] = current_msg
                self.db.messages_by_name[current_msg.name] = current_msg
                continue

            if stripped.startswith("SG_ "):
                if current_msg is None:
                    if self.strict:
                        raise DBCParseError(f"Line {line_num}: SG_ entry found without prior BO_ message: {stripped!r}")
                    continue

                m = self.RE_SIGNAL.match(stripped)
                if not m:
                    if self.strict:
                        raise DBCParseError(f"Line {line_num}: invalid SG_ syntax: {stripped!r}")
                    continue

                sig_name = m.group(1)
                mux_str = m.group(2) or ""
                start_bit = int(m.group(3))
                length = int(m.group(4))
                byte_order = int(m.group(5))
                is_signed = m.group(6) == "-"
                factor = float(m.group(7))
                offset = float(m.group(8))
                min_val = self._float_or_none(m.group(9))
                max_val = self._float_or_none(m.group(10))
                unit = m.group(11)  # Correctly extracted unit string from quotes
                receivers_raw = m.group(12) or ""
                receivers = [r.strip() for r in re.split(r'[, ]+', receivers_raw) if r.strip()]

                # Multiplexing flags
                is_multiplexer = False
                multiplexer_val: Optional[int] = None
                is_mux_mux = False

                if mux_str == "M":
                    is_multiplexer = True
                elif mux_str.startswith("m"):
                    if mux_str.endswith("M"):
                        is_multiplexer = True
                        is_mux_mux = True
                        multiplexer_val = int(mux_str[1:-1])
                    else:
                        multiplexer_val = int(mux_str[1:])

                msg_key = (current_msg.id, current_msg.is_extended)
                sig_enums = val_tables.get(msg_key, {}).get(sig_name, {})
                sig_comment = sig_comments.get(msg_key, {}).get(sig_name, "")

                if sig_name in current_msg.signals:
                    if self.strict:
                        raise DBCParseError(
                            f"Line {line_num}: duplicate signal name '{sig_name}' in message '{current_msg.name}'"
                        )

                sig_def = CANSignalDef(
                    name=sig_name,
                    start_bit=start_bit,
                    length=length,
                    byte_order=byte_order,
                    is_signed=is_signed,
                    factor=factor,
                    offset=offset,
                    min_val=min_val,
                    max_val=max_val,
                    unit=unit,
                    receivers=receivers,
                    enums=sig_enums,
                    comment=sig_comment,
                    is_multiplexer=is_multiplexer,
                    multiplexer_value=multiplexer_val,
                    is_multiplexed_multiplexer=is_mux_mux,
                )
                current_msg.add_signal(sig_def)

        return self.db


class DBCDecoder:
    """High-performance CAN signal decoder using a DBCDatabase."""

    def __init__(self, database: DBCDatabase, strict: bool = False):
        self.db = database
        self.strict = strict

    @staticmethod
    def _motorola_positions(start_bit: int, length: int) -> List[int]:
        """Compute bit positions for Motorola bit order (legacy / debugging helper)."""
        positions = []
        bit = start_bit
        for _ in range(length):
            positions.append(bit)
            bit = bit + 15 if bit % 8 == 0 else bit - 1
        return positions

    @staticmethod
    def extract_raw(data: bytes, signal: CANSignalDef) -> int:
        """Extract the raw integer value of a signal from payload bytes with O(1) complexity."""
        data_len = len(data)
        if data_len < signal._min_bytes:
            raise ValueError(
                f"Signal '{signal.name}': payload too short (requires at least "
                f"{signal._min_bytes} bytes, got {data_len})"
            )

        if signal.is_intel:
            # Little-endian integer extraction
            v = int.from_bytes(data, "little")
            raw = (v >> signal.start_bit) & signal._mask
        else:
            # Motorola (big-endian sequential) integer extraction
            v = int.from_bytes(data, "big")
            shift = (data_len * 8) - signal._be_start - signal.length
            raw = (v >> shift) & signal._mask

        if signal.is_signed and (raw & signal._sign_bit):
            raw -= signal._sign_sub
        return raw

    @staticmethod
    def physical_value(raw: int, signal: CANSignalDef) -> Union[int, float]:
        """Convert a raw integer signal value to its physical scaled floating point / integer value."""
        val = raw * signal.factor + signal.offset
        # Clean rounding / integer representation when appropriate
        if isinstance(val, float) and val.is_integer() and signal.factor.is_integer() and signal.offset.is_integer():
            return int(val)
        return val

    def _decode_signal_dict(self, data: bytes, signal: CANSignalDef) -> Dict[str, Any]:
        """Decode a single signal into its full metadata dictionary."""
        raw = self.extract_raw(data, signal)
        phys = self.physical_value(raw, signal)
        enum_desc = signal.enums.get(raw)

        return {
            "raw": raw,
            "value": phys,
            "unit": signal.unit,
            "comment": signal.comment,
            "enum": enum_desc,
            "is_multiplexer": signal.is_multiplexer,
            "multiplexer_value": signal.multiplexer_value,
            "min": signal.min_val,
            "max": signal.max_val,
            "is_signed": signal.is_signed,
            "receivers": signal.receivers,
        }

    def decode_frame(
        self,
        frame: Any,
        include_unmatched: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Decode a CAN frame into a comprehensive dictionary containing all message and signal metadata.

        Accepts any frame object with can_id, data (or payload), timestamp, and is_extended,
        or a standard dictionary.
        """
        # Duck-typing extraction of frame fields
        if isinstance(frame, dict):
            can_id = frame.get("can_id", frame.get("id", 0))
            is_extended = frame.get("is_extended")
            data = frame.get("data", frame.get("payload", b""))
            timestamp = float(frame.get("timestamp", 0.0))
            channel = int(frame.get("channel", 0))
            dlc = frame.get("dlc")
        else:
            can_id = getattr(frame, "can_id", getattr(frame, "id", 0))
            is_extended = getattr(frame, "is_extended", None)
            data = getattr(frame, "data", getattr(frame, "payload", b""))
            timestamp = float(getattr(frame, "timestamp", 0.0))
            channel = int(getattr(frame, "channel", 0))
            dlc = getattr(frame, "dlc", None)

        if isinstance(data, str):
            # Hex string support
            data = bytes.fromhex(data.replace("0x", "").replace(" ", "").replace(",", ""))
        elif isinstance(data, (bytearray, memoryview)):
            data = bytes(data)
        elif not isinstance(data, bytes):
            data = bytes(data)

        if dlc is None:
            dlc = len(data)

        message = self.db.get_message_by_id(can_id, is_extended)
        if message is None:
            if include_unmatched:
                ext = bool(is_extended) if is_extended is not None else (can_id > 0x7FF)
                return {
                    "timestamp": timestamp,
                    "channel": channel,
                    "can_id": can_id,
                    "hex_id": f"0x{can_id:0{8 if ext else 3}X}",
                    "is_extended": ext,
                    "message": None,
                    "dlc": dlc,
                    "comment": "",
                    "transmitter": "",
                    "signals": {},
                    "error": "Unmatched CAN ID (not in DBC)",
                }
            return None

        decoded_signals: Dict[str, Dict[str, Any]] = {}
        mux_values: Dict[str, int] = {}

        try:
            # 1. Decode multiplexer switch signals first
            for sig in message._multiplexers:
                sig_info = self._decode_signal_dict(data, sig)
                decoded_signals[sig.name] = sig_info
                mux_values[sig.name] = sig_info["raw"]

            # 2. Decode unmultiplexed (always present) signals
            for sig in message._unmultiplexed:
                decoded_signals[sig.name] = self._decode_signal_dict(data, sig)

            # 3. Decode multiplexed signals matching the active multiplexer value
            if message._multiplexed:
                # If multiplexer signals were present, use their value; default to single active mux
                active_mux_val = next(iter(mux_values.values())) if mux_values else None
                if active_mux_val is not None and active_mux_val in message._multiplexed:
                    for sig in message._multiplexed[active_mux_val]:
                        decoded_signals[sig.name] = self._decode_signal_dict(data, sig)

        except Exception as exc:
            if self.strict:
                raise DBCDecodeError(
                    f"Error decoding message '{message.name}' (ID {message.hex_id}): {exc}"
                ) from exc
            return None

        return {
            "timestamp": timestamp,
            "channel": channel,
            "can_id": message.id,
            "hex_id": message.hex_id,
            "is_extended": message.is_extended,
            "message": message.name,
            "dlc": dlc,
            "comment": message.comment,
            "transmitter": message.transmitter,
            "signals": decoded_signals,
        }


class StreamingJSONWriter:
    """Incrementally writes JSON array elements to a file or stream with O(1) memory overhead."""

    def __init__(self, file_or_path: Union[str, Path, TextIO], indent: Optional[int] = 2):
        self.indent = indent
        self._close_on_exit = False
        if isinstance(file_or_path, (str, Path)):
            self.file: TextIO = open(file_or_path, "w", encoding="utf-8")
            self._close_on_exit = True
        else:
            self.file = file_or_path

        self.first = True
        self.count = 0
        self.file.write("[\n" if indent is not None else "[")

    def write(self, item: Any) -> None:
        """Write a single serializable object to the streaming JSON array."""
        if not self.first:
            self.file.write(",\n" if self.indent is not None else ",")
        else:
            self.first = False

        if self.indent is not None:
            item_json = json.dumps(item, indent=self.indent)
            indented_lines = ["  " + line for line in item_json.splitlines()]
            self.file.write("\n".join(indented_lines))
        else:
            self.file.write(json.dumps(item))

        self.count += 1

    def close(self) -> None:
        """Close the JSON array and underlying file if opened by this instance."""
        if not hasattr(self, "file") or self.file.closed:
            return
        self.file.write("\n]\n" if self.indent is not None else "]")
        self.file.flush()
        if self._close_on_exit:
            self.file.close()

    def __enter__(self) -> StreamingJSONWriter:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


def parse_dbc_file(filepath: Union[str, Path], strict: bool = True) -> DBCDatabase:
    """Convenience function to parse a DBC file."""
    return DBCParser(filepath, strict=strict).db


def decode_frames(
    frames: Iterable[Any],
    database: DBCDatabase,
    output_json: Optional[Union[str, Path, TextIO]] = None,
    indent: Optional[int] = 2,
    strict: bool = False,
    include_unmatched: bool = False,
) -> Generator[Dict[str, Any], None, None]:
    """Decode an iterable of CAN frames using a DBC database.

    If output_json is provided, incrementally streams every decoded result to the JSON file.
    Yields each decoded frame dictionary.
    """
    decoder = DBCDecoder(database, strict=strict)
    json_writer: Optional[StreamingJSONWriter] = None

    if output_json is not None:
        json_writer = StreamingJSONWriter(output_json, indent=indent)

    try:
        for frame in frames:
            decoded = decoder.decode_frame(frame, include_unmatched=include_unmatched)
            if decoded is not None:
                if json_writer is not None:
                    json_writer.write(decoded)
                yield decoded
    finally:
        if json_writer is not None:
            json_writer.close()


def decode_file(
    dbc_source: Union[str, Path, DBCDatabase],
    frames_or_file: Union[str, Path, Iterable[Any]],
    output_json: Optional[Union[str, Path, TextIO]] = None,
    indent: Optional[int] = 2,
    strict: bool = False,
    include_unmatched: bool = False,
    frame_parser: Optional[Callable[[Union[str, Path]], Iterable[Any]]] = None,
) -> List[Dict[str, Any]]:
    """Complete end-to-end decoding function.

    Decodes a collection of frames or a log file using a DBC file/database,
    optionally writing the entire complete result to a JSON file.
    """
    if isinstance(dbc_source, DBCDatabase):
        db = dbc_source
    else:
        db = parse_dbc_file(dbc_source, strict=strict)

    if isinstance(frames_or_file, (str, Path)):
        path = Path(frames_or_file)
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {path}")

        if frame_parser is not None:
            frame_iter = frame_parser(path)
        else:
            # Check if JSON file
            if path.suffix.lower() == ".json":
                with path.open("r", encoding="utf-8") as f:
                    records = json.load(f)
                frame_iter = records if isinstance(records, list) else [records]
            else:
                # Built-in lightweight ASC reader fallback
                def _quick_asc_iter(p: Path):
                    with p.open("r", encoding="utf-8", errors="replace") as fh:
                        for line in fh:
                            s = line.strip()
                            if not s or s.startswith(("//", "***", "date", "base", "Begin", "version")):
                                continue
                            parts = s.split()
                            if len(parts) >= 6:
                                try:
                                    ts = float(parts[0])
                                    ch = int(parts[1])
                                    raw_id = parts[2]
                                    is_ext = raw_id.lower().endswith("x")
                                    can_id = int(raw_id[:-1] if is_ext else raw_id, 16)
                                    dlc = int(parts[5])
                                    data_bytes = bytes.fromhex("".join(parts[6:6 + dlc]))
                                    yield {
                                        "timestamp": ts,
                                        "channel": ch,
                                        "can_id": can_id,
                                        "is_extended": is_ext or (can_id > 0x7FF),
                                        "dlc": dlc,
                                        "data": data_bytes,
                                    }
                                except (ValueError, IndexError):
                                    continue

                frame_iter = _quick_asc_iter(path)
    else:
        frame_iter = frames_or_file

    results = []
    for decoded in decode_frames(
        frame_iter,
        database=db,
        output_json=output_json,
        indent=indent,
        strict=strict,
        include_unmatched=include_unmatched,
    ):
        results.append(decoded)

    return results