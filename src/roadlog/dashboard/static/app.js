const COLORS = {
  driving: "#4fb3ff",
  break: "#ffc857",
  "crew-change": "#56d4a8",
  loading: "#8a94a8",
  offline: "#4a5266",
};
const INK = { driving: "#0b0f17", break: "#0b0f17", "crew-change": "#0b0f17", loading: "#0b0f17", offline: "#0b0f17" };
const LABELS = { driving: "Driving", break: "Break", "crew-change": "Crew change", loading: "Loading", offline: "Offline" };
const CONTINUOUS_LIMIT = 4.5 * 3600;
const DAILY_LIMIT = 9 * 3600;
const TRAIL = 40;
const arrow = (ink) => `<svg viewBox="0 0 24 24"><path d="M12 2 L20 21 L12 16 L4 21 Z" fill="${ink}"/></svg>`;

const source = window.roadlogReplay || null;
const api = (path, options) => (source ? source.api(path, options) : fetch(path, options));

const state = { vehicles: new Map(), markers: new Map(), trails: new Map(), selected: null, tab: "telemetry", series: [] };

const map = L.map("map", { zoomControl: false, attributionControl: true }).setView([40.2, -3.6], 6);
L.control.zoom({ position: "bottomright" }).addTo(map);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 18,
  className: "dark-tiles",
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
}).addTo(map);

const $ = (id) => document.getElementById(id);

function clock(seconds) {
  const minutes = Math.floor((seconds || 0) / 60);
  return `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, "0")}`;
}

function since(timestamp) {
  const seconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  return `${Math.floor(seconds / 60)}m ago`;
}

function time(timestamp) {
  return new Date(timestamp).toLocaleTimeString([], { hour12: false });
}

