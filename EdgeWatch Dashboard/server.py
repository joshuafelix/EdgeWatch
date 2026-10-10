"""
EdgeWatch Dashboard server.

Reads what the ingestion pipeline already writes (edgewatch.db) and serves
it to the dashboard frontend. Doesn't touch the pipeline at all -- read-only,
polls the same SQLite file pipeline.py writes to.

Run:
    python3 server.py --db ../LLM/edgewatch.db
"""

import argparse
import os
import sqlite3
from datetime import datetime, timezone

# pyright: reportMissingImports=false
from flask import Flask, jsonify, request, send_from_directory  # type: ignore[reportMissingImports]

app = Flask(__name__, static_folder="static", static_url_path="")

# Populated from CLI args in main()
DB_PATH = "edgewatch.db"
EXPECTED_NODES = 6

# Three-tier connectivity, not just online/offline:
#   LIVE      -- heard from within LIVE_AFTER_SEC        -> full color, counted "online"
#   LAST_SEEN -- heard from within OFFLINE_AFTER_SEC      -> keeps its last known severity/badge,
#                just not counted "online" -- e.g. a node that was critical right before it
#                went quiet still SHOWS critical, it doesn't reset to a neutral state
#   OFFLINE   -- nothing heard for longer than that, or never heard from at all -> neutral grey,
#                distinct from a real critical alert
LIVE_AFTER_SEC = 60
OFFLINE_AFTER_SEC = 120
LAST_SEEN_AFTER_SEC = OFFLINE_AFTER_SEC  # for clarity, not used in code


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _latest_readings_by_node():
    if not os.path.exists(DB_PATH):
        return {}
    conn = _db()
    rows = conn.execute(
        """
        SELECT t.* FROM telemetry_raw t
        INNER JOIN (
            SELECT node_id, MAX(id) AS max_id FROM telemetry_raw GROUP BY node_id
        ) latest ON t.node_id = latest.node_id AND t.id = latest.max_id
        """
    ).fetchall()
    conn.close()
    return {r["node_id"]: dict(r) for r in rows}


def _latest_analysis_by_node():
    """Most recent LLM analysis row per node_id (may be empty before the first cycle)."""
    if not os.path.exists(DB_PATH):
        return {}
    conn = _db()
    rows = conn.execute(
        """
        SELECT a.* FROM llm_analysis a
        INNER JOIN (
            SELECT node_id, MAX(id) AS max_id FROM llm_analysis GROUP BY node_id
        ) latest ON a.node_id = latest.node_id AND a.id = latest.max_id
        """
    ).fetchall()
    conn.close()
    return {r["node_id"]: dict(r) for r in rows}


def _status_label(behavior: str, anomaly: bool, trend: str) -> tuple[str, str]:
    """Returns (label, severity) where severity is one of: ok, warn, critical."""
    if anomaly and behavior == "degrading_voltage":
        return "Voltage Drop", "critical" if trend == "critical" else "warn"
    if anomaly and behavior == "degrading_temp":
        return "Temperature Rise", "critical" if trend == "critical" else "warn"
    if anomaly:
        return "Anomaly Detected", "critical" if trend == "critical" else "warn"
    return "Normal", "ok"


def _seconds_since(received_at: str | None) -> float:
    if not isinstance(received_at, str):
        return float("inf")
    try:
        ts = datetime.fromisoformat(received_at)
    except (TypeError, ValueError):
        return float("inf")
    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now - ts).total_seconds()


def _connectivity_tier(seconds_since: float) -> str:
    if seconds_since <= LIVE_AFTER_SEC:
        return "live"
    if seconds_since <= OFFLINE_AFTER_SEC:
        return "last_seen"    
    return "offline"
    


def _format_uptime(uptime_sec) -> str:
    if uptime_sec is None:
        return "—"
    days, rem = divmod(int(uptime_sec), 86400)
    hours, _ = divmod(rem, 3600)
    return f"{days:02d}d {hours:02d}h"


