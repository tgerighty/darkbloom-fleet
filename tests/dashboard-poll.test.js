import { afterEach, describe, expect, it, vi } from "vitest";

import {
  boot, cardStub, deferredFetch, fold, host, okFetch, scroller,
} from "./dashboard-harness.js";

function jsonOk(payload) {
  return { ok: true, status: 200, json: async function () { return payload; } };
}

afterEach(function () {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.resetModules();
});

describe("dashboard poll and redraw", function () {
  it("removes event handlers and unsafe URI attributes", async function () {
    const removed = [];
    const node = {
      attributes: [{ name: "onclick", value: "run()" }, { name: "href", value: " javascript:run()" }],
      removeAttribute: function (name) { removed.push(name); },
    };
    await boot({ fetch: okFetch({ hosts: [host("M3")] }), parsedNodes: [node] });
    expect(removed).toEqual(["onclick", "href", "onclick", "href"]);
  });

  it("renders both hosts, hourly rows, KEEP under OBSERVE, and restores fold scroll and window focus",
    async function () {
      const foldsBefore = [fold("trust", true), fold("hourly", false)];
      const scrollsBefore = [scroller("payouts", 80)];
      const foldsAfter = [fold("trust", false), fold("hourly", false)];
      const scrollsAfter = [scroller("payouts", 0)];
      const ctx = await boot({
        fetch: okFetch({ hosts: [
          host("M3"),
          host("M1", { mode: "LIVE",
            recent_decisions: [{ action: "SWITCH", target_model: "llama", executed: false }] }),
        ] }),
        before: [cardStub("M3", foldsBefore, scrollsBefore)],
        after: [cardStub("M3", foldsAfter, scrollsAfter)],
        active: { id: "serving-window", focus: vi.fn() },
      });
      const html = ctx.hosts.html();
      expect(html).toContain("data-host=\"M3\"");
      expect(html).toContain("data-host=\"M1\"");
      expect(html).toContain(">OBSERVE</span>");
      expect(html).toContain(">LIVE</span>");
      expect(html).toContain(">KEEP</span>");
      expect(html).toContain(">llama</span>");
      expect(html).toContain("payout-bearing 90-second portion");
      expect(ctx.demand.html).toContain("gemma · M3");
      expect(ctx.subtitle.textContent).toMatch(/^2 hosts · refreshed /);
      expect(ctx.hosts.toggle).toHaveBeenCalledWith("stale-poll", false);
      expect(foldsAfter[0].open).toBe(true);
      expect(scrollsAfter[0].scrollTop).toBe(80);
      expect(ctx.servingEl.focus).toHaveBeenCalled();
      expect(ctx.tick.ms).toBe(60000);
    });

  it("keeps host 1 when host 2 throws", async function () {
    const ctx = await boot({ fetch: okFetch({ hosts: [
      host("M3"),
      host("bad", { card: { ...host("bad").card, slots: 1 } }),
    ] }) });
    expect(ctx.hosts.html()).toContain("data-host=\"M3\"");
    expect(ctx.hosts.html()).toContain("data-host=\"bad\"");
    expect(ctx.hosts.html()).toContain("band red");
    expect(ctx.hosts.html()).toContain("OFF — host error");
  });

  it("keeps last data on a failed poll and escapes the error, including a zero-epoch last-good stamp",
    async function () {
      const t0 = 1_700_000_000_000;
      const fetchFn = vi.fn();
      fetchFn.mockResolvedValueOnce(jsonOk({ hosts: [host("M3")] }));
      fetchFn.mockRejectedValueOnce(new Error("<img src=x>"));
      const ctx = await boot({ fetch: fetchFn, now: t0 });
      expect(ctx.hosts.html()).toContain("data-host=\"M3\"");
      Date.now.mockReturnValue(t0 + 30_000);
      await ctx.tick();
      expect(ctx.hosts.html()).toContain("data-host=\"M3\"");
      expect(ctx.hosts.toggle).toHaveBeenCalledWith("stale-poll", true);
      expect(ctx.subtitle.innerHTML).toContain("&lt;img src=x&gt;");
      expect(ctx.subtitle.innerHTML).toContain("30s ago");
      expect(ctx.subtitle.innerHTML).not.toContain("<img src=x>");

      const zero = vi.fn();
      zero.mockResolvedValueOnce(jsonOk({ hosts: [host("M3")] }));
      zero.mockRejectedValueOnce(new Error("down"));
      const aged = await boot({ fetch: zero, now: 0 });
      await aged.tick();
      expect(aged.hosts.html()).toContain("data-host=\"M3\"");
      expect(aged.subtitle.innerHTML).toContain("showing data from never");
    });

  it("does not render when the status payload is null", async function () {
    const ctx = await boot({ fetch: okFetch(null) });
    expect(ctx.hosts.html()).toBe("");
    expect(ctx.demand.html).toBe("");
  });

  it("shows a first-poll failure, then a singular host count after recovery", async function () {
    const fetchFn = vi.fn();
    fetchFn.mockRejectedValueOnce(new Error("down"));
    fetchFn.mockResolvedValueOnce(jsonOk({ hosts: [host("M3")] }));
    const ctx = await boot({ fetch: fetchFn });
    expect(ctx.hosts.html()).toBe("");
    expect(ctx.subtitle.innerHTML).toContain("status unavailable:");
    expect(ctx.subtitle.innerHTML).toContain("down");
    await ctx.tick();
    expect(ctx.subtitle.textContent).toMatch(/^1 host · refreshed /);
    expect(ctx.hosts.html()).toContain("data-host=\"M3\"");
  });

  it("ignores abort from a replaced poll and keeps the newer snapshot", async function () {
    const { fn, calls } = deferredFetch();
    fn.mockImplementation(function (_url, init) {
      return new Promise(function (resolve, reject) {
        if (init && init.signal) {
          init.signal.addEventListener("abort", function () {
            const err = new Error("aborted");
            err.name = "AbortError";
            reject(err);
          });
        }
        calls.push(resolve);
      });
    });
    const ctxPromise = boot({ fetch: fn });
    await vi.waitFor(function () { expect(calls.length).toBe(1); });
    calls[0](jsonOk({ hosts: [host("first")] }));
    const ctx = await ctxPromise;
    const aborted = ctx.tick();
    await vi.waitFor(function () { expect(calls.length).toBe(2); });
    const newer = ctx.tick();
    await vi.waitFor(function () { expect(calls.length).toBe(3); });
    await aborted;
    calls[2](jsonOk({ hosts: [host("fresh")] }));
    await newer;
    expect(ctx.hosts.html()).toContain("data-host=\"fresh\"");
    expect(ctx.hosts.html()).not.toContain("data-host=\"first\"");
  });

  it("does not apply a late payload when a newer poll already owns the gate", async function () {
    const { fn, calls } = deferredFetch();
    const ctxPromise = boot({ fetch: fn });
    await vi.waitFor(function () { expect(calls.length).toBe(1); });
    calls[0].resolve(jsonOk({ hosts: [host("first")] }));
    const ctx = await ctxPromise;
    const p1 = ctx.tick();
    await vi.waitFor(function () { expect(calls.length).toBe(2); });
    const p2 = ctx.tick();
    await vi.waitFor(function () { expect(calls.length).toBe(3); });
    calls[1].resolve(jsonOk({ hosts: [host("stale")] }));
    await p1;
    expect(ctx.hosts.html()).toContain("data-host=\"first\"");
    expect(ctx.hosts.html()).not.toContain("data-host=\"stale\"");
    calls[2].resolve(jsonOk({ hosts: [host("fresh")] }));
    await p2;
    expect(ctx.hosts.html()).toContain("data-host=\"fresh\"");
  });

  it("throws HTTP errors, skips change redraw without data, then redraws with the selected window",
    async function () {
      const fetchFn = vi.fn();
      fetchFn.mockResolvedValueOnce({ ok: false, status: 503 });
      fetchFn.mockResolvedValueOnce(jsonOk({ hosts: [host("M3")] }));
      const ctx = await boot({ fetch: fetchFn, servingValue: "" });
      expect(ctx.subtitle.innerHTML).toContain("HTTP 503");
      ctx.servingEl.handler({ target: { value: "7h" } });
      expect(ctx.hosts.html()).toBe("");
      await ctx.tick();
      expect(ctx.hosts.html()).toContain("Serving · 7h");
      ctx.servingEl.handler({ target: { value: "1h" } });
      expect(ctx.hosts.html()).toContain("Serving · 1h");
    });

  it("uses a missing serving control, ages a stale poll, and escapes a render failure",
    async function () {
      const t0 = 1_700_000_000_000;
      const fetchFn = vi.fn();
      fetchFn.mockResolvedValueOnce(jsonOk({}));
      fetchFn.mockRejectedValueOnce(new Error("later"));
      fetchFn.mockRejectedValueOnce(new Error("later"));
      const ctx = await boot({ fetch: fetchFn, noServing: true, now: t0 });
      expect(ctx.servingEl).toBeNull();
      expect(ctx.subtitle.textContent).toMatch(/^0 hosts · refreshed /);
      Date.now.mockReturnValue(t0 + 120_000);
      await ctx.tick();
      expect(ctx.subtitle.innerHTML).toContain("2m ago");
      Date.now.mockReturnValue(t0 + 7_200_000);
      await ctx.tick();
      expect(ctx.subtitle.innerHTML).toContain("2h ago");

      const fail = await boot({
        fetch: okFetch({ hosts: [host("M3")] }),
        demandThrow: new Error("<b>bad</b>"),
      });
      expect(fail.subtitle.innerHTML).toContain("render failed:");
      expect(fail.subtitle.innerHTML).toContain("&lt;b&gt;bad&lt;/b&gt;");
      expect(fail.subtitle.innerHTML).not.toContain("<b>bad</b>");
    });

  it("drops a late failure from a replaced poll without changing last data", async function () {
    const { fn, calls } = deferredFetch();
    const ctxPromise = boot({ fetch: fn });
    await vi.waitFor(function () { expect(calls.length).toBe(1); });
    calls[0].resolve(jsonOk({ hosts: [host("first")] }));
    const ctx = await ctxPromise;
    const p1 = ctx.tick();
    await vi.waitFor(function () { expect(calls.length).toBe(2); });
    const p2 = ctx.tick();
    await vi.waitFor(function () { expect(calls.length).toBe(3); });
    calls[1].reject(new Error("late"));
    await p1;
    expect(ctx.hosts.html()).toContain("data-host=\"first\"");
    expect(ctx.subtitle.textContent).toMatch(/^1 host · refreshed /);
    calls[2].resolve(jsonOk({ hosts: [host("fresh")] }));
    await p2;
    expect(ctx.hosts.html()).toContain("data-host=\"fresh\"");
  });
});
