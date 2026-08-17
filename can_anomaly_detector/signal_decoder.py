"""
signal_decoder.py
Decodes CAN raw payload bytes into physical values based on DBC signal definitions.
Handles byte order (Intel / Motorola), bit alignment, signed/unsigned types,
scaling factors, offsets, and value descriptions (enums).
"""

from dataclasses import dataclass
from typing import Dict, Optional
from dbc_parser import CANSignalDef, CANMessageDef, DBCDatabase
from asc_parser import CANFrame


@dataclass
class DecodedSignal:
    """Represents a decoded signal with raw and physical values."""
    name: str
    raw_value: int
    physical_value: float
    unit: str
    enum_name: Optional[str] = None
    min_val: float = 0.0
    max_val: float = 0.0

    @property
    def display_value(self) -> str:
        if self.enum_name:
            return f"{self.physical_value} ({self.enum_name})"
        if self.unit:
            return f"{self.physical_value:.2f} {self.unit}".strip()
        return f"{self.physical_value:.2f}"


class SignalDecoder:
    """Decodes CAN frame payloads using DBC signal definitions."""

    def __init__(self, db: Optional[DBCDatabase] = None):
        self.db: Optional[DBCDatabase] = None
        self.set_database(db)

    def set_database(self, db: Optional[DBCDatabase]):
        """
        Dynamically update DBC database reference and reset any decoder-specific state.
        Ensures perfect synchronization when DBC is changed or reloaded.
        """
        self.db = db

    @staticmethod
    def is_corruption_or_test_pattern(data: bytes) -> bool:
        """Check if payload is a raw bus test pattern or corrupt sequence."""
        if not data:
            return True
        # All FF
        if all(b == 0xFF for b in data):
            return True
        # Alternating AA 55 test patterns
        if data in (b"\xAA\x55\xAA\x55\xAA\x55\xAA\x55", b"\x55\xAA\x55\xAA\x55\xAA\x55\xAA"):
            return True
        return False

    @staticmethod
    def extract_raw_value(data_bytes: bytes, start_bit: int, length: int,
                          byte_order: int, is_signed: bool) -> int:
        """
        Extract raw integer value from payload bytes with strict boundary checks.
        
        :param data_bytes: Raw CAN payload bytes
        :param start_bit: DBC start bit position
        :param length: Signal bit length
        :param byte_order: 1 for Intel (Little Endian), 0 for Motorola (Big Endian)
        :param is_signed: True for signed (2's complement), False for unsigned
        :return: Decoded integer raw value
        """
        if not data_bytes or length <= 0 or start_bit < 0:
            return 0

        num_bytes = len(data_bytes)
        max_bits = num_bytes * 8

        if byte_order == 1:
            # Intel / Little Endian
            if start_bit >= max_bits:
                return 0
            val = 0
            for i, b in enumerate(data_bytes):
                val |= (b << (8 * i))
            raw = (val >> start_bit) & ((1 << length) - 1)
        else:
            # Motorola / Big Endian (Vector convention: start_bit is MSB)
            raw = 0
            pos = start_bit
            for _ in range(length):
                if 0 <= pos < max_bits:
                    byte_idx = pos // 8
                    bit_idx = pos % 8
                    if 0 <= byte_idx < num_bytes:
                        bit_val = (data_bytes[byte_idx] >> bit_idx) & 1
                    else:
                        bit_val = 0
                else:
                    bit_val = 0

                raw = (raw << 1) | bit_val
                
                # Advance to next bit in Vector Motorola order (MSB to LSB across bytes)
                bit_idx = pos % 8
                if bit_idx == 0:
                    pos += 15
                else:
                    pos -= 1

        # Sign extension
        if is_signed:
            sign_bit = 1 << (length - 1)
            if raw & sign_bit:
                raw = raw - (1 << length)

        return raw

    def decode_signal(self, data_bytes: bytes, sig_def: CANSignalDef) -> DecodedSignal:
        """Decode a single signal from data bytes according to its definition."""
        raw = self.extract_raw_value(
            data_bytes=data_bytes,
            start_bit=sig_def.start_bit,
            length=sig_def.length,
            byte_order=sig_def.byte_order,
            is_signed=sig_def.is_signed
        )

        # Calculate physical value
        physical = raw * sig_def.factor + sig_def.offset

        # Check for enum description: prioritize integer raw value matching first
        enum_name = None
        if raw in sig_def.enums:
            enum_name = sig_def.enums[raw]
        else:
            int_phys = int(round(physical))
            if int_phys in sig_def.enums:
                enum_name = sig_def.enums[int_phys]

        return DecodedSignal(
            name=sig_def.name,
            raw_value=raw,
            physical_value=physical,
            unit=sig_def.unit,
            enum_name=enum_name,
            min_val=sig_def.min_val,
            max_val=sig_def.max_val
        )

    def decode_frame(self, frame: CANFrame) -> Dict[str, DecodedSignal]:
        """Decode all signals for a given CAN frame using the DBC database."""
        if self.db is None:
            raise ValueError("DBC database not set in SignalDecoder.")

        # Ignore corruption/test-pattern payloads
        if self.is_corruption_or_test_pattern(frame.data):
            return {}

        msg_def = self.db.get_message_by_id(frame.can_id)
        if not msg_def:
            return {}

        decoded: Dict[str, DecodedSignal] = {}
        for sig_name, sig_def in msg_def.signals.items():
            decoded[sig_name] = self.decode_signal(frame.data, sig_def)

        return decoded