@app.route("/api/fleet")
def api_fleet():
    readings = _latest_readings_by_node()
    analyses = _latest_analysis_by_node()

    nodes = []
    live_count = 0
    attention_count = 0
    risk_scores = []

    for node_id in sorted(readings.keys()):
        r = readings[node_id]
        a = analyses.get(node_id, {})

        seconds_since = _seconds_since(r.get("received_at"))
        connectivity = _connectivity_tier(seconds_since)
        if connectivity == "live":
            live_count += 1

        behavior = r.get("behavior", "normal")
        anomaly = bool(a.get("anomaly", 0))
        trend = a.get("trend", "stable")
        label, severity = _status_label(behavior, anomaly, trend)

        if connectivity == "offline":
            # True offline overrides any prior severity -- distinct neutral state,
            # not a critical alert.
            label, severity = "Offline", "offline"
        elif severity in ("warn", "critical"):
            attention_count += 1

        risk_score = a.get("risk_score")
        if risk_score is not None:
            risk_scores.append(risk_score)

        nodes.append({
            "node_id": node_id,
            "connectivity": connectivity,  # "live" | "last_seen" | "offline"
            "behavior": behavior,
            "status_label": label,
            "severity": severity,  # "ok" | "warn" | "critical" | "offline"
            "voltage_v": r.get("voltage_v") if connectivity != "offline" else None,
            "temperature_c": r.get("temperature_c") if connectivity != "offline" else None,
            "vibration_g": r.get("vibration_g") if connectivity != "offline" else None,
            "rssi_dbm": r.get("rssi_dbm") if connectivity != "offline" else None,
            "cpu_load_pct": r.get("cpu_load_pct") if connectivity != "offline" else None,
            "uptime_sec": r.get("uptime_sec"),
            "uptime_display": _format_uptime(r.get("uptime_sec")),
            "risk_score": risk_score,
            "trend": trend,
            "predicted_failure_window": a.get("predicted_failure_window"),
            "reasoning": a.get("reasoning"),
        })

    latest_analysis = next(iter(analyses.values()), {})

    avg_risk = round(sum(risk_scores) / len(risk_scores)) if risk_scores else 0

    return jsonify({
        "nodes": nodes,
        "nodes_online": live_count,
        "nodes_total": EXPECTED_NODES,
        "nodes_attention": attention_count,
        "avg_risk": avg_risk,
        "fleet_summary": latest_analysis.get("fleet_summary", ""),
        "confidence": latest_analysis.get("confidence"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/node/<node_id>/history")
def api_node_history(node_id):
    if not os.path.exists(DB_PATH):
        return jsonify({"node_id": node_id, "readings": [], "risk_history": []})

    # ?range=60s|5m|1h -- how far back to pull raw readings for the chart
    range_param = request.args.get("range", "60s")
    window_seconds = {"60s": 60, "5m": 300, "1h": 3600}.get(range_param, 60)
    cutoff = datetime.now(timezone.utc).timestamp() - window_seconds
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()

    conn = _db()
    readings = conn.execute(
        """SELECT uptime_sec, voltage_v, temperature_c, vibration_g, rssi_dbm, cpu_load_pct, behavior, received_at
           FROM telemetry_raw WHERE node_id = ? AND received_at >= ? ORDER BY id ASC LIMIT 200""",
        (node_id, cutoff_iso),
    ).fetchall()

    # Fall back to "last N regardless of window" if the range came back empty --
    # e.g. right after startup, before enough history has accumulated
    if not readings:
        readings = conn.execute(
            """SELECT uptime_sec, voltage_v, temperature_c, vibration_g, rssi_dbm, cpu_load_pct, behavior, received_at
               FROM telemetry_raw WHERE node_id = ? ORDER BY id DESC LIMIT 30""",
            (node_id,),
        ).fetchall()
        readings = list(reversed(readings))

    conn.close()
    readings = [dict(r) for r in readings]

    behavior = readings[-1]["behavior"] if readings else "normal"
    if behavior == "degrading_voltage":
        metric_key, metric_label = "voltage_v", "Voltage"
    elif behavior == "degrading_temp":
        metric_key, metric_label = "temperature_c", "Temperature"
    else:
        metric_key, metric_label = "cpu_load_pct", "CPU Load"

    return jsonify({
        "node_id": node_id,
        "range": range_param,
        "metric_key": metric_key,
        "metric_label": metric_label,
        "readings": readings,
    })


@app.route("/")
def index():
    static_dir = app.static_folder or "static"
    return send_from_directory(static_dir, "index.html")


def main():
    global DB_PATH, EXPECTED_NODES, LIVE_AFTER_SEC, OFFLINE_AFTER_SEC

    parser = argparse.ArgumentParser(description="EdgeWatch dashboard server")
    parser.add_argument("--db", default="../LLM/edgewatch.db", help="path to pipeline's SQLite db")
    parser.add_argument("--nodes", type=int, default=6, help="expected fleet size, for the online count")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--live-after", type=int, default=LIVE_AFTER_SEC,
                         help="seconds since last reading before a node drops from 'live' to 'last seen'")
    parser.add_argument("--offline-after", type=int, default=OFFLINE_AFTER_SEC,
                         help="seconds since last reading before a node is marked fully 'offline'")
    args = parser.parse_args()

    DB_PATH = args.db
    EXPECTED_NODES = args.nodes
    LIVE_AFTER_SEC = args.live_after
    OFFLINE_AFTER_SEC = args.offline_after

    if not os.path.exists(DB_PATH):
        print(f"NOTE: {DB_PATH} doesn't exist yet -- the dashboard will show an empty state "
              f"until pipeline.py has been run and produced telemetry.")

    app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()