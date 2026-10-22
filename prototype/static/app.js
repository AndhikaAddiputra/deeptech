import { createClassroom } from "./scene.js";

const modes = [
  [3, "Jalankan sendiri"],
  [1, "Rekomendasi"],
];
const modeHints = {
  1: "Sistem hanya menyarankan arah udara. Kipas tidak bergerak.",
  3: "Sistem menyalakan kipas sendiri: udara luar masuk, atau udara dalam dibuang.",
};
const airModes = [
  [null, "Ikuti rekomendasi"],
  ["air_in", "Masukkan udara luar"],
  ["air_out", "Buang udara dalam"],
  ["air_stay", "Biarkan diam"],
];
const presetsByEnvironment = {};
const scenarios = [
  ["breath", "Tambah CO₂"],
  ["sensor_dead", "Putuskan sensor"],
  ["sensor_ok", "Pulihkan sensor"],
  ["broker_down", "Putuskan koneksi"],
  ["broker_up", "Pulihkan koneksi"],
  ["outdoor_dirty", "Udara luar kotor"],
  ["outdoor_clean", "Udara luar bersih"],
  ["humid", "Ruangan lembab"],
  ["dry", "Kelembapan normal"],
];

const modeBox = document.querySelector("#modes");
const airBox = document.querySelector("#air-modes");
const presetBox = document.querySelector("#presets");
const scenarioBox = document.querySelector("#scenarios");
const twinForm = document.querySelector("#twin-form");
const popup = document.querySelector("#popup");
const canvas = document.querySelector("#view");

let latest = null;
let roomTitle = "Kelas standar";
let selected = null;

const view = createClassroom(canvas, (id) => {
  selected = id;
  paintPopup();
  paintCards();
});

document.querySelector("#zoom-in").addEventListener("click", () => view.zoom(1));
document.querySelector("#zoom-out").addEventListener("click", () => view.zoom(-1));
document.querySelector("#popup-close").addEventListener("click", () => {
  selected = null;
  paintPopup();
  paintCards();
});

for (const [mode, label] of modes) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.dataset.mode = String(mode);
  button.addEventListener("click", () => post("/api/command", { cmd: "set_mode", mode, source: "dashboard" }));
  modeBox.append(button);
}

for (const [override, label] of airModes) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.dataset.air = override || "auto";
  button.addEventListener("click", () => post("/api/twin", { override }));
  airBox.append(button);
}

const loader = document.querySelector("#loader");
const loaderText = document.querySelector("#loader-text");
const envNames = {
  kelas: "ruang kelas",
  pabrik: "lantai pabrik",
  rig: "kabin MLQ",
};

for (const button of document.querySelectorAll("[data-env]")) {
  button.addEventListener("click", () => switchEnvironment(button.dataset.env));
}

async function switchEnvironment(name) {
  if (name === latest?.environment?.id) return;
  loaderText.textContent = `Menyiapkan ${envNames[name] || "ruang"}`;
  loader.hidden = false;
  const started = performance.now();
  try {
    const environment = await post("/api/environment", { name });
    roomTitle = environment.title;
    renderPresets(environment.presets || []);
  } finally {
    const remain = 720 - (performance.now() - started);
    if (remain > 0) await new Promise((resolve) => setTimeout(resolve, remain));
    loader.hidden = true;
  }
}

for (const [name, label] of scenarios) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", () => post("/api/scenario", { name }));
  scenarioBox.append(button);
}

for (const button of document.querySelectorAll("[data-cmd]")) {
  button.addEventListener("click", () => post("/api/command", { cmd: button.dataset.cmd, source: "dashboard" }));
}

twinForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const spec = Object.fromEntries(new FormData(twinForm).entries());
  for (const key of Object.keys(spec)) spec[key] = Number(spec[key]);
  fillTwin(await post("/api/twin", { spec }));
});

async function post(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  await refresh();
  return payload;
}

async function refresh() {
  latest = await (await fetch("/api/state")).json();
  const record = latest.record;
  if (latest.environment) {
    roomTitle = latest.environment.title;
    renderPresets(latest.environment.presets || []);
    document.querySelector("#env-note").textContent = latest.environment.note || "";
    for (const button of document.querySelectorAll("[data-env]")) {
      button.classList.toggle("active", button.dataset.env === latest.environment.id);
    }
  }
  document.querySelector("#room-title").textContent = roomTitle;
  const preset = (latest.environment?.presets || []).find((item) => item.id === latest.environment?.preset_id);
  document.querySelector("#room-variant").textContent = preset ? preset.label : "Ukuran khusus";
  document.querySelector("#clock").textContent = record
    ? `${record.ts} · 1 detik dinding = 30 detik sensor`
    : "Menunggu sampel";
  paintDecision(record);
  paintProof(latest.proof);
  paintTwin(latest.twin);
  paintSpark(latest.history || []);
  paintEvents(latest.events || []);
  paintCards();
  paintPopup();
  view.update(latest);
}

