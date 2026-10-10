# EdgeWatch

**IoT fleet monitoring with batched LLM anomaly detection.**

EdgeWatch simulates a fleet of ESP32 edge nodes, streams their telemetry through a Python ingestion pipeline, and uses a single batched LLM call over the whole fleet to flag anomalies and predict failures. Instead of running inference per device, EdgeWatch acts as a centralized inference layer over distributed edge telemetry.

Built for the **AI Infra Summit Hackathon** (lablab.ai x Kisaco Research), targeting the *AI Data Centers* and *Data Movement* tracks.

---

## Why batched inference?

Most LLM-for-IoT demos call a model once per device or per reading. EdgeWatch sends a windowed snapshot of the **entire fleet** in one request, which:

- cuts API calls and cost as the fleet grows,
- lets the model reason about **cross-node patterns**, not just single-device thresholds,
- frames the LLM as an infrastructure-layer component rather than a chatbot.

**Tradeoff:** LLM-based detection is more flexible than fixed thresholds but less auditable. Pairing it with deterministic rules is a natural next step.

---

## Architecture

```
┌──────────────┐   JSON over    ┌────────────────┐   batches   ┌──────────────┐
│  ESP32 nodes │ ─────Serial──▶ │   Ingestion    │ ──────────▶ │ LLM analyzer │
│ (Wokwi sim)  │   every 5 s    │ + ring buffer  │             │ Gemini/Claude│
└──────────────┘                └────────────────┘             └──────┬───────┘
                                                                      │
                                              ┌───────────────────────▼───────┐
                                              │ SQLite + latest_snapshot.json │
                                              └───────────────────────┬───────┘
                                                                      │ polled by
                                                               ┌──────▼───────┐
                                                               │  Dashboard   │
                                                               │  (planned)   │
                                                               └──────────────┘
```

Each layer is separate, so components (LLM provider, storage, frontend) can be swapped independently.

---

## Project structure

```
EdgeWatch/
├── firmware/                # ESP32 firmware (PlatformIO)
│   └── main.cpp             # Simulates 6 virtual nodes, emits JSON telemetry
└── ingestion-llm/
    ├── pipeline.py          # Orchestrates the full flow
    ├── schema.py            # Telemetry schema
    ├── buffer.py            # Rolling buffer of recent readings
    ├── serial_reader.py     # Reads live Serial output from Wokwi
    ├── mock_stream.py       # Mock telemetry for dev/testing without Wokwi
    ├── llm_analyzer.py      # Batched anomaly detection (Gemini / Claude)
    └── storage.py           # SQLite + snapshot writer
```

---

## Telemetry schema

Each node emits JSON over Serial every 5 seconds:

| Field | Description |
|---|---|
| `voltage_v` | Supply voltage (V) |
| `temperature_c` | Temperature (°C) |
| `uptime_sec` | Time since boot (s) |
| `behavior` | Node behavior state |
| `vibration_g` | Vibration (g) |
| `rssi_dbm` | Wi-Fi signal strength (dBm) |
| `cpu_load_pct` | *Synthetic* load, correlated with degrading nodes to represent retry/throttling overhead |

### Demo scenarios

- **node-03** — scripted voltage drain
- **node-05** — scripted temperature climb

These show the LLM catching degradation early across the fleet.

---

## Tech stack

- **Firmware:** ESP32, PlatformIO, ArduinoJson, [Wokwi](https://wokwi.com) simulator
- **Backend:** Python 3, `python-dotenv`
- **LLMs:** Google Gemini (primary), Anthropic Claude (alternative)
- **Storage:** SQLite (`edgewatch.db`) + `latest_snapshot.json`

---

## Getting started

### Prerequisites

- Python 3.10+
- [PlatformIO](https://platformio.org/) and the Wokwi VS Code extension (only for the live simulation)
- A Gemini API key (or an Anthropic key if using Claude)

### Setup

```bash
git clone https://github.com/<your-username>/EdgeWatch.git
cd EdgeWatch

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_key_here
# ANTHROPIC_API_KEY=your_key_here   # if using Claude
```

### Run with the mock stream (no hardware or simulator)

```bash
cd ingestion-llm
python pipeline.py --mock
```

### Run with the Wokwi simulation

1. Build the firmware with PlatformIO and start the Wokwi simulation from `firmware/`.
2. In a second terminal, start the pipeline:

```bash
cd ingestion-llm
python pipeline.py
```

Outputs are written to `edgewatch.db` and `latest_snapshot.json`.

> **Note:** If you change telemetry field names, delete `edgewatch.db` first. A stale schema will cause `sqlite3.OperationalError`.

---

## Roadmap

- [x] ESP32 fleet simulation firmware
- [x] Ingestion pipeline with buffering and mock stream
- [x] Batched LLM anomaly detection (Gemini / Claude)
- [x] SQLite storage and snapshot output
- [ ] Dashboard frontend: **Fleet Health Grid** + **AI Insights Panel**
- [ ] Deterministic threshold rules alongside LLM detection for auditability
- [ ] Hackathon pitch and live demo

---

## Target use cases

Data center operators, telecom and cell tower operators, industrial IoT, renewable energy farms, and logistics / cold-chain monitoring.

---

## License

Add a license of your choice (e.g. MIT) before publishing.

## Author

**Felix** — Electronics & Communication Engineering student working on embedded systems and IoT.