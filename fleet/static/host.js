import { esc } from "./ui.js?v=4";
export { esc };

const TD = "</td><td>";
const TR = "<tr><td>";
const TR_END = "</td></tr>";
const SPAN_END = "</span>";
const SPAN_DIV_END = "</span></div>";
const DIV_END = "</div>";
const FOLD_END = "</details>";
const THERMAL_LABELS = { nominal: "Nominal", fair: "Fair", serious: "Serious", critical: "Critical" };
const THERMAL_FILL = { nominal: 0.15, fair: 0.45, serious: 0.75, critical: 0.95 };
const BANDS = {
  EARNING: "✓ EARNING — receiving traffic",
  TRUSTED: "TRUSTED — no request in 10 min",
  ATTESTING: "ATTESTING — trust re-attestation",
  STALE: "STALE — daemon state not fresh",
  OFF: "OFF — no daemon snapshot",
};
const EMPTY_CARD = { status: null, resources: {}, gpu: {}, loaded: [], catalog: [], kpis: {}, slots: [] };
const EMPTY_ROUT = { models: [], session: null, self_route_as_of: null, last_served_at: null, switch_cost: null };

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
function mins(v) { return v === null || v === undefined ? "not yet" : v + " min"; }
function yes(v) { return v ? "yes" : "–"; }
function tri(v) {
  if (v === null || v === undefined) return "unknown";
  return v ? "yes" : "–";
}
export function actionLabel(decision, mode) {
  if (!decision || !decision.action) return "";
  const switchLike = decision.action === "SWITCH" || decision.action === "SWITCH_WHEN_IDLE";
  if (String(mode || "").toUpperCase() === "OBSERVE" && switchLike && !decision.executed) {
    return "would switch";
  }
  return decision.action;
}

function decisionBlock(s) {
  const latest = (s.recent_decisions || [])[0];
  if (!latest) return '<div class="band-sub">no decisions yet</div>';
  const line = esc(latest.current_model || "–") + " → " + esc(latest.target_model || "–") +
    " · " + esc(actionLabel(latest, s.mode)) + " · " + esc(latest.reason || "") +
    " · " + fmtAge(latest.observed_at);
  const err = latest.error ? '<div class="band-sub err">' + esc(latest.error) + "</div>" : "";
  return '<div class="band-sub">' + line + "</div>" + err;
}

export function bandHtml(s, card) {
  const b = (card && card.status) || { state: "OFF", tone: "grey", detail: "" };
  const model = s.current_model || "no model";
  const busy = s.inference_active ? "serving" : "idle";
  return '<div class="band ' + (b.tone || "grey") + '"><div class="band-line"><span>' +
    esc(BANDS[b.state] || b.state) + '</span><span class="gvalue">' + esc(model) + " · " + busy +
    SPAN_DIV_END + '<div class="band-sub">' + esc(b.detail || "") + "</div>" +
    loadErrorBlock(card) + decisionBlock(s) + "</div>";
}

function loadErrorBlock(card) {
  const err = card && card.last_model_load_error;
  if (!err) return "";
  const when = err.at ? " (" + fmtAge(err.at) + ")" : "";
  const model = err.model ? esc(err.model) + ": " : "";
  const msg = esc(err.message || "load failed");
  const cls = err.recent ? "band-sub err" : "band-sub";
  return '<div class="' + cls + '">load error' + when + ": " + model + msg + "</div>";
}

function gauge(label, value, fill, cls) {
  const width = fill === null || fill === undefined ? 0 : Math.round(100 * Math.min(1, Math.max(0, fill)));
  return '<div class="gauge"><div class="pair"><span class="glabel">' + label + '</span><span class="gvalue">' +
    value + '</span></div><div class="gtrack"><div class="gfill ' + (cls || "") + '" style="width:' + width +
    '%"></div></div></div>';
}

function thermalClass(state) {
  if (state === "serious" || state === "critical") return "err";
  if (state === "nominal" || state === "fair") return "good";
  return "";
}

