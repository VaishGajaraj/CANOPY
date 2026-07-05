"use strict";

const EMITTER_COLOR = {
  tac_vhf: "#4fd1c5", tac_uhf: "#6fb1ff", cellular: "#ffb454",
  gps_anomaly: "#ff5d5d", bt_region: "#b1ff6f", wideband: "#9aa7b5",
  sar_disturbance: "#b388ff",
};
const EMITTER_LABEL = {
  tac_vhf: "VHF tactical", tac_uhf: "UHF tactical", cellular: "Cellular uplink",
  gps_anomaly: "GPS L1 anomaly (jamming)", bt_region: "2.4 GHz ISM",
  wideband: "Wideband / unknown", sar_disturbance: "SAR disturbance",
};

const state = { sources: [], detections: [], fixes: [], report: null, proj: null, hot: null };

async function getJSON(url) { const r = await fetch(url); return r.json(); }

async function loadAll() {
  const [sources, detections, fixes, report] = await Promise.all([
    getJSON("/api/sources"), getJSON("/api/detections"),
    getJSON("/api/fixes"), getJSON("/api/report"),
  ]);
  state.sources = sources; state.detections = detections;
  state.fixes = fixes; state.report = report;
  renderMeta(); buildProjection(); draw(); renderReport();
}

// --- projection ------------------------------------------------------------
function buildProjection() {
  const canvas = document.getElementById("plot");
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth, H = canvas.clientHeight;
  canvas.width = W * dpr; canvas.height = H * dpr;
  const ctx = canvas.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const pts = [];
  state.sources.forEach(s => { if (s.lat != null) pts.push([s.lon, s.lat]); });
  state.fixes.forEach(f => pts.push([f.lon, f.lat]));
  state.detections.forEach(d => {
    const g = d.geom;
    if (g && g.type === "Polygon") g.coordinates[0].forEach(c => pts.push(c));
  });
  if (!pts.length) { state.proj = null; return; }

  const lat0 = pts.reduce((a, p) => a + p[1], 0) / pts.length;
  const lon0 = pts.reduce((a, p) => a + p[0], 0) / pts.length;
  const mPerLat = 111320, mPerLon = 111320 * Math.cos(lat0 * Math.PI / 180);
  const toM = ([lon, lat]) => [(lon - lon0) * mPerLon, (lat - lat0) * mPerLat];
  const ms = pts.map(toM);
  let minX = Math.min(...ms.map(m => m[0])), maxX = Math.max(...ms.map(m => m[0]));
  let minY = Math.min(...ms.map(m => m[1])), maxY = Math.max(...ms.map(m => m[1]));
  // pad the frame by 18%
  const padX = (maxX - minX) * 0.18 + 60, padY = (maxY - minY) * 0.18 + 60;
  minX -= padX; maxX += padX; minY -= padY; maxY += padY;
  const pad = 20;
  const scale = Math.min((W - 2 * pad) / (maxX - minX), (H - 2 * pad) / (maxY - minY));
  const offX = pad + (W - 2 * pad - (maxX - minX) * scale) / 2;
  const offY = pad + (H - 2 * pad - (maxY - minY) * scale) / 2;

  state.proj = {
    ctx, W, H, scale,
    toPx(lon, lat) {
      const [mx, my] = toM([lon, lat]);
      return [offX + (mx - minX) * scale, H - offY - (my - minY) * scale];
    },
  };
}

