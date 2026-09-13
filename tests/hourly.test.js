import { describe, expect, it } from "vitest";

import { hourlySection } from "../fleet/static/hourly.js";

describe("hourly job rendering", function () {
  it("shows one letter or dot per portion and aligns serving versus idle", function () {
    const html = hourlySection({ hourly_jobs: {
      legend: [{ letter: "G", model: "gemma" }],
      rows: [{ hour: 0, jobs: 2, portions: ["gemma", null],
               serving_percentage: 50, idle_percentage: 50 }],
    } });

    expect(html).toContain(">G</span>=gemma");
    expect(html).toContain('<span class="m0">G</span><span class="gap">.</span>' +
      " ".repeat(38) + "    50% / 50%");
  });

  it("keeps an empty current hour without inventing an idle portion", function () {
    const html = hourlySection({ hourly_jobs: {
      legend: [],
      rows: [{ hour: 0, jobs: 0, portions: [], serving_percentage: 0, idle_percentage: 0 }],
    } });

    expect(html).not.toContain("Legend:");
    expect(html).toContain("0% / 0%");
    expect(hourlySection({})).toContain("Serving / idle");
  });

  it("does not stop dashboard rendering for a cached legacy row", function () {
    const html = hourlySection({ hourly_jobs: {
      legend: [{ letter: "G", model: "gemma" }],
      rows: [{ hour: 0, jobs: 2, counts: { gemma: 2 } }],
    } });

    expect(html).toContain(" ".repeat(40) + "    0% / 0%");
  });

  it("clamps a long portions array so the bar cannot throw", function () {
    const portions = [];
    for (let i = 0; i < 41; i++) portions.push("gemma");
    const html = hourlySection({ hourly_jobs: {
      legend: [{ letter: "G", model: "gemma" }],
      rows: [{ hour: 0, jobs: 41, portions: portions, serving_percentage: 100, idle_percentage: 0 }],
    } });
    expect(html).toContain("data-fold=\"hourly\"");
    expect(html).toContain("payout-bearing 90-second portion");
    // legend letter plus 40 bar cells; a 41st portion would add one more G
    expect(html.match(/class="m0">G</g)).toHaveLength(41);
  });

  it("prints the date once, then time-only, and escapes legend models", function () {
    const html = hourlySection({ hourly_jobs: {
      legend: [{ letter: "X", model: "a&b<c>" }],
      rows: [
        { hour: 1_700_000_000, jobs: 1, portions: [null], serving_percentage: 0, idle_percentage: 0 },
        { hour: 1_700_003_600, jobs: 2, portions: [], serving_percentage: undefined, idle_percentage: undefined },
      ],
    } });
    expect(html).toContain("=a&amp;b&lt;c&gt;");
    expect(html).not.toContain("a&b<c>");
    const lines = html.replace(/.*<pre class="hourly">/, "").replace(/<\/pre>.*/, "").split("\n");
    const data = lines.filter(function (l) { return l.indexOf("Legend") === -1 && l.indexOf("Time") === -1; });
    expect(data[0]).toMatch(/\d{4}-\d{2}-\d{2}/);
    expect(data[1]).not.toMatch(/\d{4}-\d{2}-\d{2}/);
  });

  it("renders rows when legend is omitted", function () {
    const html = hourlySection({ hourly_jobs: {
      rows: [{ hour: 0, jobs: 0, portions: [], serving_percentage: 0, idle_percentage: 0 }],
    } });
    expect(html).not.toContain("Legend:");
    expect(html).toContain("0% / 0%");
  });
});
