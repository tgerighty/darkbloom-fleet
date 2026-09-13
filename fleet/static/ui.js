const TD = "</td><td>";
const TR = "<tr><td>";

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;" };
export function esc(v) {
  return v === null || v === undefined ? "" : String(v).replaceAll(/[&<>"'`]/g, (c) => ESC[c]);
}
function num(v, digits) { return v === null || v === undefined ? "–" : Number(v).toFixed(digits); }

export function mergeDemand(hosts) {
  const byModel = new Map();
  (hosts || []).forEach(function (h) {
    (h.demand || []).forEach(function (r) {
      const seen = byModel.get(r.model);
      if (!seen || (r.observed_at || 0) > (seen.observed_at || 0)) byModel.set(r.model, r);
    });
  });
  return Array.from(byModel.values()).sort(function (a, b) { return (b.ema_score || 0) - (a.ema_score || 0); });
}

export function renderDemand(rows, hosts) {
  if (!rows || !rows.length) return '<tr><td colspan="7"><i>no demand samples yet</i></td></tr>';
  const current = (hosts || []).map(function (h) {
    return { model: h.current_model, label: (h.host || {}).label };
  }).filter(function (c) { return c.model && c.label; });
  return rows.map(function (r) {
    const marks = current.filter(function (c) { return c.model === r.model; })
      .map(function (c) { return c.label; });
    const model = esc(r.model) + (marks.length ? " · " + marks.map(esc).join(", ") : "");
    return TR + model + TD + r.active_requests + TD + r.warm_providers + TD + num(r.pressure, 2) + TD +
      num(r.output_usd_per_million, 2) + TD + num(r.score, 3) + "</td><td><b>" + num(r.ema_score, 3) +
      "</b></td></tr>";
  }).join("");
}

export function captureUiState(cardEls) {
  return Array.from(cardEls).map(function (el) {
    const open = [];
    el.querySelectorAll("details[data-fold]").forEach(function (d) {
      if (d.open) open.push(d.getAttribute("data-fold"));
    });
    const scrolls = {};
    el.querySelectorAll("[data-scroll]").forEach(function (n) {
      scrolls[n.getAttribute("data-scroll")] = n.scrollTop;
    });
    return { host: el.getAttribute("data-host"), open: open, scrolls: scrolls };
  });
}

export function restoreUiState(cardEls, snap) {
  const byHost = {};
  (snap || []).forEach(function (s) { byHost[s.host] = s; });
  Array.from(cardEls).forEach(function (el) {
    const st = byHost[el.getAttribute("data-host")];
    if (!st) return;
    el.querySelectorAll("details[data-fold]").forEach(function (d) {
      d.open = st.open.indexOf(d.getAttribute("data-fold")) !== -1;
    });
    el.querySelectorAll("[data-scroll]").forEach(function (n) {
      const k = n.getAttribute("data-scroll");
      if (st.scrolls[k] !== undefined) n.scrollTop = st.scrolls[k];
    });
  });
}

export function captureFocus(active, hostsRoot) {
  if (!active) return null;
  if (active.id === "serving-window") return { id: "serving-window" };
  if (hostsRoot && typeof hostsRoot.contains === "function" && !hostsRoot.contains(active)) return null;
  const card = typeof active.closest === "function" ? active.closest(".card") : null;
  const fold = typeof active.closest === "function" ? active.closest("details[data-fold]") : null;
  return {
    host: card ? card.getAttribute("data-host") : null,
    id: active.id || "",
    fold: fold ? fold.getAttribute("data-fold") : "",
    tag: active.tagName || "",
  };
}

function cardByHost(root, host) {
  const cards = root.querySelectorAll ? root.querySelectorAll(".card") : [];
  for (let i = 0; i < cards.length; i++) {
    if (cards[i].getAttribute("data-host") === host) return cards[i];
  }
  return null;
}

export function restoreFocus(doc, snap) {
  if (!snap || !doc) return;
  if (snap.id === "serving-window" && doc.getElementById) {
    const serving = doc.getElementById("serving-window");
    if (serving && serving.focus) serving.focus();
    return;
  }
  const card = snap.host ? cardByHost(doc, snap.host) : null;
  const root = card || doc;
  let el = snap.id && root.querySelector ? root.querySelector("#" + snap.id) : null;
  if (!el && snap.fold && snap.tag === "SUMMARY" && root.querySelector) {
    const details = root.querySelector('details[data-fold="' + snap.fold + '"]');
    el = details && details.querySelector ? details.querySelector("summary") : null;
  }
  if (el && el.focus) el.focus();
}

export function makeRefreshGate() {
  let seq = 0;
  return {
    begin: function () { seq += 1; return seq; },
    isCurrent: function (token) { return token === seq; },
  };
}
