"""
EdgeWatch ingestion + LLM analysis pipeline.

Reads the JSON telemetry stream (from a real ESP32 over serial, a replayed
log file, or the built-in mock generator), buffers a sliding window per
node, and periodically sends the ENTIRE fleet's windowed data to an LLM in
one batched call for anomaly detection + failure prediction.

ARCHITECTURE: ingestion and analysis run on SEPARATE THREADS. This matters
because an LLM API call is a blocking network round-trip -- if it ran on the
same loop that reads incoming serial data, that read loop would stall for
the entire duration of the call, and any telemetry arriving during that
window could be delayed or lost. Splitting them means the ingestion thread
never stops reading regardless of how slow (or flaky) the LLM call is; the
analysis thread just reads a snapshot of whatever's in the shared buffer on
its own schedule.

Usage:
    python pipeline.py --source mock --analysis-interval 15 --duration 60
    python pipeline.py --source serial --port COM5 --baud 115200
    python pipeline.py --source wokwi --analysis-interval 30
    python pipeline.py --source file --path capture.log --replay-delay 0.2

Env:
    ANTHROPIC_API_KEY   required if --provider claude and not --dry-run
    GEMINI_API_KEY      required if --provider gemini and not --dry-run
    (or whatever your llm_analyzer.py's provider factory expects)

    Loaded automatically from a .env file in this directory, if present.
"""

import argparse
import json
import logging
import threading
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

from buffer import TelemetryBuffer
from schema import TelemetryReading
from serial_reader import get_source
from storage import Storage

load_dotenv()  # reads .env in the current directory into os.environ, if it exists

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("edgewatch")

LATEST_SNAPSHOT_PATH = "latest_snapshot.json"


def parse_args():
    p = argparse.ArgumentParser(description="EdgeWatch ingestion + LLM analysis pipeline")
    p.add_argument("--source", choices=["serial", "wokwi", "file", "mock"], default="mock")
    p.add_argument("--port", help="serial port, e.g. COM5 or /dev/ttyUSB0")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--rfc2217-host", default="localhost", help="wokwi source: host running the VS Code simulator")
    p.add_argument("--rfc2217-port", type=int, default=8000, help="wokwi source: must match rfc2217ServerPort in wokwi.toml")
    p.add_argument("--path", help="log file path for --source file")
    p.add_argument("--replay-delay", type=float, default=0.0, help="seconds between replayed lines")
    p.add_argument("--interval", type=float, default=5.0, help="mock source: seconds between readings")
    p.add_argument("--window-size", type=int, default=12, help="readings kept per node (12 * 5s ~= 60s)")
    p.add_argument("--analysis-interval", type=float, default=30.0, help="seconds between LLM analysis runs")
    p.add_argument("--db", default="edgewatch.db")
    p.add_argument("--duration", type=float, default=None, help="stop after N seconds (omit to run forever)")
    p.add_argument("--dry-run", action="store_true", help="skip LLM calls; just print buffered snapshots")
    p.add_argument("--provider", choices=["claude", "gemini", "freellm"], default="freellm", help="which LLM to use for analysis (whatever your llm_analyzer.py supports)")
    return p.parse_args()


def print_alerts(analysis: dict) -> None:
    for node in analysis.get("nodes", []):
        if node.get("anomaly"):
            log.warning(
                "ALERT  %-10s  risk=%-3s  trend=%-10s  eta=%-10s  %s",
                node.get("node_id"),
                node.get("risk_score"),
                node.get("trend"),
                node.get("predicted_failure_window") or "-",
                node.get("reasoning"),
            )
    summary = analysis.get("fleet_summary")
    if summary:
        log.info("Fleet summary: %s", summary)


def write_latest_snapshot(analysis: dict) -> None:
    """Small JSON file a dashboard can poll without touching SQLite."""
    payload = {"updated_at": datetime.now(timezone.utc).isoformat(), **analysis}
    with open(LATEST_SNAPSHOT_PATH, "w") as f:
        json.dump(payload, f, indent=2)


