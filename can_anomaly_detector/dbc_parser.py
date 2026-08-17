"""
dbc_parser.py
DBC file parser for automotive CAN bus definitions.
Parses messages (BO_), signals (SG_), value tables (VAL_), and comments (CM_).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import os
import re


@dataclass
class CANSignalDef:
    """Definition of a single CAN signal within a message."""
    name: str
    start_bit: int
    length: int
    byte_order: int          # 1 = Intel (Little Endian), 0 = Motorola (Big Endian)
    is_signed: bool          # True = signed (-), False = unsigned (+)
    factor: float
    offset: float
    min_val: float
    max_val: float
    unit: str
    receivers: List[str] = field(default_factory=list)
    enums: Dict[int, str] = field(default_factory=dict)
    comment: str = ""

    @property
    def is_intel(self) -> bool:
        return self.byte_order == 1

    @property
    def is_motorola(self) -> bool:
        return self.byte_order == 0


@dataclass
class CANMessageDef:
    """Definition of a CAN message containing one or more signals."""
    id: int                  # Standard or decoded numeric ID
    raw_id: int              # Raw ID from DBC (may include extended flag)
    name: str
    dlc: int
    transmitter: str
    signals: Dict[str, CANSignalDef] = field(default_factory=dict)
    comment: str = ""

    @property
    def hex_id(self) -> str:
        return f"0x{self.id:03X}"

    def get_signal(self, name: str) -> Optional[CANSignalDef]:
        return self.signals.get(name)


@dataclass
class DBCDatabase:
    """Container for all messages and metadata in a DBC file."""
    version: str = ""
    messages: Dict[int, CANMessageDef] = field(default_factory=dict)
    messages_by_name: Dict[str, CANMessageDef] = field(default_factory=dict)

    def get_message_by_id(self, can_id: int) -> Optional[CANMessageDef]:
        # Support direct lookup or masked lookup
        if can_id in self.messages:
            return self.messages[can_id]
        masked = can_id & 0x1FFFFFFF
        return self.messages.get(masked)

    def get_message_by_name(self, name: str) -> Optional[CANMessageDef]:
        return self.messages_by_name.get(name)


class DBCParser:
    """Dynamic parser for Vector CAN DBC files."""

    # Regular expressions for DBC tokens
    RE_MESSAGE = re.compile(r'^BO_\s+(\d+)\s+([a-zA-Z0-9_]+)\s*:\s*(\d+)\s+([a-zA-Z0-9_]+)')
    RE_SIGNAL = re.compile(
        r'^\s*SG_\s+([a-zA-Z0-9_]+)\s*(?:M|m\d+)?\s*:\s*(\d+)\|(\d+)@([01])([+-])\s*\(([\d.eE+-]+),([\d.eE+-]+)\)\s*\[([\d.eE+-]+)\|([\d.eE+-]+)\]\s*"([^"]*)"\s+(.+)'
    )
    RE_VAL_TABLE = re.compile(r'VAL_\s+(\d+)\s+([a-zA-Z0-9_]+)\s+([^;]+);')
    RE_VAL_ENTRY = re.compile(r'(-?\d+)\s+"([^"]+)"')
    RE_COMMENT_SG = re.compile(r'CM_\s+SG_\s+(\d+)\s+([a-zA-Z0-9_]+)\s+"([^"]*)";')
    RE_COMMENT_BO = re.compile(r'CM_\s+BO_\s+(\d+)\s+"([^"]*)";')

    def __init__(self, filepath: Optional[str] = None):
        self.filepath = filepath
        self.db = DBCDatabase()
        if filepath:
            self.parse(filepath)

    def parse(self, filepath: str) -> DBCDatabase:
        """Parse DBC file from given path with file validation."""
        if not isinstance(filepath, str) or not filepath.strip():
            raise ValueError("Invalid DBC filepath provided.")
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"DBC file not found at: {filepath}")

        self.filepath = filepath
        self.db = DBCDatabase()

        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        # 1. Parse all VAL_ (value descriptions / enums)
        val_tables: Dict[int, Dict[str, Dict[int, str]]] = {}
        for match in self.RE_VAL_TABLE.finditer(content):
            raw_id = int(match.group(1))
            can_id = raw_id & 0x1FFFFFFF
            sig_name = match.group(2)
            pairs_str = match.group(3).strip()
            
            val_map = {}
            for entry in self.RE_VAL_ENTRY.finditer(pairs_str):
                val_map[int(entry.group(1))] = entry.group(2)
                
            if can_id not in val_tables:
                val_tables[can_id] = {}
            val_tables[can_id][sig_name] = val_map

        # 2. Parse all comments
        sig_comments: Dict[int, Dict[str, str]] = {}
        for match in self.RE_COMMENT_SG.finditer(content):
            raw_id = int(match.group(1))
            can_id = raw_id & 0x1FFFFFFF
            sig_name = match.group(2)
            comment = match.group(3)
            if can_id not in sig_comments:
                sig_comments[can_id] = {}
            sig_comments[can_id][sig_name] = comment

        msg_comments: Dict[int, str] = {}
        for match in self.RE_COMMENT_BO.finditer(content):
            raw_id = int(match.group(1))
            can_id = raw_id & 0x1FFFFFFF
            comment = match.group(2)
            msg_comments[can_id] = comment

        # 3. Parse BO_ and SG_ definitions
        current_msg: Optional[CANMessageDef] = None
        for line in content.splitlines():
            line_stripped = line.strip()
            if not line_stripped:
                continue

            if line_stripped.startswith("BO_ "):
                m = self.RE_MESSAGE.match(line_stripped)
                if m:
                    raw_id = int(m.group(1))
                    can_id = raw_id & 0x1FFFFFFF
                    name = m.group(2)
                    dlc = int(m.group(3))
                    transmitter = m.group(4)
                    current_msg = CANMessageDef(
                        id=can_id,
                        raw_id=raw_id,
                        name=name,
                        dlc=dlc,
                        transmitter=transmitter,
                        comment=msg_comments.get(can_id, "")
                    )
                    self.db.messages[can_id] = current_msg
                    self.db.messages_by_name[name] = current_msg
                else:
                    current_msg = None

            elif line_stripped.startswith("SG_ ") and current_msg is not None:
                m = self.RE_SIGNAL.match(line_stripped)
                if m:
                    sig_name = m.group(1)
                    start_bit = int(m.group(2))
                    length = int(m.group(3))
                    byte_order = int(m.group(4))
                    is_signed = (m.group(5) == '-')
                    factor = float(m.group(6))
                    offset = float(m.group(7))
                    min_val = float(m.group(8))
                    max_val = float(m.group(9))
                    unit = m.group(10)
                    receivers = [r.strip() for r in m.group(11).split(",") if r.strip()]

                    enums = val_tables.get(current_msg.id, {}).get(sig_name, {})
                    comment = sig_comments.get(current_msg.id, {}).get(sig_name, "")

                    signal_def = CANSignalDef(
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
                        enums=enums,
                        comment=comment
                    )
                    current_msg.signals[sig_name] = signal_def

        return self.db
