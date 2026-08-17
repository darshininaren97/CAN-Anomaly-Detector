"""Core Temporal, Timing, and Behavioral Anomaly Detection Engine for CAN Bus."""

import math
import statistics
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from timing_module.config import TimingConfig
from timing_module.models import (
    AnomalyEvent,
    AnomalyType,
    BaselineProfile,
    ECUProfile,
    Frame,
    Severity,
)


class TimingAnalyzer:
    """
    Offline Temporal and Behavioral Anomaly Detection Engine.

    Analyzes inter-frame timing intervals, transmission rates, payload repetitions,
    and timeout gaps to detect timing jitter, flooding bursts, replay bursts,
    and ECU communication blackouts.
    """

    def __init__(self, config: Optional[TimingConfig] = None):
        """Initialize analyzer with custom or default timing configuration."""
        self.config: TimingConfig = config or TimingConfig()
        self.baseline_profiles: Dict[str, BaselineProfile] = {}
        self.ecu_profiles: Dict[str, ECUProfile] = {}
        self.can_id_to_ecu: Dict[str, str] = {}
        self._last_anomalies: List[AnomalyEvent] = []

    def fit(self, frames: Sequence[Frame]) -> Dict[str, BaselineProfile]:
        """
        Fit nominal timing baselines for all CAN IDs present in the given frames.

        Calculates median interval (nominal period), mean, standard deviation,
        minimum, maximum, frames per second, and coefficient of variation.
        """
        grouped_frames = self._group_and_sort_frames(frames)
        self.baseline_profiles.clear()
        self.can_id_to_ecu.clear()

        for can_id_hex, group in grouped_frames.items():
            # Record ECU association if present in baseline frames
            for f in group:
                if f.ecu:
                    self.can_id_to_ecu[can_id_hex] = f.ecu
                    break

            resolved_ecu = self.can_id_to_ecu.get(can_id_hex)

            if len(group) < 2:
                # Single frame CAN ID: insufficient to establish interval
                int_id = group[0].can_id
                self.baseline_profiles[can_id_hex] = BaselineProfile(
                    can_id=can_id_hex,
                    can_id_int=int_id,
                    sample_count=len(group),
                    median_interval=0.0,
                    mean_interval=0.0,
                    std_interval=0.0,
                    min_interval=0.0,
                    max_interval=0.0,
                    frames_per_second=0.0,
                    coefficient_of_variation=0.0,
                    ecu=resolved_ecu,
                )
                continue

            intervals = [
                round(group[i].timestamp - group[i - 1].timestamp, 9)
                for i in range(1, len(group))
            ]

            # Eliminate non-positive intervals from unsorted/duplicate timestamps if any
            valid_intervals = [dt for dt in intervals if dt > 0]
            if not valid_intervals:
                valid_intervals = intervals

            sample_count = len(group)
            median_val = statistics.median(valid_intervals)
            mean_val = statistics.mean(valid_intervals)
            std_val = statistics.stdev(valid_intervals) if len(valid_intervals) >= 2 else 0.0
            if abs(std_val) < 1e-9:
                std_val = 0.0
            min_val = min(valid_intervals)
            max_val = max(valid_intervals)
            fps = 1.0 / median_val if median_val > 0 else 0.0
            cv = (std_val / mean_val) if (mean_val > 0 and std_val > 0) else 0.0

            self.baseline_profiles[can_id_hex] = BaselineProfile(
                can_id=can_id_hex,
                can_id_int=group[0].can_id,
                sample_count=sample_count,
                median_interval=median_val,
                mean_interval=mean_val,
                std_interval=std_val,
                min_interval=min_val,
                max_interval=max_val,
                frames_per_second=fps,
                coefficient_of_variation=cv,
                ecu=resolved_ecu,
            )

        return self.baseline_profiles

    def analyze(self, frames: Sequence[Frame]) -> List[AnomalyEvent]:
        """
        Analyze frames against fitted baselines for temporal and behavioral anomalies.

        Requires fit() to have been executed beforehand on nominal training data
        to prevent contamination from anomalous test traffic.

        Detects:
        - Timing deviations (jitter, clock drift, period shift)
        - Sustained flooding bursts (aggregated)
        - Duplicate payload bursts (aggregated)
        - Communication timeouts (missed frames)
        """
        if not self.baseline_profiles:
            raise RuntimeError(
                "Baseline profiles have not been fitted. Call fit() with nominal baseline data prior to calling analyze()."
            )

        if not frames:
            self._last_anomalies = []
            return []

        grouped_frames = self._group_and_sort_frames(frames)
        all_anomalies: List[AnomalyEvent] = []

        for can_id_hex, group in grouped_frames.items():
            profile = self.baseline_profiles.get(can_id_hex)
            if (
                profile is None
                or profile.sample_count < self.config.min_baseline_samples
                or profile.median_interval <= 0
            ):
                # Insufficient baseline observations to reliably detect timing anomalies
                continue

            can_anomalies = self._analyze_can_id_stream(group, profile)
            all_anomalies.extend(can_anomalies)

        # Sort anomalies chronologically by timestamp
        all_anomalies.sort(key=lambda a: a.timestamp)
        self._last_anomalies = all_anomalies

        # Update ECU profiles based on analysis
        self._compute_ecu_profiles(frames, all_anomalies)

        return all_anomalies

    def _analyze_can_id_stream(
        self, group: List[Frame], profile: BaselineProfile
    ) -> List[AnomalyEvent]:
        """Analyze stream for a single CAN ID across all anomaly detectors."""
        nominal = profile.median_interval
        mean_period = profile.mean_interval
        std_period = profile.std_interval
        resolved_ecu = profile.ecu or self.can_id_to_ecu.get(profile.can_id) or group[0].ecu

        anomalies: List[AnomalyEvent] = []
        n_frames = len(group)
        if n_frames < 2:
            return anomalies

        # Intervals array: intervals[i] = group[i+1].timestamp - group[i].timestamp for i in 0..N-2
        intervals: List[float] = [
            round(group[i + 1].timestamp - group[i].timestamp, 9)
            for i in range(n_frames - 1)
        ]

        # -------------------------------------------------------------
        # 1. FLOODING BURST DETECTION (Aggregated)
        # -------------------------------------------------------------
        flooding_events, flooding_interval_indices = self._detect_flooding_bursts(
            group, intervals, profile, resolved_ecu
        )
        anomalies.extend(flooding_events)

        # -------------------------------------------------------------
        # 2. DUPLICATE PAYLOAD BURST DETECTION (Aggregated)
        # -------------------------------------------------------------
        duplicate_events, duplicate_interval_indices = self._detect_duplicate_bursts(
            group, intervals, profile, resolved_ecu
        )
        anomalies.extend(duplicate_events)

        # -------------------------------------------------------------
        # 3. TIMEOUT DETECTION & POINT TIMING DEVIATION DETECTION
        # -------------------------------------------------------------
        for idx, dt in enumerate(intervals):
            prev_frame = group[idx]
            curr_frame = group[idx + 1]

            # If this interval was already aggregated into a flooding burst or duplicate burst,
            # avoid duplicate alert storms
            if idx in flooding_interval_indices or idx in duplicate_interval_indices:
                continue

            # Check for Timeout
            if dt >= nominal * self.config.timeout_multiplier:
                missed_count = max(1, math.floor(round(dt / nominal, 6)) - 1)
                deviation = (dt - nominal) / nominal
                severity = self._evaluate_timeout_severity(missed_count, deviation)

                timeout_event = AnomalyEvent(
                    anomaly_type=AnomalyType.TIMING_TIMEOUT,
                    severity=severity,
                    can_id=profile.can_id,
                    ecu=resolved_ecu,
                    timestamp=curr_frame.timestamp,
                    start_time=prev_frame.timestamp,
                    end_time=curr_frame.timestamp,
                    observed_value=dt,
                    expected_value=nominal,
                    deviation=deviation,
                    abnormal_frame_count=missed_count + 1,
                    nominal_period=nominal,
                    observed_period=dt,
                    diagnosis=f"CAN message timeout detected; gap of {dt:.4f}s exceeds nominal period {nominal:.4f}s ({missed_count} estimated missed frames).",
                    possible_causes=[
                        "ECU offline/reset",
                        "CAN bus disconnection",
                        "Denial of service",
                        "ECU task starvation",
                    ],
                    evidence={
                        "nominal_period": round(nominal, 6),
                        "observed_gap": round(dt, 6),
                        "missed_messages": missed_count,
                        "last_seen_timestamp": round(prev_frame.timestamp, 6),
                        "resumed_timestamp": round(curr_frame.timestamp, 6),
                    },
                )
                anomalies.append(timeout_event)
                continue

            # Check for Single Timing Deviation (Jitter / Shift)
            if nominal > 0:
                relative_error = abs(dt - nominal) / nominal
                z_score = (abs(dt - mean_period) / std_period) if std_period > 0 else 0.0

                # Trigger if relative error exceeds threshold (and z_score if std > 0)
                is_anomalous = False
                if std_period > 0:
                    if (
                        relative_error > self.config.relative_deviation_threshold
                        and z_score > self.config.z_score_threshold
                    ):
                        is_anomalous = True
                else:
                    if relative_error > self.config.relative_deviation_threshold:
                        is_anomalous = True

                if is_anomalous:
                    severity = self._evaluate_deviation_severity(relative_error)
                    dev_event = AnomalyEvent(
                        anomaly_type=AnomalyType.TIMING_DEVIATION,
                        severity=severity,
                        can_id=profile.can_id,
                        ecu=resolved_ecu,
                        timestamp=curr_frame.timestamp,
                        start_time=prev_frame.timestamp,
                        end_time=curr_frame.timestamp,
                        observed_value=dt,
                        expected_value=nominal,
                        deviation=relative_error,
                        abnormal_frame_count=1,
                        nominal_period=nominal,
                        observed_period=dt,
                        diagnosis=f"Abnormal inter-frame timing interval: observed {dt:.4f}s vs nominal {nominal:.4f}s ({relative_error * 100:.1f}% deviation).",
                        possible_causes=[
                            "Clock drift or CPU scheduling jitter",
                            "Bus arbitration delay",
                            "Timing manipulation / injection",
                        ],
                        evidence={
                            "nominal_period": round(nominal, 6),
                            "observed_period": round(dt, 6),
                            "relative_error": round(relative_error, 4),
                            "z_score": round(z_score, 4) if std_period > 0 else "N/A (std=0)",
                        },
                    )
                    anomalies.append(dev_event)

        return anomalies

    def _detect_flooding_bursts(
        self,
        group: List[Frame],
        intervals: List[float],
        profile: BaselineProfile,
        ecu: Optional[str],
    ) -> Tuple[List[AnomalyEvent], Set[int]]:
        """
        Detect sustained high-frequency flooding bursts and aggregate into single events.
        Interval intervals[i] maps between frame group[i] and group[i+1].
        """
        events: List[AnomalyEvent] = []
        aggregated_indices: Set[int] = set()

        nominal = profile.median_interval
        flooding_threshold = nominal * self.config.flooding_ratio_threshold

        i = 0
        n_intervals = len(intervals)

        while i < n_intervals:
            if intervals[i] <= flooding_threshold:
                burst_start_idx = i
                burst_end_idx = i
                burst_intervals = [intervals[i]]

                while (
                    burst_end_idx + 1 < n_intervals
                    and intervals[burst_end_idx + 1] <= flooding_threshold
                ):
                    burst_end_idx += 1
                    burst_intervals.append(intervals[burst_end_idx])

                # Frame count is number of intervals + 1
                abnormal_frame_count = (burst_end_idx - burst_start_idx + 1) + 1

                if abnormal_frame_count >= self.config.flooding_min_burst_count:
                    start_time = group[burst_start_idx].timestamp
                    end_time = group[burst_end_idx + 1].timestamp
                    obs_period = statistics.mean(burst_intervals)
                    deviation = (nominal - obs_period) / nominal if nominal > 0 else 1.0

                    severity = (
                        Severity.CRITICAL
                        if abnormal_frame_count >= 20 or deviation >= 0.90
                        else Severity.HIGH
                    )

                    event = AnomalyEvent(
                        anomaly_type=AnomalyType.TIMING_FLOODING,
                        severity=severity,
                        can_id=profile.can_id,
                        ecu=ecu,
                        timestamp=start_time,
                        start_time=start_time,
                        end_time=end_time,
                        observed_value=obs_period,
                        expected_value=nominal,
                        deviation=deviation,
                        abnormal_frame_count=abnormal_frame_count,
                        nominal_period=nominal,
                        observed_period=obs_period,
                        diagnosis="Abnormally high-frequency CAN transmission; possible flooding, replay-like activity, or ECU malfunction.",
                        possible_causes=[
                            "CAN flooding",
                            "Replay-like transmission",
                            "ECU malfunction",
                        ],
                        evidence={
                            "nominal_period": round(nominal, 6),
                            "observed_period": round(obs_period, 6),
                            "repeat_count": abnormal_frame_count,
                            "start_time": round(start_time, 6),
                            "end_time": round(end_time, 6),
                            "burst_duration": round(end_time - start_time, 6),
                        },
                    )
                    events.append(event)
                    for k in range(burst_start_idx, burst_end_idx + 1):
                        aggregated_indices.add(k)

                i = burst_end_idx + 1
            else:
                i += 1

        return events, aggregated_indices

    def _detect_duplicate_bursts(
        self,
        group: List[Frame],
        intervals: List[float],
        profile: BaselineProfile,
        ecu: Optional[str],
    ) -> Tuple[List[AnomalyEvent], Set[int]]:
        """
        Detect rapid repeated identical payload bursts and aggregate into single events.
        Interval intervals[i] maps between frame group[i] and group[i+1].
        """
        events: List[AnomalyEvent] = []
        aggregated_indices: Set[int] = set()

        nominal = profile.median_interval
        dup_interval_threshold = nominal * self.config.duplicate_max_interval_factor

        i = 0
        n_intervals = len(intervals)

        while i < n_intervals:
            curr_payload = group[i].data
            next_payload = group[i + 1].data
            dt = intervals[i]

            # Check if payload is identical AND transmitted unusually fast compared to nominal
            if curr_payload and curr_payload == next_payload and dt <= dup_interval_threshold:
                burst_start_idx = i
                burst_end_idx = i
                burst_intervals = [dt]

                while burst_end_idx + 1 < n_intervals:
                    next_dt = intervals[burst_end_idx + 1]
                    following_payload = group[burst_end_idx + 2].data
                    if following_payload == curr_payload and next_dt <= dup_interval_threshold:
                        burst_end_idx += 1
                        burst_intervals.append(next_dt)
                    else:
                        break

                repeat_count = (burst_end_idx - burst_start_idx + 1) + 1

                if repeat_count >= self.config.duplicate_min_repeat_count:
                    start_time = group[burst_start_idx].timestamp
                    end_time = group[burst_end_idx + 1].timestamp
                    avg_int = statistics.mean(burst_intervals)
                    deviation = (nominal - avg_int) / nominal if nominal > 0 else 1.0

                    severity = Severity.CRITICAL if repeat_count >= 10 else Severity.HIGH

                    event = AnomalyEvent(
                        anomaly_type=AnomalyType.DUPLICATE_BURST,
                        severity=severity,
                        can_id=profile.can_id,
                        ecu=ecu,
                        timestamp=start_time,
                        start_time=start_time,
                        end_time=end_time,
                        observed_value=avg_int,
                        expected_value=nominal,
                        deviation=deviation,
                        abnormal_frame_count=repeat_count,
                        nominal_period=nominal,
                        observed_period=avg_int,
                        diagnosis="Repeated identical payload burst transmitted at unusually high rate; possible replay attack or ECU sensor fault.",
                        possible_causes=[
                            "Replay attack",
                            "ECU sensor latching fault",
                            "High-frequency replay injection",
                        ],
                        evidence={
                            "payload": curr_payload,
                            "repeat_count": repeat_count,
                            "average_interval": round(avg_int, 6),
                            "nominal_period": round(nominal, 6),
                            "start_time": round(start_time, 6),
                            "end_time": round(end_time, 6),
                        },
                    )
                    events.append(event)
                    for k in range(burst_start_idx, burst_end_idx + 1):
                        aggregated_indices.add(k)

                i = burst_end_idx + 1
            else:
                i += 1

        return events, aggregated_indices

    def _evaluate_deviation_severity(self, relative_error: float) -> Severity:
        """Assign explainable severity based on relative timing deviation magnitude."""
        if relative_error >= self.config.severity_critical_deviation:
            return Severity.CRITICAL
        if relative_error >= self.config.severity_high_deviation:
            return Severity.HIGH
        if relative_error >= self.config.severity_medium_deviation:
            return Severity.MEDIUM
        return Severity.LOW

    def _evaluate_timeout_severity(self, missed_messages: int, deviation: float) -> Severity:
        """Assign severity for communication timeout based on missed message count."""
        if missed_messages >= 10 or deviation >= 10.0:
            return Severity.CRITICAL
        if missed_messages >= 3 or deviation >= 3.0:
            return Severity.HIGH
        return Severity.MEDIUM

    def _group_and_sort_frames(self, frames: Sequence[Frame]) -> Dict[str, List[Frame]]:
        """Group frames by normalized CAN ID hex string and sort each group chronologically."""
        grouped: Dict[str, List[Frame]] = defaultdict(list)
        for frame in frames:
            grouped[frame.can_id_hex].append(frame)

        # Sort each group by timestamp
        for can_id_hex in grouped:
            grouped[can_id_hex].sort(key=lambda f: f.timestamp)

        return grouped

    def _compute_ecu_profiles(
        self, frames: Sequence[Frame], anomalies: Sequence[AnomalyEvent]
    ) -> Dict[str, ECUProfile]:
        """Aggregate behavioral and timing metrics per ECU."""
        ecu_frame_map: Dict[str, List[Frame]] = defaultdict(list)
        ecu_can_ids: Dict[str, Set[str]] = defaultdict(set)

        for frame in frames:
            # Fallback to CAN ID -> ECU mapping if frame.ecu is missing
            ecu_name = frame.ecu or self.can_id_to_ecu.get(frame.can_id_hex) or "UNKNOWN"
            ecu_frame_map[ecu_name].append(frame)
            ecu_can_ids[ecu_name].add(frame.can_id_hex)

        # Count anomalies per ECU
        ecu_anomaly_counts: Dict[str, int] = defaultdict(int)
        ecu_timeout_counts: Dict[str, int] = defaultdict(int)
        ecu_duplicate_counts: Dict[str, int] = defaultdict(int)

        for anom in anomalies:
            ecu_name = anom.ecu or self.can_id_to_ecu.get(anom.can_id) or "UNKNOWN"
            ecu_anomaly_counts[ecu_name] += 1
            anom_type = (
                anom.anomaly_type.value
                if isinstance(anom.anomaly_type, AnomalyType)
                else str(anom.anomaly_type)
            )
            if anom_type == AnomalyType.TIMING_TIMEOUT.value:
                ecu_timeout_counts[ecu_name] += 1
            elif anom_type == AnomalyType.DUPLICATE_BURST.value:
                ecu_duplicate_counts[ecu_name] += 1

        self.ecu_profiles.clear()

        for ecu_name, ecu_frames in ecu_frame_map.items():
            msg_count = len(ecu_frames)
            can_list = sorted(list(ecu_can_ids[ecu_name]))

            if msg_count > 1:
                times = [f.timestamp for f in sorted(ecu_frames, key=lambda f: f.timestamp)]
                span = times[-1] - times[0]
                freq = (msg_count - 1) / span if span > 0 else 0.0

                intervals = [round(times[i] - times[i - 1], 9) for i in range(1, len(times))]
                variance = statistics.variance(intervals) if len(intervals) >= 2 else 0.0
                if abs(variance) < 1e-9:
                    variance = 0.0
            else:
                freq = 0.0
                variance = 0.0

            dup_rate = (ecu_duplicate_counts[ecu_name] / msg_count) if msg_count > 0 else 0.0

            self.ecu_profiles[ecu_name] = ECUProfile(
                ecu=ecu_name,
                message_count=msg_count,
                can_ids=can_list,
                nominal_frequency=freq,
                timing_variance=variance,
                duplicate_rate=dup_rate,
                timeout_occurrences=ecu_timeout_counts[ecu_name],
                timing_anomaly_count=ecu_anomaly_counts[ecu_name],
            )

        return self.ecu_profiles

    def get_profiles(self) -> Dict[str, Any]:
        """Return fitted baseline profiles and ECU behavioral profiles."""
        return {
            "baseline_profiles": [p.to_dict() for p in self.baseline_profiles.values()],
            "ecu_profiles": [p.to_dict() for p in self.ecu_profiles.values()],
        }

    def generate_report(self, frames: Sequence[Frame]) -> Dict[str, Any]:
        """
        Generate a complete JSON-serializable anomaly analysis report.

        Matches required schema with profiles, anomalies, and summary.
        """
        anomalies = self.analyze(frames)
        profiles_data = [p.to_dict() for p in self.baseline_profiles.values()]
        anomalies_data = [a.to_dict() for a in anomalies]
        ecu_data = [p.to_dict() for p in self.ecu_profiles.values()]

        # Severity breakdown
        sev_counts: Dict[str, int] = defaultdict(int)
        type_counts: Dict[str, int] = defaultdict(int)

        for a in anomalies:
            sev_str = a.severity.value if isinstance(a.severity, Severity) else str(a.severity)
            anom_str = (
                a.anomaly_type.value
                if isinstance(a.anomaly_type, AnomalyType)
                else str(a.anomaly_type)
            )
            sev_counts[sev_str] += 1
            type_counts[anom_str] += 1

        summary = {
            "total_frames": len(frames),
            "total_can_ids": len(self.baseline_profiles),
            "total_anomalies": len(anomalies),
            "critical_severity": sev_counts[Severity.CRITICAL.value],
            "high_severity": sev_counts[Severity.HIGH.value],
            "medium_severity": sev_counts[Severity.MEDIUM.value],
            "low_severity": sev_counts[Severity.LOW.value],
            "anomaly_type_counts": dict(type_counts),
        }

        return {
            "summary": summary,
            "profiles": profiles_data,
            "ecu_profiles": ecu_data,
            "anomalies": anomalies_data,
        }
