import { esc, payoutExpand, renderHosts } from "./host.js?v=11";
import {
  captureFocus, captureUiState, fmtAge, makeRefreshGate, mergeDemand, renderDemand, restoreFocus, restoreUiState,
} from "./ui.js?v=8";

const SUBTITLE_ID = "fleet-subtitle";
const POLL_MS = 60000;
const HOURLY_STUB =
  '<details class="fold" open data-fold="hourly"><summary>Jobs · hourly buckets · 24 h</summary>' +
  '<div class="sub">Each letter is a payout-bearing 90-second portion, not GPU busy time.</div>' +
  '<pre class="hourly" data-hourly-pending aria-busy="true">Loading hourly…</pre></details>';

let servingWindow = "24h";
let lastStatus = null;
let lastGoodAt = null;
let pollError = null;
let lastFingerprint = null;
let hourlySectionFn = null;
let hourlyLoad = null;
const gate = makeRefreshGate();
let inflight = null;

function subtitleEl() {
  return document.getElementById(SUBTITLE_ID);
}

function showError(msg) {
  subtitleEl().innerHTML = '<span class="err">' + msg + "</span>";
}

function setSubtitle(s) {
  const n = s?.hosts ? s.hosts.length : 0;
  const el = subtitleEl();
  if (pollError) {
    const age = fmtAge(lastGoodAt);
    showError("status unavailable: " + esc(pollError) + " · showing data from " + age);
    return;
  }
  el.textContent = n + " host" + (n === 1 ? "" : "s") +
    " · refreshed " + new Date().toLocaleTimeString();
}

function safeNodes(html, context) {
  const isTableBody = context.tagName === "TBODY";
  const parsed = new DOMParser().parseFromString(isTableBody ? "<table><tbody>" + html + "</tbody></table>" : html, "text/html");
  const root = isTableBody ? parsed.querySelector("tbody") : parsed.body;
  root.querySelectorAll("script,iframe,object,embed").forEach(function (node) { node.remove(); });
  root.querySelectorAll("*").forEach(function (node) {
    Array.from(node.attributes).forEach(function (attr) {
      const value = attr.value.replaceAll(/[\u0000-\u0020\u007f]/g, "").toLowerCase();
      const unsafeUri = ["javascript:", "data:", "vbscript:"].some(function (scheme) {
        return value.startsWith(scheme);
      });
      if (attr.name.toLowerCase().startsWith("on") || unsafeUri) {
        node.removeAttribute(attr.name);
      }
    });
  });
  return Array.from(root.childNodes);
}

function fingerprint(s) {
  const expand = Array.from(payoutExpand).sort().join(",");
  return JSON.stringify(s) + "|" + (pollError ? String(pollError) : "") + "|" + servingWindow + "|" +
    (hourlySectionFn ? "h1" : "h0") + "|" + expand;
}

function hourlyHtml(s) {
  return hourlySectionFn ? hourlySectionFn(s) : HOURLY_STUB;
}

function ensureHourly() {
  if (hourlySectionFn) return Promise.resolve(hourlySectionFn);
  if (hourlyLoad) return hourlyLoad;
  hourlyLoad = import("./hourly.js?v=5").then(function (mod) {
    hourlySectionFn = mod.hourlySection;
    if (lastStatus) render(lastStatus, true);
    return hourlySectionFn;
  });
  return hourlyLoad;
}

function scheduleHourly() {
  const run = function () { ensureHourly(); };
  if (typeof requestIdleCallback === "function") requestIdleCallback(run, { timeout: 1500 });
  else setTimeout(run, 0);
}

function render(s, force) {
  const fp = fingerprint(s);
  if (!force && fp === lastFingerprint) {
    setSubtitle(s);
    return;
  }
  lastFingerprint = fp;
  const hostsRoot = document.getElementById("hosts");
  const snap = captureUiState(hostsRoot.querySelectorAll(".card"));
  const focus = captureFocus(document.activeElement, hostsRoot);
  try {
    const demandRoot = document.getElementById("demand");
    demandRoot.replaceChildren(...safeNodes(renderDemand(mergeDemand(s.hosts), s.hosts), demandRoot));
    hostsRoot.replaceChildren(...safeNodes(renderHosts(s.hosts, servingWindow, hourlyHtml), hostsRoot));
    hostsRoot.classList.toggle("stale-poll", Boolean(pollError));
    restoreUiState(hostsRoot.querySelectorAll(".card"), snap);
    restoreFocus(document, focus);
  } catch (e) {
    showError("render failed: " + esc(e));
    return;
  }
  setSubtitle(s);
  if (!hourlySectionFn) scheduleHourly();
}

const servingEl = document.getElementById("serving-window");
if (servingEl) {
  servingWindow = servingEl.value || servingWindow;
  servingEl.addEventListener("change", function (event) {
    servingWindow = event.target.value;
    if (lastStatus) render(lastStatus, true);
  });
}

const hostsEl = document.getElementById("hosts");
if (hostsEl) {
  hostsEl.addEventListener("click", function (event) {
    const btn = event.target.closest("[data-action=\"payouts-expand\"], [data-action=\"payouts-collapse\"]");
    if (!btn) return;
    const label = btn.getAttribute("data-host");
    if (!label) return;
    if (btn.getAttribute("data-action") === "payouts-expand") payoutExpand.add(label);
    else payoutExpand.delete(label);
    if (lastStatus) render(lastStatus, true);
  });
}

async function loadStatus(signal) {
  const response = await fetch("/api/status", { signal });
  if (!response.ok) throw new Error("HTTP " + response.status);
  const data = await response.json();
  if (!Array.isArray(data?.hosts) || data.hosts.some(h => !h || typeof h !== "object" ||
    (h.demand && (!Array.isArray(h.demand) || h.demand.some(r => !r || typeof r !== "object"))))) {
    throw new TypeError("status payload has malformed hosts");
  }
  return data;
}

function applyStatus(token, data) {
  if (!gate.isCurrent(token)) return false;
  lastStatus = data;
  lastGoodAt = Date.now() / 1000;
  pollError = null;
  return true;
}

function applyPollError(token, e) {
  if (e.name === "AbortError" || !gate.isCurrent(token)) return false;
  pollError = e;
  if (lastStatus) return true;
  showError("status unavailable: " + esc(e));
  return false;
}

async function refresh() {
  if (document.hidden) return;
  const token = gate.begin();
  if (inflight) inflight.abort();
  const ac = new AbortController();
  inflight = ac;
  try {
    const data = await loadStatus(ac.signal);
    if (!applyStatus(token, data)) return;
  } catch (e) {
    if (!applyPollError(token, e)) return;
  }
  if (lastStatus) render(lastStatus);
}

document.addEventListener("visibilitychange", function () {
  if (!document.hidden) refresh();
});

await refresh();
setInterval(refresh, POLL_MS);
