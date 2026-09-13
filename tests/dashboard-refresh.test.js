import { describe, expect, it } from "vitest";

import {
  captureFocus, captureUiState, esc, makeRefreshGate, mergeDemand, renderDemand,
  restoreFocus, restoreUiState,
} from "../fleet/static/ui.js";

function details(fold, open) {
  return {
    open: open,
    dataset: { fold: fold },
  };
}

function scroll(key, top) {
  return {
    scrollTop: top,
    dataset: { scroll: key },
  };
}

function cardEl(host, folds, scrolls) {
  return {
    dataset: { host: host },
    querySelectorAll: function (sel) {
      if (sel === "details[data-fold]") return folds;
      if (sel === "[data-scroll]") return scrolls;
      return [];
    },
  };
}

describe("refresh UI snapshot", function () {
  it("restores open folds and scroll positions by host", function () {
    const first = cardEl("M3", [details("trust", true), details("hourly", true)], [scroll("payouts", 80)]);
    const snap = captureUiState([first]);
    expect(snap).toEqual([{ host: "M3", open: ["trust", "hourly"], scrolls: { payouts: 80 } }]);

    const later = cardEl("M3", [details("trust", false), details("hourly", true), details("slots", false)],
      [scroll("payouts", 0), scroll("decisions", 0)]);
    restoreUiState([later], snap);
    expect(later.querySelectorAll("details[data-fold]")[0].open).toBe(true);
    expect(later.querySelectorAll("details[data-fold]")[1].open).toBe(true);
    expect(later.querySelectorAll("details[data-fold]")[2].open).toBe(false);
    expect(later.querySelectorAll("[data-scroll]")[0].scrollTop).toBe(80);
  });

  it("keeps serving-window focus across a rebuild", function () {
    const focused = { id: "serving-window", focus: function () { this.focused = true; } };
    const snap = captureFocus(focused, { contains: function () { return false; } });
    expect(snap).toEqual({ id: "serving-window" });
    const doc = {
      getElementById: function (id) { return id === "serving-window" ? focused : null; },
    };
    restoreFocus(doc, snap);
    expect(focused.focused).toBe(true);
  });

  it("restores summary focus inside a card", function () {
    const summary = { tagName: "SUMMARY", focus: function () { this.focused = true; } };
    const foldEl = {
      dataset: { fold: "trust" },
      querySelector: function (sel) { return sel === "summary" ? summary : null; },
    };
    const card = {
      dataset: { host: "M3" },
      querySelector: function (sel) { return String(sel).indexOf("trust") !== -1 ? foldEl : null; },
    };
    const active = {
      id: "",
      tagName: "SUMMARY",
      closest: function (sel) {
        if (sel === ".card") return card;
        if (sel === "details[data-fold]") return foldEl;
        return null;
      },
    };
    const snap = captureFocus(active, { contains: function () { return true; } });
    restoreFocus({ querySelectorAll: function () { return [card]; } }, snap);
    expect(summary.focused).toBe(true);
  });
});

describe("overlapping refresh gate", function () {
  it("rejects a late response after a newer refresh started", function () {
    const gate = makeRefreshGate();
    const first = gate.begin();
    const second = gate.begin();
    expect(gate.isCurrent(first)).toBe(false);
    expect(gate.isCurrent(second)).toBe(true);
  });
});

