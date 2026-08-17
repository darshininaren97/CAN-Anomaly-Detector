"""
Command-line interface for the Temporal / Timing / Behavioral CAN Anomaly Detection Module.

Usage:
    python -m timing_module [path_to_can_log.json]
    python -m timing_module examples/anomalous.json --baseline examples/normal.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from timing_module.config import TimingConfig
from timing_module.parser_adapter import ParserAdapter
from timing_module.timing_analyzer import TimingAnalyzer

# Package root directory (where timing_module/ package resides)
PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def resolve_file_path(path_str: Union[str, Path], base_dir: Path) -> Path:
    """
    Resolve a file path by checking:
    1. Absolute path
    2. Relative to current working directory (Path.cwd())
    3. Relative to the package root directory
    """
    p = Path(path_str)
    if p.is_absolute() and p.exists():
        return p
    cwd_path = Path.cwd() / p
    if cwd_path.exists():
        return cwd_path.resolve()
    pkg_path = base_dir / p
    if pkg_path.exists():
        return pkg_path.resolve()
    # Return cwd-based path if not found so error reports reflect user's cwd
    return cwd_path


def safe_format_float(val: Any, decimals: int = 4, default: str = "N/A") -> str:
    """Safely format a numeric value without raising TypeError on None or non-floats."""
    if val is None:
        return default
    try:
        return f"{float(val):.{decimals}f}"
    except (ValueError, TypeError):
        return default


def format_header(title: str, width: int = 72) -> str:
    """Format a decorative section header."""
    return f"\n{'=' * width}\n {title}\n{'=' * width}"


def run_cli(
    input_path: Optional[str] = None,
    baseline_path: Optional[str] = None,
    config_path: Optional[str] = None,
    output_path: Optional[str] = None,
    parsed_output_path: Optional[str] = None,
    allow_self_baseline: bool = False,
) -> int:
    """Run CLI analysis pipeline with strict validation and safe path resolution."""
    # 1. Resolve Target Input Log File
    if input_path:
        target_file = resolve_file_path(input_path, PACKAGE_ROOT)
    else:
        target_file = resolve_file_path("examples/anomalous.json", PACKAGE_ROOT)
        if not target_file.exists():
            target_file = resolve_file_path("examples/normal.json", PACKAGE_ROOT)

    if not target_file.exists():
        print(f"[ERROR] Target CAN log file not found: {input_path or target_file}", file=sys.stderr)
        return 1

    # 2. Resolve Baseline Training File
    if baseline_path:
        baseline_file = resolve_file_path(baseline_path, PACKAGE_ROOT)
        if not baseline_file.exists():
            print(f"[ERROR] Specified baseline file not found: {baseline_path}", file=sys.stderr)
            return 1
    else:
        default_normal = resolve_file_path("examples/normal.json", PACKAGE_ROOT)
        if default_normal.exists() and target_file.resolve() != default_normal.resolve():
            baseline_file = default_normal
        elif allow_self_baseline:
            baseline_file = target_file
        elif default_normal.exists():
            baseline_file = default_normal
        else:
            print(
                "[ERROR] No baseline dataset specified. Please provide --baseline <path_to_clean_nominal.json> "
                "or ensure examples/normal.json exists.",
                file=sys.stderr,
            )
            return 1

    # 3. Resolve Configuration File
    if config_path:
        resolved_cfg_path = resolve_file_path(config_path, PACKAGE_ROOT)
        if not resolved_cfg_path.exists():
            print(f"[ERROR] Specified configuration file not found: {config_path}", file=sys.stderr)
            return 1
        try:
            config = TimingConfig.from_json_file(resolved_cfg_path)
            used_config_str = str(resolved_cfg_path)
        except Exception as e:
            print(f"[ERROR] Failed to parse configuration file '{resolved_cfg_path}': {e}", file=sys.stderr)
            return 1
    else:
        default_cfg = resolve_file_path("config.json", PACKAGE_ROOT)
        if default_cfg.exists():
            config = TimingConfig.from_json_file(default_cfg)
            used_config_str = str(default_cfg)
        else:
            config = TimingConfig()
            used_config_str = "Default In-Memory Configuration"

    print(format_header("CAN BUS TEMPORAL & BEHAVIORAL ANOMALY DETECTOR"))
    print(f"Target CAN Log File : {target_file}")
    print(f"Baseline Data File  : {baseline_file}")
    print(f"Configuration File  : {used_config_str}")

    adapter = ParserAdapter()

    # 4. Ingest & Fit Baseline Frames
    try:
        baseline_frames = adapter.parse_json_file(baseline_file)
    except Exception as e:
        print(f"[ERROR] Failed to ingest baseline file '{baseline_file}': {e}", file=sys.stderr)
        return 1

    analyzer = TimingAnalyzer(config=config)
    analyzer.fit(baseline_frames)
    print(f"Baseline Fitted     : {len(baseline_frames)} frames across {len(analyzer.baseline_profiles)} CAN IDs")

    # 5. Ingest & Normalize Evaluation Frames
    try:
        eval_frames = adapter.parse_json_file(target_file)
    except Exception as e:
        print(f"[ERROR] Failed to ingest evaluation file '{target_file}': {e}", file=sys.stderr)
        return 1

    print(f"Evaluation Frames   : {len(eval_frames)} frames")

    # 6. Run Timing and Behavioral Anomaly Detection
    try:
        report = analyzer.generate_report(eval_frames)
    except Exception as e:
        print(f"[ERROR] Anomaly detection engine failure: {e}", file=sys.stderr)
        return 1

    # 7. Print Formatted Terminal Summary
    summary: Dict[str, Any] = report.get("summary", {})
    profiles: List[Dict[str, Any]] = report.get("profiles", [])
    anomalies: List[Dict[str, Any]] = report.get("anomalies", [])
    ecu_profiles: List[Dict[str, Any]] = report.get("ecu_profiles", [])

    print(format_header("BASELINE TIMING PROFILES"))
    print(f"{'CAN ID':<10} {'ECU':<8} {'Nominal (s)':<14} {'Mean (s)':<12} {'Std (s)':<12} {'FPS':<8} {'Count':<8}")
    print(f"{'-' * 10} {'-' * 8} {'-' * 14} {'-' * 12} {'-' * 12} {'-' * 8} {'-' * 8}")
    for p in profiles:
        can_id = str(p.get("can_id", "N/A"))
        ecu = str(p.get("ecu", "N/A"))
        nom_str = safe_format_float(p.get("nominal_period"))
        mean_str = safe_format_float(p.get("mean_period"))
        std_str = safe_format_float(p.get("std_period"))
        fps_str = safe_format_float(p.get("frames_per_second"), decimals=1)
        count_str = str(p.get("sample_count", "0"))
        print(f"{can_id:<10} {ecu:<8} {nom_str:<14} {mean_str:<12} {std_str:<12} {fps_str:<8} {count_str:<8}")

    if ecu_profiles:
        print(format_header("ECU BEHAVIORAL PROFILES"))
        print(f"{'ECU':<10} {'Messages':<10} {'Nominal Freq (Hz)':<20} {'Variance':<14} {'Timeouts':<10} {'Anomalies':<10}")
        print(f"{'-' * 10} {'-' * 10} {'-' * 20} {'-' * 14} {'-' * 10} {'-' * 10}")
        for ep in ecu_profiles:
            ecu = str(ep.get("ecu", "N/A"))
            msg_cnt = str(ep.get("message_count", "0"))
            freq_str = safe_format_float(ep.get("nominal_frequency"), decimals=2)
            var_str = safe_format_float(ep.get("timing_variance"), decimals=6)
            to_cnt = str(ep.get("timeout_occurrences", "0"))
            anom_cnt = str(ep.get("timing_anomaly_count", "0"))
            print(f"{ecu:<10} {msg_cnt:<10} {freq_str:<20} {var_str:<14} {to_cnt:<10} {anom_cnt:<10}")

    print(format_header("DETECTED ANOMALIES"))
    if not anomalies:
        print("  [OK] No temporal or behavioral anomalies detected. Traffic is nominal.")
    else:
        print(f"Total Anomalies Detected: {len(anomalies)}")
        for idx, anom in enumerate(anomalies, 1):
            st = anom.get("start_time")
            et = anom.get("end_time")
            ts = anom.get("timestamp")

            if st is not None and et is not None and st != et:
                time_str = f"t={safe_format_float(st)}s -> t={safe_format_float(et)}s"
            else:
                primary_ts = ts if ts is not None else (st if st is not None else 0.0)
                time_str = f"t={safe_format_float(primary_ts)}s"

            sev = str(anom.get("severity", "UNKNOWN"))
            atype = str(anom.get("anomaly_type", "UNKNOWN"))
            can_id = str(anom.get("can_id", "N/A"))
            ecu = str(anom.get("ecu", "N/A"))
            diag = str(anom.get("diagnosis", "No diagnosis provided."))
            causes = anom.get("possible_causes", [])
            evidence = anom.get("evidence", {})

            print(f"\n  [{idx}] [{sev}] {atype} on {can_id} ({ecu}) at {time_str}")
            print(f"      Diagnosis      : {diag}")
            if causes:
                print(f"      Possible Causes: {', '.join(str(c) for c in causes)}")
            if evidence:
                evidence_str = ", ".join(f"{k}={v}" for k, v in evidence.items())
                print(f"      Evidence       : {evidence_str}")

    print(format_header("ANALYSIS SUMMARY"))
    print(f"  Total Processed Frames : {summary.get('total_frames', len(eval_frames))}")
    print(f"  Total CAN IDs Tracked  : {summary.get('total_can_ids', len(profiles))}")
    print(f"  Total Anomalies Found  : {summary.get('total_anomalies', len(anomalies))}")
    print(f"    - CRITICAL Severity  : {summary.get('critical_severity', 0)}")
    print(f"    - HIGH Severity      : {summary.get('high_severity', 0)}")
    print(f"    - MEDIUM Severity    : {summary.get('medium_severity', 0)}")
    print(f"    - LOW Severity       : {summary.get('low_severity', 0)}")

    # 8. Save Anomaly Report JSON
    out_dir = PACKAGE_ROOT / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_file = Path(output_path) if output_path else out_dir / "anomaly_report.json"
    report_file.parent.mkdir(parents=True, exist_ok=True)

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\n[SAVED] Anomaly report written to: {report_file}")

    # 9. Save Normalized Frames JSON (Parsed Output)
    parsed_file = Path(parsed_output_path) if parsed_output_path else out_dir / "parsed_frames.json"
    parsed_file.parent.mkdir(parents=True, exist_ok=True)

    normalized_frames_dict = [f.to_dict() for f in eval_frames]
    with open(parsed_file, "w", encoding="utf-8") as f:
        json.dump(normalized_frames_dict, f, indent=2)
    print(f"[SAVED] Normalized frames written to: {parsed_file}")

    # Also maintain examples/parsed_output.json containing normalized frames
    legacy_parsed_file = PACKAGE_ROOT / "examples" / "parsed_output.json"
    if legacy_parsed_file.parent.exists():
        with open(legacy_parsed_file, "w", encoding="utf-8") as f:
            json.dump(normalized_frames_dict, f, indent=2)

    return 0


def main() -> None:
    """Entry point for python -m timing_module."""
    parser = argparse.ArgumentParser(
        description="Offline Temporal and Behavioral CAN Bus Anomaly Detector"
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        default=None,
        help="Path to CAN log JSON file to evaluate (defaults to examples/anomalous.json)",
    )
    parser.add_argument(
        "--baseline",
        "-b",
        default=None,
        help="Path to clean baseline CAN log JSON file for nominal training",
    )
    parser.add_argument(
        "--config",
        "-c",
        default=None,
        help="Path to custom config.json file",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Path to write anomaly report JSON (defaults to output/anomaly_report.json)",
    )
    parser.add_argument(
        "--parsed-output",
        "-p",
        default=None,
        help="Path to write normalized frames JSON (defaults to output/parsed_frames.json)",
    )
    parser.add_argument(
        "--allow-self-baseline",
        action="store_true",
        help="Allow fitting baseline on the evaluation log if no separate baseline is provided",
    )

    args = parser.parse_args()
    sys.exit(
        run_cli(
            input_path=args.input_file,
            baseline_path=args.baseline,
            config_path=args.config,
            output_path=args.output,
            parsed_output_path=args.parsed_output,
            allow_self_baseline=args.allow_self_baseline,
        )
    )


if __name__ == "__main__":
    main()