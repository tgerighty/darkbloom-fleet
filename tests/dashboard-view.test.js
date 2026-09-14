import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { actionLabel, bandHtml, errorCard, renderHost, renderHosts } from "../fleet/static/host.js";
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
    const html = bandHtml(host({ recent_decisions: [{ ...SWITCH, payout_target_models: ["qwen", "oss"],
      payout_action: "KEEP", payout_reason: "insufficient payout evidence" }] }), host().card);
    expect(html).toContain("gemma");
    expect(html).toContain("idle");
    expect(html).toContain("would switch");
    expect(html).toContain("ranks first");
    expect(html).toContain("ssh fail");
    expect(html).toContain('class="band-sub err"');
    expect(html).toContain("payout shadow: qwen + oss · KEEP · insufficient payout evidence");
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

  it("shows a recent load error in the band and escapes untrusted text", function () {
    const html = bandHtml(host(), { ...host().card, last_model_load_error: {
      model: "<b>", message: "<img src=x>", at: 1_700_000_000, recent: true,
    } });
    expect(html).toContain("load error");
    expect(html).toMatch(/class="band-sub err">load error/);
    expect(html).toContain("&lt;b&gt;");
    expect(html).toContain("&lt;img src=x&gt;");
    expect(html).not.toContain("<b>");
    expect(html).not.toContain("<img src=x>");
    expect(bandHtml(host(), host().card)).not.toContain("load error");
  });

  it("shows installed status in the trust table and escapes model ids", function () {
    const html = renderHost(host({
      routability: {
        trust_level: "hardware",
        models: [
          { model: "<img src=x>", advertised: true, warm: false, routable_providers: 0,
            last_served_at: null, installed: true },
          { model: "gemma", advertised: false, warm: true, routable_providers: 1,
            last_served_at: null, installed: false },
          { model: "llama", advertised: false, warm: false, routable_providers: 0,
            last_served_at: null, installed: null },
        ],
      },
    }), "24h", "");
    expect(html).toContain("<th>installed</th>");
    expect(html).toContain("&lt;img src=x&gt;");
    expect(html).not.toContain("<img src=x>");
    expect(html).toContain("trust: hardware");
    expect(html).toMatch(/<td>yes<\/td><td>–<\/td><td>yes<\/td>/); // advertised, not warm, installed
    expect(html).toMatch(/<td>–<\/td><td>–<\/td><td>unknown<\/td>/); // installed unknown
    expect(html).not.toContain('class="chips"><span class="glabel">installed');
    expect(html).not.toContain("catalog");
  });

  it("shows an old load error without the fault class", function () {
    const html = bandHtml(host(), { ...host().card, last_model_load_error: {
      model: "gemma", message: "oom", at: 1, recent: false,
    } });
    expect(html).toContain("load error");
    expect(html).toContain("gemma");
    expect(html).toContain("oom");
    expect(html).not.toMatch(/class="band-sub err">load error/);
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

  it("escapes quotes in data-host attributes", function () {
    const label = 'x" onfocus="alert(1)" tabindex="1';
    const html = renderHost(host({ host: { label: label, spec: "" } }), "24h", "");
    expect(html).toContain("data-host=\"x&quot; onfocus=&quot;alert(1)&quot; tabindex=&quot;1\"");
    expect(html).not.toContain("onfocus=\"alert(1)\"");
    const err = errorCard({ host: { label: label }, error: "e" }, null);
    expect(err).toContain("data-host=\"x&quot; onfocus=&quot;alert(1)&quot; tabindex=&quot;1\"");
    expect(err).not.toContain("onfocus=\"alert(1)\"");
  });
});

