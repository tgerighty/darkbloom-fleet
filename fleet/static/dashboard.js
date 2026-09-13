import { hourlySection } from "./hourly.js?v=4";
import { esc, renderHosts } from "./host.js?v=4";
import {
  captureFocus, captureUiState, makeRefreshGate, mergeDemand, renderDemand, restoreFocus, restoreUiState,
} from "./ui.js?v=4";

const SUBTITLE_ID = "fleet-subtitle";

let servingWindow = "24h";
let lastStatus = null;
let lastGoodAt = null;
let pollError = null;
const gate = makeRefreshGate();
let inflight = null;

function fmtAge(epoch) {
  if (!epoch) return "never";
  const s = Math.max(0, Math.round(Date.now() / 1000 - epoch));
  if (s < 90) return s + "s ago";
  if (s < 5400) return Math.round(s / 60) + "m ago";
  return Math.round(s / 3600) + "h ago";
}

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

function render(s) {
  const hostsRoot = document.getElementById("hosts");
  const snap = captureUiState(hostsRoot.querySelectorAll(".card"));
  const focus = captureFocus(document.activeElement, hostsRoot);
  try {
    document.getElementById("demand").innerHTML = renderDemand(mergeDemand(s.hosts), s.hosts);
    hostsRoot.innerHTML = renderHosts(s.hosts, servingWindow, hourlySection);
    hostsRoot.classList.toggle("stale-poll", Boolean(pollError));
    restoreUiState(hostsRoot.querySelectorAll(".card"), snap);
    restoreFocus(document, focus);
  } catch (e) {
    showError("render failed: " + esc(e));
    return;
  }
  setSubtitle(s);
}

const servingEl = document.getElementById("serving-window");
if (servingEl) {
  servingWindow = servingEl.value || servingWindow;
  servingEl.addEventListener("change", function (event) {
    servingWindow = event.target.value;
    if (lastStatus) render(lastStatus);
  });
}

async function loadStatus(signal) {
  const response = await fetch("/api/status", { signal });
  if (!response.ok) throw new Error("HTTP " + response.status);
  return response.json();
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

await refresh();
setInterval(refresh, 60000);
