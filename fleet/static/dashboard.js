import { hourlySection } from "./hourly.js";

const TD = "</td><td>";
const TR = "<tr><td>";
const TR_END = "</td></tr>";
const SPAN_END = "</span>";
const SPAN_DIV_END = "</span></div>";
const DIV_END = "</div>";
const FOLD_END = "</details>";
const WINDOWS = ["1h", "7h", "24h", "30d", "lifetime"];
const THERMAL_LABELS = { nominal: "Nominal", fair: "Fair", serious: "Serious", critical: "Critical" };
const THERMAL_FILL = { nominal: 0.15, fair: 0.45, serious: 0.75, critical: 0.95 };
const BANDS = {
  EARNING: "✓ EARNING — receiving traffic",
  TRUSTED: "TRUSTED — no traffic yet",
  ATTESTING: "ATTESTING — trust re-attestation",
  STALE: "STALE — daemon state not fresh",
  OFF: "OFF — no daemon snapshot",
};
const HEALTH_TONE = { DAEMON_DOWN: "down", DEAD_SESSION: "down", THRASH: "warn", STALE: "warn", HEALTHY: "ok" };
const EMPTY_CARD = { status: null, resources: {}, gpu: {}, loaded: [], catalog: [], kpis: {}, slots: [] };
const EMPTY_ROUT = { models: [], session: null, self_route_as_of: null, last_served_at: null, switch_cost: null };
let servingWindow = "24h";
let lastStatus = null;

