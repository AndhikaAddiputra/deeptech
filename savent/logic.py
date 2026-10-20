"""Aturan FSD-SAVENT yang tidak bergantung pada sensor atau jaringan."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


P_REF_HPA = 1013.25
CO2_ON_PPM = 1000
CO2_PRED_ON_PPM = 1000
CO2_OFF_PPM = 800
CO2_PRED_OFF_PPM = 900
PM_OUTDOOR_MARGIN = 10
RH_PM_LIMIT = 75.0
WARMUP_CO2_S = 180.0
WARMUP_GAS_S = 300.0
WARMUP_PM_S = 30.0
STUCK_HOLD_S = 900.0
MIN_ON_S = 180.0
MIN_OFF_S = 120.0
CONFIRM_TTL_S = 60.0
SLOPE_TARGET_S = 120.0
SLOPE_MIN_S = 90.0
BUFFER_LIMIT = 480
EPOCH = datetime(2026, 10, 21, tzinfo=timezone.utc)

# Diisi ulang oleh savent.model bila jejak latihan dihitung.
# Fallback ini adalah ekstrapolasi laju: CO2 + 10 menit * dCO2/dt.
DEFAULT_COEFFICIENTS = (0.0, 1.0, 10.0, 0.0)


def correct_co2(raw_ppm: float, p_hpa: float) -> float:
    """Campuran CO2 setelah koreksi tekanan. Arah: tekanan Bandung menaikkan bacaan."""
    return raw_ppm * P_REF_HPA / p_hpa


def voc_index(gas_ohm: float, baseline_ohm: float) -> int:
    """Indeks 0–500. Resistansi lebih kecil dari baseline menaikkan indeks."""
    if baseline_ohm <= 0:
        return 0
    raw = 500.0 * (baseline_ohm - gas_ohm) / baseline_ohm
    return int(max(0, min(500, round(raw))))


def co2_quality(
    *,
    uptime_s: float,
    raw: int | None,
    checksum_ok: bool,
    pressure_ok: bool,
    held_s: float,
) -> str:
    if uptime_s < WARMUP_CO2_S:
        return "warming"
    if raw is None or not checksum_ok or not pressure_ok:
        return "fault"
    if held_s >= STUCK_HOLD_S and raw in (0, 400, 5000):
        return "stuck"
    if raw < 400 or raw > 5000:
        return "out_of_range"
    return "ok"


def pm_quality(*, uptime_s: float, value: int | None, checksum_ok: bool, rh_pct: float | None) -> str:
    if uptime_s < WARMUP_PM_S:
        return "warming"
    if value is None or not checksum_ok:
        return "fault"
    if rh_pct is not None and rh_pct >= RH_PM_LIMIT:
        return "rh_high"
    return "ok"


def gas_quality(*, uptime_s: float, gas_ohm: float | None) -> str:
    if uptime_s < WARMUP_GAS_S:
        return "warming"
    if gas_ohm is None:
        return "fault"
    return "ok"


def climate_quality(*, t_c: float | None, rh_pct: float | None, p_hpa: float | None) -> str:
    if t_c is None or rh_pct is None or p_hpa is None:
        return "fault"
    return "ok"


def predict(co2_ppm: float, dco2_dt: float, rh_pct: float, coefficients: tuple[float, float, float, float]) -> float:
    a0, a1, a2, a3 = coefficients
    return a0 + a1 * co2_ppm + a2 * dco2_dt + a3 * rh_pct


def compliance(co2_ppm: float | None, t_c: float | None, rh_pct: float | None, pm25: float | None, pm_quality_flag: str) -> dict[str, Any]:
    """Status tampilan. PM2.5 sesaat bukan klaim rata-rata 24 jam."""
    return {
        "co2": _band(co2_ppm, high=CO2_ON_PPM),
        "temperature": _inside(t_c, 23.0, 26.0),
        "humidity": _inside(rh_pct, 40.0, 60.0),
        "pm25_instant_indicator": None if pm_quality_flag == "fault" or pm25 is None else ("tinggi" if pm25 > 25 else "dalam_indikator"),
        "pm25_note": "Ambang 25 µg/m³ adalah rata-rata 24 jam, bukan bacaan sesaat.",
        "voc_note": "Indeks tidak terkalibrasi.",
    }


def _band(value: float | None, high: float) -> str | None:
    if value is None:
        return None
    return "di_atas" if value >= high else "di_bawah"


def _inside(value: float | None, low: float, high: float) -> str | None:
    if value is None:
        return None
    if value < low:
        return "di_bawah"
    if value > high:
        return "di_atas"
    return "di_dalam"


def outdoor_intake_ok(indoor_pm25: float | None, indoor_flag: str, outdoor_pm25: float | None, outdoor_flag: str | None) -> bool:
    """False hanya bila kedua sampel PM layak dibandingkan dan udara luar lebih kotor."""
    if outdoor_pm25 is None or outdoor_flag != "ok" or indoor_flag != "ok" or indoor_pm25 is None:
        return True
    return outdoor_pm25 <= indoor_pm25 + PM_OUTDOOR_MARGIN


@dataclass
class Sample:
    co2_raw: int | None = None
    co2_checksum_ok: bool = True
    t_c: float | None = None
    rh_pct: float | None = None
    p_hpa: float | None = None
    gas_ohm: float | None = None
    pm25: int | None = None
    pm10: int | None = None
    pm_checksum_ok: bool = True


@dataclass
class OutdoorSample:
    pm25: float | None = None
    pm_quality: str = "fault"


@dataclass
class Node:
    site: str = "hackathon-demo"
    node_id: str = "indoor-01"
    coefficients: tuple[float, float, float, float] = DEFAULT_COEFFICIENTS
    mode: int = 1
    now: float = 0.0
    uptime: float = 0.0
    seq: int = 0
    fan_on: bool = False
    demand: bool = False
    force_off: bool = False
    confirm_until: float | None = None
    fan_changed_at: float = -1.0e9
    co2_valid: bool = False
    gas_baseline: float | None = None
    buffer: deque = field(default_factory=lambda: deque(maxlen=BUFFER_LIMIT))
    events: list[dict[str, Any]] = field(default_factory=list)
    history: list[tuple[float, float]] = field(default_factory=list)
    _last_raw: int | None = None
    _held_s: float = 0.0
    last_record: dict[str, Any] | None = None
    firmware: str = "savent-0.1.0"

    def command(self, payload: dict[str, Any]) -> dict[str, Any]:
        source = payload.get("source")
        if not source:
            return self._event("command_rejected", "node", "perintah tanpa source ditolak")
        cmd = payload.get("cmd")
        if cmd == "set_mode":
            mode = payload.get("mode")
            if mode not in (0, 1, 2, 3):
                return self._event("command_rejected", source, "mode tidak dikenal")
            if mode != self.mode:
                self.mode = mode
                self._event("mode_changed", source, f"mode {mode}")
            self._apply_fan(source)
            return self.events[-1]
        if cmd == "confirm":
            self.confirm_until = self.now + CONFIRM_TTL_S
            self._event("command", source, "confirm")
            self._apply_fan(source)
            return self.events[-1]
        if cmd == "force_off":
            self.force_off = True
            self._event("command", source, "force_off")
            self._apply_fan(source)
            return self.events[-1]
        if cmd == "force_off_release":
            self.force_off = False
            self._event("command", source, "force_off_release")
            self._apply_fan(source)
            return self.events[-1]
        return self._event("command_rejected", source, "cmd tidak dikenal")

    def advance(self, dt: float, sample: Sample, outdoor: OutdoorSample | None = None, broker_up: bool = True) -> dict[str, Any]:
        self.now += dt
        self.uptime += dt
        self._track_hold(sample.co2_raw, dt)
        flags = self._flags(sample)
        co2_corr = None
        if sample.co2_raw is not None and sample.p_hpa not in (None, 0):
            co2_corr = correct_co2(sample.co2_raw, sample.p_hpa)
        co2_ok = flags["co2"] == "ok" and co2_corr is not None
        if co2_ok:
            self.history.append((self.now, co2_corr))
        self.history = [(t, v) for t, v in self.history if self.now - t <= 900]
        dco2, slope_ready = self._slope(co2_corr if co2_ok else None)
        rh_ok = flags["climate"] == "ok" and sample.rh_pct is not None
        model_ready = bool(co2_ok and slope_ready and rh_ok)
        pred = predict(co2_corr, dco2, sample.rh_pct, self.coefficients) if model_ready else None
        self._update_demand(co2_corr, pred, co2_ok, model_ready)
        self._apply_fan("node")
        if flags["gas"] == "ok" and sample.gas_ohm is not None and self.gas_baseline is None:
            self.gas_baseline = sample.gas_ohm
        voc = voc_index(sample.gas_ohm, self.gas_baseline) if self.gas_baseline and sample.gas_ohm is not None else None
        intake = outdoor_intake_ok(
            sample.pm25,
            flags["pm"],
            None if outdoor is None else outdoor.pm25,
            None if outdoor is None else outdoor.pm_quality,
        )
        self.seq += 1
        record = {
            "ts": (EPOCH + timedelta(seconds=self.now)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "time_source": "ntp",
            "seq": self.seq,
            "node": self.node_id,
            "site": self.site,
            "co2_raw_ppm": sample.co2_raw,
            "co2_ppm": None if co2_corr is None else int(round(co2_corr)),
            "t_c": sample.t_c,
            "rh_pct": sample.rh_pct,
            "p_hpa": sample.p_hpa,
            "gas_ohm": sample.gas_ohm,
            "voc_index_uncalibrated": voc,
            "pm25_ugm3": sample.pm25,
            "pm10_ugm3": sample.pm10,
            "quality": flags,
            "co2_pred_10min_ppm": None if pred is None else int(round(pred)),
            "model_used": model_ready,
            "dco2_dt_ppm_per_min": None if not slope_ready else round(dco2, 3),
            "vent_request": self.vent_request(co2_ok),
            "outdoor_intake_ok": intake,
            "mode": self.mode,
            "fan_on": self.fan_on,
            "force_off": self.force_off,
            "compliance": compliance(
                None if co2_corr is None else co2_corr,
                sample.t_c,
                sample.rh_pct,
                sample.pm25,
                flags["pm"],
            ),
        }
        self.last_record = record
        if broker_up:
            flushing = list(self.buffer)
            self.buffer.clear()
            record["_flush"] = flushing
        else:
            self.buffer.append(record)
            record["_flush"] = []
        record["buffer_depth"] = len(self.buffer)
        return record

    def vent_request(self, co2_ok: bool) -> str:
        if not self.demand or not co2_ok:
            return "off"
        if self.fan_on:
            return "on"
        return "recommend_on"

    def _track_hold(self, raw: int | None, dt: float) -> None:
        if raw is None:
            self._last_raw = None
            self._held_s = 0.0
            return
        if raw == self._last_raw:
            self._held_s += dt
        else:
            self._last_raw = raw
            self._held_s = 0.0

    def _flags(self, sample: Sample) -> dict[str, str]:
        pressure_ok = sample.p_hpa not in (None, 0)
        return {
            "co2": co2_quality(
                uptime_s=self.uptime,
                raw=sample.co2_raw,
                checksum_ok=sample.co2_checksum_ok,
                pressure_ok=pressure_ok,
                held_s=self._held_s,
            ),
            "climate": climate_quality(t_c=sample.t_c, rh_pct=sample.rh_pct, p_hpa=sample.p_hpa),
            "gas": gas_quality(uptime_s=self.uptime, gas_ohm=sample.gas_ohm),
            "pm": pm_quality(
                uptime_s=self.uptime,
                value=sample.pm25,
                checksum_ok=sample.pm_checksum_ok,
                rh_pct=sample.rh_pct,
            ),
        }

    def _slope(self, co2_now: float | None) -> tuple[float, bool]:
        if co2_now is None or len(self.history) < 2:
            return 0.0, False
        target = self.now - SLOPE_TARGET_S
        past = [item for item in self.history if self.now - item[0] >= SLOPE_MIN_S]
        if not past:
            return 0.0, False
        t_then, v_then = min(past, key=lambda item: abs(item[0] - target))
        minutes = (self.now - t_then) / 60.0
        if minutes <= 0:
            return 0.0, False
        return (co2_now - v_then) / minutes, True

    def _update_demand(self, co2: float | None, pred: float | None, co2_ok: bool, model_ready: bool) -> None:
        self.co2_valid = bool(co2_ok and co2 is not None)
        if not self.co2_valid:
            if self.demand:
                self._event("fan_blocked", "node", "CO2 tidak valid, permintaan hidup dibatalkan")
            self.demand = False
            return
        if model_ready and pred is not None:
            if pred >= CO2_PRED_ON_PPM or co2 >= CO2_ON_PPM:
                self.demand = True
            elif pred < CO2_PRED_OFF_PPM and co2 <= CO2_OFF_PPM:
                self.demand = False
            return
        if co2 >= CO2_ON_PPM:
            self.demand = True
        elif co2 <= CO2_OFF_PPM:
            self.demand = False

    def _apply_fan(self, source: str) -> None:
        previous = self.fan_on
        target = self._fan_target()
        if target == previous:
            return
        self.fan_on = target
        self.fan_changed_at = self.now
        self._event("fan_on" if target else "fan_off", source, "kipas demo")

    def _fan_target(self) -> bool:
        if self.mode in (0, 1):
            return False
        want = self.demand and not self.force_off and self.co2_valid
        if self.mode == 2:
            confirmed = self.confirm_until is not None and self.now <= self.confirm_until
            return want and confirmed
        if self.fan_on and not want:
            if self.force_off or not self.co2_valid:
                return False
            if (self.now - self.fan_changed_at) < MIN_ON_S:
                return True
            return False
        if (not self.fan_on) and want and (self.now - self.fan_changed_at) < MIN_OFF_S:
            return False
        return want

    def _event(self, kind: str, source: str, detail: str) -> dict[str, Any]:
        event = {
            "ts": (EPOCH + timedelta(seconds=self.now)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "type": kind,
            "source": source,
            "detail": detail,
        }
        self.events.append(event)
        return event
