
# CAN Bus  Anomaly Detector

## What is this?

Cars use an internal network called **CAN bus** for all their electronic
parts (engine, brakes, airbags, etc.) to talk to each other. Each message on
this network is just a number ID plus a handful of raw bytes — not human
readable on its own.

This project is a tool that:

1. Reads a **DBC file**, which is like a dictionary that explains what each
   CAN message ID means and how to turn its raw bytes into real values
   (e.g. "ID 0x1A0 = Vehicle Speed, in km/h").
2. Reads a **CAN log file** — a recording of real messages that were sent on
   the bus over time.
3. Uses the DBC dictionary to decode the raw log into readable signal values.
4. Checks those decoded values for signs of trouble — sensor values that
   don't make sense, messages that arrive too fast, too slow, or not at all,
   signals that contradict each other, corrupted data, and so on.
5. Prints a report of everything suspicious it found, and can also save that
   report as a file or draw it as a chart-filled webpage.

In short: **you give it a DBC file and a log file, and it tells you what
looks wrong with the traffic.**

## How it is implemented

The project is plain Python (no external libraries needed to run it) and is
organized as a pipeline with clearly separated stages:

1. **Parsing (`parsers/`)**
   - `dbc_parser.py` reads the DBC file and builds a lookup table of message
     IDs, signal names, bit positions, scaling, and valid min/max ranges.
   - `log_parser.py` reads the CAN log file (plain text, Vector ASC, or JSON)
     line by line and turns each line into a raw `CANFrame` (ID + bytes +
     timestamp).
   - `signal_decoder.py` combines the two: for every raw frame, it looks up
     the matching DBC message and extracts the actual signal values, producing
     a `DecodedFrame`.

2. **Detection (`detectors/`)**
   Once frames are decoded, five independent "detector" modules each scan the
   same data looking for a different kind of problem. Every detector follows
   the same interface (`detectors/base.py`), so they can be swapped in or out
   without touching the rest of the code:
   - **Range** – is a decoded value outside the min/max the DBC says it
     should be?
   - **Logic** – do two or more signals contradict each other, or does a
     signal change in a way that breaks a known rule (checked using a small
     history of past values)?
   - **Timing** – is a message arriving too often (flooding), repeating the
     exact same payload too many times in a row, jittering unusually, or
     missing when it was expected?
   - **Frame** – does the raw frame's length match what the DBC says it
     should be, or is it malformed?
   - **Integrity** – has a message timed out, does its data look corrupted,
     or does its checksum/CRC fail to validate?

   A `DetectorRegistry` (`detectors/registry.py`) keeps a list of all
   available detectors and builds the ones the user asked for (or all of
   them, by default).

3. **Orchestration (`core/pipeline.py`)**
   The `UnifiedAnomalyPipeline` class ties everything together: it parses the
   DBC, parses the log, decodes the frames, runs each selected detector in
   turn (catching and logging any single detector's failure without
   crashing the whole run), and collects every finding into one combined
   list.

4. **Aggregation & Reporting (`core/aggregator.py`, `core/reporter.py`)**
   All findings from every detector are merged into a common `UnifiedAnomaly`
   format (same fields regardless of which detector found it), then counted
   and grouped by severity and category. The reporter turns this into a
   human-readable text report, JSON, or CSV.

5. **Dashboard (`core/dashboard.py`)**
   Optionally, the pipeline can also produce a single self-contained HTML
   file that plots each signal's timeline, shows which CAN IDs were active
   when, and summarizes anomalies visually, using the bundled Chart.js file
   in `dashboard/static/` — no internet connection or server needed to view
   it.

The detector adapters in `detectors/` don't reimplement their logic from
scratch — they wrap and reuse standalone modules that were originally
built and tested on their own (`can_anomaly_detector_logic`,
`can_integrity_detector`, `can_range_anomaly_detector_outofrange`, and
`timing_module`). Those folders are still part of the project and are
imported directly by the matching detector.

## Does it work with other DBC/log files, or only the sample?

We built and tested this against the sample `CAN.dbc` / `CAN_log.txt` files
included in the repo (a small mock vehicle network). Whether it also works
on a file you bring yourself depends on which detector you're looking at:

**Works with other files, most likely yes:**
- **Parsing** (`dbc_parser.py`, `log_parser.py`, `signal_decoder.py`) follows
  the standard DBC syntax (`BO_`, `SG_`, `VAL_`, `CM_`) and standard log
  formats (Vector ASC, plain text, or JSON), so it isn't tied to our sample
  file's contents.
- **Range**, **Frame**, **Timing**, and **Integrity** detectors read their
  thresholds and rules straight from whatever DBC file you give them (min/max
  values, DLC, timing config), so they should work on a different real-world
  DBC/log pair too.

