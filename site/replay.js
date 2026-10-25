(() => {
  const HISTORY = 15 * 60 * 1000;
  const NOTICE = "Configuration is disabled in this recorded replay.";
  const listeners = [];
  let recording = null;
  let vehicles = new Map();
  let latest = new Map();
  let telemetry = [];
  let events = [];

  function respond(body, status = 200) {
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  }

  function reset() {
    vehicles = new Map(recording.vehicles.map((vehicle) => [vehicle.vehicle_id, { ...vehicle }]));
    latest = new Map(
      recording.vehicles
        .filter((vehicle) => vehicle.telemetry)
        .map((vehicle) => [vehicle.vehicle_id, { ...vehicle.telemetry, timestamp: Date.now() }]),
    );
  }

  function emit(item) {
    const data = { ...item.data, timestamp: Date.now() };
    const cutoff = Date.now() - HISTORY;
    if (item.type === "telemetry") {
      latest.set(data.vehicle_id, data);
      telemetry.push(data);
      telemetry = telemetry.filter((row) => row.timestamp > cutoff);
      const vehicle = vehicles.get(data.vehicle_id);
      if (vehicle) vehicle.online = true;
    } else if (item.type === "events") {
      events.push(data);
      events = events.filter((row) => row.timestamp > cutoff);
    } else if (item.type === "presence" && data.status === "offline") {
      for (const vehicle of vehicles.values()) {
        if (vehicle.hostname === data.hostname) vehicle.online = false;
      }
    }
    listeners.forEach((listener) => listener({ type: item.type, data }));
  }

  function play() {
    const began = performance.now();
    const timeline = recording.timeline;
    let index = 0;
    const tick = () => {
      const elapsed = (performance.now() - began) / 1000;
      while (index < timeline.length && timeline[index].at <= elapsed) emit(timeline[index++]);
      if (index < timeline.length) setTimeout(tick, 100);
      else setTimeout(play, 1000);
    };
    tick();
  }

  const ready = fetch("recording.json")
    .then((response) => response.json())
    .then((session) => {
      recording = session;
      reset();
      play();
    });

  async function api(path) {
    await ready;
    const url = new URL(path, location.href);
    const since = Date.now() - Number(url.searchParams.get("seconds") || 60) * 1000;
    const vehicleId = url.searchParams.get("vehicle_id");
    if (url.pathname.endsWith("/api/fleet")) {
      const fleet = [...vehicles.values()].map((vehicle) => ({ ...vehicle, telemetry: latest.get(vehicle.vehicle_id) || null }));
      return respond({ vehicles: fleet, sim_speed: recording.sim_speed });
    }
    if (url.pathname.endsWith("/api/routes")) return respond(recording.routes);
    if (url.pathname.endsWith("/api/events")) {
      return respond(events.filter((e) => e.timestamp >= since && (!vehicleId || e.vehicle_id === vehicleId)).reverse());
    }
    const match = url.pathname.match(/\/api\/vehicles\/([^/]+)\/(telemetry|config)$/);
    if (match && match[2] === "telemetry") {
      return respond(telemetry.filter((row) => row.vehicle_id === match[1] && row.timestamp >= since).reverse());
    }
    if (match) return respond({ detail: NOTICE }, 409);
    return respond({ detail: "not found" }, 404);
  }

  window.roadlogReplay = { api, subscribe: (listener) => listeners.push(listener) };
})();
