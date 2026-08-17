"""
Command-line interface for the Temporal / Timing / Behavioral CAN Anomaly Detection Module.

Usage:
    python -m timing_module [path_to_can_log.json]
    python -m timing_module examples/anomalous.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from timing_module.config import TimingConfig
from timing_module.parser_adapter import ParserAdapter
from timing_module.timing_analyzer import TimingAnalyzer


def format_header(title: str, width: int = 72) -> str:
    """Format a decorative section header."""
    return f"\n{'=' * width}\n {title}\n{'=' * width}"


def run_cli(
    input_path: Optional[str] = None,
    config_path: Optional[str] = None,
    output_path: Optional[str] = None,
) -> int:
    """Run CLI analysis pipeline."""
    # Resolve input file
    project_root = Path.cwd()
    if input_path:
        target_file = Path(input_path)
    else:
        # Default to examples/anomalous.json
        target_file = project_root / "examples" / "anomalous.json"
        if not target_file.exists():
            target_file = project_root / "examples" / "normal.json"

    if not target_file.exists():
        print(f"[ERROR] Input file not found: {target_file}", file=sys.stderr)
        return 1

    # Load configuration
    config = TimingConfig()
    if config_path and Path(config_path).exists():
        config = TimingConfig.from_json_file(config_path)
    elif (project_root / "config.json").exists():
        config = TimingConfig.from_json_file(project_root / "config.json")

    print(format_header("CAN BUS TEMPORAL & BEHAVIORAL ANOMALY DETECTOR"))
    print(f"Target CAN Log File : {target_file}")
    print(f"Configuration File  : {config_path or 'config.json'}")

    # 1. Parse & Normalize
    adapter = ParserAdapter()
    try:
        frames = adapter.parse_json_file(target_file)
    except Exception as e:
        print(f"[ERROR] Failed to parse input file: {e}", file=sys.stderr)
        return 1

    print(f"Loaded Frames       : {len(frames)} frames")

    # 2. Fit Baseline & Analyze
    analyzer = TimingAnalyzer(config=config)
    analyzer.fit(frames)
    report = analyzer.generate_report(frames)

    # 3. Print Summary to Terminal
    summary = report["summary"]
    profiles = report["profiles"]
    anomalies = report["anomalies"]
    ecu_profiles = report["ecu_profiles"]

    print(format_header("BASELINE TIMING PROFILES"))
    print(f"{'CAN ID':<10} {'ECU':<8} {'Nominal (s)':<14} {'Mean (s)':<12} {'Std (s)':<12} {'FPS':<8} {'Count':<8}")
    print(f"{'-' * 10} {'-' * 8} {'-' * 14} {'-' * 12} {'-' * 12} {'-' * 8} {'-' * 8}")
    for p in profiles:
        print(
            f"{p['can_id']:<10} {p['ecu']:<8} {p['nominal_period']:<14.4f} "
            f"{p['mean_period']:<12.4f} {p['std_period']:<12.4f} "
            f"{p['frames_per_second']:<8.1f} {p['sample_count']:<8}"
        )

    if ecu_profiles:
        print(format_header("ECU BEHAVIORAL PROFILES"))
        print(f"{'ECU':<10} {'Messages':<10} {'Nominal Freq (Hz)':<20} {'Variance':<14} {'Timeouts':<10} {'Anomalies':<10}")
        print(f"{'-' * 10} {'-' * 10} {'-' * 20} {'-' * 14} {'-' * 10} {'-' * 10}")
        for ep in ecu_profiles:
            print(
                f"{ep['ecu']:<10} {ep['message_count']:<10} {ep['nominal_frequency']:<20.2f} "
                f"{ep['timing_variance']:<14.6f} {ep['timeout_occurrences']:<10} {ep['timing_anomaly_count']:<10}"
            )

    print(format_header("DETECTED ANOMALIES"))
    if not anomalies:
        print("  [OK] No temporal or behavioral anomalies detected. Traffic is nominal.")
    else:
        print(f"Total Anomalies Detected: {len(anomalies)}")
        for idx, anom in enumerate(anomalies, 1):
            time_str = f"t={anom.get('timestamp', anom.get('start_time', 0.0)):.4f}s"
            if "end_time" in anom:
                time_str += f" -> t={anom['end_time']:.4f}s"
            sev = anom["severity"]
            atype = anom["anomaly_type"]
            can_id = anom["can_id"]
            ecu = anom.get("ecu", "N/A")
            diag = anom["diagnosis"]

            print(f"\n  [{idx}] [{sev}] {atype} on {can_id} ({ecu}) at {time_str}")
            print(f"      Diagnosis      : {diag}")
            print(f"      Possible Causes: {', '.join(anom['possible_causes'])}")
            evidence_str = ", ".join(f"{k}={v}" for k, v in anom["evidence"].items())
            print(f"      Evidence       : {evidence_str}")

    print(format_header("ANALYSIS SUMMARY"))
    print(f"  Total Processed Frames : {summary['total_frames']}")
    print(f"  Total CAN IDs Tracked  : {summary['total_can_ids']}")
    print(f"  Total Anomalies Found  : {summary['total_anomalies']}")
    print(f"    - CRITICAL Severity  : {summary['critical_severity']}")
    print(f"    - HIGH Severity      : {summary['high_severity']}")
    print(f"    - MEDIUM Severity    : {summary['medium_severity']}")
    print(f"    - LOW Severity       : {summary['low_severity']}")

    # 4. Save JSON Outputs
    # Save to output/anomaly_report.json
    output_dir = project_root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_file = Path(output_path) if output_path else output_dir / "anomaly_report.json"

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\n[SAVED] Anomaly report written to: {report_file}")

    # Also save to examples/parsed_output.json for convenience
    parsed_output_file = project_root / "examples" / "parsed_output.json"
    parsed_output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(parsed_output_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"[SAVED] Parsed output written to : {parsed_output_file}\n")

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
        help="Path to CAN log JSON file (defaults to examples/anomalous.json)",
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

    args = parser.parse_args()
    sys.exit(run_cli(args.input_file, args.config, args.output))


if __name__ == "__main__":
    main()
