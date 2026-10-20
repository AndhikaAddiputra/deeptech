"""Dasbor demo SAVENT. Satu proses, tanpa broker terpisah.

Waktu sensor berjalan 30 detik tiap 1 detik jam dinding supaya loop
ventilasi bisa diperlihatkan. Label di dasbor menyatakan percepatan ini.
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from savent.logic import Node, OutdoorSample, Sample
from savent.model import fit, replay_metrics

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA = ROOT.parent / "data"
HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8765"))


class Room:
    def __init__(self) -> None:
        self.co2_raw = 700.0
        self.breath_ticks = 0
        self.sensor_dead = False
        self.checksum_fail = False
        self.humid = False

    def sample(self, uptime_s: float) -> Sample:
        if self.breath_ticks > 0:
            self.co2_raw += 50
            self.breath_ticks -= 1
        elif uptime_s >= 180 and not self.sensor_dead:
            self.co2_raw += 18
        self.co2_raw = min(self.co2_raw, 1800)
        raw = None if self.sensor_dead else int(round(self.co2_raw))
        return Sample(
            co2_raw=raw,
            co2_checksum_ok=not self.checksum_fail,
            t_c=27.4,
            rh_pct=82.0 if self.humid else 62.0,
            p_hpa=932.0,
            gas_ohm=150_000,
            pm25=18,
            pm10=24,
            pm_checksum_ok=True,
        )


class Demo:
    def __init__(self) -> None:
        self.coefficients = fit()
        self.metrics = replay_metrics(self.coefficients)
        self.node = Node(coefficients=self.coefficients)
        self.room = Room()
        self.outdoor = OutdoorSample(pm25=12, pm_quality="ok")
        self.broker_up = True
        self.published: list[dict] = []
        self.lock = threading.Lock()
        self._stop = threading.Event()

    def tick(self) -> None:
        with self.lock:
            record = self.node.advance(30.0, self.room.sample(self.node.uptime), self.outdoor, self.broker_up)
            self._ingest(record)

    def command(self, payload: dict) -> dict:
        with self.lock:
            event = self.node.command(payload)
            if self.node.last_record is not None:
                self.node.last_record["fan_on"] = self.node.fan_on
                self.node.last_record["mode"] = self.node.mode
                self.node.last_record["vent_request"] = self.node.vent_request(self.node.co2_valid)
                self.node.last_record["force_off"] = self.node.force_off
            return event

    def scenario(self, name: str) -> None:
        with self.lock:
            if name == "breath":
                self.room.breath_ticks = 8
            elif name == "sensor_dead":
                self.room.sensor_dead = True
            elif name == "sensor_ok":
                self.room.sensor_dead = False
                self.room.checksum_fail = False
            elif name == "broker_down":
                self.broker_up = False
            elif name == "broker_up":
                self.broker_up = True
            elif name == "outdoor_dirty":
                self.outdoor = OutdoorSample(pm25=80, pm_quality="ok")
            elif name == "outdoor_clean":
                self.outdoor = OutdoorSample(pm25=12, pm_quality="ok")
            elif name == "humid":
                self.room.humid = True
            elif name == "dry":
                self.room.humid = False

    def snapshot(self) -> dict:
        with self.lock:
            record = dict(self.node.last_record or {})
            record.pop("_flush", None)
            return {
                "record": record or None,
                "events": self.node.events[-30:],
                "buffer_depth": len(self.node.buffer),
                "broker_up": self.broker_up,
                "published": len(self.published),
                "coefficients": {
                    "a0": round(self.coefficients[0], 4),
                    "a1": round(self.coefficients[1], 4),
                    "a2": round(self.coefficients[2], 4),
                    "a3": round(self.coefficients[3], 4),
                },
                "metrics": self.metrics,
                "history": [
                    {"seq": item["seq"], "co2_ppm": item["co2_ppm"], "pred": item["co2_pred_10min_ppm"]}
                    for item in self.published[-60:]
                ],
                "clock": "1 detik dinding = 30 detik sensor",
            }

    def _ingest(self, record: dict) -> None:
        batch = list(record.get("_flush", []))
        if self.broker_up:
            batch.append(record)
        for item in batch:
            clean = {key: value for key, value in item.items() if key != "_flush"}
            self.published.append(clean)
            _append_line(clean)
        del self.published[:-480]

    def serve(self) -> None:
        def loop() -> None:
            while not self._stop.wait(1.0):
                self.tick()

        self.tick()
        threading.Thread(target=loop, daemon=True).start()
        handler = make_handler(self)
        server = ThreadingHTTPServer((HOST, PORT), handler)
        print(f"SAVENT demo di http://{HOST}:{PORT}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            self._stop.set()
            server.shutdown()


def _append_line(record: dict) -> None:
    if record.get("co2_ppm") is None:
        return
    DATA.mkdir(exist_ok=True)
    fields = ",".join(
        f"{key}={record[key]}"
        for key in ("co2_ppm", "co2_raw_ppm", "t_c", "rh_pct", "p_hpa", "pm25_ugm3", "pm10_ugm3", "mode")
        if isinstance(record.get(key), (int, float))
    )
    line = f"telemetry,site={record['site']},node={record['node']} {fields} {record['seq']}\n"
    with (DATA / "telemetry.line").open("a", encoding="utf-8") as handle:
        handle.write(line)


def make_handler(demo: Demo):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/state":
                self._json(demo.snapshot())
                return
            if path == "/":
                path = "/index.html"
            file_path = (STATIC / path.lstrip("/")).resolve()
            if not str(file_path).startswith(str(STATIC.resolve())) or not file_path.is_file():
                self.send_error(404)
                return
            kind = "text/html" if file_path.suffix == ".html" else "text/css" if file_path.suffix == ".css" else "text/javascript"
            body = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if path == "/api/command":
                payload.setdefault("source", "dashboard")
                self._json(demo.command(payload))
                return
            if path == "/api/scenario":
                demo.scenario(payload.get("name", ""))
                self._json({"ok": True})
                return
            self.send_error(404)

        def _json(self, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            return

    return Handler


def main() -> None:
    Demo().serve()


if __name__ == "__main__":
    main()
