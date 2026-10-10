# EdgeWatch Dashboard

Read-only web dashboard for the fleet. Polls `edgewatch.db` and
`latest_snapshot.json` (written by the ingestion pipeline in `LLM/`) — doesn't
touch or modify the pipeline in any way.

## Setup

```bash
pip install -r requirements.txt
```

## Running it

Point `--db` at wherever your ingestion pipeline's `edgewatch.db` actually
lives (adjust the relative path to match your folder layout):

```bash
python3 server.py --db ../LLM/edgewatch.db --port 5050
```

Then open **http://localhost:5050** in a browser.

Run this *alongside* the ingestion pipeline (in a separate terminal) — the
dashboard just reads the same SQLite file the pipeline is writing to, so
both can run at once:

```bash
# terminal 1
cd LLM && python3 pipeline.py --source mock --provider claude --analysis-interval 30

# terminal 2
cd dashboard && python3 server.py --db ../LLM/edgewatch.db --port 5050
```

The dashboard polls every 4 seconds — no need to refresh the page manually.

## What's real vs. a placeholder

- **Live**: node status, all metrics (voltage/temp/vibration/rssi/cpu_load),
  risk score, trend, LLM reasoning, and the per-node performance chart — all
  pulled straight from what the pipeline actually wrote.
- **Placeholder only**: the "Turn off all nodes" / "Pause all nodes" / "Turn
  off" / "Profile" buttons are visually present but disabled. There's no
  command channel from the dashboard back to the ESP32 yet — the firmware
  only sends telemetry outward, it doesn't listen for commands. Wiring that
  up would need a new firmware feature (e.g. listening on a second serial
  channel or an MQTT topic) as a separate piece of work.

## How status labels are derived

Not hardcoded per node — computed live from two signals:
- `behavior`: the firmware's own self-reported mode (`normal` /
  `degrading_voltage` / `degrading_temp`)
- `anomaly` / `trend`: the LLM's independent verdict from the latest
  analysis cycle

A node only shows a red "Voltage Drop" / "Temperature Rise" badge once the
LLM has actually flagged it as anomalous — not just because the firmware
is *scripted* to degrade. Before the first analysis cycle completes, every
node shows "Normal" even if it's mid-degrade, since there's no LLM verdict
yet to base a badge on.

## Which metric the performance chart shows

Chosen automatically per node, based on that node's most recent `behavior`
value: voltage for `degrading_voltage` nodes, temperature for
`degrading_temp` nodes, CPU load otherwise. Not hand-mapped per node ID —
if you add a 7th node or change which nodes degrade in `main.cpp`, this
adapts without any dashboard code changes.
