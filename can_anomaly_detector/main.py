"""
main.py
CLI entry point for the CAN Bus Contradictory Signal & Correlation Anomaly Detector.

Usage:
  python main.py --dbc CAN.dbc --log CAN.log.txt
  python main.py --dbc CAN.dbc --log CAN.log.txt --output results.json
  python main.py --dbc CAN.dbc --log CAN.log.txt --verbose
"""

import sys
import os
import argparse
import logging
import traceback
from typing import Optional, List
from dbc_parser import DBCParser
from detector import AnomalyDetector
from reporter import AnomalyReporter

# Differentiated CLI exit codes
EXIT_SUCCESS = 0
EXIT_INVALID_ARGS = 2
EXIT_FILE_NOT_FOUND = 3
EXIT_DBC_ERROR = 4
EXIT_LOG_ERROR = 5
EXIT_OUTPUT_ERROR = 6
EXIT_RUNTIME_ERROR = 7


def configure_logging(verbose: bool = False, log_file: Optional[str] = None):
    """Configure standard logging format and output streams."""
    log_level = logging.DEBUG if verbose else logging.INFO
    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stderr)]

    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True
    )


def parse_args(args: Optional[List[str]] = None):
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="CAN Bus Contradictory Signal & Signal Correlation Anomaly Detector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit Codes:
  0 : Success
  2 : Invalid CLI arguments (e.g. directory passed instead of file)
  3 : Input file not found
  4 : DBC parsing error
  5 : Log parsing / detection runtime error
  6 : Output report writing error
  7 : General unexpected runtime error

Examples:
  python main.py --dbc CAN.dbc --log CAN.log.txt
  python main.py --dbc CAN.dbc --log CAN.log.txt --output results.json
  python main.py --dbc CAN.dbc --log CAN.log.txt --output results.json --verbose
        """
    )
    parser.add_argument(
        "--dbc",
        type=str,
        required=True,
        help="Path to automotive DBC definition file (e.g. CAN.dbc)"
    )
    parser.add_argument(
        "--log",
        type=str,
        required=True,
        help="Path to Vector ASC CAN log file (e.g. CAN.log.txt)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional path to save anomaly report in JSON format (e.g. results.json)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable detailed verbose / debug logging and tracebacks"
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Optional path to save diagnostic execution logs"
    )
    return parser.parse_args(args)


def run_pipeline(args) -> int:
    """Execute the anomaly detection pipeline with granular error stages and salvage logic."""
    logger = logging.getLogger("can_detector")

    # 1. Validate input paths: existence and file type checks
    for label, path in [("DBC", args.dbc), ("Log", args.log)]:
        if not os.path.exists(path):
            logger.error(f"{label} file not found: '{path}'")
            print(f"Error: {label} file not found at: {path}", file=sys.stderr)
            return EXIT_FILE_NOT_FOUND
        if os.path.isdir(path):
            logger.error(f"{label} path is a directory, not a file: '{path}'")
            print(f"Error: {label} path must point to a file, got directory: {path}", file=sys.stderr)
            return EXIT_INVALID_ARGS

    if args.output and os.path.isdir(args.output):
        logger.error(f"Output path is a directory: '{args.output}'")
        print(f"Error: Output path must point to a target file, got directory: {args.output}", file=sys.stderr)
        return EXIT_INVALID_ARGS

    # Initialize Detector
    detector = AnomalyDetector()

    # 2. Stage: DBC Parsing
    try:
        logger.info(f"Parsing DBC file from: {args.dbc}")
        detector.load_dbc(args.dbc)
        if detector.db is not None:
            logger.info(f"Loaded DBC successfully with {len(detector.db.messages)} message definitions.")
    except Exception as e:
        logger.error(f"[DBC Parsing Error] Failed to parse DBC file '{args.dbc}': {e}", exc_info=args.verbose)
        print(f"Error [Stage: DBC Parsing]: Failed to parse DBC definition from '{args.dbc}': {e}", file=sys.stderr)
        if args.verbose:
            traceback.print_exc()
        return EXIT_DBC_ERROR

    # 3. Stage: Log Processing & Anomaly Detection
    anomalies = []
    try:
        logger.info(f"Processing CAN log file from: {args.log}")
        anomalies = detector.process_log(args.log)
        logger.info(f"Log processing complete. Total anomalies detected: {len(anomalies)}")
    except Exception as e:
        logger.error(f"[Log Processing Error] Failure while processing log file '{args.log}': {e}", exc_info=args.verbose)
        print(f"Error [Stage: Log Processing]: Failure occurred while reading '{args.log}': {e}", file=sys.stderr)
        
        # Salvage partial results if anomalies were detected before crash
        partial_anomalies = detector.detected_anomalies
        if partial_anomalies:
            print(f"\n[SALVAGED] Partial anomalies detected prior to interruption ({len(partial_anomalies)} events):", file=sys.stderr)
            AnomalyReporter.print_console_report(partial_anomalies)
            if args.output:
                try:
                    AnomalyReporter.export_json(partial_anomalies, args.output)
                    print(f"[INFO] Partial JSON report saved to: {args.output}", file=sys.stderr)
                except Exception as export_err:
                    logger.error(f"Failed writing partial JSON: {export_err}")

        if args.verbose:
            traceback.print_exc()
        return EXIT_LOG_ERROR

    # 4. Stage: Console Report Display
    AnomalyReporter.print_console_report(anomalies)

    # 5. Stage: JSON Export
    if args.output:
        try:
            logger.info(f"Exporting results to: {args.output}")
            AnomalyReporter.export_json(anomalies, args.output)
            print(f"\n[INFO] JSON report exported to: {args.output}")
        except Exception as e:
            logger.error(f"[JSON Export Error] Failed to write report to '{args.output}': {e}", exc_info=args.verbose)
            print(f"Error [Stage: JSON Export]: Failed to export report to '{args.output}': {e}", file=sys.stderr)
            if args.verbose:
                traceback.print_exc()
            return EXIT_OUTPUT_ERROR

    return EXIT_SUCCESS


def main(args: Optional[List[str]] = None):
    parsed = parse_args(args)
    configure_logging(verbose=parsed.verbose, log_file=parsed.log_file)
    try:
        exit_code = run_pipeline(parsed)
    finally:
        logging.shutdown()

    if exit_code != EXIT_SUCCESS and args is None:
        sys.exit(exit_code)
    return exit_code


if __name__ == "__main__":
    main()