function activityOf(vehicle) {
  if (!vehicle.online) return "offline";
  return vehicle.telemetry ? vehicle.telemetry.activity : "loading";
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function bar(label, value, limit) {
  const ratio = Math.min(1, (value || 0) / limit);
  const level = value > limit ? "over" : ratio > 0.9 ? "near" : "";
  return `<div class="bar"><span>${label}</span><div class="track"><div class="fill ${level}" style="width:${ratio * 100}%"></div></div><span class="value">${clock(value)} / ${clock(limit)}</span></div>`;
}

function renderSummary() {
  if (!state.selected) return;
  const vehicle = state.vehicles.get(state.selected);
  const activity = activityOf(vehicle);
  const t = vehicle.telemetry || {};
  const speed = vehicle.online && t.gnss_speed !== undefined ? `${Math.round(t.gnss_speed)} km/h` : "—";
  const route = (t.route || vehicle.route).replace(" - ", " → ");
  $("panel-summary").innerHTML = `<div class="summary-top"><span class="badge ${activity}">${LABELS[activity]}</span><span class="route">${escapeHtml(route)}</span><span class="speed">${speed}</span></div>
    ${bar("Continuous", t.continuous_driving, CONTINUOUS_LIMIT)}
    ${bar("Today", t.daily_driving, DAILY_LIMIT)}`;
}

function icon(vehicle) {
  const activity = activityOf(vehicle);
  const heading = vehicle.telemetry ? vehicle.telemetry.heading : 0;
  const alert = vehicle.alertUntil && vehicle.alertUntil > Date.now() ? "alert" : "";
  return L.divIcon({
    className: "",
    iconSize: [60, 50],
    iconAnchor: [30, 17],
    html: `<div class="truck ${alert}"><div class="dot" style="background:${COLORS[activity]};color:${COLORS[activity]}"><div style="transform:rotate(${heading}deg);display:grid">${arrow(INK[activity])}</div></div><div class="label">${vehicle.vehicle_id}</div></div>`,
  });
}

function animate(marker, target, duration) {
  const start = marker.getLatLng();
  if (Math.abs(start.lat - target[0]) + Math.abs(start.lng - target[1]) > 0.5) {
    marker.setLatLng(target);
    return;
  }
  const began = performance.now();
  cancelAnimationFrame(marker.frame);
  const step = (now) => {
    const progress = Math.min(1, (now - began) / duration);
    marker.setLatLng([start.lat + (target[0] - start.lat) * progress, start.lng + (target[1] - start.lng) * progress]);
    if (progress < 1) marker.frame = requestAnimationFrame(step);
  };
  marker.frame = requestAnimationFrame(step);
}

function placeMarker(vehicle) {
  const t = vehicle.telemetry;
  if (!t) return;
  const target = [t.latitude, t.longitude];
  let marker = state.markers.get(vehicle.vehicle_id);
  if (!marker) {
    marker = L.marker(target, { icon: icon(vehicle) }).addTo(map);
    marker.on("click", () => select(vehicle.vehicle_id));
    state.markers.set(vehicle.vehicle_id, marker);
  } else {
    marker.setIcon(icon(vehicle));
    animate(marker, target, (t.telemetry_interval || 2) * 1000);
  }
  marker.setOpacity(vehicle.online ? 1 : 0.4);
  const trail = state.trails.get(vehicle.vehicle_id) || [];
  const last = trail[trail.length - 1];
  if (last && Math.abs(last[0] - target[0]) + Math.abs(last[1] - target[1]) > 0.5) trail.length = 0;
  trail.push(target);
  if (trail.length > TRAIL) trail.shift();
  state.trails.set(vehicle.vehicle_id, trail);
  if (!vehicle.trailLine) {
    vehicle.trailLine = L.polyline(trail, { color: COLORS.driving, weight: 3, opacity: 0.5 }).addTo(map);
  } else {
    vehicle.trailLine.setLatLngs(trail);
  }
}

function eventHtml(event) {
  return `<div class="event"><div class="stripe ${event.severity}"></div><div><div class="title">${escapeHtml(event.message)}</div><div class="when">${event.kind} · ${since(event.timestamp)}</div></div></div>`;
}

function onTelemetry(data) {
  const vehicle = state.vehicles.get(data.vehicle_id);
  if (!vehicle) return;
  vehicle.online = true;
  vehicle.telemetry = data;
  placeMarker(vehicle);
  if (state.selected === data.vehicle_id) renderSummary();
  if (state.selected === data.vehicle_id && state.tab === "telemetry") {
    state.series.push(data);
    state.series = state.series.filter((row) => row.timestamp > Date.now() - 60000);
    renderTelemetry();
  }
}

function onEvent(data) {
  const vehicle = state.vehicles.get(data.vehicle_id);
  if (vehicle) {
    vehicle.alertUntil = Date.now() + 5000;
    placeMarker(vehicle);
  }
  if (state.selected === data.vehicle_id && state.tab === "events") loadEvents();
}

function onPresence(data) {
  if (data.status !== "offline") return;
  for (const vehicle of state.vehicles.values()) {
    if (vehicle.hostname === data.hostname) {
      vehicle.online = false;
      placeMarker(vehicle);
    }
  }
}

async function refreshFleet() {
  const response = await api("/api/fleet");
  const body = await response.json();
  for (const vehicle of body.vehicles) {
    const known = state.vehicles.get(vehicle.vehicle_id);
    state.vehicles.set(vehicle.vehicle_id, { ...known, ...vehicle, telemetry: known && known.telemetry ? known.telemetry : vehicle.telemetry });
    placeMarker(state.vehicles.get(vehicle.vehicle_id));
  }
  renderSummary();
}

async function loadRoutes() {
  const routes = await (await api("/api/routes")).json();
  routes.forEach((route) => L.polyline(route.points, { color: "#5b6b8f", weight: 2, opacity: 0.35, dashArray: "4 6" }).addTo(map));
}

function drawChart(rows) {
  const canvas = $("speed-chart");
  const context = canvas.getContext("2d");
  const ratio = window.devicePixelRatio || 1;
  canvas.width = canvas.clientWidth * ratio;
  canvas.height = 120 * ratio;
  context.scale(ratio, ratio);
  const width = canvas.clientWidth;
  const height = 120;
  context.clearRect(0, 0, width, height);
  const end = Date.now();
  const start = end - 60000;
  const top = Math.max(100, ...rows.map((r) => Math.max(r.gnss_speed, r.odometer_speed))) * 1.1;
  const x = (t) => ((t - start) / 60000) * width;
  const y = (v) => height - 8 - (v / top) * (height - 16);
  context.strokeStyle = "rgba(255,93,108,0.6)";
  context.setLineDash([4, 4]);
  context.beginPath();
  context.moveTo(0, y(90));
  context.lineTo(width, y(90));
  context.stroke();
  context.setLineDash([]);
  [["gnss_speed", COLORS.driving], ["odometer_speed", COLORS.break]].forEach(([key, color]) => {
    context.strokeStyle = color;
    context.lineWidth = 2;
    context.beginPath();
    rows.forEach((row, index) => (index ? context.lineTo(x(row.timestamp), y(row[key])) : context.moveTo(x(row.timestamp), y(row[key]))));
    context.stroke();
  });
}

function renderTelemetry() {
  const rows = [...state.series].sort((a, b) => a.timestamp - b.timestamp);
  drawChart(rows);
  $("telemetry-rows").innerHTML = rows
    .slice(-20)
    .reverse()
    .map((r) => `<tr><td>${time(r.timestamp)}</td><td>${r.gnss_speed.toFixed(1)}</td><td>${r.odometer_speed.toFixed(1)}</td><td>${r.driver_card || "none"}</td><td>${LABELS[r.activity] || r.activity}</td></tr>`)
    .join("");
}

async function loadTelemetry() {
  state.series = await (await api(`/api/vehicles/${state.selected}/telemetry?seconds=60`)).json();
  renderTelemetry();
}

async function loadEvents() {
  const events = await (await api(`/api/events?seconds=300&vehicle_id=${state.selected}`)).json();
  $("vehicle-events").innerHTML = events.length ? events.map(eventHtml).join("") : '<div class="empty">No events in the last five minutes</div>';
}

function loadConfig() {
  const vehicle = state.vehicles.get(state.selected);
  const form = $("config-form");
  form.telemetry_interval.value = vehicle.telemetry_interval;
  form.sampling_interval.value = vehicle.sampling_interval;
  $("config-result").textContent = "";
}

function showTab(tab) {
  state.tab = tab;
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  ["telemetry", "events", "config"].forEach((name) => ($(`tab-${name}`).hidden = name !== tab));
  ({ telemetry: loadTelemetry, events: loadEvents, config: loadConfig })[tab]();
}

function select(vehicleId) {
  state.selected = vehicleId;
  const vehicle = state.vehicles.get(vehicleId);
  $("panel").hidden = false;
  $("panel-title").textContent = `${vehicle.vehicle_id} · ${vehicle.plate}`;
  $("panel-subtitle").textContent = `${vehicle.driver_name} · ${vehicle.driver_card}`;
  if (vehicle.telemetry) map.panTo([vehicle.telemetry.latitude, vehicle.telemetry.longitude]);
  renderSummary();
  showTab(state.tab);
}

function closePanel() {
  state.selected = null;
  $("panel").hidden = true;
}

$("panel-close").addEventListener("click", closePanel);
map.on("click", closePanel);
document.querySelectorAll(".tabs button").forEach((button) => button.addEventListener("click", () => showTab(button.dataset.tab)));
$("config-form").addEventListener("submit", async (submission) => {
  submission.preventDefault();
  const form = submission.target;
  const body = { telemetry_interval: Number(form.telemetry_interval.value), sampling_interval: Number(form.sampling_interval.value) };
  const response = await api(`/api/vehicles/${state.selected}/config`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const result = $("config-result");
  if (response.ok) {
    Object.assign(state.vehicles.get(state.selected), body);
    result.className = "ok";
    result.textContent = `Sent to ${state.selected}: telemetry every ${body.telemetry_interval}s, sensors every ${body.sampling_interval}s`;
  } else {
    const error = await response.json();
    result.className = "error";
    result.textContent = typeof error.detail === "string" ? error.detail : "The configuration was rejected";
  }
});

function handle({ type, data }) {
  if (type === "telemetry") onTelemetry(data);
  else if (type === "events") onEvent(data);
  else if (type === "presence") onPresence(data);
}

function connect() {
  if (source) {
    source.subscribe(handle);
    return;
  }
  const socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  socket.onmessage = (message) => handle(JSON.parse(message.data));
  socket.onclose = () => setTimeout(connect, 2000);
}

loadRoutes();
refreshFleet();
connect();
setInterval(refreshFleet, 15000);
