import { describe, expect, it } from "vitest";

import {
  captureFocus, captureUiState, makeRefreshGate, restoreFocus, restoreUiState,
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