describe("proposed-action indicator", function () {
  function head(html) {
    const start = html.indexOf("card-head");
    const band = html.indexOf('class="band');
    return html.slice(start, band);
  }

  it("shows KEEP under the mode badge when there is no switch proposal", function () {
    const html = renderHost(host(), "24h", "");
    const hdr = head(html);
    expect(hdr.indexOf("badge observe")).toBeLessThan(hdr.indexOf("badge proposed"));
    expect(hdr).toContain('role="status"');
    expect(hdr).toContain('title="KEEP"');
    expect(hdr).toContain('aria-label="KEEP"');
    expect(hdr).toContain(">KEEP</span>");
    expect(html).not.toContain("<button");
  });

  it("shows KEEP for a non-switch decision", function () {
    const html = renderHost(host({ recent_decisions: [{ ...SWITCH, action: "KEEP", target_model: "llama" }] }), "24h", "");
    expect(head(html)).toContain(">KEEP</span>");
    expect(head(html)).not.toContain("llama");
  });

  it("shows the proposed target for SWITCH and SWITCH_WHEN_IDLE", function () {
    const switched = renderHost(host({ recent_decisions: [SWITCH] }), "24h", "");
    expect(head(switched)).toContain(">llama</span>");
    expect(head(switched)).toContain('title="llama"');
    const idle = renderHost(host({ recent_decisions: [{ ...SWITCH, action: "SWITCH_WHEN_IDLE" }] }), "24h", "");
    expect(head(idle)).toContain(">llama</span>");
  });

  it("truncates a long target and keeps the full name in title and aria-label", function () {
    const target = "gemma-4-26b-qat-4bit";
    const html = renderHost(host({ recent_decisions: [{ ...SWITCH, target_model: target }] }), "24h", "");
    const hdr = head(html);
    expect(hdr).toContain(">" + target.slice(0, 9) + "…</span>");
    expect(hdr).toContain('title="' + target + '"');
    expect(hdr).toContain('aria-label="' + target + '"');
    expect(hdr).not.toContain(">" + target + "</span>");
  });

  it("escapes an untrusted proposed target in text and attributes", function () {
    const target = 'x"><img src=x onerror="alert(1)';
    const html = renderHost(host({ recent_decisions: [{ ...SWITCH, target_model: target }] }), "24h", "");
    const hdr = head(html);
    expect(hdr).toContain("title=\"x&quot;&gt;&lt;img src=x onerror=&quot;alert(1)\"");
    expect(hdr).toContain("aria-label=\"x&quot;&gt;&lt;img src=x onerror=&quot;alert(1)\"");
    expect(hdr).not.toContain("<img src=x");
    expect(hdr).not.toContain("onerror=\"alert(1)\"");
  });

  it("does not put the proposed indicator on an error card", function () {
    const html = renderHost({ host: { label: "M1", spec: "" }, mode: "OBSERVE", error: "timeout" }, "24h", "");
    expect(html).not.toContain("badge proposed");
    expect(html).not.toContain("head-flags");
  });

  it("gives the proposed badge the same size as LIVE/OBSERVE", function () {
    const page = readFileSync(new URL("../fleet/static/dashboard.html", import.meta.url), "utf8");
    const flags = page.match(/\.card-head \.head-flags \{[^}]+\}/)[0];
    const proposed = page.match(/\.badge\.proposed \{[^}]+\}/)[0];
    expect(flags).toContain("align-items: stretch");
    expect(flags).toContain("text-align: center");
    expect(proposed).not.toMatch(/font-size:|padding:/);
    expect(proposed).toContain("border: 1px solid");
  });

  it("keeps wide demand data and the hourly panel inside the mobile viewport", function () {
    const page = readFileSync(new URL("../fleet/static/dashboard.html", import.meta.url), "utf8");
    expect(page).toContain('<div class="table-scroll"><table>');
    expect(page).toMatch(/\.table-scroll \{[^}]*overflow-x: auto/);
    expect(page).toMatch(/\.table-scroll table \{[^}]*min-width: 42rem/);
    expect(page).toMatch(/\.card \{[^}]*min-width: 0/);
    expect(page).toMatch(/pre\.hourly \{[^}]*box-sizing: border-box/);
    expect(page).toMatch(/pre\.hourly \{[^}]*max-width: 100%/);
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
