import { describe, expect, it } from "vitest";

import { errorCard, renderHost, renderHosts } from "../fleet/static/host.js";

const NOW = Math.floor(Date.now() / 1000);

function host(over = {}) {
  return {
    host: { label: "M3", spec: "Ultra" },
    mode: "OBSERVE",
    current_model: "gemma",
    inference_active: false,
    as_of: NOW - 30,
    demand: [],
    serving: { "24h": { idle: 20, gemma: 50, llama: 30 } },
    recent_decisions: [],
    recent_earnings: [],
    unattributed_recent: 0,
    card: {
      manager: { mode: "LIVE" },
      status: { state: "EARNING", tone: "green", detail: "busy" },
      resources: { thermal_state: "fair", memory_pressure: null, cpu_usage: undefined },
      gpu: { active_gb: 8, cache_gb: 2, total_gb: 20, peak_gb: 9 },
      loaded: [],
      kpis: { requests: 1, tokens: null, started_at: NOW - 60, last_served_at: NOW - 120 },
      slots: [
        { model: "gemma", kv_backend: null, mtp_active: false, mtp_inactive_reason: "cool" },
        { model: "llama", mtp_active: false },
      ],
    },
    routability: { models: [] },
    ...over,
  };
}

function head(html) {
  return html.slice(html.indexOf("card-head"), html.indexOf('class="band'));
}