function paintDecision(record) {
  document.querySelector("#request").textContent = record ? requestLabel(record.vent_request) : "–";
  document.querySelector("#fan").textContent = record ? airLabel(record.air_mode) : "";
  document.querySelector("#model").textContent = record?.model_used ? "Model tepi dipakai" : "Cadangan aturan ambang";
  const co2 = record?.co2_ppm;
  document.querySelector("#co2-read").textContent = co2 == null
    ? "CO₂ belum valid"
    : `${co2} ppm terkoreksi · mentah ${record.co2_raw_ppm} · ${record.quality.co2}`;
  const limit = record?.co2_on_ppm || latest?.environment?.co2_on_ppm || 1000;
  document.querySelector("#co2-bar").style.width = `${Math.min(100, ((co2 || 0) / (limit * 1.6)) * 100)}%`;
  document.querySelector("#pred").textContent = record?.co2_pred_10min_ppm == null ? "–" : `${record.co2_pred_10min_ppm} ppm`;
  const spec = latest?.twin?.spec;
  document.querySelector("#outdoor").textContent = spec
    ? `${spec.outdoor_co2_ppm} ppm · PM2.5 ${spec.outdoor_pm25} · ${spec.outdoor_t_c} °C · RH ${spec.outdoor_rh}%`
    : "";
  document.querySelector("#intake").textContent = record
    ? (record.outdoor_intake_ok ? "Udara luar layak dimasukkan." : "Udara luar lebih kotor, jadi sistem tidak memasukkan udara luar.")
    : "";
  document.querySelector("#broker").textContent = latest?.broker_up
    ? "Data tersimpan."
    : `Koneksi putus. ${latest?.buffer_depth ?? 0} rekaman menunggu dikirim.`;
  const activeMode = record?.mode ?? 1;
  const auto = activeMode === 3;
  document.querySelector("#mode-hint").textContent = modeHints[auto ? 3 : 1];
  for (const button of modeBox.querySelectorAll("button")) {
    button.classList.toggle("active", Number(button.dataset.mode) === (auto ? 3 : 1));
  }
  const metrics = latest?.metrics;
  if (metrics) {
    document.querySelector("#metrics").textContent =
      `MAE model ${num(metrics.mae_model_ppm)} ppm · persistensi ${num(metrics.mae_persistence_ppm)} ppm · lead ${metrics.lead_time_s ?? "–"} dtk`;
  }
}

function renderPresets(presets) {
  const current = presets.map((item) => item.id).join();
  if (presetBox.dataset.key !== current) {
    presetBox.dataset.key = current;
    presetBox.replaceChildren(...presets.map((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = item.label;
      button.dataset.preset = item.id;
      button.addEventListener("click", () => post("/api/twin", { preset: item.id }));
      return button;
    }));
  }
  const active = latest?.environment?.preset_id || "";
  for (const button of presetBox.querySelectorAll("button")) {
    button.classList.toggle("active", button.dataset.preset === active);
  }
}

function paintTwin(twin) {
  if (!twin) return;
  for (const button of airBox.querySelectorAll("button")) {
    button.classList.toggle("active", button.dataset.air === (twin.override || "auto"));
  }
  if (document.activeElement && twinForm.contains(document.activeElement)) return;
  for (const input of twinForm.querySelectorAll("input")) {
    if (twin.spec[input.name] != null) input.value = twin.spec[input.name];
  }
}

function paintProof(proof) {
  const banner = document.querySelector("#proof");
  if (!proof) {
    banner.textContent = "";
    return;
  }
  banner.textContent = `${proof.lead} ${proof.compare} ${proof.reason}`;
}

function fillTwin(twin) {
  paintTwin(twin);
}

