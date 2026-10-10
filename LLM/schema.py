"""
Telemetry schema for EdgeWatch.

Verified against real firmware Serial output. Field names match
firmware/src/main.cpp's printReadingJSON() exactly.

cpu_load_pct is modeled in firmware to correlate with degrading nodes
(retry/throttling overhead) rather than being decorative noise — see the
comment above updateNode() in main.cpp for the reasoning.
"""

from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator


class TelemetryReading(BaseModel):
    node_id: str
    behavior: str  # "normal" | "degrading_voltage" | "degrading_temp"
    temperature_c: float
    voltage_v: float
    vibration_g: float
    rssi_dbm: int
    cpu_load_pct: float
    uptime_sec: int

    # Firmware sends no epoch/timestamp field — this is the server's receipt
    # time instead, independent of device clock (the ESP32 doesn't track wall time).
    received_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @field_validator("node_id")
    @classmethod
    def _node_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("node_id must not be empty")
        return v

    @classmethod
    def from_raw_line(cls, line: str) -> "TelemetryReading":
        """Parse one raw Serial line into a TelemetryReading.

        Tolerates firmware boot noise / log lines that aren't JSON
        (e.g. "EdgeWatch fleet simulation booting...", "WiFi connected: ...",
        "---- fleet cycle complete ----") by raising ValueError, which
        callers should catch and skip.
        """
        import json

        line = line.strip()
        if not line or not line.startswith("{"):
            raise ValueError("not a JSON telemetry line")
        data = json.loads(line)
        return cls(**data)