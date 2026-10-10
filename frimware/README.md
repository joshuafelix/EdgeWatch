# EdgeWatch — Fleet Simulation Firmware

Simulates a fleet of 6 edge IoT devices on a **single ESP32** running in Wokwi.
Two nodes are scripted to slowly degrade so you have real "trouble" for the
AI layer to catch:

- `node-03` → `DEGRADING_VOLTAGE` (battery drains ~0.015V per cycle)
- `node-05` → `DEGRADING_TEMP` (temperature climbs ~0.08°C per cycle)

The rest report stable, noisy-but-healthy readings.

## Run it in Wokwi (fastest way — no local install needed)

1. Go to https://wokwi.com/projects/new/esp32
2. Replace the default `src/main.cpp` with this project's `src/main.cpp`
3. Replace `diagram.json` with this project's `diagram.json`
4. Click the green ▶️ Play button
5. Open the Serial Monitor — you'll see JSON readings for all 6 nodes every 5 seconds, like:

```json
{"node_id":"node-03","behavior":"degrading_voltage","temperature_c":24.31,"voltage_v":3.92,"vibration_g":0.023,"rssi_dbm":-57,"uptime_sec":45}
```

That JSON stream is exactly what the ingestion/LLM pipeline (next step) will consume.

## Run it locally with PlatformIO (optional, if you want it on real hardware later)

```bash
pio run -t upload
pio device monitor
```

## Tuning the simulation

- `NUM_NODES`, `READING_INTERVAL_MS` — fleet size and reporting frequency
- Each node's starting values and `Behavior` are set in the `fleet[]` array in `main.cpp`
- To make a node fail faster for a snappier demo, increase the drift amount in `updateNode()` (e.g. `-0.015` → `-0.04` for a faster voltage drain)

## Sending to ThingSpeak (optional)

Set `SEND_TO_THINGSPEAK = true` and add your Write API Key. Note: ThingSpeak's
free tier is one channel = up to 8 fields, so for a real multi-node fleet you'd
either use one channel per node or (recommended for the hackathon demo) just
feed the Serial JSON straight into the local ingestion script — simpler and
avoids ThingSpeak's rate limits (15s between updates on the free tier) which
would otherwise force you to slow down the whole fleet.

## Next step

Point your ingestion script at this Serial JSON stream (or ThingSpeak, if
enabled) — that's where the rolling-window buffering and LLM anomaly
detection happens.
