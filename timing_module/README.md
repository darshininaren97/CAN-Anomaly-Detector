# PC-Based Offline CAN Bus Data Decoder & Anomaly Detector
## Temporal / Timing / Behavioral Anomaly Detection Module

A deterministic, high-performance, offline Python module for detecting temporal, timing, and behavioral anomalies in Controller Area Network (CAN) bus communication streams.

---

## 1. Project Purpose

In automotive CAN bus networks, electronic control units (ECUs) transmit periodic frames according to strict timing schedules defined by vehicle manufacturers. Cyberattacks (such as CAN bus flooding, replay attacks, message injection, or denial-of-service) and hardware faults (such as clock drift, ECU resets, or bus line disconnects) produce distinctive temporal signatures.

This module analyzes inter-frame timing intervals, payload repetition patterns, transmission frequencies, and timeout gaps to detect:
1. **Timing Deviations / Jitter**: Jitter, clock drift, or unexpected transmission delays.
2. **Flooding Bursts**: Sustained high-frequency transmission bursts.
3. **Duplicate Payload Bursts**: Rapid replay-like repetition of identical payloads.
4. **Communication Timeouts**: ECU transmission blackouts or missed frames.
5. **ECU Behavioral Anomalies**: Shift in message frequency, variance, or error rates.

---

## 2. Project Structure

```
timing_module/
│
├── timing_module/
│   ├── __init__.py           # Package exports & public API symbols
│   ├── timing_analyzer.py    # Main timing and behavioral detection engine
│   ├── models.py             # Dataclasses: Frame, BaselineProfile, AnomalyEvent, ECUProfile
│   ├── config.py             # Configurable thresholds and parameter loader
│   ├── parser_adapter.py     # Ingestion & normalization adapter for raw CAN JSON logs
│   └── __main__.py           # CLI entrypoint for analysis and reporting
│
├── tests/
│   ├── __init__.py
│   ├── test_timing.py        # Baseline calculations, intervals, jitter, zero std
│   ├── test_flooding.py      # Flooding burst detection, persistence, aggregation
│   ├── test_duplicates.py    # Duplicate payload bursts vs normal repeating payloads
│   ├── test_timeout.py       # Communication timeouts & missed frame estimation
│   └── test_behavior.py      # ECU profiling, parser adapter, end-to-end integration
│
├── examples/
│   ├── normal.json           # Synthetic nominal periodic CAN log (451 frames)
│   ├── anomalous.json        # Synthetic CAN log with injected anomalies (559 frames)
│   └── parsed_output.json    # JSON analysis report output
│
├── output/
│   └── anomaly_report.json   # Full generated anomaly and profiling report
│
├── config.json               # Default configuration threshold file
├── requirements.txt          # Minimal dependencies (pytest)
└── README.md                 # Complete module documentation
```

---

## 3. Installation & Environment Setup

The module relies primarily on the Python standard library, requiring only `pytest` for test execution.

```powershell
# From the project root (timing_module/)
python -m pip install -r requirements.txt
```

---

## 4. Package Import Verification

The module is structured as a standard Python package. Run the verification command from the project root:

```powershell
python -c "from timing_module.timing_analyzer import TimingAnalyzer; print('IMPORT OK')"
```

**Expected Output:**
```
IMPORT OK
```

---

## 5. Running Tests

Run the complete test suite from the project root using either `pytest` or `unittest`:

```powershell
python -m pytest -v
```

or:

```powershell
python -m unittest discover -v -s tests
```

---

## 6. Running the Command-Line Demo

Execute the module directly against sample CAN bus logs:

```powershell
# Analyze the anomalous dataset:
python -m timing_module examples/anomalous.json

# Analyze the nominal dataset:
python -m timing_module examples/normal.json

# Custom configuration or output paths:
python -m timing_module examples/anomalous.json --config config.json --output output/custom_report.json
```

---

## 7. Architecture & Detection Engine Details

### System Flow
```
            Existing CAN Log
                   │
                   ▼
            Existing Parser
                   │
                   ▼
          parser_adapter.py
                   │
                   ▼
          Normalized Frames
                   │
                   ▼
             TimingAnalyzer
          ┌────────┼────────┐
          │        │        │
       Timing   Flooding  Duplicate
      Analysis Detection Detection
          │        │        │
          └────────┼────────┘
                   │
                Timeout
                   │
                   ▼
             Anomaly Events
                   │
                   ▼
              JSON Report
                   │
                   ▼
            Team's Anomaly
                Fusion
```

### 1. Normalized Frame Structure
The parser adapter converts external records into normalized `Frame` objects:
```json
{
  "timestamp": 1.250,
  "can_id": "0x464",
  "data": "01A2000000000000",
  "dlc": 8,
  "ecu": "VSA"
}
```
- CAN IDs can be passed as decimal integers (`1124`), decimal strings (`"1124"`), or hex strings (`"0x464"`, `0x464`).
- Data payloads are standardized into uppercase hex strings.