function paintCards() {
  const record = latest?.record;
  const spec = latest?.twin?.spec;
  const cards = [
    ["sensor", "Node Sensor Indoor", record ? `${record.co2_ppm ?? "–"} ppm · ${record.quality?.co2 ?? ""}` : "Menunggu", "Sensing"],
    ["outdoor", "Node Sensor Outdoor", spec ? `${spec.outdoor_co2_ppm} ppm · PM ${spec.outdoor_pm25}` : "Menunggu", "Sensing"],
    ["fan", "Reverseable Fan", record?.fan_actuator ? airLabel(record.air_mode) : "Diam", "Aktuator"],
  ];
  const host = document.querySelector("#cards");
  host.replaceChildren(...cards.map(([id, title, detail, kind]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `card${selected === id ? " active" : ""}`;
    const kicker = document.createElement("span");
    kicker.className = "kicker";
    kicker.textContent = kind;
    const name = document.createElement("strong");
    name.textContent = title;
    const line = document.createElement("p");
    line.className = "sub";
    line.textContent = detail;
    button.append(kicker, name, line);
    button.addEventListener("click", () => view.select(id));
    return button;
  }));
}

function paintPopup() {
  if (!selected || !latest?.record) {
    popup.hidden = true;
    return;
  }
  const record = latest.record;
  const twin = latest.twin;
  const spec = twin?.spec;
  popup.hidden = false;
  const rect = canvas.getBoundingClientRect();
  popup.style.left = `${Math.min(rect.width * 0.42, rect.width - 300)}px`;
  popup.style.top = "18%";
  const titles = {
    sensor: "Node Sensor Indoor",
    outdoor: "Node Sensor Outdoor",
    fan: "Reverseable Fan",
  };
  const rows = selected === "sensor"
    ? [
      ["CO₂ terkoreksi", record.co2_ppm == null ? "–" : `${record.co2_ppm} ppm`],
      ["CO₂ mentah", record.co2_raw_ppm == null ? "–" : `${record.co2_raw_ppm} ppm`],
      ["Suhu", `${record.t_c} °C`],
      ["RH", `${record.rh_pct}%`],
      ["PM2.5", record.pm25_ugm3],
      ["Bendera", record.quality.co2],
    ]
    : selected === "outdoor"
      ? [
        ["CO₂ luar", spec ? `${spec.outdoor_co2_ppm} ppm` : "–"],
        ["PM2.5 luar", spec?.outdoor_pm25 ?? "–"],
        ["Suhu luar", spec ? `${spec.outdoor_t_c} °C` : "–"],
        ["RH luar", spec ? `${spec.outdoor_rh}%` : "–"],
        ["Tekanan", spec ? `${spec.pressure_hpa} hPa` : "–"],
        ["Kelayakan", record.outdoor_intake_ok ? "Layak masuk" : "Lebih kotor"],
      ]
      : [
        ["Keadaan", record.fan_actuator ? "Berputar" : "Diam"],
        ["Arah", airLabel(record.air_mode)],
        ["Alasan", record.reason],
      ];
  document.querySelector("#popup-kicker").textContent = selected === "fan" ? "Aktuator" : "Sensing";
  document.querySelector("#popup-title").textContent = titles[selected] || "Perangkat";
  const body = document.querySelector("#popup-body");
  body.replaceChildren();
  for (const [label, value] of rows) {
    const term = document.createElement("dt");
    term.textContent = label;
    const data = document.createElement("dd");
    data.textContent = value ?? "–";
    body.append(term, data);
  }
}

function paintSpark(history) {
  const spark = document.querySelector("#spark");
  const ctx = spark.getContext("2d");
  ctx.clearRect(0, 0, spark.width, spark.height);
  const line = (key, color) => {
    const points = history.map((item, index) => [index, item[key]]).filter((pair) => pair[1] != null);
    if (!points.length) return;
    ctx.strokeStyle = color;
    ctx.beginPath();
    points.forEach(([index, value], order) => {
      const x = (index / Math.max(history.length - 1, 1)) * spark.width;
      const y = spark.height - 4 - (Math.min(value, 1600) / 1600) * (spark.height - 8);
      if (order === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  };
  line("co2_ppm", "#1d1c1a");
  line("pred", "#d97848");
}

function paintEvents(events) {
  const list = document.querySelector("#events");
  list.replaceChildren(...[...events].slice(-4).reverse().map((event) => {
    const item = document.createElement("li");
    item.textContent = `${event.type} · ${event.detail}`;
    return item;
  }));
}

function requestLabel(value) {
  if (value === "on") return "Ventilasi berjalan";
  if (value === "recommend_on") return "Disarankan menyala";
  return "Ventilasi diam";
}

function airLabel(mode) {
  if (mode === "air_in") return "Udara luar masuk";
  if (mode === "air_out") return "Udara dalam dibuang";
  if (mode === "air_stay") return "Udara dibiarkan diam";
  return "–";
}

function num(value) {
  return value == null ? "–" : Number(value).toFixed(1);
}

refresh();
setInterval(refresh, 1000);