// --- draw ------------------------------------------------------------------
function draw() {
  const p = state.proj; if (!p) return;
  const { ctx, W, H, scale } = p;
  ctx.clearRect(0, 0, W, H);
  drawGrid(p);

  // DF web: every bearing, very faint — converges on the emitters
  ctx.lineWidth = 1;
  state.detections.forEach(d => {
    const g = d.geom;
    if (!g || g.type !== "LineString") return;
    const a = p.toPx(g.coordinates[0][0], g.coordinates[0][1]);
    const b = p.toPx(g.coordinates[1][0], g.coordinates[1][1]);
    ctx.strokeStyle = hexA(EMITTER_COLOR[d.emitter_type] || "#9aa7b5", 0.05);
    ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
  });

  // SAR coherence patches
  state.detections.filter(d => d.source_int === "sar").forEach(d => {
    const ring = d.geom.coordinates[0].map(c => p.toPx(c[0], c[1]));
    ctx.beginPath(); ring.forEach((pt, i) => i ? ctx.lineTo(pt[0], pt[1]) : ctx.moveTo(pt[0], pt[1]));
    ctx.closePath();
    ctx.fillStyle = hexA(EMITTER_COLOR.sar_disturbance, 0.16);
    ctx.strokeStyle = EMITTER_COLOR.sar_disturbance; ctx.lineWidth = 1.4;
    ctx.fill(); ctx.stroke();
  });

  // all raw fixes as a faint density cloud
  state.fixes.forEach(f => {
    const [x, y] = p.toPx(f.lon, f.lat);
    ctx.fillStyle = "rgba(255,255,255,0.10)";
    ctx.beginPath(); ctx.arc(x, y, 2, 0, 7); ctx.fill();
  });

  // per-emitter BEST fix with a bold, honest error ellipse
  state.hot = [];
  (state.report ? state.report.worst_offenders : []).forEach(o => {
    if (!o.best_fix) return;
    const f = o.best_fix, col = EMITTER_COLOR[o.emitter_type] || "#9aa7b5";
    const [x, y] = p.toPx(f.lon, f.lat);
    drawEllipse(ctx, x, y, f.err_semimajor_m * scale, f.err_semiminor_m * scale,
      f.err_orient_deg, col);
    ctx.fillStyle = col; ctx.beginPath(); ctx.arc(x, y, 4, 0, 7); ctx.fill();
    ctx.strokeStyle = "#0b0f14"; ctx.lineWidth = 1.5; ctx.stroke();
    // label
    ctx.fillStyle = col; ctx.font = "11px monospace";
    ctx.fillText(`${EMITTER_LABEL[o.emitter_type] || o.emitter_type}`, x + 9, y - 4);
    ctx.fillStyle = "#9aa7b5";
    ctx.fillText(`CEP ${Math.round(f.cep50_m)} m · ${Math.round(f.err_semimajor_m)}×${Math.round(f.err_semiminor_m)} m`, x + 9, y + 9);
    state.hot.push({ x, y, r: 12, kind: "fix", o });
  });

  // nodes
  state.sources.filter(s => s.lat != null).forEach(s => {
    const [x, y] = p.toPx(s.lon, s.lat);
    ctx.fillStyle = "#e7eef6";
    ctx.beginPath(); ctx.moveTo(x, y - 7); ctx.lineTo(x + 6, y + 5); ctx.lineTo(x - 6, y + 5);
    ctx.closePath(); ctx.fill();
    ctx.fillStyle = "#8aa0b6"; ctx.font = "10px monospace";
    ctx.fillText(s.label, x + 8, y + 4);
    state.hot.push({ x, y, r: 12, kind: "node", s });
  });

  drawScaleBar(p);
  buildLegend();
}

function drawGrid(p) {
  const { ctx, W, H } = p;
  ctx.strokeStyle = "#16202c"; ctx.lineWidth = 1;
  const step = 60;
  for (let x = 0; x < W; x += step) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
  for (let y = 0; y < H; y += step) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
}

function drawScaleBar(p) {
  const { ctx, H, scale } = p;
  const meters = niceMeters(150 / scale); // ~150px target
  const px = meters * scale;
  const x0 = 16, y0 = H - 22;
  ctx.strokeStyle = "#9aa7b5"; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x0 + px, y0);
  ctx.moveTo(x0, y0 - 4); ctx.lineTo(x0, y0 + 4);
  ctx.moveTo(x0 + px, y0 - 4); ctx.lineTo(x0 + px, y0 + 4); ctx.stroke();
  ctx.fillStyle = "#9aa7b5"; ctx.font = "10px monospace";
  ctx.fillText(meters >= 1000 ? `${meters / 1000} km` : `${meters} m`, x0 + px + 6, y0 + 3);
}
function niceMeters(m) {
  const pows = [50, 100, 200, 250, 500, 1000, 2000, 5000];
  return pows.reduce((a, b) => Math.abs(b - m) < Math.abs(a - m) ? b : a);
}

function drawEllipse(ctx, x, y, a, b, orientDeg, color) {
  // orientDeg is the azimuth (clockwise from north) of the semi-major axis.
  const th = orientDeg * Math.PI / 180;
  const rot = Math.atan2(-Math.cos(th), Math.sin(th)); // north-up screen mapping
  ctx.save();
  ctx.beginPath();
  ctx.ellipse(x, y, Math.max(a, 2), Math.max(b, 2), rot, 0, Math.PI * 2);
  ctx.fillStyle = hexA(color, 0.12); ctx.fill();
  ctx.strokeStyle = hexA(color, 0.9); ctx.lineWidth = 1.5; ctx.setLineDash([4, 3]);
  ctx.stroke();
  ctx.restore();
}

