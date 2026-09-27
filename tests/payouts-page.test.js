import { describe, expect, it } from "vitest";
import { PAYOUT_INITIAL, payoutExpand, renderHost } from "../fleet/static/host.js";

function earnings(n) {
  return Array.from({ length: n }, (_, i) => ({
    created_at: 1_700_000_000 - i * 60,
    model: "m" + i,
    completion_tokens: i,
    micro_usd: i * 1000,
  }));
}

describe("payouts pagination", function () {
  it("shows an initial page and keeps the rest reachable via Show all", function () {
    payoutExpand.clear();
    const html = renderHost({
      host: { label: "M3", spec: "M" },
      recent_earnings: earnings(PAYOUT_INITIAL + 5),
      unattributed_recent: 2,
    }, "24h", "");
    const start = html.indexOf('data-fold="payouts"');
    const panel = html.slice(start, html.indexOf("</details>", start) + 10);
    expect(panel.match(/<tr><td>/g).length).toBe(PAYOUT_INITIAL);
    expect(panel).toContain('data-action="payouts-expand"');
    expect(panel).toContain("Show all " + (PAYOUT_INITIAL + 5));
    expect(panel).toContain("unattributed of last 50");
  });

  it("expands to the full history when the host is in payoutExpand", function () {
    payoutExpand.clear();
    payoutExpand.add("M3");
    const html = renderHost({
      host: { label: "M3", spec: "M" },
      recent_earnings: earnings(PAYOUT_INITIAL + 5),
      unattributed_recent: 2,
    }, "24h", "");
    const start = html.indexOf('data-fold="payouts"');
    const panel = html.slice(start, html.indexOf("</details>", start) + 10);
    expect(panel.match(/<tr><td>/g).length).toBe(PAYOUT_INITIAL + 5);
    expect(panel).toContain('data-action="payouts-collapse"');
    payoutExpand.clear();
  });
});
