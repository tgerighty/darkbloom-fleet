import { hourlySection } from "./hourly.js?v=3";
import { esc, renderHosts } from "./host.js?v=3";
import {
  captureFocus, captureUiState, makeRefreshGate, mergeDemand, renderDemand, restoreFocus, restoreUiState,
} from "./ui.js?v=3";

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

function setSubtitle(s) {
  const n = s && s.hosts ? s.hosts.length : 0;
  const el = document.getElementById("fleet-subtitle");
  if (pollError) {
    const age = lastGoodAt ? fmtAge(lastGoodAt) : "never";
    el.innerHTML = '<span class="err">status unavailable: ' + esc(pollError) +
      " · showing data from " + age + "</span>";
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
    document.getElementById("fleet-subtitle").innerHTML =
      '<span class="err">render failed: ' + esc(e) + "</span>";
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

async function refresh() {
  const token = gate.begin();
  if (inflight) inflight.abort();
  const ac = new AbortController();
  inflight = ac;
  try {
    const response = await fetch("/api/status", { signal: ac.signal });
    if (!response.ok) throw new Error("HTTP " + response.status);
    const data = await response.json();
    if (!gate.isCurrent(token)) return;
    lastStatus = data;
    lastGoodAt = Date.now() / 1000;
    pollError = null;
  } catch (e) {
    if (e.name === "AbortError") return;
    if (!gate.isCurrent(token)) return;
    pollError = e;
    if (!lastStatus) {
      document.getElementById("fleet-subtitle").innerHTML =
        '<span class="err">status unavailable: ' + esc(e) + "</span>";
      return;
    }
  }
  if (lastStatus) render(lastStatus);
}

await refresh();
setInterval(refresh, 60000);
