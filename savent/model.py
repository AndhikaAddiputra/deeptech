"""Regresi linier deterministik dan metrik terhadap baseline persistensi."""

from __future__ import annotations

from savent.logic import Node, Sample, predict


def rising_trace(steps: int = 100, dt: float = 30.0) -> list[tuple[float, float, float]]:
    """Kenaikan 12 ppm/menit selama 35 menit, lalu datar. RH digoyang supaya tidak menyamar sebagai intercept."""
    co2 = 650.0
    rows = []
    for i in range(steps):
        t = i * dt
        if i > 0 and i < 70:
            co2 += 6.0
        rh = 55.0 + (i % 11)
        rows.append((t, co2, rh))
    return rows


def design_row(rows: list[tuple[float, float, float]], index: int) -> tuple[float, float, float, float] | None:
    """Fitur pada index dan target 10 menit kemudian. Butuh sejarah 2 menit."""
    t, co2, rh = rows[index]
    future_t = t + 600.0
    future = [row for row in rows if abs(row[0] - future_t) < 1e-6]
    past = [row for row in rows if t - row[0] >= 90.0]
    if not future or not past:
        return None
    t_then, co2_then, _ = min(past, key=lambda row: abs((t - 120.0) - row[0]))
    minutes = (t - t_then) / 60.0
    if minutes <= 0:
        return None
    dco2 = (co2 - co2_then) / minutes
    return co2, dco2, rh, future[0][1]


def fit(rows: list[tuple[float, float, float]] | None = None) -> tuple[float, float, float, float]:
    """Kuadrat terkecil untuk y = a0 + a1·co2 + a2·dco2 + a3·rh."""
    rows = rows if rows is not None else rising_trace()
    samples = [design_row(rows, i) for i in range(len(rows))]
    samples = [row for row in samples if row is not None]
    # Normal equation dengan penambahan kecil pada diagonal agar RH yang konstan tidak meledak.
    dim = 4
    ata = [[0.0 for _ in range(dim)] for _ in range(dim)]
    atb = [0.0 for _ in range(dim)]
    for co2, dco2, rh, y in samples:
        x = [1.0, co2, dco2, rh]
        for r in range(dim):
            atb[r] += x[r] * y
            for c in range(dim):
                ata[r][c] += x[r] * x[c]
    for r in range(dim):
        ata[r][r] += 1e-6
    coeff = _solve(ata, atb)
    return tuple(coeff)  # type: ignore[return-value]


def replay_metrics(coefficients: tuple[float, float, float, float] | None = None) -> dict[str, float | None]:
    """MAE model, MAE persistensi, dan lead time pada jejak yang sama."""
    coefficients = coefficients if coefficients is not None else fit()
    rows = rising_trace()
    node = Node(coefficients=coefficients)
    node.uptime = 180.0
    node.now = 0.0
    abs_model = []
    abs_persist = []
    first_warn = None
    first_cross = None
    by_t = {t: co2 for t, co2, _ in rows}
    for t, co2, rh in rows:
        raw = int(round(co2 * 932.0 / 1013.25))
        record = node.advance(
            30.0,
            Sample(co2_raw=raw, t_c=27.0, rh_pct=rh, p_hpa=932.0, gas_ohm=200_000, pm25=18, pm10=24),
        )
        future = by_t.get(t + 600.0)
        if record["model_used"] and future is not None and record["co2_pred_10min_ppm"] is not None:
            abs_model.append(abs(record["co2_pred_10min_ppm"] - future))
            abs_persist.append(abs(record["co2_ppm"] - future))
        if first_warn is None and record["vent_request"] == "recommend_on":
            first_warn = t
        if first_cross is None and record["co2_ppm"] is not None and record["co2_ppm"] >= 1000:
            first_cross = t
    lead = None if first_warn is None or first_cross is None else first_cross - first_warn
    return {
        "mae_model_ppm": _mean(abs_model),
        "mae_persistence_ppm": _mean(abs_persist),
        "lead_time_s": lead,
        "n": float(len(abs_model)),
    }


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    n = len(vector)
    a = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        a[col], a[pivot] = a[pivot], a[col]
        scale = a[col][col]
        for j in range(col, n + 1):
            a[col][j] /= scale
        for r in range(n):
            if r == col:
                continue
            factor = a[r][col]
            for j in range(col, n + 1):
                a[r][j] -= factor * a[col][j]
    return [a[i][n] for i in range(n)]


def persistence_predict(co2_ppm: float) -> float:
    return predict(co2_ppm, 0.0, 0.0, (0.0, 1.0, 0.0, 0.0))
