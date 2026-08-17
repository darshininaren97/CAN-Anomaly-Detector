"""
asc_parser.py
Vector ASC log parser for CAN bus frames.
Yields timestamped CAN frame objects.
"""

from dataclasses import dataclass
from typing import List, Generator, Optional
import os
import re


@dataclass
class CANFrame:
    """Represents a single parsed CAN frame from a Vector ASC log."""
    timestamp: float
    channel: int
    can_id: int
    direction: str
    frame_type: str
    dlc: int
    data: bytes
    raw_line: str = ""

    @property
    def hex_id(self) -> str:
        return f"0x{self.can_id:03X}"

    def __repr__(self) -> str:
        data_hex = self.data.hex(' ').upper()
        return f"CANFrame(ts={self.timestamp:.6f}, ID={self.hex_id}, DLC={self.dlc}, Data=[{data_hex}])"


class ASCParser:
    """Parser for Vector ASC CAN log files."""

    RE_FRAME = re.compile(
        r'^\s*([\d.]+)\s+(\d+)\s+([0-9a-fA-F]+)\s+([Rr][Xx]|[Tt][Xx])\s+([a-zA-Z]+)\s+(\d+)(?:\s+(.*))?$'
    )

    IGNORE_PREFIXES = (
        "//", "***", "begin", "end", "date", "base", "internal", "version", "start"
    )

    def __init__(self, filepath: Optional[str] = None):
        self.filepath = filepath

    def parse_frames(self, filepath: Optional[str] = None) -> Generator[CANFrame, None, None]:
        """
        Stream CAN frames one by one from an ASC log file with comprehensive error handling.
        """
        target_path = filepath or self.filepath
        if not target_path or not isinstance(target_path, str) or not target_path.strip():
            raise ValueError("No valid filepath provided for ASC parser.")

        if not os.path.exists(target_path):
            raise FileNotFoundError(f"CAN ASC log file not found at: {target_path}")

        try:
            with open(target_path, "r", encoding="utf-8", errors="replace") as f:
                for line_num, line in enumerate(f, start=1):
                    clean = line.strip()
                    if not clean:
                        continue

                    # Skip header lines and comments
                    clean_lower = clean.lower()
                    if any(clean_lower.startswith(prefix) for prefix in self.IGNORE_PREFIXES):
                        continue

                    # Match frame regex
                    match = self.RE_FRAME.match(clean)
                    if not match:
                        continue

                    try:
                        timestamp = float(match.group(1))
                        channel = int(match.group(2))
                        can_id = int(match.group(3), 16)
                        direction = match.group(4)
                        frame_type = match.group(5)
                        dlc = int(match.group(6))

                        data_str = match.group(7) or ""
                        byte_tokens = data_str.strip().split()
                        
                        # Convert byte hex tokens up to dlc
                        data_bytes = bytes([int(token, 16) for token in byte_tokens[:dlc]])

                        yield CANFrame(
                            timestamp=timestamp,
                            channel=channel,
                            can_id=can_id,
                            direction=direction,
                            frame_type=frame_type,
                            dlc=dlc,
                            data=data_bytes,
                            raw_line=clean
                        )
                    except (ValueError, TypeError):
                        # Gracefully skip malformed data lines
                        continue
        except OSError as e:
            raise OSError(f"Failed reading ASC log file at {target_path}: {e}") from e

    def load_all_frames(self, filepath: Optional[str] = None) -> List[CANFrame]:
        """Load all CAN frames into a list."""
        return list(self.parse_frames(filepath))