def ingestion_loop(args, lines, buf: TelemetryBuffer, store: Storage, start: float, stop_event: threading.Event) -> None:
    """
    Runs continuously on its own thread. Never blocked by the LLM analysis
    thread -- this is the whole point of the split. Reads every line as fast
    as it arrives, parses, buffers, and persists it, with no network calls
    of its own (aside from whatever the source itself does, e.g. the wokwi
    rfc2217 socket, which is not an LLM call and stays fast).
    """
    for raw_line in lines:
        if stop_event.is_set():
            break
        if args.duration is not None and (time.monotonic() - start) > args.duration:
            log.info("Duration limit reached, stopping ingestion.")
            stop_event.set()
            break

        try:
            reading = TelemetryReading.from_raw_line(raw_line)
        except (ValueError, Exception) as e:  # tolerate boot noise / malformed lines
            if raw_line.strip():
                log.debug("Skipping non-telemetry line: %r (%s)", raw_line, e)
            continue

        buf.add(reading)
        store.save_reading(reading)
        log.info(
            "%-10s  V=%.3fV  T=%.1fC  vib=%s  rssi=%sdBm  cpu=%.1f%%  behavior=%s",
            reading.node_id, reading.voltage_v, reading.temperature_c,
            reading.vibration_g, reading.rssi_dbm, reading.cpu_load_pct, reading.behavior,
        )


def analysis_loop(args, buf: TelemetryBuffer, store: Storage, analyzer, stop_event: threading.Event) -> None:
    """
    Runs on its own thread, independent of ingestion. Wakes up every
    --analysis-interval seconds, takes a snapshot of whatever's currently in
    the buffer (a thread-safe copy -- see TelemetryBuffer), and calls the
    LLM. However long that call takes, it NEVER blocks the ingestion thread,
    which keeps reading serial data the entire time.
    """
    while not stop_event.wait(timeout=args.analysis_interval):
        snapshot = buf.snapshot()
        if not snapshot:
            continue

        if args.dry_run:
            log.info("[dry-run] buffered nodes=%s readings=%s", buf.node_ids(), buf.reading_count())
            continue

        log.info("Running LLM analysis over %d nodes...", len(snapshot))
        try:
            analysis = analyzer.analyze(snapshot)
        except Exception as e:
            # Transient API errors (503 overload, rate limits, network blips)
            # shouldn't kill the pipeline -- skip this cycle and try again
            # next interval. Ingestion was never affected either way.
            log.warning("LLM analysis call failed (%s), will retry next cycle.", e)
            continue

        print_alerts(analysis)
        store.save_analysis(analysis)
        write_latest_snapshot(analysis)


def main():
    args = parse_args()

    if args.source == "serial" and not args.port:
        raise SystemExit("--port is required for --source serial")
    if args.source == "file" and not args.path:
        raise SystemExit("--path is required for --source file")

    source_kwargs = {
        "serial": {"port": args.port, "baud": args.baud},
        "wokwi": {"host": args.rfc2217_host, "rfc2217_port": args.rfc2217_port, "baud": args.baud},
        "file": {"path": args.path, "replay_delay": args.replay_delay},
        "mock": {"interval": args.interval},
    }[args.source]

    lines = get_source(args.source, **source_kwargs)
    buf = TelemetryBuffer(window_size=args.window_size)

    # Separate Storage/connection per thread -- each opens its own sqlite3
    # connection to the same file; WAL mode (enabled in storage.py) makes
    # this safe for concurrent reads/writes from two threads.
    store_ingest = Storage(args.db)
    store_analysis = Storage(args.db)

    analyzer = None
    if not args.dry_run:
        from llm_analyzer import LLMAnalyzer  # lazy import: no provider SDK needed in dry-run
        analyzer = LLMAnalyzer(provider=args.provider)

    log.info(
        "EdgeWatch pipeline started (source=%s, provider=%s, dry_run=%s, analysis_interval=%ss) -- "
        "ingestion and analysis run on separate threads.",
        args.source, args.provider, args.dry_run, args.analysis_interval,
    )

    start = time.monotonic()
    stop_event = threading.Event()

    ingest_thread = threading.Thread(
        target=ingestion_loop, args=(args, lines, buf, store_ingest, start, stop_event), daemon=True,
    )
    analysis_thread = threading.Thread(
        target=analysis_loop, args=(args, buf, store_analysis, analyzer, stop_event), daemon=True,
    )

    ingest_thread.start()
    analysis_thread.start()

    try:
        while ingest_thread.is_alive():
            ingest_thread.join(timeout=0.5)
            if args.duration is not None and (time.monotonic() - start) > args.duration:
                stop_event.set()
                break
    except KeyboardInterrupt:
        log.info("Interrupted, shutting down both threads...")
        stop_event.set()

    stop_event.set()
    ingest_thread.join(timeout=5)
    analysis_thread.join(timeout=5)

    store_ingest.close()
    store_analysis.close()
    log.info("Shutdown complete.")


if __name__ == "__main__":
    main()