const TD = "</td><td>";
const TR = "<tr><td>";
const FOLD_SEL = "details[data-fold]";
const SCROLL_SEL = "[data-scroll]";
const SERVING_WINDOW_ID = "serving-window";

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;" };
export function esc(v) {
  return v === null || v === undefined ? "" : String(v).replaceAll(/[&<>"'`]/g, (c) => ESC[c]);
}
function num(v, digits) { return v === null || v === undefined ? "–" : Number(v).toFixed(digits); }

export function mergeDemand(hosts) {
  const byModel = new Map();
  (hosts || []).forEach(function (h) {
    (h.demand || []).forEach(function (r) {
      const key = (h.host?.label || "") + ":" + r.model;
      const seen = byModel.get(key);
      if (!seen || (r.observed_at || 0) > (seen.observed_at || 0)) byModel.set(key, { ...r, host_label: h.host?.label || "" });
    });
  });
  return Array.from(byModel.values()).sort(function (a, b) { return (b.score || 0) - (a.score || 0); });
}

export function renderDemand(rows, hosts) {
  if (!rows?.length) return '<tr><td colspan="7"><i>no fresh manager scores yet</i></td></tr>';
  const current = (hosts || []).map(function (h) {
    return { model: h.current_model, label: h.host?.label };
  }).filter(function (c) { return c.model && c.label; });
  return rows.map(function (r) {
    const marks = current.filter(function (c) { return c.model === r.model; })
      .map(function (c) { return c.label; });
    const model = esc(r.model) + (marks.length ? " · " + marks.map(esc).join(", ") : "");
    return TR + esc(r.host_label) + TD + model + TD + num(r.pressure, 2) + TD +
      num(r.average_pressure, 2) + TD + num(r.blended_usd_per_million, 4) + TD +
      num(r.weight, 2) + "</td><td><b>" + num(r.score, 3) + "</b></td></tr>";
  }).join("");
}

export function captureUiState(cardEls) {
  return Array.from(cardEls).map(function (el) {
    const open = [];
    el.querySelectorAll(FOLD_SEL).forEach(function (d) {
      if (d.open) open.push(d.dataset.fold);
    });
    const scrolls = {};
    el.querySelectorAll(SCROLL_SEL).forEach(function (n) {
      scrolls[n.dataset.scroll] = n.scrollTop;
    });
    return { host: el.dataset.host, open: open, scrolls: scrolls };
  });
}

export function restoreUiState(cardEls, snap) {
  const byHost = {};
  (snap || []).forEach(function (s) { byHost[s.host] = s; });
  Array.from(cardEls).forEach(function (el) {
    const st = byHost[el.dataset.host];
    if (!st) return;
    el.querySelectorAll(FOLD_SEL).forEach(function (d) {
      d.open = st.open.includes(d.dataset.fold);
    });
    el.querySelectorAll(SCROLL_SEL).forEach(function (n) {
      const k = n.dataset.scroll;
      if (st.scrolls[k] !== undefined) n.scrollTop = st.scrolls[k];
    });
  });
}

function closest(el, sel) {
  return typeof el.closest === "function" ? el.closest(sel) : null;
}

function outsideHosts(active, hostsRoot) {
  return hostsRoot && typeof hostsRoot.contains === "function" && !hostsRoot.contains(active);
}

export function captureFocus(active, hostsRoot) {
  if (!active) return null;
  if (active.id === SERVING_WINDOW_ID) return { id: SERVING_WINDOW_ID };
  if (outsideHosts(active, hostsRoot)) return null;
  const card = closest(active, ".card");
  const fold = closest(active, FOLD_SEL);
  return {
    host: card?.dataset.host ?? null,
    id: active.id || "",
    fold: fold?.dataset.fold || "",
    tag: active.tagName || "",
  };
}

function cardByHost(root, host) {
  const cards = root.querySelectorAll?.(".card") || [];
  for (const card of cards) {
    if (card.dataset.host === host) return card;
  }
  return null;
}

function query(root, sel) {
  return root?.querySelector?.(sel) || null;
}

function focusEl(el) {
  el?.focus?.();
}

function restoreServingFocus(doc) {
  focusEl(doc.getElementById(SERVING_WINDOW_ID));
}

function elementToFocus(doc, snap) {
  const root = (snap.host ? cardByHost(doc, snap.host) : null) || doc;
  const byId = snap.id ? query(root, "#" + snap.id) : null;
  if (byId) return byId;
  if (snap.fold && snap.tag === "SUMMARY") {
    return query(query(root, 'details[data-fold="' + snap.fold + '"]'), "summary");
  }
  return null;
}

export function restoreFocus(doc, snap) {
  if (!snap || !doc) return;
  if (snap.id === SERVING_WINDOW_ID && doc.getElementById) {
    restoreServingFocus(doc);
    return;
  }
  focusEl(elementToFocus(doc, snap));
}

export function makeRefreshGate() {
  let seq = 0;
  return {
    begin: function () { seq += 1; return seq; },
    isCurrent: function (token) { return token === seq; },
  };
}
