"""
Thread-safe per-node sliding window of recent telemetry readings.

Ingestion adds every telemetry reading.
The analysis thread takes a snapshot without blocking ingestion
for any meaningful amount of time.
"""

import threading
from collections import defaultdict, deque
from typing import Dict, List

from schema import TelemetryReading


class TelemetryBuffer:
    def __init__(self, window_size: int = 12):
        self.window_size = window_size

        self._nodes: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=self.window_size)
        )

        self._lock = threading.Lock()

    def add(self, reading: TelemetryReading) -> None:
        """Add one telemetry reading to its node's sliding window."""
        with self._lock:
            self._nodes[reading.node_id].append(reading)

    def node_ids(self) -> List[str]:
        """Return all nodes currently known to the buffer."""
        with self._lock:
            return list(self._nodes.keys())

    def snapshot(self) -> Dict[str, List[dict]]:
        """
        Return a complete copy of the current telemetry windows.

        The lock is held only while copying the data.
        The LLM call happens after the lock is released.
        """
        with self._lock:
            return {
                node_id: [
                    reading.model_dump()
                    for reading in readings
                ]
                for node_id, readings in self._nodes.items()
                if readings
            }

    def reading_count(self) -> int:
        """Return total number of readings currently buffered."""
        with self._lock:
            return sum(
                len(readings)
                for readings in self._nodes.values()
            )