**Works with other files, likely not (as-is):**
- The **Logic** detector is the exception. Its rules (in
  `can_anomaly_detector_logic/rules/`) check for specific signal names we
  used in our sample DBC — things like `Vehicle_Speed`, `Engine_Status`,
  `Gear_Position`, `Wheel_Speed_FL`/`Wheel_Speed_FR`, and `Brake_Status`. If
  a different DBC file names its signals differently, these rules simply
  won't find those signals and will quietly report nothing (they won't
  crash, they just won't have anything to check). To make the Logic detector
  useful for another vehicle's DBC file, the signal names in
  `can_anomaly_detector_logic/rules/` would need to be updated to match.

So: the pipeline as a whole, and four of the five detectors, are built to be
general-purpose. The Logic detector is currently specific to the signal
naming used in our sample data.

## Features

- **Unified pipeline** — decodes a log against a DBC file and runs all
  detectors end to end.
- **Five detector modules**, independently selectable:
  - `range` — flags decoded signal values that fall outside DBC-defined
    physical bounds.
  - `logic` — flags contradictory or correlated signal states using rule-based
    and temporal signal-history checks.
  - `timing` — flags jitter, message flooding, duplicate-payload bursts, and
    communication timeouts.
  - `frame` — flags DLC mismatches, malformed payloads, and frame decoding
    failures.
  - `integrity` — flags missing/timed-out messages, deterministic data
    corruption, and CRC/checksum violations.
- **Pluggable detector registry** — new detectors can be registered without
  modifying the pipeline.
- **Multiple report formats** — human-readable text, JSON, or CSV.
- **Decoded data export** — dump fully decoded CAN traffic to CSV for
  inspection outside the tool.
- **Interactive HTML dashboard** — self-contained, offline-viewable signal
  timelines, CAN-ID activity swimlanes, and severity/category summaries
  (Chart.js, no server required).
- **Zero third-party runtime dependencies** — built entirely on the Python
  standard library.

## Requirements

- Python 3.9 or newer (tested on Python 3.12)
- [pytest](https://pypi.org/project/pytest/) — only needed if you want to run
  the test suite

## Installation

```bash
git clone <repository-url>
cd vit
```

That's it — no packages need to be installed to run the tool itself, since it
only uses Python's built-in standard library. If you also want to run the
tests, install pytest:

```bash
pip install pytest
```

## Usage

Run the tool by pointing it at a DBC file and a log file:

```bash
python main.py --dbc CAN.dbc --log CAN.log.txt
```

Some other things you can do:

```bash
# Save the report as JSON or CSV instead of printing text
python main.py --dbc CAN.dbc --log CAN.log.txt --format json --output report.json

# Only run some of the detectors
python main.py --dbc CAN.dbc --log CAN.log.txt --detectors range,logic,timing

# Generate the interactive HTML dashboard
python main.py --dbc CAN.dbc --log CAN.log.txt --dashboard dashboard.html
```

Run `python main.py --help` to see every available option.

## Project structure

```
vit/
├── main.py                              # Entry point
├── core/                                 # Pipeline orchestration
│   ├── pipeline.py                       # UnifiedAnomalyPipeline
│   ├── models.py                         # Shared data models (frames, anomalies)
│   ├── aggregator.py                     # Anomaly aggregation across detectors
│   ├── reporter.py                       # Text / JSON / CSV report generation
│   └── dashboard.py                      # Interactive HTML dashboard generation
├── detectors/                            # Pluggable anomaly detectors
│   ├── base.py                           # BaseAnomalyDetector interface
│   ├── registry.py                       # DetectorRegistry (factory/lookup)
│   ├── range_detector.py                 # Physical-range validation
│   ├── logic_detector.py                 # Contradictory signal / correlation rules
│   ├── timing_detector.py                # Timing, flooding, and behavioral analysis
│   ├── frame_detector.py                 # Frame format / DLC validation
│   └── integrity_detector.py             # Timeout, corruption, and CRC validation
├── parsers/                              # DBC and log parsing / decoding
│   ├── dbc_parser.py
│   ├── log_parser.py
│   ├── signal_decoder.py
│   └── exporter.py
├── dashboard/static/                     # Vendored Chart.js asset for the dashboard
├── tests/                                # Pytest suite covering the pipeline
└── can_anomaly_detector_logic/,
    can_integrity_detector/,
    can_range_anomaly_detector_outofrange/,
    timing_module/, can/, parse/          # Standalone origin modules consumed
                                           # as libraries by the detectors above
```

The `detectors/` adapters wrap logic originally developed as standalone
modules (`can_anomaly_detector_logic`, `can_integrity_detector`,
`can_range_anomaly_detector_outofrange`, `timing_module`). Those directories
remain part of the codebase and are imported directly by their corresponding
detector adapters, rather than being duplicated.

## Running the tests

```bash
python -m pytest tests -q
```

## Trying it out with sample data

A sample DBC file and log file are included so you can try the tool right
away, without needing your own data:

```bash
python main.py --dbc can/CAN.dbc --log can/CAN_log.txt --dashboard dashboard.html
```
## Team

Developed as a **4-member team** during a hackathon.