describe("demand merge and escape", function () {
  it("keeps the newest sample, sorts by ema, and escapes model marks", function () {
    expect(esc(null)).toBe("");
    expect(esc(undefined)).toBe("");
    expect(mergeDemand()).toEqual([]);
    const older = { model: "a", ema_score: 9, observed_at: 1, active_requests: 0,
      warm_providers: 0, pressure: null, output_usd_per_million: undefined, score: 0 };
    const newer = { ...older, ema_score: 1, observed_at: 5 };
    const rows = mergeDemand([
      { demand: [older] },
      { demand: [{ ...older, observed_at: 1 }, newer] },
      { demand: [{ model: "b", ema_score: 3, observed_at: 1 }] },
      { demand: undefined },
    ]);
    expect(rows[0].model).toBe("b");
    expect(rows[1].model).toBe("a");
    expect(rows[1].observed_at).toBe(5);
    const same = mergeDemand([{ demand: [
      { model: "a", observed_at: undefined, ema_score: 1 },
      { model: "a", observed_at: undefined, ema_score: 9 },
    ] }]);
    expect(same).toHaveLength(1);
    expect(same[0].ema_score).toBe(1);
    const unranked = mergeDemand([{ demand: [
      { model: "z", observed_at: 1 },
      { model: "a", observed_at: 1, ema_score: 0 },
    ] }]);
    expect(unranked.map(function (r) { return r.model; }).sort()).toEqual(["a", "z"]);
    const html = renderDemand(rows, [
      { current_model: "b", host: { label: "<m>" } },
      { current_model: "b", host: { label: "M1" } },
      { current_model: "", host: { label: "x" } },
      { current_model: "b", host: {} },
    ]);
    expect(html).toContain("&lt;m&gt;");
    expect(html).toContain("b · &lt;m&gt;, M1");
    expect(html).toContain("–");
    expect(renderDemand(rows)).toContain(">a</td>");
  });
});

describe("focus and restore edges", function () {
  it("skips missing hosts, missing scroll keys, and empty snapshots", function () {
    const folds = [details("trust", false)];
    const scrolls = [scroll("payouts", 0), scroll("decisions", 3)];
    const m1 = cardEl("M1", folds, scrolls);
    restoreUiState([m1], null);
    expect(folds[0].open).toBe(false);
    restoreUiState([m1], [{ host: "M3", open: ["trust"], scrolls: { payouts: 9 } }]);
    expect(folds[0].open).toBe(false);
    expect(scrolls[0].scrollTop).toBe(0);
    restoreUiState([m1], [{ host: "M1", open: ["trust"], scrolls: { payouts: 9 } }]);
    expect(folds[0].open).toBe(true);
    expect(scrolls[0].scrollTop).toBe(9);
    expect(scrolls[1].scrollTop).toBe(3);
  });

  it("captures nothing without an active node and ignores focus outside the host list", function () {
    expect(captureFocus(null, {})).toBeNull();
    expect(captureFocus({ id: "other" }, { contains: function () { return false; } })).toBeNull();
    const snap = captureFocus({ id: "x", tagName: "BUTTON" }, { contains: function () { return true; } });
    expect(snap).toEqual({ host: null, id: "x", fold: "", tag: "BUTTON" });
    const named = captureFocus({
      id: "",
      tagName: "DIV",
      closest: function (sel) {
        if (sel === ".card") return { dataset: { host: "M3" } };
        if (sel === "details[data-fold]") return { dataset: {} };
        return null;
      },
    }, { contains: function () { return true; } });
    expect(named).toEqual({ host: "M3", id: "", fold: "", tag: "DIV" });
    const untagged = captureFocus({
      id: "x",
      closest: function () { return null; },
    }, { contains: function () { return true; } });
    expect(untagged.tag).toBe("");
    expect(untagged.fold).toBe("");
  });

  it("restores by element id, no-ops on missing targets, and skips a serving window without getElementById",
    function () {
      const target = { focus: function () { this.focused = true; } };
      const card = {
        dataset: { host: "M3" },
        querySelector: function (sel) { return sel === "#fld" ? target : null; },
      };
      restoreFocus({ querySelectorAll: function () { return [card]; } },
        { host: "M3", id: "fld", fold: "", tag: "" });
      expect(target.focused).toBe(true);
      restoreFocus(null, { id: "serving-window" });
      restoreFocus({}, null);
      restoreFocus({}, { id: "serving-window" });
      restoreFocus({ querySelectorAll: function () { return []; } },
        { host: "nope", id: "", fold: "trust", tag: "DIV" });
      restoreFocus({ querySelectorAll: function () { return []; } },
        { host: "nope", id: "", fold: "trust", tag: "SUMMARY" });
      const hit = { focus: function () { this.focused = true; } };
      restoreFocus({
        querySelectorAll: function () {
          return [
            { dataset: { host: "other" } },
            { dataset: { host: "M3" }, querySelector: function (sel) { return sel === "#fld" ? hit : null; } },
          ];
        },
      }, { host: "M3", id: "fld", fold: "", tag: "" });
      expect(hit.focused).toBe(true);
      restoreFocus({}, { host: "M3", id: "", fold: "", tag: "" });
    });
});
