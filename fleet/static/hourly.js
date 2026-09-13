// Terminal-style "Jobs · hourly buckets" panel: one row per hour (newest
// first), with one character per 90-second portion of the hour.
const BAR_WIDTH = 40;
const TIME_W = 16;
const JOBS_W = 4;
const SLOTS = 8;          // colour classes m0..m7, validated for light/dark
const SPC = " ";
const GAP = "  ";
const COL_GAP = "    ";
const NL = "\n";
const FOLD = '<details class="fold" open><summary>Jobs · hourly buckets · 24 h</summary>';
const EMPTY = { legend: [], rows: [] };

function esc(value) {
  return String(value).replaceAll(/[&<>]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[char]));
}

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

function headerLine() {
  return "Time".padEnd(TIME_W) + GAP + "Jobs".padStart(JOBS_W) + GAP +
    "Distribution".padEnd(BAR_WIDTH) + COL_GAP + "Serving / idle";
}

const DOT = '<span class="gap">.</span>';

function bucketHtml(row, legend) {
  const byModel = Object.fromEntries(legend.map(function (entry) { return [entry.model, entry]; }));
  const bar = row.portions.map(function (model) {
    return model ? span(byModel[model].slot, byModel[model].letter) : DOT;
  }).join("");
  return bar + SPC.repeat(BAR_WIDTH - row.portions.length) + COL_GAP +
    row.serving_percentage + "% / " + row.idle_percentage + "%";
}

function rowsHtml(rows, legend) {
  let prevDate = null;
  return rows.map(function (row) {
    const parts = stampParts(row.hour);
    const line = stampField(parts, prevDate) + GAP + String(row.jobs).padStart(JOBS_W) + GAP +
      bucketHtml(row, legend);
    prevDate = parts.date;
    return line;
  }).join(NL);
}

export function hourlySection(s) {
  const h = s.hourly_jobs || EMPTY;
  const legend = (h.legend || []).map(function (e, i) {
    return { letter: e.letter, model: e.model, slot: i };
  });
  const lines = legend.length ? [legendLine(legend), headerLine()] : [headerLine()];
  lines.push(rowsHtml(h.rows || [], legend));
  return FOLD + '<pre class="hourly">' + lines.join(NL) + "</pre></details>";
}
