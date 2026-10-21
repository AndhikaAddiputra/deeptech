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
from savent.twin import AIR_MODES, AIR_STAY, PRESETS, ClassroomTwin, recommend_air_mode
from savent.proof import compare_text, explain_decision, lead_text

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA = ROOT.parent / "data"
HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8765"))


class Demo:
    def __init__(self) -> None:
        self.coefficients = fit()
        self.metrics = replay_metrics(self.coefficients)
        self.node = Node(coefficients=self.coefficients)
        self.twin = ClassroomTwin()
        self.shadow = ClassroomTwin(self.twin.spec)
        self.air_override: str | None = None
        self.breath_ticks = 0
        self.sensor_dead = False
        self.checksum_fail = False
        self.broker_up = True
        self.published: list[dict] = []
        self.above_s = 0.0
        self.shadow_above_s = 0.0
        self.model_warn_at: float | None = None
        self.rule_warn_at: float | None = None
        self.lock = threading.Lock()
        self._stop = threading.Event()

    def tick(self) -> None:
        with self.lock:
            if self.breath_ticks > 0:
                self.twin.co2_ppm += 40
                self.shadow.co2_ppm += 40
                self.breath_ticks -= 1
            seen_co2 = self.twin.co2_ppm
            seen_shadow = self.shadow.co2_ppm
            outdoor = OutdoorSample(pm25=self.twin.spec.outdoor_pm25, pm_quality="ok")
            record = self.node.advance(30.0, self._sample(), outdoor, self.broker_up)
            mode = self._air_mode(record)
            self.twin.step(30.0, mode)
            self.shadow.step(30.0, AIR_STAY)
            self._tally(seen_co2, seen_shadow, record)
            record["air_mode"] = mode
            record["recommended_air_mode"] = recommend_air_mode(self.node.demand, record["outdoor_intake_ok"])
            record["reason"] = explain_decision(record, mode)
            record["fan_actuator"] = mode in ("air_in", "air_out")
            self._ingest(record)

    def _tally(self, seen_co2: float, seen_shadow: float, record: dict) -> None:
        if record.get("quality", {}).get("co2") != "ok":
            return
        if seen_co2 >= 1000:
            self.above_s += 30
        if seen_shadow >= 1000:
            self.shadow_above_s += 30
        co2 = record.get("co2_ppm")
        pred = record.get("co2_pred_10min_ppm")
        if self.model_warn_at is None and record.get("model_used") and pred is not None and co2 is not None and pred >= 1000 and co2 < 1000:
            self.model_warn_at = self.node.now
        if self.rule_warn_at is None and co2 is not None and co2 >= 1000:
            self.rule_warn_at = self.node.now

    def _proof(self) -> dict:
        return {
            "reason": explain_decision(self.node.last_record or {}, (self.node.last_record or {}).get("air_mode", "air_stay")),
            "lead": lead_text(self.model_warn_at, self.rule_warn_at, self.metrics.get("lead_time_s")),
            "compare": compare_text(self.above_s, self.shadow_above_s),
        }

    def _sample(self) -> Sample:
        raw = None if self.sensor_dead else self.twin.raw_co2()
        return Sample(
            co2_raw=raw,
            co2_checksum_ok=not self.checksum_fail,
            t_c=round(self.twin.t_c, 1),
            rh_pct=round(self.twin.rh_pct, 1),
            p_hpa=self.twin.spec.pressure_hpa,
            gas_ohm=self.twin.gas_ohm(),
            pm25=int(round(self.twin.pm25)),
            pm10=int(round(self.twin.pm10)),
        )

    def _air_mode(self, record: dict) -> str:
        if self.air_override in AIR_MODES:
            return self.air_override
        if not record["fan_on"]:
            return "air_stay"
        return recommend_air_mode(True, record["outdoor_intake_ok"])

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
                self.breath_ticks = 8
            elif name == "sensor_dead":
                self.sensor_dead = True
            elif name == "sensor_ok":
                self.sensor_dead = False
                self.checksum_fail = False
            elif name == "broker_down":
                self.broker_up = False
            elif name == "broker_up":
                self.broker_up = True
            elif name == "outdoor_dirty":
                self.twin.spec.outdoor_pm25 = 90
                self.twin.spec.outdoor_pm10 = 120
            elif name == "outdoor_clean":
                self.twin.spec.outdoor_pm25 = 12
                self.twin.spec.outdoor_pm10 = 20
            elif name == "humid":
                self.twin.rh_pct = 82
            elif name == "dry":
                self.twin.rh_pct = 60
            elif name in PRESETS:
                self.twin.spec.replace(PRESETS[name])

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
                    {
                        "seq": item["seq"],
                        "co2_ppm": item["co2_ppm"],
                        "pred": item["co2_pred_10min_ppm"],
                        "air_mode": item.get("air_mode"),
                    }
                    for item in self.published[-60:]
                ],
                "twin": self._twin_view(),
                "proof": self._proof(),
                "clock": "1 detik dinding = 30 detik sensor",
            }

    def _twin_view(self) -> dict:
        view = self.twin.public_state()
        record = self.node.last_record or {}
        view["override"] = self.air_override
        view["recommended_air_mode"] = recommend_air_mode(
            bool(record.get("vent_request") in ("recommend_on", "on")),
            bool(record.get("outdoor_intake_ok", True)),
        )
        return view

    def configure_twin(self, payload: dict) -> dict:
        with self.lock:
            preset = payload.get("preset")
            if preset in PRESETS:
                self.twin.spec.replace(PRESETS[preset])
            if "spec" in payload:
                self.twin.spec.replace(payload["spec"])
            override = payload.get("override", self.air_override)
            self.air_override = override if override in AIR_MODES else None
            return self._twin_view()

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

        handler = make_handler(self)
        try:
            server = ThreadingHTTPServer((HOST, PORT), handler)
        except OSError as exc:
            if exc.errno == 48:
                raise SystemExit(
                    f"Port {PORT} sudah dipakai server SAVENT yang masih hidup. "
                    f"Hentikan proses itu, lalu jalankan perintah ini lagi. "
                    f"Atau pakai port lain: PORT=8766 python3 -m prototype.server"
                ) from exc
            raise
        self.tick()
        threading.Thread(target=loop, daemon=True).start()
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
            if path == "/api/twin":
                self._json(demo.configure_twin(payload))
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
