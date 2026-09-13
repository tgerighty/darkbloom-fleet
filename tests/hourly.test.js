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
  });
});
