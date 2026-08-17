"""
signal_history.py
Temporal signal history buffer and latest vehicle state store.
Stores timestamped physical signal values and provides sliding window access
for temporal correlation rules (such as R-006 and R-007).
Prevents signal name collisions by indexing on composite (can_id, signal_name) keys,
maintains time-based window retention, and anchors temporal queries on evaluation timestamps.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Deque, Tuple, Set
from collections import deque
from signal_decoder import DecodedSignal
from asc_parser import CANFrame


@dataclass
class SignalObservation:
    """A single timestamped observation of a physical signal."""
    timestamp: float
    value: float
    raw_value: int
    can_id: int
    message_name: str
    signal_name: str
    unit: str = ""
    enum_name: Optional[str] = None

    def __post_init__(self):
        # Runtime type validation and coercion
        self.timestamp = float(self.timestamp)
        self.value = float(self.value)
        self.raw_value = int(self.raw_value)
        self.can_id = int(self.can_id)
        self.message_name = str(self.message_name)
        self.signal_name = str(self.signal_name)
        self.unit = str(self.unit) if self.unit is not None else ""
        self.enum_name = str(self.enum_name) if self.enum_name is not None else None

    @property
    def display_value(self) -> str:
        if self.enum_name:
            return f"{self.value} ({self.enum_name})"
        if self.unit:
            return f"{self.value:.2f} {self.unit}".strip()
        return f"{self.value:.2f}"


class SignalHistory:
    """
    Maintains bounded temporal history of decoded signals and latest vehicle state.
    Indexed by composite key (can_id, signal_name) to avoid collisions across CAN messages.
    """

    def __init__(self, max_history_per_signal: int = 5000, time_window_seconds: float = 5.0):
        if not isinstance(max_history_per_signal, int) or max_history_per_signal <= 0:
            raise ValueError(f"max_history_per_signal must be a positive integer, got: {max_history_per_signal}")
        if not isinstance(time_window_seconds, (int, float)) or time_window_seconds <= 0:
            raise ValueError(f"time_window_seconds must be a positive number, got: {time_window_seconds}")

        self.max_history = max_history_per_signal
        self.time_window = float(time_window_seconds)

        # Storage keyed by (can_id, signal_name)
        self._history: Dict[Tuple[int, str], Deque[SignalObservation]] = {}
        self._latest_state: Dict[Tuple[int, str], SignalObservation] = {}

        # Indices for convenient lookup and collision detection
        self._signal_name_to_keys: Dict[str, Set[Tuple[int, str]]] = {}
        self._msg_sig_to_key: Dict[Tuple[str, str], Tuple[int, str]] = {}

    def _resolve_key(
        self,
        signal_name: str,
        can_id: Optional[int] = None,
        message_name: Optional[str] = None
    ) -> Optional[Tuple[int, str]]:
        """Resolve signal identifier to internal (can_id, signal_name) key with ambiguity check."""
        if can_id is not None:
            return (can_id, signal_name)

        if message_name is not None:
            return self._msg_sig_to_key.get((message_name, signal_name))

        # Look up by bare signal_name
        matching_keys = self._signal_name_to_keys.get(signal_name)
        if not matching_keys:
            return None

        if len(matching_keys) == 1:
            return next(iter(matching_keys))

        # Collision detected: multiple messages have this signal name
        # Return the most recently updated key among them
        latest_obs = None
        best_key = None
        for k in matching_keys:
            obs = self._latest_state.get(k)
            if obs is not None and (latest_obs is None or obs.timestamp > latest_obs.timestamp):
                latest_obs = obs
                best_key = k

        return best_key

    def record(self, frame: CANFrame, message_name: str, decoded_signals: Dict[str, DecodedSignal]):
        """Record all decoded signals from a frame into history and update latest state."""
        for sig_name, sig_val in decoded_signals.items():
            key = (frame.can_id, sig_name)
            obs = SignalObservation(
                timestamp=frame.timestamp,
                value=sig_val.physical_value,
                raw_value=int(sig_val.raw_value),
                can_id=frame.can_id,
                message_name=message_name,
                signal_name=sig_name,
                unit=sig_val.unit,
                enum_name=sig_val.enum_name
            )

            # Update indices
            if sig_name not in self._signal_name_to_keys:
                self._signal_name_to_keys[sig_name] = set()
            self._signal_name_to_keys[sig_name].add(key)
            self._msg_sig_to_key[(message_name, sig_name)] = key

            # Update latest state
            self._latest_state[key] = obs

            # Append to history deque
            if key not in self._history:
                self._history[key] = deque(maxlen=self.max_history)
            
            history_deque = self._history[key]
            history_deque.append(obs)

            # Time-based eviction: prune observations older than time_window
            cutoff_ts = frame.timestamp - self.time_window
            while history_deque and history_deque[0].timestamp < cutoff_ts:
                history_deque.popleft()

    def get_latest(
        self,
        signal_name: str,
        can_id: Optional[int] = None,
        message_name: Optional[str] = None
    ) -> Optional[SignalObservation]:
        """Get the most recent observation of a signal."""
        key = self._resolve_key(signal_name, can_id=can_id, message_name=message_name)
        if key is None:
            return None
        return self._latest_state.get(key)

    def get_latest_value(
        self,
        signal_name: str,
        can_id: Optional[int] = None,
        message_name: Optional[str] = None,
        default: Optional[float] = None
    ) -> Optional[float]:
        """Get the physical value of the most recent observation of a signal."""
        obs = self.get_latest(signal_name, can_id=can_id, message_name=message_name)
        return obs.value if obs is not None else default

    def get_history(
        self,
        signal_name: str,
        can_id: Optional[int] = None,
        message_name: Optional[str] = None
    ) -> List[SignalObservation]:
        """Get full history list for a signal in timestamp order."""
        key = self._resolve_key(signal_name, can_id=can_id, message_name=message_name)
        if key is not None and key in self._history:
            return list(self._history[key])
        return []

    def get_recent_history(
        self,
        signal_name: str,
        duration_seconds: Optional[float] = None,
        as_of_timestamp: Optional[float] = None,
        can_id: Optional[int] = None,
        message_name: Optional[str] = None
    ) -> List[SignalObservation]:
        """
        Get history within the last `duration_seconds` anchored on `as_of_timestamp` or latest sample.
        
        :param signal_name: Name of the signal
        :param duration_seconds: Duration window in seconds (defaults to self.time_window)
        :param as_of_timestamp: Reference evaluation timestamp (defaults to signal's latest sample)
        :param can_id: Optional CAN ID filter
        :param message_name: Optional message name filter
        :return: List of observations within window in chronological order
        """
        key = self._resolve_key(signal_name, can_id=can_id, message_name=message_name)
        if key is None or key not in self._history or not self._history[key]:
            return []

        history = list(self._history[key])
        if duration_seconds is None:
            duration_seconds = self.time_window

        if as_of_timestamp is not None:
            reference_ts = as_of_timestamp
            cutoff_ts = reference_ts - duration_seconds
            return [obs for obs in history if cutoff_ts <= obs.timestamp <= reference_ts]
        else:
            reference_ts = history[-1].timestamp
            cutoff_ts = reference_ts - duration_seconds
            return [obs for obs in history if obs.timestamp >= cutoff_ts]

    def clear(self):
        """Reset all history, latest state, and lookup indices."""
        self._history.clear()
        self._latest_state.clear()
        self._signal_name_to_keys.clear()
        self._msg_sig_to_key.clear()
