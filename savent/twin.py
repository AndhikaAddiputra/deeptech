"""Digital twin satu zona untuk ruang kelas.

Udara dianggap tercampur rata. Volume = luas lantai × tinggi plafon.
Tiga mode hanya mengubah laju dan sumber udara pengganti:

- air_stay: tidak ada ventilasi mekanis, hanya bocoran selubung.
- air_in: udara luar masuk dan mengencerkan ruangan.
- air_out: udara dalam dibuang. Udara pengganti tetap dari luar,
  tetapi partikelnya berkurang oleh filter dummy. CO₂ tidak tersaring.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass


AIR_STAY = "air_stay"
AIR_IN = "air_in"
AIR_OUT = "air_out"
AIR_MODES = (AIR_STAY, AIR_IN, AIR_OUT)


@dataclass
class RoomSpec:
    floor_area_m2: float = 72.0
    ceiling_m: float = 3.2
    occupants: int = 24
    co2_l_per_person_h: float = 18.0
    pm25_ug_per_person_h: float = 6.0
    infiltration_ach: float = 0.2
    supply_ach: float = 6.0
    exhaust_ach: float = 6.0
    exhaust_pm_filter: float = 0.6
    outdoor_co2_ppm: float = 450.0
    outdoor_pm25: float = 12.0
    outdoor_pm10: float = 20.0
    outdoor_t_c: float = 28.0
    outdoor_rh: float = 68.0
    pressure_hpa: float = 932.0
    heat_w_per_person: float = 70.0
    process_co2_m3_h: float = 0.0
    process_pm_ug_h: float = 0.0
    co2_on_ppm: int = 1000
    co2_off_ppm: int = 800
    co2_pred_off_ppm: int = 900
    environment: str = "kelas"

    @property
    def volume_m3(self) -> float:
        return self.floor_area_m2 * self.ceiling_m

    def replace(self, values: dict) -> None:
        for key, raw in values.items():
            if not hasattr(self, key) or key == "volume_m3":
                continue
            current = getattr(self, key)
            setattr(self, key, type(current)(raw))
        self._clamp()

    def _clamp(self) -> None:
        self.floor_area_m2 = _bound(self.floor_area_m2, 10, 800)
        self.ceiling_m = _bound(self.ceiling_m, 2.4, 15)
        self.occupants = int(_bound(self.occupants, 0, 400))
        self.infiltration_ach = _bound(self.infiltration_ach, 0, 2)
        self.supply_ach = _bound(self.supply_ach, 0, 20)
        self.exhaust_ach = _bound(self.exhaust_ach, 0, 20)
        self.exhaust_pm_filter = _bound(self.exhaust_pm_filter, 0, 0.95)
        self.outdoor_co2_ppm = _bound(self.outdoor_co2_ppm, 350, 800)
        self.outdoor_pm25 = _bound(self.outdoor_pm25, 0, 500)
        self.pressure_hpa = _bound(self.pressure_hpa, 800, 1100)
        self.process_co2_m3_h = _bound(self.process_co2_m3_h, 0, 20)
        self.process_pm_ug_h = _bound(self.process_pm_ug_h, 0, 5_000_000)
        self.co2_on_ppm = int(_bound(self.co2_on_ppm, 400, 5000))
        self.co2_off_ppm = int(_bound(self.co2_off_ppm, 300, self.co2_on_ppm))
        self.co2_pred_off_ppm = int(_bound(self.co2_pred_off_ppm, self.co2_off_ppm, self.co2_on_ppm))
        if self.environment not in ENVIRONMENTS:
            self.environment = "kelas"


PRESETS = {
    "kelas-kecil": {"floor_area_m2": 40, "ceiling_m": 3.0, "occupants": 15},
    "kelas-standar": {"floor_area_m2": 72, "ceiling_m": 3.2, "occupants": 24},
    "auditorium": {"floor_area_m2": 200, "ceiling_m": 5.0, "occupants": 80},
}

ENVIRONMENTS = {
    "kelas": {
        "title": "Ruang Kelas",
        "initial_co2": 650.0,
        "spec": {
            "environment": "kelas",
            "floor_area_m2": 72,
            "ceiling_m": 3.2,
            "occupants": 24,
            "co2_l_per_person_h": 18,
            "pressure_hpa": 932,
            "outdoor_pm25": 12,
            "outdoor_rh": 68,
            "co2_on_ppm": 1000,
            "co2_off_ppm": 800,
            "co2_pred_off_ppm": 900,
        },
        "presets": [
            {"id": "kelas-kecil", "label": "Kelas kecil"},
            {"id": "kelas-standar", "label": "Kelas standar"},
            {"id": "auditorium", "label": "Auditorium"},
        ],
    },
    "pabrik": {
        "title": "Ruang Pabrik",
        "initial_co2": 900.0,
        "spec": {
            "environment": "pabrik",
            "floor_area_m2": 400,
            "ceiling_m": 8,
            "occupants": 12,
            "co2_l_per_person_h": 22,
            "process_co2_m3_h": 5,
            "process_pm_ug_h": 80000,
            "supply_ach": 12,
            "exhaust_ach": 12,
            "pressure_hpa": 932,
            "outdoor_pm25": 28,
            "outdoor_t_c": 31,
            "co2_on_ppm": 2500,
            "co2_off_ppm": 2000,
            "co2_pred_off_ppm": 2200,
        },
        "presets": [
            {"id": "pabrik-kecil", "label": "Bengkel"},
            {"id": "pabrik", "label": "Lantai produksi"},
        ],
    },
    "rig": {
        "title": "Modular Living Quarters (MLQ) di Oil Rig",
        "initial_co2": 700.0,
        "spec": {
            "environment": "rig",
            "floor_area_m2": 15,
            "ceiling_m": 2.4,
            "occupants": 4,
            "co2_l_per_person_h": 12,
            "supply_ach": 8,
            "exhaust_ach": 8,
            "infiltration_ach": 0.35,
            "pressure_hpa": 1013,
            "outdoor_co2_ppm": 480,
            "outdoor_pm25": 35,
            "outdoor_pm10": 55,
            "outdoor_t_c": 30,
            "outdoor_rh": 82,
            "co2_on_ppm": 1000,
            "co2_off_ppm": 800,
            "co2_pred_off_ppm": 900,
        },
        "presets": [
            {"id": "mlq", "label": "Satu kabin MLQ"},
            {"id": "mlq-ganda", "label": "Dua kabin"},
        ],
    },
}

PRESETS.update({
    "pabrik-kecil": {"floor_area_m2": 180, "ceiling_m": 6, "occupants": 6, "environment": "pabrik"},
    "pabrik": {"floor_area_m2": 400, "ceiling_m": 8, "occupants": 12, "environment": "pabrik"},
    "mlq": {"floor_area_m2": 15, "ceiling_m": 2.4, "occupants": 4, "environment": "rig"},
    "mlq-ganda": {"floor_area_m2": 30, "ceiling_m": 2.4, "occupants": 8, "environment": "rig"},
})


class ClassroomTwin:
    def __init__(self, spec: RoomSpec | None = None) -> None:
        self.spec = spec or RoomSpec()
        self.co2_ppm = 650.0
        self.t_c = 27.0
        self.rh_pct = 60.0
        self.pm25 = 18.0
        self.pm10 = 24.0
        self.air_mode = AIR_STAY

    def flow_m3_h(self, mode: str) -> float:
        volume = self.spec.volume_m3
        leak = self.spec.infiltration_ach * volume
        if mode == AIR_IN:
            return leak + self.spec.supply_ach * volume
        if mode == AIR_OUT:
            return leak + self.spec.exhaust_ach * volume
        return leak

    def ach(self, mode: str) -> float:
        volume = self.spec.volume_m3
        if volume <= 0:
            return 0.0
        return self.flow_m3_h(mode) / volume

    def step(self, dt_s: float, mode: str) -> None:
        if mode not in AIR_MODES:
            mode = AIR_STAY
        self.air_mode = mode
        dt_h = dt_s / 3600.0
        volume = max(self.spec.volume_m3, 1.0)
        flow = self.flow_m3_h(mode)
        co2_in = self.spec.outdoor_co2_ppm
        pm_in = self.spec.outdoor_pm25
        if mode == AIR_OUT:
            pm_in = self.spec.outdoor_pm25 * (1.0 - self.spec.exhaust_pm_filter)
        co2_gen = self.spec.occupants * self.spec.co2_l_per_person_h / 1000.0 + self.spec.process_co2_m3_h
        pm_gen = self.spec.occupants * self.spec.pm25_ug_per_person_h + self.spec.process_pm_ug_h
        heat_w = self.spec.occupants * self.spec.heat_w_per_person
        self.co2_ppm = _mix(self.co2_ppm, co2_in, co2_gen * 1_000_000.0, flow, volume, dt_h)
        self.pm25 = max(0.0, _mix(self.pm25, pm_in, pm_gen, flow, volume, dt_h))
        self.pm10 = max(self.pm25, _mix(self.pm10, self.spec.outdoor_pm10, pm_gen * 1.3, flow, volume, dt_h))
        self.t_c = _mix(self.t_c, self.spec.outdoor_t_c, heat_w * 3.0, flow, volume, dt_h)
        self.rh_pct = _bound(_mix(self.rh_pct, self.spec.outdoor_rh, self.spec.occupants * 0.4, flow, volume, dt_h), 20, 95)

    def raw_co2(self) -> int:
        """Nilai sebelum koreksi tekanan, supaya jalur sensor yang ada tetap terpakai."""
        return int(round(self.co2_ppm * self.spec.pressure_hpa / 1013.25))

    def gas_ohm(self) -> float:
        return float(_bound(220_000 - (self.co2_ppm - 450) * 90, 20_000, 400_000))

    def public_state(self) -> dict:
        return {
            "spec": {key: value for key, value in asdict(self.spec).items()},
            "volume_m3": round(self.spec.volume_m3, 1),
            "air_mode": self.air_mode,
            "ach": round(self.ach(self.air_mode), 2),
            "co2_ppm": round(self.co2_ppm, 1),
            "t_c": round(self.t_c, 1),
            "rh_pct": round(self.rh_pct, 1),
            "pm25": round(self.pm25, 1),
            "pm10": round(self.pm10, 1),
        }


def recommend_air_mode(demand: bool, outdoor_intake_ok: bool) -> str:
    if not demand:
        return AIR_STAY
    if outdoor_intake_ok:
        return AIR_IN
    return AIR_OUT


def _mix(current: float, incoming: float, generation: float, flow: float, volume: float, dt_h: float) -> float:
    """current bergerak ke incoming dengan laju flow, ditambah generation per jam."""
    if flow <= 1e-9:
        return current + generation / volume * dt_h
    equilibrium = incoming + generation / flow
    decay = math.exp(-flow / volume * dt_h)
    return equilibrium + (current - equilibrium) * decay


def _bound(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