function fmtAge(epoch) {
  if (!epoch) return "never";
  const s = Math.max(0, Math.round(Date.now() / 1000 - epoch));
  if (s < 90) return s + "s ago";
  if (s < 5400) return Math.round(s / 60) + "m ago";
  return Math.round(s / 3600) + "h ago";
}
function fmtUp(epoch) {
  if (!epoch) return "–";
  const s = Math.max(0, Math.round(Date.now() / 1000 - epoch));
  if (s < 5400) return Math.round(s / 60) + "m";
  if (s < 172800) return Math.round(s / 3600) + "h";
  return Math.round(s / 86400) + "d";
}
function clock(epoch) {
  return new Date(epoch * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
function num(v, digits) { return v === null || v === undefined ? "–" : Number(v).toFixed(digits); }
function pct01(v) { return v === null || v === undefined ? "–" : Math.round(100 * v) + "%"; }
function esc(v) { return v === null || v === undefined ? "" : String(v).replaceAll(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }
export { esc };
function mins(v) { return v === null || v === undefined ? "not yet" : v + " min"; }
function yes(v) { return v ? "yes" : "–"; }

function renderDemand(rows) {
  return rows.map(function (r) {
    return TR + esc(r.model) + TD + r.active_requests + TD + r.warm_providers + TD + num(r.pressure, 2) + TD +
      num(r.output_usd_per_million, 2) + TD + num(r.score, 3) + "</td><td><b>" + num(r.ema_score, 3) + "</b></td></tr>";
  }).join("");
}

function renderServing(shares) {
  const entries = Object.entries(shares || {}).sort(function (a, b) { return (a[0] === "idle") - (b[0] === "idle") || b[1] - a[1]; });
  if (!entries.length) return "<i>not enough history yet</i>";
  return entries.map(function ([model, pct]) {
    return '<div class="bar-row"><div class="bar-label">' + esc(model) + DIV_END +
      '<div class="bar-track"><div class="bar-fill' + (model === "idle" ? " idle" : "") + '" style="width:' + pct + '%"></div></div>' +
      '<div>' + pct + '%</div></div>';
  }).join("");
}

function healthBadge(h) {
  const state = h?.state || "HEALTHY";
  return '<span class="badge ' + (HEALTH_TONE[state] || "ok") + '" title="' + esc(h?.detail) + '">' +
    esc(state) + SPAN_END;
}

function bandHtml(band) {
  const b = band || { state: "OFF", tone: "grey", detail: "", priority: "normal" };
  return '<div class="band ' + b.tone + '"><div class="band-line"><span>' + esc(BANDS[b.state] || b.state) +
    '</span><span class="gvalue">priority: ' + esc(b.priority) + SPAN_DIV_END +
    '<div class="band-sub">' + esc(b.detail) + '</div></div>';
}

function gauge(label, value, fill, cls) {
  const width = fill === null || fill === undefined ? 0 : Math.round(100 * Math.min(1, Math.max(0, fill)));
  return '<div class="gauge"><div class="pair"><span class="glabel">' + label + '</span><span class="gvalue">' +
    value + '</span></div><div class="gtrack"><div class="gfill ' + (cls || "") + '" style="width:' + width +
    '%"></div></div></div>';
}

function resourceRow(s, card) {
  const r = card.resources || {};
  const thermal = r.thermal_state ? (THERMAL_LABELS[r.thermal_state] || esc(r.thermal_state)) : "–";
  return '<div class="gauges">' +
    gauge("thermal", thermal, THERMAL_FILL[r.thermal_state] || null, "good") +
    gauge("memory", pct01(r.memory_pressure), r.memory_pressure) +
    gauge("cpu", pct01(r.cpu_usage), r.cpu_usage) +
    gauge("concurrency", s.inference_active ? "1/–" : "0/–", null) +
    gauge("decode", "– tok/s", null) +
    DIV_END;
}

function gpuRow(gpu) {
  const g = gpu || {};
  const total = g.total_gb;
  const pctOf = function (gb) { return total ? Math.min(100, Math.round(100 * gb / total)) : 0; };
  const text = num(g.active_gb, 1) + " active · " + num(g.cache_gb, 1) + " cache · " +
    (total ? total + " GB" : "–");
  return '<div class="gpu-row"><span class="glabel">gpu memory</span>' +
    '<div class="gtrack wide"><div class="gfill" style="width:' + pctOf(g.active_gb || 0) + '%"></div>' +
    '<div class="gfill cache" style="width:' + pctOf(g.cache_gb || 0) + '%"></div></div>' +
    '<span class="gvalue">' + text + SPAN_DIV_END;
}

function chip(model, active) {
  return '<span class="chip' + (active ? " active" : "") + '">' + esc(model) + (active ? " · active" : "") + SPAN_END;
}
function chipRow(label, chips) {
  return '<div class="chips"><span class="glabel">' + label + SPAN_END +
    (chips.length ? chips.join("") : '<span class="none">none</span>') + DIV_END;
}

function tile(value, label, sub) {
  return '<div class="tile"><div class="tvalue">' + value + '</div><div class="tlabel">' + label + DIV_END +
    (sub ? '<div class="tsub">' + sub + DIV_END : "") + DIV_END;
}

function kpiGrid(s, card) {
  const k = card.kpis || {};
  const since = k.started_at ? "since " + clock(k.started_at) : "";
  return '<div class="tiles">' +
    tile(k.requests, "requests", since) +
    tile(num(k.tokens, 0), "tokens", k.token_requests + " reqs") +
    tile(fmtUp(k.started_at), "uptime") +
    tile("$" + num(s.earnings_usd_1h, 4), "$ earned 1h") +
    tile("$" + num(s.earnings_usd_24h, 2), "$ earned 24h") +
    tile(fmtAge(k.last_served_at), "last served") +
    tile("console only", "reputation", "see darkbloom.dev") +
    tile("console only", "avg ttft", "see darkbloom.dev") +
    DIV_END;
}

function servingSection(s, index) {
  const options = WINDOWS.map(function (w) {
    return '<option value="' + w + '"' + (w === servingWindow ? " selected" : "") + ">" + w + "</option>";
  }).join("");
  return '<section><h2>Serving <select data-serving-window="' + index + '">' + options + '</select></h2>' +
    '<div class="sub">share of the window actively serving a request, per model; idle = warm with no request, ' +
    'no model, or no data (1-minute samples)</div>' + renderServing(s.serving?.[servingWindow]) + '</section>';
}

function slotRow(slot, current, busy) {
  const running = busy && slot.model === current;
  let mtp = "active";
  if (!slot.mtp_active) mtp = slot.mtp_inactive_reason ? "inactive (" + slot.mtp_inactive_reason + ")" : "inactive";
  return '<div class="slot-row"><span class="smodel">' + esc(slot.model) + SPAN_END +
    '<span class="sbadge ' + (running ? "run" : "idle") + '">' + (running ? "RUNNING" : "IDLE") + SPAN_END +
    '<span class="sdetail">kv=' + esc(slot.kv_backend || "–") + " · mtp " + esc(mtp) + SPAN_DIV_END;
}

function slotsSection(s, card) {
  const slots = card.slots || [];
  const g = card.gpu || {};
  const tiles = '<div class="tiles">' + tile(num(g.active_gb, 1) + " GB", "gpu active") +
    tile(num(g.peak_gb, 1) + " GB", "gpu peak") + tile(num(g.cache_gb, 1) + " GB", "gpu cache") + DIV_END;
  const rows = slots.map(function (sl) { return slotRow(sl, s.current_model, s.inference_active); }).join("");
  return '<details class="fold" open><summary>⚡ Backend slots · ' + slots.length + ' model(s)</summary>' +
    tiles + (rows || '<div class="none">no slot data</div>') + FOLD_END;
}

function switchCost(c) {
  if (!c) return "";
  const measured = c.measured_seconds !== null && c.measured_seconds !== undefined;
  return " · switch cost: " + (measured
    ? "measured " + c.measured_seconds + " s over " + c.measured_sessions + " sessions"
    : "configured " + c.configured_seconds + " s (" + c.measured_sessions + " measured sessions, need 3)");
}

function trustSection(r) {
  const modelRows = r.models.length ? r.models.map(function (m) {
    return TR + esc(m.model) + TD + yes(m.advertised) + TD + yes(m.warm) + TD + m.routable_providers + TD +
      fmtAge(m.last_served_at) + TR_END;
  }).join("") : "<tr><td colspan=5><i>no probe data yet</i></td></tr>";
  const session = r.session
    ? "daemon restarted " + fmtAge(r.session.started_at) + " · first request after " + mins(r.session.first_request_after_min) +
      " · any host routable after " + mins(r.session.any_host_routable_after_min)
    : "no session data";
  const trust = "trust: " + esc(r.trust_level || "unknown") + (r.trust_reason ? " (" + esc(r.trust_reason) + ")" : "");
  const probeNote = "routable = coordinator self-route view for our own requests, account-wide (probed " + fmtAge(r.self_route_as_of) + ")";
  return '<details class="fold"><summary>🛡 Trust &amp; attestation</summary>' +
    '<div class="sub">' + trust + switchCost(r.switch_cost) + '<br>' + esc(session) + '<br>' + esc(probeNote) + DIV_END +
    '<table><thead><tr><th>model</th><th>advertised</th><th>warm</th><th>routable providers</th><th>last served</th></tr></thead>' +
    '<tbody>' + modelRows + '</tbody></table></details>';
}

function decisionsSection(decisions) {
  const rows = decisions.map(function (d) {
    return TR + fmtAge(d.observed_at) + TD + esc(d.current_model || "–") + TD + esc(d.target_model || "–") + TD +
      esc(d.action) + (d.executed ? " ✓" : "") + TD + esc(d.reason) + TR_END;
  }).join("");
  return '<details class="fold"><summary>Recent decisions</summary><div class="scroll"><table>' +
    '<thead><tr><th>when</th><th>current</th><th>target</th><th>action</th><th>reason</th></tr></thead>' +
    '<tbody>' + rows + '</tbody></table></div></details>';
}

function payoutsSection(rows, unattributed) {
  const body = rows.length ? rows.map(function (e) {
    return TR + fmtAge(e.created_at) + TD + esc(e.model) + TD + e.completion_tokens + TD +
      "$" + num(e.micro_usd / 1e6, 4) + TR_END;
  }).join("") : "<tr><td colspan=4><i>no payouts recorded yet</i></td></tr>";
  return '<details class="fold"><summary>Recent payouts · ' + unattributed + ' unattributed of last 50</summary>' +
    '<div class="scroll tall"><table><thead><tr><th>when</th><th>model</th><th>completion tokens</th><th>paid</th></tr></thead>' +
    '<tbody>' + body + '</tbody></table></div></details>';
}

function renderHost(s, index) {
  const card = s.card || EMPTY_CARD;
  const state = card.status?.state || "OFF";
  const loaded = card.loaded.map(function (c) { return chip(c.model, c.active); });
  const catalog = card.catalog.map(function (m) { return chip(m, false); });
  return '<div class="card ' + state.toLowerCase() + '">' +
    '<div class="card-head"><h1>' + esc(s.host.label) + '</h1><span class="sub">' + esc(s.host.spec) +
    ' · daemon ' + fmtAge(s.as_of) + '</span><span class="badge ' + s.mode.toLowerCase() + '">' + s.mode + SPAN_END +
    healthBadge(s.health) + DIV_END +
    bandHtml(card.status) +
    '<div class="card-body">' +
    resourceRow(s, card) + gpuRow(card.gpu) +
    chipRow("loaded", loaded) + chipRow("catalog (" + card.catalog.length + ")", catalog) +
    '<div class="idle-note"><span class="glabel">memory when idle</span>Always ready — models stay loaded</div>' +
    kpiGrid(s, card) +
    servingSection(s, index) +
    hourlySection(s) +
    slotsSection(s, card) +
    trustSection(s.routability || EMPTY_ROUT) +
    DIV_END +
    decisionsSection(s.recent_decisions) + payoutsSection(s.recent_earnings || [], s.unattributed_recent || 0) +
    DIV_END;
}

function render(s) {
  document.getElementById("fleet-subtitle").textContent = s.hosts.length + " host" + (s.hosts.length === 1 ? "" : "s") +
    " · refreshed " + new Date().toLocaleTimeString();
  // Demand is network-wide but each host records only its configured models: merge by model, newest sample wins.
  const byModel = new Map();
  s.hosts.forEach(function (h) { h.demand.forEach(function (r) {
    const seen = byModel.get(r.model);
    if (!seen || (r.observed_at || 0) > (seen.observed_at || 0)) byModel.set(r.model, r);
  }); });
  const demand = Array.from(byModel.values()).sort(function (a, b) { return (b.ema_score || 0) - (a.ema_score || 0); });
  document.getElementById("demand").innerHTML = renderDemand(demand);
  document.getElementById("hosts").innerHTML = s.hosts.map(renderHost).join("");
}

document.getElementById("hosts").addEventListener("change", function (event) {
  if (event.target.matches("select[data-serving-window]") && lastStatus) {
    servingWindow = event.target.value;
    render(lastStatus);
  }
});

async function refresh() {
  try {
    const response = await fetch("/api/status");
    if (!response.ok) throw new Error("HTTP " + response.status);
    lastStatus = await response.json();
  } catch (e) {
    document.getElementById("fleet-subtitle").innerHTML = '<span class="err">status unavailable: ' + esc(e) + SPAN_END;
    return;
  }
  render(lastStatus);
}
await refresh();
setInterval(refresh, 60000);
