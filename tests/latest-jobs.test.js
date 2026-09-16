import { describe, expect, it } from "vitest";
import { renderHost } from "../fleet/static/host.js";

describe("last five jobs", () => {
  it("renders five newest payouts below hourly, with precise dollars and unavailable TPS", () => {
    const earnings = Array.from({ length: 7 }, (_, i) => ({
      created_at: Date.now() / 1000 - i * 60, model: `model<${i}>`,
      completion_tokens: 10 + i, micro_usd: i,
    }));
    const html = renderHost({ recent_earnings: earnings }, "24h", "HOURLY_PANEL");
    const start = html.indexOf('data-fold="latest-jobs"');
    const panel = html.slice(start, html.indexOf("</details>", start));
    expect(start).toBeGreaterThan(html.indexOf("HOURLY_PANEL"));
    expect(panel.match(/<tr><td>/g)).toHaveLength(5);
    expect(panel).toContain("model&lt;4&gt;");
    expect(panel).not.toContain("model&lt;5&gt;");
    expect(panel).toContain("$0.000000");
    expect(panel).toContain("$0.000001");
    expect(panel).toContain("TPS is unavailable");
    expect(panel).toContain("</td><td>—</td>");
    expect(panel).toContain('class="scroll table-scroll"');
    expect(panel).toContain('tabindex="0"');
    expect(panel).toContain('aria-label="Last 5 jobs"');
  });
  it("handles missing job data", () => {
    expect(renderHost({})).toContain("No jobs recorded yet");
  });
});