function resourceRow(card) {
  const r = card.resources || {};
  const thermal = r.thermal_state ? (THERMAL_LABELS[r.thermal_state] || esc(r.thermal_state)) : "–";
  return '<div class="gauges">' +
    gauge("thermal", thermal, THERMAL_FILL[r.thermal_state] || null, thermalClass(r.thermal_state)) +
    gauge("memory", pct01(r.memory_pressure), r.memory_pressure) +
    gauge("cpu", pct01(r.cpu_usage), r.cpu_usage) + DIV_END;
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

export function chip(model, current, busy) {
  const isCurrent = Boolean(current) && model === current;
  let cls = "chip";
  let mark = "";
  if (isCurrent && busy) { cls += " active"; mark = " · active"; }
  else if (isCurrent) { cls += " current"; mark = " · current"; }
  return '<span class="' + cls + '">' + esc(model) + mark + SPAN_END;
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
    tile(num(k.tokens, 0), "tokens", (k.token_requests || 0) + " payouts") +
    tile(fmtUp(k.started_at), "uptime") +
    tile("$" + num(s.earnings_usd_1h, 4), "$ earned 1h") +
    tile("$" + num(s.earnings_usd_24h, 2), "$ earned 24h") +
    tile(fmtAge(k.last_served_at), "last served") + DIV_END;
}

function renderServing(shares) {
  const entries = Object.entries(shares || {}).sort(function (a, b) {
    return (a[0] === "idle") - (b[0] === "idle") || b[1] - a[1];
  });
  if (!entries.length) return "<i>not enough history yet</i>";
  return entries.map(function ([model, pct]) {
    return '<div class="bar-row"><div class="bar-label">' + esc(model) + DIV_END +
      '<div class="bar-track"><div class="bar-fill' + (model === "idle" ? " idle" : "") +
      '" style="width:' + pct + '%"></div></div><div>' + pct + "%</div></div>";
  }).join("");
}

function servingSection(s, windowName) {
  return '<details class="fold" data-fold="serving"><summary>Serving · ' + esc(windowName) + "</summary>" +
    '<div class="sub">share of the window actively serving a request, per model; idle = warm with no request, ' +
    "no model, or no data (1-minute samples)</div>" + renderServing(s.serving?.[windowName]) + FOLD_END;
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
  return '<details class="fold" data-fold="slots"><summary>⚡ Backend slots · ' + slots.length +
    " model(s)</summary>" + tiles + (rows || '<div class="none">no slot data</div>') + FOLD_END;
}

function switchCost(c) {
  if (!c) return "";
  const measured = c.measured_seconds !== null && c.measured_seconds !== undefined;
  return " · switch cost: " + (measured
    ? "measured " + c.measured_seconds + " s over " + c.measured_sessions + " sessions"
    : "configured " + c.configured_seconds + " s (" + c.measured_sessions + " measured sessions, need 3)");
}

function trustSection(r) {
  const models = r.models || [];
  const modelRows = models.length ? models.map(function (m) {
    return TR + esc(m.model) + TD + yes(m.advertised) + TD + yes(m.warm) + TD + tri(m.installed) + TD +
      m.routable_providers + TD + fmtAge(m.last_served_at) + TR_END;
  }).join("") : "<tr><td colspan=6><i>no probe data yet</i></td></tr>";
  const session = r.session
    ? "daemon restarted " + fmtAge(r.session.started_at) + " · first request after " +
      mins(r.session.first_request_after_min) + " · any host routable after " +
      mins(r.session.any_host_routable_after_min)
    : "no session data";
  const trust = "trust: " + esc(r.trust_level || "unknown") + (r.trust_reason ? " (" + esc(r.trust_reason) + ")" : "");
  const probeNote = "routable = coordinator self-route view for our own requests, account-wide (probed " +
    fmtAge(r.self_route_as_of) + ")";
  return '<details class="fold" data-fold="trust"><summary>🛡 Trust &amp; attestation</summary>' +
    '<div class="sub">' + trust + switchCost(r.switch_cost) + "<br>" + esc(session) + "<br>" +
    esc(probeNote) + DIV_END +
    "<table><thead><tr><th>model</th><th>advertised</th><th>warm</th><th>installed</th>" +
    "<th>routable providers</th><th>last served</th></tr></thead><tbody>" + modelRows +
    "</tbody></table></details>";
}

function decisionsSection(decisions, mode) {
  const rows = decisions.length ? decisions.map(function (d) {
    return TR + fmtAge(d.observed_at) + TD + esc(d.current_model || "–") + TD +
      esc(d.target_model || "–") + TD + esc(actionLabel(d, mode)) + (d.executed ? " ✓" : "") + TD +
      esc(d.reason) + (d.error ? ' <span class="err">' + esc(d.error) + "</span>" : "") + TR_END;
  }).join("") : "<tr><td colspan=5><i>no decisions yet</i></td></tr>";
  return '<details class="fold" data-fold="decisions"><summary>Recent decisions</summary>' +
    '<div class="scroll" data-scroll="decisions"><table>' +
    "<thead><tr><th>when</th><th>current</th><th>target</th><th>action</th><th>reason</th></tr></thead>" +
    "<tbody>" + rows + "</tbody></table></div></details>";
}

function payoutsSection(rows, unattributed) {
  const body = rows.length ? rows.map(function (e) {
    return TR + fmtAge(e.created_at) + TD + esc(e.model) + TD + e.completion_tokens + TD +
      "$" + num(e.micro_usd / 1e6, 4) + TR_END;
  }).join("") : "<tr><td colspan=4><i>no payouts recorded yet</i></td></tr>";
  return '<details class="fold" data-fold="payouts"><summary>Recent payouts · ' + unattributed +
    ' unattributed of last 50</summary><div class="scroll tall" data-scroll="payouts"><table>' +
    "<thead><tr><th>when</th><th>model</th><th>completion tokens</th><th>paid</th></tr></thead>" +
    "<tbody>" + body + "</tbody></table></div></details>";
}

function proposedIndicator(s) {
  const latest = (s.recent_decisions || [])[0];
  const switchLike = latest && (latest.action === "SWITCH" || latest.action === "SWITCH_WHEN_IDLE");
  const full = (switchLike && latest.target_model) ? String(latest.target_model) : "KEEP";
  const shown = full.length <= 10 ? full : full.slice(0, 9) + "\u2026";
  return '<span class="badge proposed" role="status" title="' + esc(full) +
    '" aria-label="' + esc(full) + '">' + esc(shown) + SPAN_END;
}

function headHtml(s, host) {
  const mode = s.mode || "OBSERVE";
  return '<div class="card-head"><h1>' + esc(host.label) + '</h1><span class="sub">' +
    esc(host.spec) + " · daemon " + fmtAge(s.as_of) + '</span><span class="head-flags">' +
    '<span class="badge ' + String(mode).toLowerCase() + '">' + esc(mode) + SPAN_END +
    proposedIndicator(s) + SPAN_DIV_END;
}

export function errorCard(s, err) {
  const host = (s && s.host) || {};
  const label = host.label || "host";
  const text = (s && s.error) || (err && (err.message || String(err))) || "error";
  return '<div class="card off" data-host="' + esc(label) + '">' +
    '<div class="card-head"><h1>' + esc(label) + "</h1></div>" +
    '<div class="band red"><div class="band-line"><span>OFF — host error</span></div>' +
    '<div class="band-sub err">' + esc(text) + "</div></div></div>";
}

export function renderHost(s, servingWindow, hourlyHtml) {
  if (s && s.error && !s.card) return errorCard(s, s.error);
  const card = s.card || EMPTY_CARD;
  const host = s.host || { label: "host", spec: "" };
  const state = (card.status && card.status.state) || "OFF";
  const loaded = (card.loaded || []).map(function (c) {
    return chip(c.model, s.current_model, s.inference_active);
  });
  return '<div class="card ' + state.toLowerCase() + '" data-host="' + esc(host.label) + '">' +
    headHtml(s, host) + bandHtml(s, card) +
    '<div class="card-body">' + resourceRow(card) + gpuRow(card.gpu) +
    chipRow("loaded", loaded) + kpiGrid(s, card) +
    servingSection(s, servingWindow || "24h") + (hourlyHtml || "") +
    slotsSection(s, card) + trustSection(s.routability || EMPTY_ROUT) + DIV_END +
    decisionsSection(s.recent_decisions || [], s.mode) +
    payoutsSection(s.recent_earnings || [], s.unattributed_recent || 0) + DIV_END;
}

export function renderHosts(hosts, servingWindow, hourlyFn) {
  return (hosts || []).map(function (h) {
    try {
      return renderHost(h, servingWindow, hourlyFn ? hourlyFn(h) : "");
    } catch (err) {
      return errorCard(h, err);
    }
  }).join("");
}
