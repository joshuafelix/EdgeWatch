# EdgeWatch — Ingestion + LLM Analysis Pipeline

Second layer of the EdgeWatch stack: consumes the JSON telemetry stream produced
by the ESP32/Wokwi firmware (six simulated nodes, one every 5s), buffers a
sliding window per node, and runs periodic **batched** Claude analysis over
the whole fleet to detect anomalies and predict failures.

```
Firmware (ESP32/Wokwi)  →  serial_reader.py  →  buffer.py  →  llm_analyzer.py  →  storage.py
      JSON over Serial        ingestion            sliding         Claude              SQLite +
                               abstraction          window          (1 call/           latest_snapshot.json
                                                                      cycle,             (for a future
                                                                      all nodes)         dashboard)
```

## Why one batched call instead of per-node calls

Each analysis cycle sends **all active nodes' windows in a single API call**,
not one call per node. This is deliberate: it's cheaper, it lets the model
reason about the fleet as a whole (e.g. "is this a single flaky sensor or a
systemic power issue?"), and it fits the pitch better — a centralized
inference layer sitting over distributed edge telemetry ("AI Data Centers" /
"Data Movement" tracks), not a chatbot bolted onto a single device.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # then fill in whichever key(s) you're using
```

You only need ONE of the two providers set up:

**Claude** (default) — get a key at console.anthropic.com:
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

**Gemini** — get a key at aistudio.google.com/apikey:
```bash
export GEMINI_API_KEY=AIza...
```

## Running it

Add `--provider gemini` to any command below to use Gemini instead of Claude
(default is `claude`). Both expose the exact same output shape, so nothing
else about the pipeline changes.

**Against the real firmware**, once Wokwi is running and exposing a serial port
(or once you've flashed real hardware):
```bash
python pipeline.py --source serial --port COM5 --baud 115200
python pipeline.py --source serial --port COM5 --baud 115200 --provider gemini
```

**Against a captured log**, if you exported the Wokwi serial monitor output to
a text file:
```bash
python pipeline.py --source file --path capture.log --replay-delay 0.2
```

**Without any hardware/simulator**, using the built-in mock generator (reproduces
the same node-03-voltage-drain / node-05-temp-climb scenario as the firmware):
```bash
python pipeline.py --source mock --interval 5 --analysis-interval 30
```

**Dry run** (ingestion only, no API calls at all — useful for checking the
schema matches your firmware's JSON without spending any credits, from
either provider):
```bash
python pipeline.py --source mock --dry-run
```

Useful flags: `--provider claude|gemini`, `--window-size` (readings kept per
node, default 12 ≈ 60s of history), `--analysis-interval` (seconds between
LLM calls), `--duration` (auto-stop after N seconds, handy for demos), `--db`
(SQLite path).

## If your firmware's JSON differs from what's assumed here

Everything reads through one model in `schema.py` (`TelemetryReading`):
`node_id`, `timestamp`, `voltage`, `temperature`, `cpu_load`, `uptime_s`,
`status`. If `main.cpp` emits different field names, that's the only file
you need to touch — buffer, storage, and the LLM analyzer all consume
`TelemetryReading` objects, not raw JSON.

## Files

| File | Role |
|---|---|
| `schema.py` | Pydantic model for one telemetry reading; parses raw Serial lines |
| `serial_reader.py` | Ingestion source abstraction: serial port / log file replay / mock |
| `mock_stream.py` | Standalone generator reproducing the firmware's 6-node degrade scenario |
| `buffer.py` | Per-node sliding window (in-memory) |
| `llm_analyzer.py` | Batched Claude call → structured anomaly/risk JSON per node |
| `storage.py` | SQLite: raw telemetry + analysis history |
| `pipeline.py` | CLI entrypoint wiring it all together |

Each analysis cycle also writes `latest_snapshot.json` — a small file a
future dashboard frontend can poll directly without touching SQLite.

## Output shape (per analysis cycle)

```json
{
  "nodes": [
    {
      "node_id": "node-03",
      "anomaly": true,
      "risk_score": 72,
      "trend": "degrading",
      "predicted_failure_window": "10-15 min",
      "reasoning": "Voltage has dropped steadily from 3.70V to 3.34V over the last 12 readings, ~0.03V/reading."
    }
  ],
  "fleet_summary": "5 of 6 nodes stable; node-03 shows a consistent power drain trend."
}
```

## Next steps

- Wire `latest_snapshot.json` (or a small FastAPI wrapper around `storage.py`)
  into a dashboard frontend — the two degrading nodes should visibly diverge
  from the other four over a demo run.
- Sponsor-track framing: ingestion/buffering = **Data Movement** (streaming
  edge telemetry through a compute pipeline in near-real-time); batched
  Claude analysis = **AI Data Centers** (centralized inference over
  distributed device state). Worth checking Qualcomm/SiMa.ai/Intel Robotics
  bonus criteria for whether an on-device pre-filter (only forward
  windows that look anomalous, cutting bandwidth) would strengthen the
  Data Movement pitch further.
