"""Kalimat bukti untuk juri: alasan keputusan dan selisih waktu terhadap aturan ambang."""

from __future__ import annotations


def explain_decision(record: dict, air_mode: str) -> str:
    quality = (record.get("quality") or {}).get("co2")
    co2 = record.get("co2_ppm")
    pred = record.get("co2_pred_10min_ppm")
    if quality != "ok":
        return f"Sensor CO₂ berbendera {quality or 'belum siap'}, jadi kipas tidak dinyalakan."
    if record.get("force_off"):
        return "Kipas dihentikan manual dan mengalahkan model."
    if air_mode == "air_in":
        return _ventilation_reason("Udara luar dimasukkan dan kipas menyala", record, co2, pred, record.get("outdoor_intake_ok", True))
    if air_mode == "air_out":
        base = _ventilation_reason("Udara dalam dibuang dan kipas menyala", record, co2, pred, False)
        return base + " Partikel luar tidak ikut masuk."
    if record.get("vent_request") == "recommend_on":
        return (
            f"Disarankan menyalakan kipas: prediksi 10 menit {_ppm(pred)}, "
            f"CO₂ sekarang {_ppm(co2)}. Udara belum digerakkan."
        )
    return "Udara dibiarkan diam karena belum ada permintaan ventilasi."


def lead_text(model_at_s: float | None, rule_at_s: float | None, training_lead_s: float | None, threshold: float = 1000) -> str:
    if model_at_s is not None and rule_at_s is not None and rule_at_s > model_at_s:
        minutes = (rule_at_s - model_at_s) / 60.0
        return f"Prediksi menyarankan ventilasi {minutes:.0f} menit lebih awal daripada aturan ambang."
    if model_at_s is not None and rule_at_s is None:
        return f"Prediksi sudah menyarankan ventilasi. Aturan ambang belum menyala karena CO₂ masih di bawah {threshold:.0f} ppm."
    if training_lead_s:
        return (
            f"Pada jejak latihan, prediksi lebih awal {training_lead_s / 60.0:.0f} menit "
            f"daripada menunggu CO₂ menyentuh {threshold:.0f} ppm."
        )
    return "Selisih waktu terhadap aturan ambang belum tersedia."


def compare_text(controlled_s: float, idle_s: float, threshold: float = 1000) -> str:
    return (
        f"CO₂ di atas {threshold:.0f} ppm: ruang ini {controlled_s / 60:.0f} menit, "
        f"ruang yang dibiarkan diam {idle_s / 60:.0f} menit."
    )


def _ventilation_reason(action: str, record: dict, co2: int | None, pred: int | None, outdoor_ok: bool) -> str:
    threshold = int(record.get("co2_on_ppm") or 1000)
    if pred is not None and co2 is not None and pred >= threshold and co2 < threshold:
        cause = f"prediksi 10 menit {_ppm(pred)} sementara CO₂ sekarang masih {_ppm(co2)}"
    elif co2 is not None and co2 >= threshold:
        cause = f"CO₂ sekarang {_ppm(co2)} sudah melewati {threshold} ppm"
    else:
        cause = "ada permintaan ventilasi"
    outdoor = "udara luar layak dimasukkan" if outdoor_ok else "udara luar lebih kotor"
    return f"{action} karena {cause}, dan {outdoor}."


def _ppm(value: int | None) -> str:
    return "belum ada" if value is None else f"{value} ppm"
