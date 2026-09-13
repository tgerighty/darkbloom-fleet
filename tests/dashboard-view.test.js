import { describe, expect, it } from "vitest";

import { actionLabel, bandHtml, renderHost, renderHosts } from "../fleet/static/host.js";
import { mergeDemand, renderDemand } from "../fleet/static/ui.js";

function host(over = {}) {
  return {
    host: { label: "M3", spec: "Ultra" },
    mode: "OBSERVE",
    current_model: "gemma",
    inference_active: false,
    as_of: 1_700_000_000,
    demand: [{ model: "gemma", active_requests: 1, warm_providers: 1, pressure: 1,
      output_usd_per_million: 0.4, score: 0.2, ema_score: 0.3, observed_at: 10 }],
    serving: { "24h": { idle: 100 } },
    recent_decisions: [],
    recent_earnings: [],
    unattributed_recent: 0,
    card: {
      status: { state: "TRUSTED", tone: "amber", detail: "quiet" },
      resources: { thermal_state: "nominal", memory_pressure: 0.2, cpu_usage: 0.1 },
      gpu: {},
      loaded: [{ model: "gemma", active: false }, { model: "llama", active: false }],
      kpis: { requests: 3, tokens: 9, token_requests: 2, started_at: 1, last_served_at: 1 },
      slots: [{ model: "gemma", kv_backend: "paged", mtp_active: true }],
    },
    routability: { models: [] },
    ...over,
  };
}

const SWITCH = {
  observed_at: 1_700_000_000,
  current_model: "gemma",
  target_model: "llama",
  action: "SWITCH",
  reason: "ranks first",
  mode: "OBSERVE",
  executed: false,
  error: "ssh fail",
};

describe("high-level band and chips", function () {
  it("shows current model, idle, would-switch, and the decision error", function () {
    const html = bandHtml(host({ recent_decisions: [SWITCH] }), host().card);
    expect(html).toContain("gemma");
    expect(html).toContain("idle");
    expect(html).toContain("would switch");
    expect(html).toContain("ranks first");
    expect(html).toContain("ssh fail");
    expect(html).toContain('class="band-sub err"');
    expect(html).toContain("TRUSTED — no request in 10 min");
    expect(html).not.toContain("priority:");
    expect(html).not.toContain("no traffic yet");
  });

  it("labels only non-executed OBSERVE switch actions as would switch", function () {
    expect(actionLabel(SWITCH, "OBSERVE")).toBe("would switch");
    expect(actionLabel({ ...SWITCH, action: "SWITCH_WHEN_IDLE" }, "OBSERVE")).toBe("would switch");
    expect(actionLabel({ ...SWITCH, executed: true }, "OBSERVE")).toBe("SWITCH");
    expect(actionLabel(SWITCH, "LIVE")).toBe("SWITCH");
    expect(actionLabel({ ...SWITCH, action: "KEEP" }, "OBSERVE")).toBe("KEEP");
  });

  it("marks the current loaded chip while idle and serving", function () {
    const idle = renderHost(host(), "24h", "");
    expect(idle).toContain("gemma · current");
    expect(idle).not.toContain("gemma · active");
    expect(idle).toContain(">llama</span>");
    const busy = renderHost(host({ inference_active: true }), "24h", "");
    expect(busy).toContain("gemma · active");
    expect(busy).toContain("serving");
  });
});

describe("no placeholder chrome", function () {
  it("omits console-only tiles, dummy gauges, idle note, catalog chips, and priority", function () {
    const html = renderHost(host(), "24h", "HOURLY");
    expect(html).not.toContain("console only");
    expect(html).not.toContain("darkbloom.dev");
    expect(html).not.toContain("Always ready");
    expect(html).not.toContain("tok/s");
    expect(html).not.toContain("1/–");
    expect(html).not.toContain("0/–");
    expect(html).not.toContain("priority:");
    expect(html).not.toContain("catalog");
    expect(html).toContain("2 payouts");
    expect(html).toContain("HOURLY");
    expect(html).toContain('data-fold="serving"');
    expect(html).not.toMatch(/<details class="fold" open data-fold="serving"/);
    expect(html).not.toMatch(/<details class="fold" open data-fold="slots"/);
    expect(html).toContain('data-fold="slots"');
  });

  it("treats serious thermal as a fault fill", function () {
    const html = renderHost(host({ card: { ...host().card,
      resources: { thermal_state: "serious" } } }), "24h", "");
    expect(html).toContain("Serious");
    expect(html).toContain('gfill err');
  });
});

describe("malformed host isolation", function () {
  it("still renders host 1 when host 2 has no demand", function () {
    const a = host();
    const b = host({ host: { label: "M1", spec: "Air" }, demand: undefined, recent_decisions: undefined });
    delete b.demand;
    delete b.recent_decisions;
    const html = renderHosts([a, b], "24h", function () { return ""; });
    expect(html).toContain("data-host=\"M3\"");
    expect(html).toContain("data-host=\"M1\"");
  });

  it("emits one error card when a host renderer throws", function () {
    const bad = host({ host: { label: "bad", spec: "x" } });
    const html = renderHosts([host(), bad], "24h", function (s) {
      if (s.host.label === "bad") throw new Error("boom");
      return "";
    });
    expect(html).toContain("data-host=\"M3\"");
    expect(html).toContain("data-host=\"bad\"");
    expect(html).toContain("boom");
    expect(html).toContain("band red");
  });

  it("renders an API error row without a card payload", function () {
    const html = renderHost({ host: { label: "M1", spec: "" }, mode: "OBSERVE", error: "timeout" }, "24h", "");
    expect(html).toContain("timeout");
    expect(html).toContain("M1");
  });
});

describe("demand merge", function () {
  it("shows an empty row and marks the host that is on that model", function () {
    expect(renderDemand([], [])).toContain("no demand samples yet");
    const rows = mergeDemand([host(), host({ host: { label: "M1", spec: "Air" }, demand: undefined })]);
    expect(rows).toHaveLength(1);
    const html = renderDemand(rows, [host(), host({ host: { label: "M1", spec: "Air" }, current_model: "other" })]);
    expect(html).toContain("gemma · M3");
  });
});