describe("host card edges", function () {
  it("shows escaped health details with severity colors and a healthy fallback", function () {
    const states = [
      ["DAEMON_DOWN", "down"], ["DEAD_SESSION", "down"], ["THRASH", "warn"],
      ["STALE", "warn"], ["HEALTHY", "ok"], ["UNKNOWN", "ok"],
    ];
    for (const [state, tone] of states) {
      const html = renderHost(host({ health: { state, detail: "<stale>" } }), "24h", "");
      expect(head(html)).toContain('class="badge ' + tone + '" title="&lt;stale&gt;">' + state);
    }
    expect(head(renderHost(host(), "24h", ""))).toContain('title="">HEALTHY</span>');
  });

  it("shows LIVE KEEP, ages, empty chips, idle-last serving, inactive slots, and measured switch cost",
    function () {
      const html = renderHost(host({
        mode: "LIVE",
        inference_active: true,
        earnings_usd_1h: null,
        earnings_usd_24h: undefined,
        recent_decisions: [{
          observed_at: NOW - 10, current_model: null, target_model: null,
          action: "KEEP", reason: "hold", executed: true,
        }],
        recent_earnings: [{
          created_at: NOW - 10, model: "gemma", completion_tokens: 4, micro_usd: 1500,
        }],
        routability: {
          trust_level: null,
          trust_reason: "probe",
          models: [],
          session: {
            started_at: NOW - 8000,
            first_request_after_min: null,
            any_host_routable_after_min: 3,
          },
          self_route_as_of: 0,
          switch_cost: { measured_seconds: 12, measured_sessions: 5, configured_seconds: 300 },
        },
      }), "24h", "");
      const hdr = head(html);
      expect(hdr).toContain(">LIVE</span>");
      expect(hdr).toContain(">KEEP</span>");
      expect(hdr.indexOf("badge live")).toBeLessThan(hdr.indexOf("badge proposed"));
      expect(html).toContain("s ago");
      expect(html).toContain("m ago");
      expect(html).toContain("✓ EARNING");
      expect(html).toContain("Fair");
      expect(html).toContain("gfill good");
      expect(html).toContain("8.0 active · 2.0 cache · 20 GB");
      expect(html).toContain("none");
      expect(html).toContain("$–");
      expect(html).toContain("1m");
      expect(html).not.toContain("not enough history yet");
      expect(html).toMatch(/gemma[\s\S]*llama[\s\S]*idle/);
      expect(html).toContain("bar-fill idle");
      expect(html).toContain("inactive (cool)");
      expect(html).toContain("mtp inactive");
      expect(html).toContain("kv=–");
      expect(html).toContain("RUNNING");
      expect(html).toContain("IDLE");
      expect(html).toContain("measured 12 s over 5 sessions");
      expect(html).toContain("trust: unknown");
      expect(html).toContain("probe");
      expect(html).toContain("not yet");
      expect(html).toContain("3 min");
      expect(html).toContain("never");
      expect(html).toContain("no probe data yet");
      expect(html).not.toContain("KEEP ✓");
      expect(html).toContain("$0.0015");
      expect(html).not.toContain("<button");
    });

  it("falls back for missing card, unknown thermal, empty serving, configured switch cost, and hours uptime",
    function () {
      const missing = renderHost({
        host: { label: "Z", spec: "" },
        mode: "",
        as_of: null,
        serving: {},
        card: { status: { state: "WEIRD" }, resources: { thermal_state: "toasty" },
          gpu: {}, loaded: [], kpis: {}, slots: [] },
        routability: {
          switch_cost: { measured_seconds: null, measured_sessions: 1, configured_seconds: 300 },
        },
      }, undefined, undefined);
      expect(missing).toContain("WEIRD");
      expect(missing).toContain("band grey");
      expect(missing).toContain("no model");
      expect(missing).toContain("idle");
      expect(missing).toContain("toasty");
      expect(missing).toContain("never");
      expect(missing).toContain("not enough history yet");
      expect(missing).toContain("no slot data");
      expect(missing).toContain("configured 300 s");
      expect(missing).toContain("need 3");
      expect(missing).toContain(">OFF</span>");

      const hours = renderHost(host({
        card: { ...host().card,
          resources: { thermal_state: "critical" },
          kpis: { requests: 0, tokens: 0, started_at: NOW - 8000, last_served_at: null },
          slots: [] },
        routability: {
          switch_cost: { measured_seconds: undefined, measured_sessions: 0, configured_seconds: 9 },
          session: {
            started_at: NOW - 200, first_request_after_min: 2, any_host_routable_after_min: 2,
          },
        },
      }), "24h", "");
      expect(hours).toContain("Critical");
      expect(hours).toContain("gfill err");
      expect(hours).toContain("2h");
      expect(hours).toContain("last served");
      expect(hours).toContain("2 min");
      expect(hours).toContain("configured 9 s");
    });

  it("renders ATTESTING/STALE/OFF, load-error fallbacks, 10-character targets, and payout-free empty tables",
    function () {
      expect(renderHost(host({ card: { ...host().card,
        status: { state: "ATTESTING", tone: "amber", detail: "" } } }), "24h", ""))
        .toContain("ATTESTING — trust re-attestation");
      expect(renderHost(host({ card: { ...host().card,
        status: { state: "STALE", tone: "red", detail: "old" } } }), "24h", ""))
        .toContain("STALE — daemon state not fresh");
      expect(renderHost(host({ card: { ...host().card, status: null } }), "24h", ""))
        .toContain("OFF — no daemon snapshot");
      const load = renderHost(host({ card: { ...host().card, last_model_load_error: { recent: false } } }),
        "24h", "");
      expect(load).toContain("load error: load failed");
      expect(load).not.toMatch(/class="band-sub err">load error/);
      const ten = "1234567890";
      const eleven = "12345678901";
      expect(head(renderHost(host({ card: { ...host().card, manager: {
        mode: "LIVE", fresh: true, current_model: "gemma", target_model: ten } } }), "24h", "")))
        .toContain(">" + ten + "</span>");
      expect(head(renderHost(host({ card: { ...host().card, manager: {
        mode: "LIVE", fresh: true, current_model: "gemma", target_model: eleven } } }), "24h", "")))
        .toContain(">" + eleven.slice(0, 9) + "…</span>");
    });

  it("escapes every remote string in text and attributes, including ampersand quote and backtick",
    function () {
      const raw = "&<>\"'`";
      const html = renderHost(host({
        host: { label: raw, spec: raw },
        current_model: raw,
        card: { ...host().card, status: { state: "TRUSTED", tone: "amber", detail: raw },
          last_model_load_error: { model: raw, message: raw, at: NOW, recent: true } },
        recent_decisions: [{
          observed_at: NOW, current_model: raw, target_model: raw,
          action: "SWITCH", reason: raw, error: raw, executed: false,
        }],
        recent_earnings: [{ created_at: NOW, model: raw, completion_tokens: 1, micro_usd: 0 }],
        routability: {
          trust_level: raw, trust_reason: raw,
          models: [{ model: raw, advertised: false, warm: false, routable_providers: 0,
            last_served_at: null, installed: false }],
        },
      }), "24h", "");
      expect(html).toContain("&amp;");
      expect(html).toContain("&lt;");
      expect(html).toContain("&gt;");
      expect(html).toContain("&quot;");
      expect(html).toContain("&#39;");
      expect(html).toContain("&#96;");
      expect(html).not.toContain("onerror=");
      expect(html).toContain("data-host=\"&amp;&lt;&gt;&quot;&#39;&#96;\"");
    });

  it("isolates a null host, defaults error-card text, and still renders a card that has both error and payload",
    function () {
      expect(renderHosts()).toBe("");
      const mixed = renderHosts([host({ host: { label: "ok", spec: "" } }), null], "24h");
      expect(mixed).toContain("data-host=\"ok\"");
      expect(mixed).toContain("data-host=\"host\"");
      expect(mixed).toContain("OFF — host error");
      expect(errorCard({}, { toString: function () { return "fallback"; } })).toContain("fallback");
      expect(errorCard({ host: {} })).toContain("error");
      expect(errorCard({ host: { label: "Z" }, error: "" }, null)).toContain("error");
      const withCard = renderHost(host({ error: "ignored" }), "24h", "");
      expect(withCard).toContain("badge proposed");
      expect(withCard).toContain("KEEP");
      expect(withCard).not.toContain("ignored");
    });

  it("shows a decision without an error span and a SWITCH with no target as KEEP", function () {
    const html = renderHost(host({
      recent_decisions: [{
        observed_at: NOW, current_model: "gemma", target_model: "llama",
        action: "SWITCH", reason: "ranks", executed: false,
      }],
    }), "24h", "");
    expect(html).not.toMatch(/Recent decisions[\s\S]*class="err"/);
    expect(head(renderHost(host({
      recent_decisions: [{ action: "SWITCH", executed: false }],
    }), "24h", ""))).toContain(">KEEP</span>");
  });

  it("fills empty card fields, host identity, and routability from defaults", function () {
    const html = renderHost({
      mode: "LIVE",
      current_model: "gemma",
      as_of: NOW - 30,
      serving: { "24h": { idle: 100 } },
      card: { status: { state: "OFF", tone: "grey", detail: "" } },
    }, "24h", "");
    expect(html).toContain("data-host=\"host\"");
    expect(html).toContain(">OFF</span>");
    expect(html).toContain("OFF — no daemon snapshot");
    expect(html).toContain("none");
    expect(html).toContain("no slot data");
    expect(html).toContain("trust: unknown");
    expect(html).toContain("no probe data yet");
    expect(html).toContain("no session data");
    const noCard = renderHost({ host: { label: "M3", spec: "x" }, mode: "OBSERVE" }, "24h", "");
    expect(noCard).toContain("data-host=\"M3\"");
    expect(noCard).toContain("OFF — no daemon snapshot");
    expect(noCard).toContain("none");
  });
});
