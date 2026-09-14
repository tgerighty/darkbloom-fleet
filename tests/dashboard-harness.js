import { vi } from "vitest";

export function nowSec() {
  return Math.floor(Date.now() / 1000);
}

export function host(label, extra = {}) {
  return {
    host: { label: label, spec: "M" },
    mode: "OBSERVE",
    current_model: "gemma",
    inference_active: false,
    as_of: nowSec() - 10,
    demand: [{ model: "gemma", active_requests: 0, warm_providers: 1, pressure: 0,
      output_usd_per_million: 0, score: 0, ema_score: 0.1, observed_at: 1 }],
    serving: { "24h": { idle: 100 }, "1h": { gemma: 100 }, "7h": { idle: 100 } },
    recent_decisions: [],
    recent_earnings: [],
    unattributed_recent: 0,
    card: {
      status: { state: "TRUSTED", tone: "amber", detail: "ok" },
      resources: {}, gpu: {}, loaded: [{ model: "gemma" }], kpis: {}, slots: [],
    },
    routability: { models: [] },
    hourly_jobs: { legend: [{ letter: "G", model: "gemma" }],
      rows: [{ hour: 0, jobs: 1, portions: ["gemma"], serving_percentage: 10, idle_percentage: 90 }] },
    ...extra,
  };
}

export function fold(name, open) {
  return { open: open, dataset: { fold: name } };
}

export function scroller(key, top) {
  return { scrollTop: top, dataset: { scroll: key } };
}

export function cardStub(label, folds, scrolls) {
  return {
    dataset: { host: label },
    _inHosts: true,
    querySelectorAll: function (sel) {
      if (sel === "details[data-fold]") return folds;
      if (sel === "[data-scroll]") return scrolls;
      return [];
    },
    querySelector: function (sel) {
      if (String(sel).indexOf("trust") !== -1) return folds[0];
      return null;
    },
  };
}

export function okFetch(data) {
  return vi.fn(async function () {
    return { ok: true, status: 200, json: async function () { return data; } };
  });
}

export function deferredFetch() {
  const calls = [];
  const fn = vi.fn(function (_url, init) {
    return new Promise(function (resolve, reject) {
      calls.push({ resolve: resolve, reject: reject, signal: init && init.signal });
    });
  });
  return { fn: fn, calls: calls };
}

function hostRoot(before, after) {
  let html = "";
  let phase = "before";
  const toggle = vi.fn();
  const root = {
    classList: { toggle: toggle },
    querySelectorAll: function () { return phase === "before" ? before : after; },
    contains: function (el) { return Boolean(el && el._inHosts); },
    toggle: toggle,
    html: function () { return html; },
    replaceChildren: function (...nodes) { html = nodes.map(function (n) { return n.html; }).join(""); phase = "after"; },
  };
  Object.defineProperty(root, "innerHTML", {
    set: function (v) { html = v; phase = "after"; },
    get: function () { return html; },
  });
  return root;
}

function demandNode(throwValue) {
  const demand = { html: "", replaceChildren: function (...nodes) {
    if (throwValue) throw throwValue;
    demand.html = nodes.map(function (n) { return n.html; }).join("");
  } };
  Object.defineProperty(demand, "innerHTML", {
    set: function (v) {
      if (throwValue) throw throwValue;
      demand.html = v;
    },
    get: function () { return demand.html; },
  });
  return demand;
}

function servingNode(opts) {
  if (opts.noServing) return null;
  const servingEl = {
    id: "serving-window",
    value: opts.servingValue === undefined ? "24h" : opts.servingValue,
    addEventListener: vi.fn(function (_t, fn) { servingEl.handler = fn; }),
    focus: vi.fn(),
  };
  return servingEl;
}

export async function boot(opts) {
  vi.resetModules();
  const subtitle = { innerHTML: "", textContent: "" };
  const demand = demandNode(opts.demandThrow);
  const hosts = hostRoot(opts.before || [], opts.after || []);
  const servingEl = servingNode(opts);
  const byId = { "fleet-subtitle": subtitle, demand: demand, hosts: hosts };
  if (servingEl) byId["serving-window"] = servingEl;
  const doc = {
    getElementById: function (id) { return byId[id] || null; },
    activeElement: opts.active || servingEl,
    querySelectorAll: function (sel) {
      return sel === ".card" ? hosts.querySelectorAll() : [];
    },
  };
  let tick;
  vi.stubGlobal("document", doc);
  vi.stubGlobal("DOMParser", class {
    parseFromString(html) {
      return { body: { childNodes: [{ html: html }] }, querySelectorAll: function (selector) {
        return selector === "*" ? (opts.parsedNodes || []) : [];
      } };
    }
  });
  vi.stubGlobal("setInterval", function (fn, ms) { tick = fn; tick.ms = ms; return 1; });
  vi.stubGlobal("fetch", opts.fetch);
  if (opts.now !== undefined) vi.spyOn(Date, "now").mockReturnValue(opts.now);
  await import("../fleet/static/dashboard.js");
  return { subtitle: subtitle, demand: demand, hosts: hosts, servingEl: servingEl, tick: tick, doc: doc };
}