function hexA(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

function buildLegend() {
  const seen = new Set(state.detections.map(d => d.emitter_type));
  const el = document.getElementById("legend");
  el.innerHTML = "";
  [...seen].forEach(t => {
    const row = document.createElement("div"); row.className = "legend-row";
    row.innerHTML = `<span class="swatch" style="background:${EMITTER_COLOR[t] || "#9aa7b5"}"></span>${EMITTER_LABEL[t] || t}`;
    el.appendChild(row);
  });
  const node = document.createElement("div"); node.className = "legend-row";
  node.innerHTML = `<span style="color:#e7eef6">▲</span> passive node`;
  el.appendChild(node);
}

// --- report ----------------------------------------------------------------
function renderMeta() {
  const r = state.report; if (!r) return;
  document.getElementById("exercise-meta").innerHTML =
    `<b>${r.exercise}</b>${r.unit ? " · " + r.unit : ""} · window ${fmtDur(r.window)}`;
}
function fmtDur(w) { return w ? `${Math.round(w.duration_s / 60)} min` : ""; }

function renderReport() {
  const r = state.report; if (!r) return;
  const score = r.targetability_score || 0;
  document.getElementById("score-value").textContent = score.toFixed(0);
  const arc = document.getElementById("gauge-arc");
  const C = 327; arc.style.strokeDashoffset = C - C * (score / 100);
  arc.style.stroke = score >= 70 ? "#ff5d5d" : score >= 40 ? "#ffb454" : "#4fd1c5";
  document.getElementById("worst-line").innerHTML = r.worst
    ? `worst: <b style="color:#ff8f8f">${r.worst.label}</b> (${r.worst.score.toFixed(0)})` : "—";

  const mi = document.getElementById("multi-int"); mi.innerHTML = "";
  (r.multi_int ? r.multi_int.source_ints : []).forEach(si => {
    const b = document.createElement("span"); b.className = "badge " + si;
    b.textContent = si.toUpperCase(); mi.appendChild(b);
  });

  const off = document.getElementById("offenders"); off.innerHTML = "";
  r.worst_offenders.forEach(o => off.appendChild(offenderCard(o)));

  renderTimeline(r);
  document.getElementById("peak-window").textContent = r.peak_window
    ? `peak-detectability window: ${hhmm(r.peak_window.start)} – ${hhmm(r.peak_window.end)}` : "";

  const m = r.methodology || {};
  document.getElementById("methodology").innerHTML =
    `<span class="formula">${m.formula || ""}</span>` +
    `weights: persistence ${m.weights?.persistence}, range ${m.weights?.range}, phase ${m.weights?.phase}<br>` +
    `range band: ${m.range_band_m?.R_MIN}–${m.range_band_m?.R_MAX} m · exercise = ${m.exercise_blend}<br>` +
    `<span class="muted">${m.caveat || ""}</span>`;

  const c = r.counts || {};
  document.getElementById("counts").innerHTML =
    `<div><span>detections</span><b>${c.detections} (RF ${c.rf_detections} / SAR ${c.sar_detections})</b></div>` +
    `<div><span>fused fixes</span><b>${c.fixes}</b></div>` +
    `<div><span>signatures in library</span><b>${c.signatures}</b></div>`;
}

function offenderCard(o) {
  const col = EMITTER_COLOR[o.emitter_type] || "#9aa7b5";
  const el = document.createElement("div"); el.className = "offender";
  const ell = o.best_fix
    ? `<span class="ellipse-tag">fix ${Math.round(o.best_fix.err_semimajor_m)}×${Math.round(o.best_fix.err_semiminor_m)} m · CEP ${Math.round(o.best_fix.cep50_m)} m · GDOP ${o.best_fix.gdop}</span>`
    : `<span class="muted">no multi-node fix</span>`;
  el.innerHTML =
    `<div class="row1"><span class="name" style="color:${col}">${o.label}</span>` +
    `<span class="score" style="color:${col}">${o.score.toFixed(0)}</span></div>` +
    `<div class="bars">${bar("persist", o.persistence, "#4fd1c5")}${bar("range", o.range_term, "#6fb1ff")}${bar("phase", o.phase, "#ff5d5d")}</div>` +
    `<div class="meta">${o.n_detections} det · duty ${(o.duty * 100).toFixed(0)}% · det.range ${fmtRange(o.detection_range_m)} · ${ell}</div>`;
  return el;
}
function bar(label, v, color) {
  return `<div class="bar-wrap"><div class="bar-label"><span>${label}</span><span>${v.toFixed(2)}</span></div>` +
    `<div class="bar-track"><div class="bar-fill" style="width:${Math.round(v * 100)}%;background:${color}"></div></div></div>`;
}
function fmtRange(m) { return m >= 1000 ? (m / 1000).toFixed(1) + " km" : Math.round(m) + " m"; }

function renderTimeline(r) {
  const el = document.getElementById("timeline"); el.innerHTML = "";
  const tl = r.timeline || []; const max = Math.max(1, ...tl.map(t => t.detections));
  const peakStart = r.peak_window ? r.peak_window.start : null;
  tl.forEach(t => {
    const b = document.createElement("div"); b.className = "tl-bar";
    if (peakStart && Math.abs(new Date(t.t) - new Date(peakStart)) < 40000) b.className += " peak";
    b.style.height = Math.max(2, (t.detections / max) * 66) + "px";
    b.title = `${hhmm(t.t)} — ${t.detections} detections`;
    el.appendChild(b);
  });
}
function hhmm(iso) { const d = new Date(iso); return d.toISOString().slice(11, 16) + "Z"; }

// --- interaction -----------------------------------------------------------
function initInteraction() {
  const canvas = document.getElementById("plot");
  const tip = document.getElementById("tooltip");
  canvas.addEventListener("mousemove", e => {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const hit = (state.hot || []).find(h => Math.hypot(h.x - mx, h.y - my) <= h.r);
    if (!hit) { tip.classList.add("hidden"); return; }
    tip.classList.remove("hidden");
    tip.style.left = (mx + 14) + "px"; tip.style.top = (my + 8) + "px";
    if (hit.kind === "node") {
      tip.innerHTML = `<b>${hit.s.label}</b><br>DF σ ${hit.s.calibration?.df_sigma_deg}°<br>${hit.s.lat.toFixed(5)}, ${hit.s.lon.toFixed(5)}`;
    } else {
      const o = hit.o, f = o.best_fix;
      tip.innerHTML = `<b style="color:${EMITTER_COLOR[o.emitter_type]}">${o.label}</b><br>` +
        `score ${o.score.toFixed(0)} · duty ${(o.duty * 100).toFixed(0)}%<br>` +
        `ellipse ${Math.round(f.err_semimajor_m)}×${Math.round(f.err_semiminor_m)} m @ ${Math.round(f.err_orient_deg)}°<br>` +
        `CEP ${Math.round(f.cep50_m)} m · GDOP ${f.gdop} · ${f.n_contributors ?? ""} nodes`;
    }
  });
  canvas.addEventListener("mouseleave", () => tip.classList.add("hidden"));

  document.getElementById("btn-cot").addEventListener("click", async () => {
    const xml = await (await fetch("/api/cot")).text();
    document.getElementById("cot-body").textContent = xml || "(no fixes yet)";
    document.getElementById("cot-modal").classList.remove("hidden");
  });
  document.getElementById("cot-close").addEventListener("click", () =>
    document.getElementById("cot-modal").classList.add("hidden"));
  window.addEventListener("resize", () => { buildProjection(); draw(); });
}

// --- live SSE --------------------------------------------------------------
let refreshTimer = null;
function connectStream() {
  const dot = document.getElementById("live-dot"), lbl = document.getElementById("live-label");
  try {
    const es = new EventSource("/api/stream");
    es.onopen = () => { dot.classList.add("on"); lbl.textContent = "live"; };
    es.onerror = () => { dot.classList.remove("on"); lbl.textContent = "offline"; };
    const bump = () => { clearTimeout(refreshTimer); refreshTimer = setTimeout(loadAll, 400); };
    ["detection", "fix", "signature", "watch_hit"].forEach(ev => es.addEventListener(ev, bump));
  } catch (e) { lbl.textContent = "no live feed"; }
}

initInteraction();
connectStream();
loadAll();
