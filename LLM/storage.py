"""SQLite storage for raw telemetry and LLM analysis results."""

import sqlite3
from datetime import datetime, timezone
import threading

from schema import TelemetryReading


class Storage:
    def __init__(self, db_path: str = "edgewatch.db"):
        # check_same_thread=False: each Storage instance is created and used
        # entirely within one thread (ingestion thread has its own instance,
        # analysis thread has its own), but sqlite3's default same-thread
        # check is overly strict about how it detects that; WAL mode below
        # is what actually makes concurrent access from two connections safe.
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.RLock()
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS telemetry_raw (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL,
                behavior TEXT,
                temperature_c REAL,
                voltage_v REAL,
                vibration_g REAL,
                rssi_dbm INTEGER,
                cpu_load_pct REAL,
                uptime_sec INTEGER,
                received_at TEXT
            );

            CREATE TABLE IF NOT EXISTS llm_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at TEXT NOT NULL,
                node_id TEXT,
                anomaly INTEGER,
                risk_score INTEGER,
                trend TEXT,
                predicted_failure_window TEXT,
                reasoning TEXT,
                fleet_summary TEXT,
                confidence INTEGER
            );
            """
        )
        self.conn.commit()

    def save_reading(self, r: TelemetryReading) -> None:
        self.conn.execute(
            """INSERT INTO telemetry_raw
               (node_id, behavior, temperature_c, voltage_v, vibration_g, rssi_dbm, cpu_load_pct, uptime_sec, received_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (r.node_id, r.behavior, r.temperature_c, r.voltage_v, r.vibration_g, r.rssi_dbm, r.cpu_load_pct, r.uptime_sec, r.received_at),
        )
        self.conn.commit()

    def save_analysis(self, analysis: dict) -> None:
        run_at = datetime.now(timezone.utc).isoformat()
        fleet_summary = analysis.get("fleet_summary", "")
        confidence = analysis.get("confidence")
        for node in analysis.get("nodes", []):
            self.conn.execute(
                """INSERT INTO llm_analysis
                   (run_at, node_id, anomaly, risk_score, trend, predicted_failure_window, reasoning, fleet_summary, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_at,
                    node.get("node_id"),
                    int(bool(node.get("anomaly"))),
                    node.get("risk_score"),
                    node.get("trend"),
                    node.get("predicted_failure_window"),
                    node.get("reasoning"),
                    fleet_summary,
                    confidence,
                ),
            )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()