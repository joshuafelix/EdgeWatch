"""
Mock telemetry generator.

Reproduces the SAME field shape as the real firmware (firmware/src/main.cpp,
printReadingJSON()) and the same 6-node degrade scenario -- node-03 draining
voltage, node-05 climbing temperature -- so the ingestion + LLM pipeline can
be built and demoed without Wokwi/hardware attached, using data that parses
identically to the real device's output.

cpu_load_pct rises for degrading nodes to mirror the firmware's modeling
(retry/throttling overhead), not just random noise.

Runs on a compressed timescale (default: 1 reading/node per `interval`
seconds, same 5s default as the firmware) but is independent of it -- pass
--interval to speed up for testing.
"""

import json
import random
import time

NODE_IDS = [f"node-{i:02d}" for i in range(1, 7)]
DEGRADE_VOLTAGE_NODE = "node-03"
DEGRADE_TEMP_NODE = "node-05"

# Per-node running cpu_load state, mirroring firmware's cumulative drift
_cpu_load_state = {node_id: 22.0 + random.uniform(-2, 2) for node_id in NODE_IDS}


def _jitter(amount: float) -> float:
    return random.uniform(-amount, amount)


def _line(node_id: str, tick: int) -> str:
    voltage_v = 4.10 + _jitter(0.01)
    temperature_c = 24.0 + _jitter(0.3)
    vibration_g = round(0.02 + _jitter(0.01), 3)
    behavior = "normal"

    cpu_load = _cpu_load_state[node_id]

    if node_id == DEGRADE_VOLTAGE_NODE:
        behavior = "degrading_voltage"
        voltage_v = max(3.0, 4.10 - tick * 0.015 + _jitter(0.005))
        cpu_load += 0.6 + _jitter(0.4)  # retry overhead as power destabilizes
    elif node_id == DEGRADE_TEMP_NODE:
        behavior = "degrading_temp"
        temperature_c = min(90.0, 25.0 + tick * 0.08 + _jitter(0.05))
        cpu_load += 0.5 + _jitter(0.4)  # throttling overhead as it overheats
    else:
        cpu_load += _jitter(1.5)  # healthy baseline wander

    cpu_load = max(5.0, min(100.0, cpu_load))
    _cpu_load_state[node_id] = cpu_load

    payload = {
        "node_id": node_id,
        "behavior": behavior,
        "temperature_c": round(temperature_c, 2),
        "voltage_v": round(voltage_v, 3),
        "vibration_g": vibration_g,
        "rssi_dbm": -55 + random.randint(-2, 2),
        "cpu_load_pct": round(cpu_load, 1),
        "uptime_sec": tick * 5,
    }
    return json.dumps(payload)


def generate(interval: float = 5.0):
    """Yield raw JSON lines forever, one per node per `interval` seconds."""
    tick = 0
    while True:
        for node_id in NODE_IDS:
            yield _line(node_id, tick)
        tick += 1
        time.sleep(interval)