### 2. Baseline Fitting (`fit`)
For each CAN ID:
- Frames are grouped and sorted by timestamp.
- Inter-frame intervals $\Delta t_i = t_i - t_{i-1}$ are calculated.
- Primary nominal period is defined as the **median interval** ($\tilde{T}$), avoiding skew from startup jitter.
- Arithmetic mean ($\mu$), standard deviation ($\sigma$), minimum, maximum, frames per second ($\text{FPS} = 1/\tilde{T}$), and coefficient of variation ($\text{CV} = \sigma / \mu$) are computed.

### 3. Timing Deviation Detection
- Relative error:
  $$\text{relative\_error} = \frac{|\Delta t - \tilde{T}|}{\tilde{T}}$$
- Z-score:
  $$Z = \frac{|\Delta t - \mu|}{\sigma} \quad (\text{if } \sigma > 0)$$
- Triggered when relative error exceeds `relative_deviation_threshold` (default 20%) and Z-score exceeds `z_score_threshold` (default 3.0).

### 4. Flooding Detection (Aggregated)
- Identifies sequences of intervals where $\Delta t \le \tilde{T} \times \text{flooding\_ratio\_threshold}$ (default 0.25).
- Requires persistence: $\ge \text{flooding\_min\_burst\_count}$ consecutive frames (default 5 frames).
- Aggregates the entire burst into **ONE** anomaly event containing start time, end time, abnormal frame count, and observed rate, preventing alert storms.

### 5. Duplicate Payload Burst Detection (Aggregated)
- Identifies identical data payloads repeated with intervals $\le \tilde{T} \times \text{duplicate\_max\_interval\_factor}$ (default 0.30).
- Requires $\ge \text{duplicate\_min\_repeat\_count}$ consecutive identical frames (default 3).
- Does **not** flag normal periodic messages with static payloads.

### 6. Timeout Detection
- Detects gaps where $\Delta t \ge \tilde{T} \times \text{timeout\_multiplier}$ (default 2.5).
- Calculates estimated missed frames:
  $$\text{missed\_messages} = \lfloor \frac{\Delta t}{\tilde{T}} \rfloor - 1$$

### 7. Explainable Severity Scoring
- `LOW`: Minor timing drift ($25\% - 60\%$).
- `MEDIUM`: Moderate timing shift ($60\% - 120\%$) or brief timeout (1-2 missed frames).
- `HIGH`: Severe deviation ($>120\%$), sustained flooding burst, or multi-frame timeout ($\ge 3$ missed frames).
- `CRITICAL`: Extreme flooding burst ($\ge 20$ frames / $>90\%$ rate increase) or extended blackout ($\ge 10$ missed frames).

---

## 8. Public Python API

```python
from timing_module import TimingAnalyzer, ParserAdapter, TimingConfig

# 1. Initialize configuration and adapter
config = TimingConfig(relative_deviation_threshold=0.20, z_score_threshold=3.0)
adapter = ParserAdapter()

# 2. Ingest and normalize CAN frames
frames = adapter.parse_json_file("examples/anomalous.json")

# 3. Fit baseline & analyze
analyzer = TimingAnalyzer(config=config)
analyzer.fit(frames)
anomalies = analyzer.analyze(frames)

# 4. Access profiles and report
profiles = analyzer.get_profiles()
report = analyzer.generate_report(frames)
```

---

## 9. Example Output JSON Report

```json
{
  "summary": {
    "total_frames": 559,
    "total_can_ids": 4,
    "total_anomalies": 6,
    "critical_severity": 3,
    "high_severity": 2,
    "medium_severity": 1,
    "low_severity": 0
  },
  "profiles": [
    {
      "can_id": "0x464",
      "can_id_int": 1124,
      "ecu": "VSA",
      "sample_count": 84,
      "nominal_period": 0.099575,
      "mean_period": 0.071687,
      "std_period": 0.044726,
      "frames_per_second": 10.04
    }
  ],
  "anomalies": [
    {
      "start_time": 3.21,
      "end_time": 3.258,
      "can_id": "0x464",
      "ecu": "VSA",
      "anomaly_type": "TIMING_FLOODING",
      "severity": "CRITICAL",
      "abnormal_frame_count": 25,
      "nominal_period": 0.099575,
      "observed_period": 0.002,
      "deviation": 0.9799,
      "diagnosis": "Abnormally high-frequency CAN transmission; possible flooding, replay-like activity, or ECU malfunction.",
      "possible_causes": [
        "CAN flooding",
        "Replay-like transmission",
        "ECU malfunction"
      ],
      "evidence": {
        "nominal_period": 0.099575,
        "observed_period": 0.002,
        "repeat_count": 25,
        "start_time": 3.21,
        "end_time": 3.258,
        "burst_duration": 0.048
      }
    }
  ]
}
```
