"""
Ingestion source abstraction: yields raw line strings regardless of whether
they come from a real ESP32 over USB serial, a replayed log file (e.g. a
serial monitor capture exported from Wokwi), or the built-in mock generator.

Serial and wokwi sources auto-reconnect on a dropped connection (network
hiccup, USB unplug/replug) instead of letting the exception kill the whole
pipeline -- a live demo shouldn't die because of one transient disconnect.
"""

import logging
import time
from typing import Iterator

import mock_stream

log = logging.getLogger("edgewatch.serial_reader")

MAX_RECONNECT_DELAY_SEC = 10


def _resilient_serial_stream(open_connection, label: str) -> Iterator[str]:
    """
    Wraps a pyserial connection with auto-reconnect. `open_connection` is a
    zero-arg callable that returns a fresh pyserial connection object (so we
    can call it again after a drop). Retries with exponential backoff, capped
    at MAX_RECONNECT_DELAY_SEC, and logs each attempt rather than failing
    silently or crashing the pipeline.
    """
    import serial

    delay = 1
    while True:
        try:
            with open_connection() as ser:
                log.info("%s: connected.", label)
                delay = 1  # reset backoff after a successful connection
                while True:
                    raw = ser.readline()
                    if not raw:
                        continue
                    yield raw.decode("utf-8", errors="ignore").strip()
        except (serial.SerialException, OSError, ConnectionError) as e:
            log.warning("%s: connection dropped (%s). Reconnecting in %ds...", label, e, delay)
            time.sleep(delay)
            delay = min(delay * 2, MAX_RECONNECT_DELAY_SEC)


def from_serial(port: str, baud: int = 115200) -> Iterator[str]:
    import serial

    yield from _resilient_serial_stream(
        lambda: serial.Serial(port, baud, timeout=2),
        label=f"serial:{port}",
    )


def from_wokwi_rfc2217(host: str = "localhost", port: int = 4000, baud: int = 115200) -> Iterator[str]:
    """
    Connect to a Wokwi VS Code simulation's serial output over the network.

    Requires `rfc2217ServerPort = <port>` set in wokwi.toml.

    Two distinct things can interrupt this stream:
    1. Wokwi's own simulator PAUSING when its VS Code tab loses visibility --
       this isn't a connection drop, the socket stays open, telemetry just
       stops arriving until the tab is visible again. No fix on this side;
       keep the Wokwi tab visible while the pipeline runs.
    2. An actual connection drop (network hiccup) -- this DOES raise an
       exception, which is what the reconnect loop below handles.
    """
    import serial

    url = f"rfc2217://{host}:{port}"
    yield from _resilient_serial_stream(
        lambda: serial.serial_for_url(url, baudrate=baud, timeout=2),
        label=f"wokwi-rfc2217:{host}:{port}",
    )


def from_file(path: str, replay_delay: float = 0.0) -> Iterator[str]:
    """Replay a captured log file. Set replay_delay>0 to simulate real timing."""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            yield line.strip()
            if replay_delay:
                time.sleep(replay_delay)


def from_mock(interval: float = 5.0) -> Iterator[str]:
    yield from mock_stream.generate(interval=interval)


def get_source(kind: str, **kwargs) -> Iterator[str]:
    if kind == "serial":
        return from_serial(kwargs["port"], kwargs.get("baud", 115200))
    if kind == "wokwi":
        return from_wokwi_rfc2217(
            kwargs.get("host", "localhost"), kwargs.get("rfc2217_port", 4000), kwargs.get("baud", 115200)
        )
    if kind == "file":
        return from_file(kwargs["path"], kwargs.get("replay_delay", 0.0))
    if kind == "mock":
        return from_mock(kwargs.get("interval", 5.0))
    raise ValueError(f"unknown source kind: {kind}")