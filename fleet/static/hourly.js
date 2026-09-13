// Terminal-style "Jobs · hourly buckets" panel: one row per hour (newest
// first), a fixed-width 40-letter model distribution bar and per-model
// percentages. The API ships data only (fleet/hourly.py shapes the legend,
// the range share and the per-hour counts); everything here is rendering.
import { esc } from "./dashboard.js";

const BAR_WIDTH = 40;
const TIME_W = 16;
const JOBS_W = 4;
const PCT_W = 3;
const SLOTS = 8;          // colour classes m0..m7, validated for light/dark
const SPC = " ";
const GAP = "  ";
const COL_GAP = "    ";
const NL = "\n";
const FOLD = '<details class="fold" open><summary>Jobs · hourly buckets · 24 h</summary>';
const EMPTY = { legend: [], range_share: {}, rows: [] };

function span(slot, text) {
  return '<span class="m' + (slot % SLOTS) + '">' + text + "</span>";
}

function two(n) {
  return String(n).padStart(2, "0");
}

function stampParts(epoch) {
  const d = new Date(epoch * 1000);
  return { date: d.getFullYear() + "-" + two(d.getMonth() + 1) + "-" + two(d.getDate()),
           time: two(d.getHours()) + ":" + two(d.getMinutes()) };
}

function stampField(parts, prevDate) {
  // The date is printed only when it changes: the first row, then midnight.
  if (parts.date === prevDate) return SPC.repeat(TIME_W - parts.time.length) + parts.time;
  return parts.date + SPC + parts.time;
}

function legendLine(legend) {
  const items = legend.map(function (e) { return span(e.slot, e.letter) + "=" + esc(e.model); });
  return "Legend: " + items.join(GAP);
}

function rangeLine(legend, share) {
  const items = legend.map(function (e) {
    return span(e.slot, e.letter) + SPC + (share?.[e.model] ?? 0) + "%";
  });
  return "Range share: " + items.join(GAP);
}

function headerLine() {
  return "Time".padEnd(TIME_W) + GAP + "Jobs".padStart(JOBS_W) + GAP +
    "Distribution".padEnd(BAR_WIDTH) + COL_GAP + "Percentages";
}

function barHtml(counts, jobs, legend) {
  // Biggest model's run first (ties keep legend order); each model gets
  // floor(40 x share) letters and the largest remainders fill up to exactly 40.
  const present = legend.filter(function (e) { return (counts[e.model] || 0) > 0; })
    .sort(function (a, b) { return counts[b.model] - counts[a.model]; });
  const raw = present.map(function (e) { return BAR_WIDTH * counts[e.model] / jobs; });
  const widths = raw.map(Math.floor);
  const byRemainder = raw.map(function (v, i) { return [v - Math.floor(v), i]; })
    .sort(function (a, b) { return b[0] - a[0]; })
    .map(function (pair) { return pair[1]; });
  const missing = BAR_WIDTH - widths.reduce(function (sum, w) { return sum + w; }, 0);
  for (let i = 0; i < missing; i++) widths[byRemainder[i]] += 1;
  return present.map(function (e, i) {
    return widths[i] ? span(e.slot, e.letter.repeat(widths[i])) : "";
  }).join("");
}

function pctHtml(counts, jobs, legend) {
  return legend.map(function (e) {
    return String(Math.round(100 * (counts[e.model] || 0) / jobs)).padStart(PCT_W) + "%";
  }).join("/");
}

function rowsHtml(rows, legend) {
  let prevDate = null;
  return rows.map(function (row) {
    const parts = stampParts(row.hour);
    const line = stampField(parts, prevDate) + GAP + String(row.jobs).padStart(JOBS_W) + GAP +
      barHtml(row.counts, row.jobs, legend) + COL_GAP + pctHtml(row.counts, row.jobs, legend);
    prevDate = parts.date;
    return line;
  }).join(NL);
}

export function hourlySection(s) {
  const h = s.hourly_jobs || EMPTY;
  const legend = (h.legend || []).map(function (e, i) {
    return { letter: e.letter, model: e.model, slot: i };
  });
  if (!legend.length) {
    return FOLD + '<div class="none">no attributed jobs in the last 24 h</div></details>';
  }
  const lines = [legendLine(legend), rangeLine(legend, h.range_share), headerLine(),
                 rowsHtml(h.rows || [], legend)];
  return FOLD + '<pre class="hourly">' + lines.join(NL) + "</pre></details>";
}
