const modes = [
  [0, "Pantau"],
  [1, "Dukungan keputusan"],
  [2, "Semi-otomatis"],
  [3, "Otomatis terbatas"],
];

const scenarios = [
  ["breath", "Hembusan napas"],
  ["sensor_dead", "Sensor CO₂ putus"],
  ["sensor_ok", "Sensor pulih"],
  ["broker_down", "Broker putus"],
  ["broker_up", "Broker pulih"],
  ["outdoor_dirty", "Udara luar kotor"],
  ["outdoor_clean", "Udara luar bersih"],
  ["humid", "RH di atas 75%"],
  ["dry", "RH normal"],
];

const modeBox = document.querySelector("#modes");
const scenarioBox = document.querySelector("#scenarios");

for (const [mode, label] of modes) {
  const button = document.createElement("button");
  button.textContent = label;
  button.dataset.mode = String(mode);
  button.addEventListener("click", () => post("/api/command", { cmd: "set_mode", mode, source: "dashboard" }));
  modeBox.append(button);
}

for (const [name, label] of scenarios) {
  const button = document.createElement("button");
  button.textContent = label;
  button.addEventListener("click", () => post("/api/scenario", { name }));
  scenarioBox.append(button);
}

for (const button of document.querySelectorAll("[data-cmd]")) {
  button.addEventListener("click", () => post("/api/command", { cmd: button.dataset.cmd, source: "dashboard" }));
}

async function post(url, body) {
  await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  refresh();
}

async function refresh() {
  const state = await (await fetch("/api/state")).json();
  const record = state.record;
  document.querySelector("#clock").textContent = state.clock;
  paintRecord(record);
  paintModes(record ? record.mode : 1);
  paintChart(state.history);
  paintMetrics(state);
  paintEvents(state.events);
}

function paintRecord(record) {
  const co2 = document.querySelector("#co2");
  const status = document.querySelector("#co2status");
  if (!record || record.co2_ppm == null) {
    co2.textContent = "–";
    document.querySelector("#co2meta").textContent = "Menunggu sampel pertama.";
    status.textContent = record ? labelQuality(record.quality.co2) : "";
    status.className = "status wait";
  } else {
    co2.textContent = String(record.co2_ppm);
    document.querySelector("#co2meta").textContent =
      `mentah ${record.co2_raw_ppm} ppm · ${record.p_hpa} hPa · ${labelQuality(record.quality.co2)}`;
    if (record.quality.co2 !== "ok") {
      status.textContent = `Belum dipakai untuk keputusan (${record.quality.co2})`;
      status.className = "status wait";
    } else {
      const high = record.co2_ppm >= 1000;
      status.textContent = high ? "Di atas 1000 ppm" : "Di bawah 1000 ppm";
      status.className = high ? "status bad" : "status good";
    }
  }
  document.querySelector("#pred").textContent = record && record.co2_pred_10min_ppm != null ? String(record.co2_pred_10min_ppm) : "–";
  document.querySelector("#model").textContent = record && record.model_used ? "Model tepi dipakai" : "Cadangan aturan ambang";
  document.querySelector("#request").textContent = record ? requestLabel(record.vent_request) : "–";
  document.querySelector("#fan").textContent = record ? (record.fan_on ? "Kipas demo menyala" : "Kipas demo mati") : "";
  document.querySelector("#intake").textContent = record
    ? (record.outdoor_intake_ok ? "Udara luar boleh dipertimbangkan" : "Udara luar lebih kotor, intake ditolak")
    : "";
  paintClimate(record);
}

function paintClimate(record) {
  const host = document.querySelector("#climate");
  const cards = [
    ["Suhu", record ? `${record.t_c} °C` : "–", record ? bandLabel(record.compliance.temperature) : ""],
    ["Kelembapan", record ? `${record.rh_pct} %` : "–", record ? bandLabel(record.compliance.humidity) : ""],
    ["PM2.5 sesaat", record ? `${record.pm25_ugm3}` : "–", record ? `bendera ${record.quality.pm}. Bukan rata-rata 24 jam.` : ""],
    ["Indeks VOC", record && record.voc_index_uncalibrated != null ? String(record.voc_index_uncalibrated) : "–", "tidak terkalibrasi"],
  ];
  host.replaceChildren(...cards.map(([label, value, note]) => {
    const article = document.createElement("article");
    article.innerHTML = `<p class="label">${label}</p><p class="figure small">${value}</p><p class="meta">${note || ""}</p>`;
    return article;
  }));
}

function paintModes(active) {
  for (const button of modeBox.querySelectorAll("button")) {
    button.classList.toggle("active", Number(button.dataset.mode) === active);
  }
}

function paintChart(history) {
  const canvas = document.querySelector("#chart");
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = "#ddd4c4";
  ctx.beginPath();
  ctx.moveTo(40, 20);
  ctx.lineTo(40, height - 24);
  ctx.lineTo(width - 12, height - 24);
  ctx.stroke();
  const line = (key, color) => {
    const points = history.map((item, index) => [index, item[key]]).filter((pair) => pair[1] != null);
    if (!points.length) return;
    ctx.strokeStyle = color;
    ctx.beginPath();
    points.forEach(([index, value], order) => {
      const x = 40 + (index / Math.max(history.length - 1, 1)) * (width - 60);
      const y = height - 24 - (Math.min(value, 1600) / 1600) * (height - 48);
      if (order === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  };
  line("co2_ppm", "#1c1915");
  line("pred", "#8a5a12");
}

function paintMetrics(state) {
  const metrics = state.metrics;
  const coeff = state.coefficients;
  const maeModel = metrics.mae_model_ppm == null ? "–" : metrics.mae_model_ppm.toFixed(1);
  const maeBase = metrics.mae_persistence_ppm == null ? "–" : metrics.mae_persistence_ppm.toFixed(1);
  const lead = metrics.lead_time_s == null ? "–" : `${metrics.lead_time_s} dtk`;
  document.querySelector("#metrics").textContent =
    `Jejak latihan: MAE model ${maeModel} ppm, MAE persistensi ${maeBase} ppm, lead time ${lead}. Koefisien a0 ${coeff.a0}, a1 ${coeff.a1}, a2 ${coeff.a2}, a3 ${coeff.a3}. Buffer ${state.buffer_depth}, broker ${state.broker_up ? "hidup" : "putus"}.`;
  document.querySelector("#broker").textContent = state.broker_up ? "Broker lokal menerima rekaman." : "Broker putus. Rekaman tinggal di buffer node.";
}

function paintEvents(events) {
  const list = document.querySelector("#events");
  list.replaceChildren(...[...events].reverse().map((event) => {
    const item = document.createElement("li");
    item.textContent = `${event.ts} · ${event.type} · ${event.source} · ${event.detail}`;
    return item;
  }));
}

function requestLabel(value) {
  if (value === "on") return "Hidup";
  if (value === "recommend_on") return "Rekomendasi hidup";
  return "Mati";
}

function bandLabel(value) {
  if (value === "di_atas") return "di atas pita";
  if (value === "di_bawah") return "di bawah pita";
  if (value === "di_dalam") return "di dalam pita";
  return "";
}

function labelQuality(flag) {
  return flag || "";
}

refresh();
setInterval(refresh, 1000);
