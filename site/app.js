/* Sector Strength - static site.
   Reads JSON produced by analysis/build.py from ./data/ and renders three
   views with hash routing: #/ (overview), #/sector/KEY, #/picks, #/record,
   #/trades (My Trades: private trade log in Supabase, needs sign-in).
   Charts are hand-built SVG so the page has no dependencies. */
"use strict";

// ------------------------------------------------------------------ state
const state = {
  bench: "NIFTY500",
  group: "Sectoral",
  fnoOnly: false,
  sel: null,                 // highlighted sector on the RRG
  tail: 4,                   // RRG tail length in weeks
  pickSort: { key: "score", dir: -1 },
  memberSort: { key: "score", dir: -1 },
  aOnly: true,               // setups: A-grade only
  capital: 1000000,          // position sizing
  riskPct: 1,
  maxPos: 20,                // max % of capital in one stock
  pendingTrade: null,        // "I took this trade" waiting for sign-in
};
const cache = {};
const QUAD = ["Leading", "Weakening", "Lagging", "Improving"];
const LVAR = { Green: "--q-leading", Amber: "--q-weakening", Red: "--q-lagging" };
const QVAR = { Leading: "--q-leading", Weakening: "--q-weakening", Lagging: "--q-lagging", Improving: "--q-improving" };

function store(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* storage off */ } }
function recall(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
(function restore() {
  const b = recall("ss-bench"); if (b === "NIFTY500" || b === "NIFTY50") state.bench = b;
  const g = recall("ss-group"); if (g === "Sectoral" || g === "Thematic") state.group = g;
  state.fnoOnly = recall("ss-fno") === "1";
  state.aOnly = recall("ss-aonly") !== "0";
  const cap = parseFloat(recall("ss-capital")); if (cap > 0) state.capital = cap;
  const rp = parseFloat(recall("ss-risk")); if (rp > 0 && rp <= 10) state.riskPct = rp;
  const mp = parseFloat(recall("ss-maxpos")); if (mp > 0 && mp <= 100) state.maxPos = mp;
})();

async function load(name) {
  if (!cache[name]) {
    cache[name] = fetch(`data/${name}.json`, { cache: "no-cache" }).then((r) => {
      if (!r.ok) throw new Error(`${name}.json: HTTP ${r.status}`);
      return r.json();
    });
  }
  return cache[name];
}

// ------------------------------------------------------------------ helpers
function h(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "style") node.style.cssText = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}
const SVGNS = "http://www.w3.org/2000/svg";
function s(tag, attrs, ...kids) {
  const node = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null) node.setAttribute(k, v);
  for (const kid of kids.flat()) if (kid != null) node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return node;
}
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const isNum = (v) => typeof v === "number" && isFinite(v);
const fmtNum = (v, d = 0) => (isNum(v) ? v.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }) : "–");
const fmtPct = (v, d = 1, signed = true) => {
  if (!isNum(v)) return "–";
  if (Math.abs(v) < 0.5 * Math.pow(10, -d)) v = 0;          // no "-0.0%"
  return `${signed && v > 0 ? "+" : ""}${v.toFixed(d)}%`;
};
const sign = (v) => (isNum(v) ? (v >= 0.05 ? "pos" : v <= -0.05 ? "neg" : "") : "muted");
function fmtDate(iso, opts = { day: "numeric", month: "short", year: "numeric" }) {
  if (!iso) return "–";
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-IN", opts);
}
function fmtCompact(v) {
  if (!isNum(v)) return "–";
  if (Math.abs(v) >= 100000) return `${(v / 100000).toFixed(1)}L`;
  if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(1)}K`;
  return fmtNum(v);
}

function seg(label, options, current, onPick) {
  return h("div", { class: "filter" },
    h("span", { class: "filter-label" }, label),
    h("div", { class: "seg", role: "group", "aria-label": label },
      options.map(([value, text]) => h("button", {
        type: "button", "aria-pressed": String(value === current),
        onclick: () => onPick(value),
      }, text))));
}
function filtersRow(extra) {
  return h("div", { class: "filters" },
    seg("Benchmark", [["NIFTY500", "Nifty 500"], ["NIFTY50", "Nifty 50"]], state.bench, (v) => {
      state.bench = v; store("ss-bench", v); route();
    }),
    seg("Indices", [["Sectoral", "Sectoral"], ["Thematic", "Thematic"]], state.group, (v) => {
      state.group = v; state.sel = null; store("ss-group", v); route();
    }),
    extra || null);
}
function quadChip(q) {
  if (!q) return h("span", { class: "muted" }, "–");
  return h("span", { class: "q" }, h("i", { style: `background:var(${QVAR[q]})` }), q);
}
function meter(v) {
  const w = isNum(v) ? Math.max(0, Math.min(100, v)) : 0;
  return h("span", { class: "meter" },
    h("span", { class: "bar" }, h("b", { style: `width:${w}%` })),
    h("em", null, isNum(v) ? Math.round(v) : "–"));
}
function stat(k, v, d) {
  return h("div", { class: "stat" }, h("div", { class: "k" }, k), h("div", { class: "v" }, v), d ? h("div", { class: "d" }, d) : null);
}


// ------------------------------------------------------------------ results calendar flags
/* r = {date, days} from stocks.json "results"; days < 0 means already out */
function resultsFlag(r, compact) {
  if (!r || !isNum(r.days)) return null;
  const d = fmtDate(r.date, { day: "numeric", month: "short" });
  if (r.days >= 0 && r.days <= 7) return h("span", { class: "flag warn", title: `Quarterly results on ${fmtDate(r.date)}: a gap through the stop is possible` },
    r.days === 0 ? "Results today" : compact ? `Results ${d}` : `Results in ${r.days}d (${d})`);
  if (r.days < 0) return h("span", { class: "flag", title: `Results announced on ${fmtDate(r.date)}` }, `Results out ${d}`);
  return null;
}
const isResultsFlag = (f) => f.startsWith("Results");

// ------------------------------------------------------------------ chart: scales and ticks
function niceTicks(min, max, count = 4) {
  if (!isFinite(min) || !isFinite(max)) return [];
  if (min === max) { min -= 1; max += 1; }
  const span = max - min;
  const step0 = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const norm = step0 / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}
function monthTicks(dates, maxTicks) {
  const idx = [];
  for (let i = 1; i < dates.length; i++) if (dates[i].slice(5, 7) !== dates[i - 1].slice(5, 7)) idx.push(i);
  const every = Math.max(1, Math.ceil(idx.length / maxTicks));
  return idx.filter((_, k) => k % every === 0);
}
function onResize(node, fn) {
  let last = 0;
  const ro = new ResizeObserver(() => {
    const w = Math.round(node.clientWidth);
    if (w && w !== last) { last = w; fn(w); }
  });
  ro.observe(node);
}

/* Line or diverging-bar chart with a crosshair tooltip listing every series.
   cfg: { dates, series:[{name, values, color}], height, fmt, bars, zero } */
function timeChart(cfg) {
  const plot = h("div", { class: "plot" });
  const tip = h("div", { class: "tip", role: "status" });
  plot.append(tip);
  const fmt = cfg.fmt || ((v) => fmtNum(v, 0));

  function draw(W) {
    plot.querySelector("svg")?.remove();
    const H = cfg.height || 170;
    const m = { l: 46, r: 10, t: 8, b: 22 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const n = cfg.dates.length;
    let lo = Infinity, hi = -Infinity;
    for (const ser of cfg.series) for (const v of ser.values) if (isNum(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    if (cfg.bars || cfg.zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    if (cfg.domain) { lo = cfg.domain[0]; hi = cfg.domain[1]; }
    const pad = (hi - lo) * 0.06 || 1;
    if (!cfg.domain) { lo -= cfg.bars ? 0 : pad; hi += pad; }
    const x = (i) => m.l + (n <= 1 ? iw / 2 : (i / (n - 1)) * iw);
    const y = (v) => m.t + ih - ((v - lo) / (hi - lo)) * ih;

    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img",
      "aria-label": cfg.label || cfg.series.map((x) => x.name).join(", ") });
    for (const t of niceTicks(lo, hi, 4)) {
      svg.append(s("line", { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), stroke: css("--grid"), "stroke-width": 1 }));
      svg.append(s("text", { x: m.l - 6, y: y(t) + 4, "text-anchor": "end", class: "axis-text" }, (cfg.tickFmt || fmtCompact)(t)));
    }
    if (lo < 0 && hi > 0) svg.append(s("line", { x1: m.l, x2: W - m.r, y1: y(0), y2: y(0), stroke: css("--axis"), "stroke-width": 1 }));
    for (const i of monthTicks(cfg.dates, Math.max(3, Math.floor(iw / 70)))) {
      svg.append(s("text", { x: x(i), y: H - 6, "text-anchor": "middle", class: "axis-text" },
        fmtDate(cfg.dates[i], { month: "short" })));
    }
    if (cfg.bars) {
      const ser = cfg.series[0];
      const bw = Math.max(1, Math.min(24, iw / n - 1));
      ser.values.forEach((v, i) => {
        if (!isNum(v)) return;
        const y0 = y(0), y1 = y(v);
        svg.append(s("rect", { x: x(i) - bw / 2, y: Math.min(y0, y1), width: bw, height: Math.max(1, Math.abs(y1 - y0)),
          fill: v >= 0 ? css("--up") : css("--down") }));
      });
    } else {
      for (const ser of cfg.series) {
        let d = "", pen = false;
        ser.values.forEach((v, i) => {
          if (!isNum(v)) { pen = false; return; }
          d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`; pen = true;
        });
        svg.append(s("path", { d, fill: "none", stroke: ser.color, "stroke-width": ser.width || 2,
          "stroke-linejoin": "round", "stroke-linecap": "round", opacity: ser.opacity || 1 }));
      }
    }
    const cross = s("line", { y1: m.t, y2: m.t + ih, stroke: css("--axis"), "stroke-width": 1, visibility: "hidden" });
    const dots = cfg.bars ? [] : cfg.series.map((ser) => s("circle", { r: 4, fill: ser.color, stroke: css("--surface"), "stroke-width": 2, visibility: "hidden" }));
    svg.append(cross, ...dots);
    const hit = s("rect", { x: m.l, y: 0, width: iw, height: H, fill: "transparent", tabindex: 0 });
    svg.append(hit);

    function show(i) {
      i = Math.max(0, Math.min(n - 1, i));
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
      cfg.series.forEach((ser, k) => {
        if (!dots[k]) return;
        const v = ser.values[i];
        if (isNum(v)) { dots[k].setAttribute("cx", x(i)); dots[k].setAttribute("cy", y(v)); dots[k].setAttribute("visibility", "visible"); }
        else dots[k].setAttribute("visibility", "hidden");
      });
      tip.replaceChildren(h("div", { class: "t-date" }, fmtDate(cfg.dates[i])),
        ...(cfg.tipRows ? cfg.tipRows(i) : cfg.series.map((ser) => [ser.name, fmt(ser.values[i]), ser.color]))
          .map(([name, val, color]) => h("div", { class: "t-row" },
            h("span", null, color ? h("i", { class: "key", style: `background:${color}` }) : null, name), h("b", null, val))));
      tip.style.display = "block";
      const px = x(i), tw = tip.offsetWidth;
      tip.style.left = `${px + 12 + tw > W ? px - tw - 12 : px + 12}px`;
      tip.style.top = `${m.t}px`;
    }
    function hide() { cross.setAttribute("visibility", "hidden"); dots.forEach((d) => d.setAttribute("visibility", "hidden")); tip.style.display = "none"; }
    let cur = n - 1;
    hit.addEventListener("pointermove", (e) => {
      const r = svg.getBoundingClientRect();
      const px = ((e.clientX - r.left) / r.width) * W;
      cur = Math.round(((px - m.l) / iw) * (n - 1)); show(cur);
    });
    hit.addEventListener("pointerleave", hide);
    hit.addEventListener("focus", () => show(cur));
    hit.addEventListener("blur", hide);
    hit.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") { cur = Math.max(0, cur - 1); show(cur); e.preventDefault(); }
      if (e.key === "ArrowRight") { cur = Math.min(n - 1, cur + 1); show(cur); e.preventDefault(); }
    });
    plot.prepend(svg);
  }
  onResize(plot, draw);
  return plot;
}

function chartCard(title, note, chart, legend) {
  return h("div", { class: "chart" }, h("h3", null, title), h("p", null, note), chart, legend || null);
}
function lineLegend(items) {
  return h("div", { class: "legend" }, items.map(([name, color]) =>
    h("span", null, h("i", { class: "line", style: `background:${color}` }), name)));
}

// ------------------------------------------------------------------ chart: Relative Rotation Graph
function rrgChart(keys, tails, names, onPick) {
  const box = h("div", { class: "rrg-box" });
  const tip = h("div", { class: "tip", role: "status" });
  box.append(tip);

  function draw(W) {
    box.querySelector("svg")?.remove();
    const H = Math.round(W < 520 ? W * 1.05 : Math.min(W * 0.82, 560));
    const m = { l: 44, r: 14, t: 14, b: 30 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    // Scale to the recent part of the tails so the cluster near 100 stays
    // readable; older tail points outside the frame are clipped.
    let dx = 1, dy = 0.5;
    for (const k of keys) for (const p of (tails[k] || []).slice(-3)) {
      if (isNum(p.x)) dx = Math.max(dx, Math.abs(p.x - 100));
      if (isNum(p.y)) dy = Math.max(dy, Math.abs(p.y - 100));
    }
    dx *= 1.2; dy *= 1.25;
    const x = (v) => m.l + ((v - (100 - dx)) / (2 * dx)) * iw;
    const y = (v) => m.t + ih - ((v - (100 - dy)) / (2 * dy)) * ih;
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img",
      "aria-label": "Relative Rotation Graph: RS-Ratio across, RS-Momentum up. The ranking table lists every value." });
    const cx = x(100), cy = y(100);
    const clipId = `rrgclip${Math.random().toString(36).slice(2, 8)}`;
    svg.append(s("defs", null, s("clipPath", { id: clipId }, s("rect", { x: m.l, y: m.t, width: iw, height: ih }))));
    const quads = [
      ["Leading", cx, m.t, W - m.r - cx, cy - m.t, "end", W - m.r - 8, m.t + 16],
      ["Weakening", cx, cy, W - m.r - cx, m.t + ih - cy, "end", W - m.r - 8, m.t + ih - 8],
      ["Lagging", m.l, cy, cx - m.l, m.t + ih - cy, "start", m.l + 8, m.t + ih - 8],
      ["Improving", m.l, m.t, cx - m.l, cy - m.t, "start", m.l + 8, m.t + 16],
    ];
    for (const [q, qx, qy, qw, qh, anchor, tx, ty] of quads) {
      svg.append(s("rect", { x: qx, y: qy, width: Math.max(0, qw), height: Math.max(0, qh), fill: css(`${QVAR[q]}-wash`) }));
      svg.append(s("text", { x: tx, y: ty, "text-anchor": anchor, class: "rrg-qname" }, q));
    }
    svg.append(s("line", { x1: cx, x2: cx, y1: m.t, y2: m.t + ih, stroke: css("--axis") }));
    svg.append(s("line", { x1: m.l, x2: W - m.r, y1: cy, y2: cy, stroke: css("--axis") }));
    for (const t of niceTicks(100 - dx, 100 + dx, 5)) svg.append(s("text", { x: x(t), y: H - 10, "text-anchor": "middle", class: "axis-text" }, t.toFixed(t % 1 ? 1 : 0)));
    for (const t of niceTicks(100 - dy, 100 + dy, 4)) svg.append(s("text", { x: m.l - 6, y: y(t) + 4, "text-anchor": "end", class: "axis-text" }, t.toFixed(t % 1 ? 1 : 0)));
    svg.append(s("text", { x: W - m.r, y: cy - 6, "text-anchor": "end", class: "axis-text" }, "RS-Ratio"));
    svg.append(s("text", { x: cx + 6, y: m.t + 30, class: "axis-text" }, "RS-Momentum"));

    const labels = [];
    for (const k of keys) {
      const pts = (tails[k] || []).slice(-(state.tail + 1)).filter((p) => isNum(p.x) && isNum(p.y));
      if (!pts.length) continue;
      const head = pts[pts.length - 1];
      const q = head.x >= 100 ? (head.y >= 100 ? "Leading" : "Weakening") : (head.y >= 100 ? "Improving" : "Lagging");
      const col = css(QVAR[q]);
      const dim = state.sel && state.sel !== k;
      const g = s("g", { class: dim ? "dim" : null, tabindex: 0, role: "button", "aria-label": `${names[k]}: ${q}`, "clip-path": `url(#${clipId})` });
      g.append(s("path", { d: pts.map((p, i) => `${i ? "L" : "M"}${x(p.x).toFixed(1)},${y(p.y).toFixed(1)}`).join(""),
        fill: "none", stroke: col, "stroke-width": 1.5, opacity: 0.55, "stroke-linejoin": "round" }));
      pts.slice(0, -1).forEach((p) => g.append(s("circle", { cx: x(p.x), cy: y(p.y), r: 2, fill: col, opacity: 0.6 })));
      g.append(s("circle", { cx: x(head.x), cy: y(head.y), r: 5.5, fill: col, stroke: css("--surface"), "stroke-width": 2 }));
      g.append(s("circle", { cx: x(head.x), cy: y(head.y), r: 13, fill: "transparent" }));
      labels.push({ k, x: x(head.x), y: y(head.y), g, dim });
      const showTip = () => {
        tip.replaceChildren(
          h("div", { class: "t-date" }, `${names[k]} · week of ${fmtDate(head.date, { day: "numeric", month: "short" })}`),
          h("div", { class: "t-row" }, h("span", null, "Quadrant"), h("b", null, q)),
          h("div", { class: "t-row" }, h("span", null, "RS-Ratio"), h("b", null, head.x.toFixed(2))),
          h("div", { class: "t-row" }, h("span", null, "RS-Momentum"), h("b", null, head.y.toFixed(2))));
        tip.style.display = "block";
        const tw = tip.offsetWidth;
        tip.style.left = `${x(head.x) + 14 + tw > W ? x(head.x) - tw - 14 : x(head.x) + 14}px`;
        tip.style.top = `${Math.max(0, y(head.y) - 20)}px`;
      };
      g.addEventListener("pointerenter", showTip);
      g.addEventListener("focus", showTip);
      g.addEventListener("pointerleave", () => { tip.style.display = "none"; });
      g.addEventListener("blur", () => { tip.style.display = "none"; });
      g.addEventListener("click", () => onPick(k));
      g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(k); } });
      svg.append(g);
    }
    // Direct labels in a top layer. Try spots around each head at growing
    // distances; far spots get a thin leader line. Dots are obstacles too.
    const layer = s("g", null);
    svg.append(layer);
    const boxes = labels.map((L) => ({ x: L.x - 6, y: L.y - 6, w: 12, h: 12 }));
    const overlaps = (b) => boxes.some((o) => b.x < o.x + o.w && b.x + b.w > o.x && b.y < o.y + o.h && b.y + b.h > o.y);
    const inside = (b) => b.x >= m.l && b.x + b.w <= W - m.r && b.y >= m.t && b.y + b.h <= m.t + ih;
    labels.sort((a, b) => a.y - b.y);
    for (const L of labels) {
      const text = names[L.k], w = text.length * 6.2 + 4, hgt = 13;
      let best = null;
      for (const r of [9, 18, 30, 44]) {
        for (const [dx, dy] of [[1, 0], [-1, 0], [0, -1], [0, 1], [1, -1], [1, 1], [-1, -1], [-1, 1]]) {
          const ax = L.x + dx * r, ay = L.y + dy * r;
          const bx = dx > 0 ? ax : dx < 0 ? ax - w : ax - w / 2;
          const by = dy > 0 ? ay : dy < 0 ? ay - hgt : ay - hgt / 2;
          const b = { x: bx, y: by, w, h: hgt };
          if (inside(b) && !overlaps(b)) { best = { b, r, ax, ay }; break; }
        }
        if (best) break;
      }
      if (!best) continue;              // no room: the tooltip and table carry it
      boxes.push(best.b);
      const grp = s("g", { "data-key": L.k, class: L.dim ? "dim" : null });
      if (best.r > 9) grp.append(s("line", { x1: L.x, y1: L.y, x2: best.ax, y2: best.ay, stroke: css("--muted"), "stroke-width": 0.75 }));
      grp.append(s("text", { x: best.b.x + 2, y: best.b.y + hgt - 3, class: "rrg-label" }, text));
      layer.append(grp);
      L.g.labelNode = grp;
    }
    box.prepend(svg);
  }
  onResize(box, draw);
  return box;
}


// ------------------------------------------------------------------ market regime
function lightChip(l, big) {
  if (!l) return h("span", { class: "muted" }, "–");
  return h("span", { class: `light${big ? " big" : ""}` }, h("i", { style: `background:var(${LVAR[l]})` }), l);
}

/* One coloured cell per session: the light's history, with a hover tooltip. */
function regimeStrip(hist) {
  const plot = h("div", { class: "plot strip" });
  const tip = h("div", { class: "tip", role: "status" });
  plot.append(tip);
  const D = hist.dates, n = D.length;
  function draw(W) {
    plot.querySelector("svg")?.remove();
    const H = 46, m = { l: 0, r: 0, t: 4, b: 18 }, ih = H - m.t - m.b;
    const cw = W / n;
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img",
      "aria-label": `Regime light over the last ${n} sessions` });
    let i0 = 0;
    for (let i = 1; i <= n; i++) {        // merge runs of the same light into one rect
      if (i < n && hist.light[i] === hist.light[i0]) continue;
      const l = hist.light[i0];
      svg.append(s("rect", { x: i0 * cw, y: m.t, width: Math.max(1, (i - i0) * cw - (i < n ? 1 : 0)), height: ih,
        rx: 2, fill: l ? css(LVAR[l]) : css("--grid") }));
      i0 = i;
    }
    for (const i of monthTicks(D, Math.max(3, Math.floor(W / 70)))) {
      svg.append(s("text", { x: i * cw, y: H - 4, "text-anchor": "middle", class: "axis-text" }, fmtDate(D[i], { month: "short" })));
    }
    const cursor = s("rect", { y: m.t - 2, width: Math.max(2, cw), height: ih + 4, fill: "none", stroke: css("--ink"), "stroke-width": 1.5, visibility: "hidden", rx: 1 });
    const hit = s("rect", { x: 0, y: 0, width: W, height: H, fill: "transparent", tabindex: 0 });
    svg.append(cursor, hit);
    let cur = n - 1;
    const show = (i) => {
      i = Math.max(0, Math.min(n - 1, i)); cur = i;
      cursor.setAttribute("x", i * cw); cursor.setAttribute("visibility", "visible");
      tip.replaceChildren(h("div", { class: "t-date" }, fmtDate(D[i])),
        h("div", { class: "t-row" }, h("span", null, "Light"), h("b", null, hist.light[i] || "–")),
        h("div", { class: "t-row" }, h("span", null, "Checks passed"), h("b", null, isNum(hist.points[i]) ? `${hist.points[i]} of 6` : "–")));
      tip.style.display = "block";
      const px = i * cw, tw = tip.offsetWidth;
      tip.style.left = `${px + 12 + tw > W ? px - tw - 12 : px + 12}px`;
      tip.style.top = "-6px";
    };
    const hide = () => { cursor.setAttribute("visibility", "hidden"); tip.style.display = "none"; };
    hit.addEventListener("pointermove", (e) => { const r = svg.getBoundingClientRect(); show(Math.floor(((e.clientX - r.left) / r.width) * n)); });
    hit.addEventListener("pointerleave", hide);
    hit.addEventListener("focus", () => show(cur));
    hit.addEventListener("blur", hide);
    hit.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") { show(cur - 1); e.preventDefault(); }
      if (e.key === "ArrowRight") { show(cur + 1); e.preventDefault(); }
    });
    plot.prepend(svg);
  }
  onResize(plot, draw);
  return plot;
}


/* Market internals gauge: leading-ish breadth and momentum, -100..+100 */
function internalsBlock(rg) {
  const I = rg.internals;
  if (!I || !isNum(I.value)) return null;
  const v = I.value, prev = I.value_10d_ago;
  const word = v >= 40 ? "Strong" : v >= 10 ? "Improving" : v > -10 ? "Neutral" : v > -40 ? "Weakening" : "Weak";
  const trend = isNum(prev) ? (v > prev + 5 ? "rising" : v < prev - 5 ? "falling" : "flat") : null;
  const status = I.topping ? h("p", { class: "note bad" }, h("b", null, "Topping warning. "), "The index is stalling near its high while the A/D line, RSI and breadth weaken. This pattern came before the falls of Nov 2025 and Sep 2026, but also gave false alarms in 2025's rising market: tighten stops rather than sell everything.")
    : I.bottoming ? h("p", { class: "note good" }, h("b", null, "Bottoming signal. "), "Internals are improving while the index is still near its low. In April 2026 this came two weeks before the breadth thrust and a month before the light left Red.")
    : null;
  const bar = (x) => {
    const w = isNum(x) ? Math.min(50, Math.abs(x) / 2) : 0;
    return h("span", { class: "div-bar" }, h("i", { class: "zero" }),
      h("b", { style: `left:${x >= 0 ? 50 : 50 - w}%;width:${w}%;background:${x >= 0 ? css("--up") : css("--down")}` }));
  };
  const H = rg.history;
  return h("div", { class: "internals in-fold" },
    h("div", { class: "internals-head" },
      h("div", null, h("h3", null, "Market internals"),
        h("p", { class: "sub" }, "An earlier read than the light: breadth and momentum under the surface, from −100 to +100.")),
      h("div", { class: "gauge" }, h("b", { class: sign(v) }, `${v > 0 ? "+" : ""}${Math.round(v)}`),
        h("span", null, `${word}${trend ? `, ${trend}` : ""}`, isNum(prev) ? h("small", null, ` (${prev > 0 ? "+" : ""}${Math.round(prev)} ten sessions ago)`) : null))),
    status,
    h("div", { class: "parts" }, I.parts.map((p) => h("div", { class: "part-row" },
      h("span", { class: "part-label" }, p.label), bar(p.value), h("span", { class: `part-val ${sign(p.value)}` }, isNum(p.value) ? `${p.value > 0 ? "+" : ""}${Math.round(p.value)}` : "–")))),
    H.internals ? h("div", { class: "charts", style: "margin-top:12px" },
      chartCard("Nifty 500", "Daily close", timeChart({ dates: H.dates, height: 150, series: [{ name: "Nifty 500", values: H.n500, color: css("--ink-2") }], fmt: (x) => fmtNum(x, 2) })),
      chartCard("Internals gauge", "Above 0 = breadth and momentum improving. Watch for it turning while the index has not.",
        timeChart({ dates: H.dates, height: 150, domain: [-100, 100], zero: true, tickFmt: (x) => `${x}`, fmt: (x) => (isNum(x) ? `${x > 0 ? "+" : ""}${Math.round(x)}` : "–"),
          series: [{ name: "Internals", values: H.internals, color: css("--s1") }] }))) : null,
    h("p", { class: "note" }, I.last_topping || I.last_bottoming ? [`Last topping warning: ${I.last_topping ? fmtDate(I.last_topping) : "none"}. Last bottoming signal: ${I.last_bottoming ? fmtDate(I.last_bottoming) : "none"}. Every past warning and what followed: `, h("a", { href: "#/record" }, "track record"), "."] : null));
}

/* <details> that remembers whether the viewer left it open */
function fold(id, summary, ...content) {
  const open = recall(`ss-fold-${id}`) === "1";
  const d = h("details", { class: "fold", open: open || null }, h("summary", null, summary), h("div", { class: "fold-body" }, ...content));
  d.addEventListener("toggle", () => store(`ss-fold-${id}`, d.open ? "1" : "0"));
  return d;
}

/* Turning-point trackers: seller exhaustion (bottom) and distribution (top) */
function trackerCard(title, sub, stages, extra) {
  // current stage = the stage that fired most recently (ties: the higher one), if within 10 sessions;
  // a later stage-1 signal resets an older stage 2 (e.g. a failed exhaustion followed by new lows)
  let reached = 0, best = Infinity;
  stages.forEach((s, i) => { if (isNum(s.sessions_ago) && s.sessions_ago <= 10 && s.sessions_ago <= best) { best = s.sessions_ago; reached = i + 1; } });
  const recentStage = (s, i) => i < reached && isNum(s.sessions_ago) && s.sessions_ago <= 10 + (reached - 1 - i) * 10;
  const when = (s) => s.met_today ? "met today"
    : s.last_met ? `last met ${fmtDate(s.last_met, { day: "numeric", month: "short", year: s.sessions_ago > 200 ? "numeric" : undefined })}${isNum(s.sessions_ago) ? ` (${s.sessions_ago} sessions ago)` : ""}` : "not met yet";
  return h("div", { class: "tracker" },
    h("div", { class: "tracker-head" }, h("h3", null, title),
      h("span", { class: `stage-chip s${reached}` }, reached ? `Stage ${reached} of 3: ${stages[reached - 1].name}` : "No signal")),
    h("p", { class: "sub" }, sub),
    h("ol", { class: "stages" }, stages.map((s, i) => h("li", { class: s.met_today ? "on" : recentStage(s, i) ? "recent" : "off" },
      h("details", null,
        h("summary", null, h("span", { class: "dot", "aria-hidden": "true" }), h("b", null, `${i + 1}. ${s.name}`), h("span", { class: "when" }, when(s))),
        h("p", { class: "note", style: "margin:4px 0 4px" }, s.help),
        h("ul", { class: "conds" }, s.parts.map((p) => h("li", { class: p.ok ? "ok" : "no" },
          h("span", { class: "mark", "aria-hidden": "true" }, p.ok ? "✓" : "✕"), h("span", { class: "sr" }, p.ok ? "Yes: " : "No: "), p.label))))))),
    extra || null);
}
function trackersBlock(T) {
  if (!T) return null;
  const R = T.readings || {}, P = R.at_prior_low;
  const cmp = (label, now, then, fmt, better) => h("tr", null, h("td", { class: "l" }, label), h("td", null, fmt(now)), h("td", null, fmt(then)),
    h("td", { class: "l" }, isNum(now) && isNum(then) ? (better(now, then) ? h("span", { class: "pos" }, "better") : h("span", { class: "neg" }, "worse")) : "–"));
  const lowTable = P ? h("div", null,
    h("p", { class: "note", style: "margin:8px 0 4px" }, `Divergence check: today vs the earlier low on ${fmtDate(R.prior_low, { day: "numeric", month: "short" })}. Stage 2 needs a retest of that low with 3 of 4 readings better.`),
    h("div", { class: "table-scroll" }, h("table", { class: "static mini" },
      h("thead", null, h("tr", null, h("th", { class: "l" }, ""), h("th", null, "Now"), h("th", null, fmtDate(R.prior_low, { day: "numeric", month: "short" })), h("th", { class: "l" }, ""))),
      h("tbody", null,
        h("tr", null, h("td", { class: "l" }, "Nifty 500"), h("td", null, fmtNum(R.n500, 0)), h("td", null, fmtNum(P.n500, 0)),
          h("td", { class: "l muted" }, R.n500 <= P.n500 * 1.01 ? "retest or lower low" : "above that low")),
        cmp("Internals gauge", R.gauge, P.gauge, (v) => (isNum(v) ? Math.round(v) : "–"), (a, b) => a >= b + 10),
        cmp("% above 50-day", R.p50, P.p50, (v) => (isNum(v) ? `${Math.round(v)}%` : "–"), (a, b) => a > b),
        cmp("New 52-week lows", R.new_lows, P.new_lows, (v) => fmtNum(v), (a, b) => a < b),
        cmp("RSI (equal weight)", R.rsi, P.rsi, (v) => (isNum(v) ? Math.round(v) : "–"), (a, b) => a > b))))) : null;
  return h("div", { class: "trackers" },
    trackerCard("Seller exhaustion", "Finds bottoms: extreme selling, then breadth holding up while price makes a lower low, then confirmation.", T.bottom, lowTable),
    trackerCard("Distribution", "Finds tops: a stretched rally, then breadth weakening while price holds near the high, then the breakdown.", T.top,
      h("p", { class: "note" }, `Heavy-volume down days in the last 25 sessions: ${R.dist_days_25 ?? "–"} (5 is normal here; 7+ counts as distribution near a high). New 52-week highs today: ${R.new_highs ?? "–"}.`)));
}

function regimePanel(rg) {
  if (!rg || !rg.light) return null;
  const notes = [];
  if (rg.washout) notes.push(h("p", { class: "note" }, h("b", null, "Washout. "),
    `Only ${Math.round(rg.pct_above_50)}% of Nifty 500 stocks are above their 50-day average (since ${fmtDate(rg.washout_since, { day: "numeric", month: "short" })}). `,
    `Washouts often come before a recovery. The signal to watch is a breadth thrust: the share jumping from under 20% to over 50% within 15 sessions.`,
    rg.last_thrust ? ` The last one was on ${fmtDate(rg.last_thrust)}.` : ""));
  if (rg.thrust_active) notes.push(h("p", { class: "note good" }, h("b", null, "Breadth thrust. "),
    `The share of stocks above their 50-day average jumped from under 20% to over 50% within 15 sessions (${fmtDate(rg.last_thrust, { day: "numeric", month: "short" })}). This often marks the start of a new advance, before the light turns green.`));
  const I = rg.internals;
  return h("div", { class: "panel regime" },
    h("div", { class: "regime-head" },
      h("div", null, h("h2", null, "Market regime"),
        h("p", { class: "sub" }, `For positional buying. ${rg.points} of ${rg.max_points} checks pass · ${rg.light} since ${fmtDate(rg.light_since, { day: "numeric", month: "short" })}`)),
      lightChip(rg.light, true)),
    h("p", { class: "guidance" }, rg.guidance),
    trackersBlock(rg.turning),
    fold("checks", `Why the light is ${rg.light}: ${rg.points} of ${rg.max_points} checks pass`,
      h("ul", { class: "checks" }, rg.checks.map((c) => h("li", { class: c.ok ? "ok" : "no" },
        h("span", { class: "mark", "aria-hidden": "true" }, c.ok ? "✓" : "✕"), h("span", { class: "sr" }, c.ok ? "Yes: " : "No: "), c.label))),
      notes,
      h("div", { class: "chart", style: "margin-top:12px" },
        h("p", null, `The light over the last ${rg.history.dates.length} sessions. It uses a 5-session average of the checks with a buffer, so one or two mixed days don't flip it.`),
        regimeStrip(rg.history),
        h("div", { class: "legend" }, ["Green", "Amber", "Red"].map((l) => h("span", null, h("i", { style: `background:var(${LVAR[l]})` }), l))))),
    I && isNum(I.value) ? fold("internals", ["Market internals gauge: ", h("b", { class: sign(I.value) }, `${I.value > 0 ? "+" : ""}${Math.round(I.value)}`),
      isNum(I.value_10d_ago) ? ` (${I.value_10d_ago > 0 ? "+" : ""}${Math.round(I.value_10d_ago)} ten sessions ago)` : ""], internalsBlock(rg)) : null,
    h("p", { class: "note" }, "How the light, the warnings and the picks have done since 2025: ", h("a", { href: "#/record" }, "Track record"), "."));
}

// ------------------------------------------------------------------ views
async function viewOverview(app) {
  const [sec, br, st, rg, ld] = await Promise.all([load("sectors"), load("breadth"), load("stocks"), load("regime"), load("leaders")]);
  const B = sec.benchmarks[state.bench];
  const keys = sec.groups[state.group];
  const rows = keys.map((k) => ({ key: k, ...B.rows[k] })).sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99));
  const L = br.latest;

  const pick = (k) => { state.sel = state.sel === k ? null : k; route(); };

  // market sentence
  const pctMove = B.return_1m;
  const lede = h("p", { class: "lede" },
    `${B.name} closed at `, h("b", null, fmtNum(B.close, 2)), `, ${pctMove >= 0 ? "up" : "down"} `,
    h("b", null, `${Math.abs(pctMove).toFixed(1)}%`), " over the past month. ",
    isNum(L.pct_above_50) ? [h("b", null, `${Math.round(L.pct_above_50)}%`),
      ` of Nifty 500 stocks are above their 50-day average, ${L.pct_above_50 < L.pct_above_50_20d_ago ? "down" : "up"} from ${Math.round(L.pct_above_50_20d_ago)}% a month ago. `] : null,
    rows[0] ? [`${sec.names[rows[0].key]} leads the ${state.group.toLowerCase()} ranking.`] : null);

  // ranking table
  const table = h("table", null,
    h("thead", null, h("tr", null,
      h("th", { class: "l" }, "#"), h("th", { class: "l" }, "Index"), h("th", { class: "l" }, "Score"),
      h("th", { title: "Rank change vs a week ago" }, "Week"), h("th", null, "Excess 1M"),
      h("th", { class: "l" }, "Quadrant"), h("th", null, "Excess 3M"), h("th", null, "Breadth"))),
    h("tbody", null, rows.map((r) => {
      const moved = isNum(r.rank_1w_ago) && isNum(r.rank) ? r.rank_1w_ago - r.rank : null;
      return h("tr", { class: state.sel === r.key ? "sel" : null, tabindex: 0,
        onclick: () => { location.hash = `#/sector/${r.key}`; },
        onkeydown: (e) => { if (e.key === "Enter") location.hash = `#/sector/${r.key}`; },
        onmouseenter: () => highlight(r.key), onmouseleave: () => highlight(null) },
        h("td", { class: "l muted" }, r.rank ?? "–"),
        h("td", { class: "l name" }, sec.names[r.key]),
        h("td", { class: "l" }, meter(r.score)),
        h("td", { class: moved > 0 ? "pos" : moved < 0 ? "neg" : "muted" },
          moved == null ? "–" : moved === 0 ? "–" : `${moved > 0 ? "+" : "−"}${Math.abs(moved)}`),
        h("td", { class: sign(r.excess_1m) }, fmtPct(r.excess_1m)),
        h("td", { class: "l" }, quadChip(r.quadrant)),
        h("td", { class: sign(r.excess_3m) }, fmtPct(r.excess_3m)),
        h("td", null, isNum(r.breadth_50) ? `${Math.round(r.breadth_50)}%` : "–"));
    })));

  const rrg = rrgChart(keys, B.tails, sec.names, pick);
  function highlight(k) {
    const active = k || state.sel;
    rrg.querySelectorAll("g[role=button]").forEach((g) => {
      const name = g.getAttribute("aria-label").split(":")[0];
      g.classList.toggle("dim", Boolean(active) && name !== sec.names[active]);
    });
    rrg.querySelectorAll("g[data-key]").forEach((g) => {
      g.classList.toggle("dim", Boolean(active) && g.dataset.key !== active);
    });
  }

  const main = h("div", { class: "grid-main" },
    h("div", { class: "panel" },
      h("h2", null, "Relative rotation"),
      h("p", { class: "sub" }, `Weekly, vs ${B.name}. Tails show the path over recent weeks; sectors usually rotate clockwise: Improving, Leading, Weakening, Lagging. Tap a dot to highlight it.`),
      seg("Tail", [[4, "4 weeks"], [8, "8 weeks"]], state.tail, (v) => { state.tail = v; route(); }),
      rrg,
      h("div", { class: "legend" }, QUAD.map((q) => h("span", null, h("i", { style: `background:var(${QVAR[q]})` }), q)))),
    h("div", { class: "panel" },
      h("h2", null, `${state.group} ranking`),
      h("p", { class: "sub" }, "Score 0–100 from relative strength trend and momentum, excess return, price trend and breadth. Tap a row for detail."),
      h("div", { class: "table-scroll" }, table)));

  // breadth section
  const S2 = br.series, D = br.dates;
  const hasAD = Array.isArray(S2.ad_line);
  const breadth = h("section", null,
    h("div", { class: "section-head" },
      h("h2", null, "Market breadth"),
      h("p", null, `Last ${D.length} sessions, to ${fmtDate(L.date)}`)),
    h("div", { class: "panel" },
      h("div", { class: "stats" },
        stat("Advances / declines", hasAD ? `${fmtNum(L.advances)} / ${fmtNum(L.declines)}` : "–", "All NSE stocks, latest session"),
        stat("A/D ratio, 10 days", hasAD ? fmtNum(L.ad_ratio_10, 2) : "–", "Below 1 means more decliners"),
        stat("Above 50-day average", `${Math.round(L.pct_above_50)}%`, `${Math.round(L.pct_above_50_20d_ago)}% a month ago`),
        stat("Above 200-day average", `${Math.round(L.pct_above_200)}%`, `${Math.round(L.pct_above_200_20d_ago)}% a month ago`),
        stat("52-week highs / lows", `${fmtNum(L.new_highs)} / ${fmtNum(L.new_lows)}`, "Total Market stocks")),
      h("div", { class: "charts" },
        chartCard("Nifty 500", "Daily close", timeChart({ dates: D, series: [{ name: "Nifty 500", values: S2.nifty500, color: css("--ink-2") }], fmt: (v) => fmtNum(v, 2) })),
        hasAD ? chartCard("Advance–decline line", "Running total of advances minus declines, all NSE stocks, with its 50-day average. Above the average = breadth improving, below = deteriorating. A falling line while the index holds up is a warning sign.",
          timeChart({ dates: D, series: [{ name: "A/D line", values: S2.ad_line, color: css("--s1") },
            ...(S2.ad_mean50 ? [{ name: "50-day average", values: S2.ad_mean50, color: css("--down"), width: 1.5 }] : [])], fmt: (v) => fmtNum(v) }),
          S2.ad_mean50 ? lineLegend([["A/D line", css("--s1")], ["50-day average", css("--down")]]) : null) : null,
        chartCard("Stocks above their averages", "Share of Nifty 500 stocks above their 50-day and 200-day averages",
          timeChart({ dates: D, domain: [0, 100], tickFmt: (v) => `${v}%`, fmt: (v) => (isNum(v) ? `${v.toFixed(0)}%` : "–"),
            series: [{ name: "Above 50-day", values: S2.pct_above_50, color: css("--s1") }, { name: "Above 200-day", values: S2.pct_above_200, color: css("--s2") }] }),
          lineLegend([["Above 50-day", css("--s1")], ["Above 200-day", css("--s2")]])),
        hasAD ? chartCard("Net advances", "Advances minus declines each session",
          timeChart({ dates: D, bars: true, series: [{ name: "Net advances", values: S2.net }],
            tipRows: (i) => [["Advances", fmtNum(S2.advances[i])], ["Declines", fmtNum(S2.declines[i])], ["Net", fmtNum(S2.net[i])]] })) : null,
        chartCard("52-week highs and lows", "Total Market stocks closing at a 52-week high or low",
          timeChart({ dates: D, series: [{ name: "New highs", values: S2.new_highs, color: css("--s3") }, { name: "New lows", values: S2.new_lows, color: css("--s2") }] }),
          lineLegend([["New highs", css("--s3")], ["New lows", css("--s2")]])))));

  // focus sectors with picks
  const focus = (st.focus[state.bench] || {})[state.group] || [];
  const focusSec = h("section", null,
    h("div", { class: "section-head" },
      h("h2", null, "Where to look"),
      h("p", null, "Leading or Improving sectors plus the top 5, with their strongest stocks")),
    focus.length ? h("div", { class: "focus" }, focus.map((f) => h("a", { class: "card", href: `#/sector/${f.key}` },
      h("h3", null, sec.names[f.key], quadChip(B.rows[f.key].quadrant)),
      h("div", { class: "why" }, `${f.reason}, score ${Math.round(B.rows[f.key].score)}`),
      f.picks.length ? h("ol", null, f.picks.map((sym) => h("li", null, `${sym} `,
        h("span", null, Math.round(st.stocks[sym].score)), st.stocks[sym].fno ? h("span", { class: "flag fno" }, "F&O") : null)))
        : h("p", { class: "empty" }, "No stock passes the filters right now.")))) : h("p", { class: "empty" }, "No focus sectors today."));

  app.replaceChildren(filtersRow(), lede, regimePanel(rg), main, breadth, rotationSection(ld, sec), focusSec);
  if (state.sel) highlight(null);
}

async function viewSector(app, key) {
  const [sec, hist, st] = await Promise.all([load("sectors"), load("sector_history"), load("stocks")]);
  const B = sec.benchmarks[state.bench];
  const r = B.rows[key];
  if (!r) { app.replaceChildren(h("p", { class: "empty" }, "That index is not tracked."), h("a", { class: "back", href: "#/" }, "Back to overview")); return; }
  const group = sec.groups.Sectoral.includes(key) ? "Sectoral" : "Thematic";
  const D = hist.dates;
  const val = sec.valuations[key] || {};

  const head = h("div", null,
    h("a", { class: "back", href: "#/" }, "Back to overview"),
    h("div", { class: "sector-title" }, h("h1", null, `Nifty ${sec.names[key]}`), quadChip(r.quadrant),
      h("span", { class: "muted" }, `${group} rank ${r.rank ?? "–"} of ${sec.groups[group].length} vs ${B.name}`)));

  const stats = h("div", { class: "stats" },
    stat("Score", isNum(r.score) ? Math.round(r.score) : "–", isNum(r.score_1w_ago) ? `${Math.round(r.score_1w_ago)} a week ago` : null),
    stat("Excess return 1M / 3M", `${fmtPct(r.excess_1m)} / ${fmtPct(r.excess_3m)}`, `vs ${B.name}`),
    stat("Return 1M / 3M", `${fmtPct(r.return_1m)} / ${fmtPct(r.return_3m)}`, `RSI ${isNum(r.rsi14) ? r.rsi14.toFixed(0) : "–"}`),
    stat("From 52-week high", fmtPct(r.pct_from_52w_high), `Above 50 / 200-day: ${r.above_50 ? "yes" : "no"} / ${r.above_200 ? "yes" : "no"}`),
    stat("Breadth", isNum(r.breadth_50) ? `${Math.round(r.breadth_50)}%` : "–", isNum(val.pe) ? `P/E ${val.pe.toFixed(1)}, P/B ${isNum(val.pb) ? val.pb.toFixed(1) : "–"}` : "Stocks above 50-day average"));

  const comps = r.components || {};
  const compNames = { rs_trend: "RS trend", rs_momentum: "RS momentum", excess_return: "Excess return", trend: "Price trend", breadth: "Breadth" };
  const compTable = h("table", null, h("tbody", null, Object.entries(compNames).map(([k, label]) =>
    h("tr", { style: "cursor:default" }, h("td", { class: "l" }, label), h("td", { class: "muted" }, `${Math.round((sec.weights[k] || 0) * 100)}% weight`), h("td", { class: "l" }, meter(comps[k]))))));

  const price = hist.prices.close[key], s50 = hist.prices.sma50[key], s200 = hist.prices.sma200[key];
  const rs = hist.benchmarks[state.bench].rs[key];
  const scoreH = hist.benchmarks[state.bench].score[key];
  const charts = h("div", { class: "charts" },
    chartCard("Price", "Index close with 50-day and 200-day averages",
      timeChart({ dates: D, fmt: (v) => fmtNum(v, 2), series: [
        { name: "Close", values: price, color: css("--ink-2") },
        { name: "50-day", values: s50, color: css("--s1") },
        { name: "200-day", values: s200, color: css("--s2") }] }),
      lineLegend([["Close", css("--ink-2")], ["50-day", css("--s1")], ["200-day", css("--s2")]])),
    chartCard(`Relative strength vs ${B.name}`, "Rising line = outperforming. Rebased to 100 a year ago.",
      timeChart({ dates: D, fmt: (v) => fmtNum(v, 1), series: [{ name: "RS", values: rs, color: css("--s1") }] })),
    chartCard("Strength score", "Daily score, 0–100",
      timeChart({ dates: D, domain: [0, 100], fmt: (v) => fmtNum(v, 0), series: [{ name: "Score", values: scoreH, color: css("--s1") }] })),
    chartCard("Breadth", "Share of the index's stocks above their 50-day average",
      timeChart({ dates: D, domain: [0, 100], tickFmt: (v) => `${v}%`, fmt: (v) => (isNum(v) ? `${v.toFixed(0)}%` : "–"),
        series: [{ name: "Above 50-day", values: hist.breadth50[key], color: css("--s3") }] })));

  app.replaceChildren(head, stats,
    h("div", { class: "grid-main" },
      h("div", { class: "panel" }, h("h2", null, "Charts"), h("p", { class: "sub" }, "Last 12 months"), charts),
      h("div", { class: "panel" }, h("h2", null, "Score breakdown"), h("p", { class: "sub" }, "Ranked parts compare this index with the others on its tab."), compTable)),
    membersSection(key, sec, st));
}

function membersSection(key, sec, st) {
  const holder = h("section", null);
  const render = () => {
    let syms = (st.members[key] || []).slice();
    if (state.fnoOnly) syms = syms.filter((x) => st.stocks[x].fno);
    const vs = st.vs_sector[key] || {};
    const cols = [
      ["score", "Score", (x) => meter(x.score)],
      ["rs_rating", "RS rating", (x) => fmtNum(x.rs_rating)],
      ["return_1m", "1M", (x) => fmtPct(x.return_1m), sign],
      ["return_3m", "3M", (x) => fmtPct(x.return_3m), sign],
      ["vs3", "vs index 3M", (x) => fmtPct(x.vs3), sign],
      ["pct_from_52w_high", "From high", (x) => fmtPct(x.pct_from_52w_high)],
      ["rsi14", "RSI", (x) => fmtNum(x.rsi14)],
      ["mcap_cr", "M-cap ₹cr", (x) => fmtNum(x.mcap_cr)],
    ];
    const rows = syms.map((x) => ({ sym: x, ...st.stocks[x], vs3: vs[x]?.excess_3m, via: vs[x]?.via }));
    sortRows(rows, state.memberSort);
    holder.replaceChildren(
      h("div", { class: "section-head" }, h("h2", null, "Stocks in this index"),
        h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: state.fnoOnly || null,
          onchange: (e) => { state.fnoOnly = e.target.checked; store("ss-fno", state.fnoOnly ? "1" : "0"); render(); } }), "F&O stocks only")),
      h("div", { class: "panel" },
        h("p", { class: "sub" }, Object.prototype.hasOwnProperty.call(st.industry_peers, key)
          ? `Official constituents plus other Nifty Total Market stocks in the ${st.industry_peers[key]} industry (marked "peer").`
          : "Official index constituents."),
        rows.length ? h("div", { class: "table-scroll" }, stockTable(rows, cols, state.memberSort, render, true)) : h("p", { class: "empty" }, "No stocks match.")));
  };
  render();
  return holder;
}

function sortRows(rows, sort) {
  rows.sort((a, b) => {
    const va = a[sort.key], vb = b[sort.key];
    if (!isNum(va) && !isNum(vb)) return 0;
    if (!isNum(va)) return 1;
    if (!isNum(vb)) return -1;
    return (va - vb) * sort.dir;
  });
}

function stockTable(rows, cols, sort, rerender, showVia, leadCols = []) {
  const th = (key, label) => h("th", { "aria-sort": sort.key === key ? (sort.dir < 0 ? "descending" : "ascending") : null },
    h("button", { type: "button", onclick: () => { if (sort.key === key) sort.dir *= -1; else { sort.key = key; sort.dir = -1; } rerender(); } }, label));
  return h("table", null,
    h("thead", null, h("tr", null, leadCols.map(([, label]) => h("th", { class: "l" }, label)),
      h("th", { class: "l" }, "Stock"), cols.map(([k, label]) => th(k, label)), h("th", { class: "l" }, "Flags"))),
    h("tbody", null, rows.map((x) => h("tr", { style: "cursor:default" },
      leadCols.map(([, , fn]) => h("td", { class: "l" }, fn(x))),
      h("td", { class: "l name" }, x.sym, h("small", null, x.company || x.industry || "")),
      cols.map(([k, , fn, cls]) => h("td", { class: cls ? cls(x[k]) : null }, fn(x))),
      h("td", { class: "l" },
        (x.flags || []).filter((f) => f !== "F&O" && !isResultsFlag(f)).map((f) => h("span", { class: "flag" }, f)),
        resultsFlag(x.results_date ? { date: x.results_date, days: x.results_days } : null),
        x.fno ? h("span", { class: "flag fno" }, "F&O") : null,
        showVia && x.via === "industry" ? h("span", { class: "flag" }, "peer") : null)))));
}

async function viewPicks(app) {
  const [sec, st, rg, ld] = await Promise.all([load("sectors"), load("stocks"), load("regime"), load("leaders")]);
  const focus = (st.focus[state.bench] || {})[state.group] || [];
  const B = sec.benchmarks[state.bench];
  const holder = h("div", null);
  const render = () => {
    const seen = new Map();
    for (const f of focus) for (const sym of f.picks) {
      if (seen.has(sym)) { seen.get(sym).sectors.push(f.key); continue; }
      seen.set(sym, { sym, ...st.stocks[sym], sectors: [f.key], vs3: st.vs_sector[f.key]?.[sym]?.excess_3m });
    }
    let rows = [...seen.values()];
    if (state.fnoOnly) rows = rows.filter((x) => x.fno);
    sortRows(rows, state.pickSort);
    const cols = [
      ["score", "Score", (x) => meter(x.score)],
      ["rs_rating", "RS rating", (x) => fmtNum(x.rs_rating)],
      ["return_1m", "1M", (x) => fmtPct(x.return_1m), sign],
      ["return_3m", "3M", (x) => fmtPct(x.return_3m), sign],
      ["vs3", "vs sector 3M", (x) => fmtPct(x.vs3), sign],
      ["pct_from_52w_high", "From high", (x) => fmtPct(x.pct_from_52w_high)],
      ["rsi14", "RSI", (x) => fmtNum(x.rsi14)],
      ["traded_value_cr", "Traded ₹cr/day", (x) => fmtNum(x.traded_value_cr)],
      ["mcap_cr", "M-cap ₹cr", (x) => fmtNum(x.mcap_cr)],
    ];
    const lead = [["sector", "Sector", (x) => x.sectors.map((k) => sec.names[k]).join(", ")]];
    holder.replaceChildren(
      h("div", { class: "panel" },
        h("h2", null, state.group === "Sectoral" ? "Top stocks in focus sectors" : "Top stocks in focus themes"),
        h("p", { class: "sub" }, `Up to ${st.picks_per_sector} per sector with score ${st.filters.min_pick_score}+, market cap ₹${st.filters.min_mcap_cr} cr+, traded value ₹${st.filters.min_traded_value_cr} cr+ a day. Focus sectors are those Leading or Improving vs ${B.name}, plus the top 5. A strong stock is a candidate, not a buy, until it forms a setup.`),
        rows.length ? h("div", { class: "table-scroll" }, stockTable(rows, cols, state.pickSort, render, false, lead)) : h("p", { class: "empty" }, "No stocks match these filters.")));
  };
  render();
  const setupsBox = setupsSection(st, sec, rg);
  app.replaceChildren(
    filtersRow(h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: state.fnoOnly || null,
      onchange: (e) => { state.fnoOnly = e.target.checked; store("ss-fno", state.fnoOnly ? "1" : "0"); route(); } }), "F&O stocks only")),
    setupsBox, nextLeadersSection(ld, st, sec), h("div", { style: "height:12px" }), holder);
}


// ------------------------------------------------------------------ rotation watch and next leaders
const STATUS_HELP = {
  "Emerging": "Fell less than the market and is leading off the low, but was not a top-5 sector at the peak: a candidate new leader.",
  "Steady leader": "A top-5 sector at the market's peak that is still holding up: leadership intact.",
  "Old leader, bouncing": "A top-5 sector at the peak that fell more than the market but is outperforming since the low.",
  "Fading leader": "A top-5 sector at the peak that fell more than the market and is not recovering: likely to lag the next rally.",
};
function statusChip(st) {
  if (!st) return h("span", { class: "muted" }, "–");
  const cls = { "Emerging": "em", "Steady leader": "sl", "Old leader, bouncing": "ob", "Fading leader": "fd" }[st];
  return h("span", { class: `status ${cls}`, title: STATUS_HELP[st] }, st);
}
function declineSentence(dc) {
  if (!dc) return "";
  const pk = fmtDate(dc.peak, { day: "numeric", month: "short", year: "numeric" }), lw = fmtDate(dc.low, { day: "numeric", month: "short", year: "numeric" });
  return dc.in_correction
    ? `Nifty 500 fell ${Math.abs(dc.fall).toFixed(1)}% from its 6-month high on ${pk} to its low on ${lw}, and is ${dc.bounce.toFixed(1)}% above that low.`
    : `Nifty 500 is within 7% of its 6-month high (${pk}), so there is no correction under way; the figures cover its latest pullback (low ${lw}, ${dc.fall.toFixed(1)}%).`;
}
function rotationSection(ld, sec) {
  if (!ld) return null;
  const dc = ld.decline;
  const keys = sec.groups[state.group];
  const rows = keys.map((k) => ({ key: k, ...ld.sectors[k] })).sort((a, b) => (a.nl_rank ?? 99) - (b.nl_rank ?? 99));
  return h("section", null,
    h("div", { class: "section-head" }, h("h2", null, "Rotation watch"),
      h("p", null, "Who is taking over leadership in this correction, vs Nifty 500")),
    h("div", { class: "panel" },
      h("p", { class: "sub" }, declineSentence(dc), " Sectors are ranked on how little they fell, how they have done since the low, and how close their relative strength is to its 52-week high.",
        dc.off_low_valid ? "" : " The low is under 5 sessions old, so performance since the low is not counted yet."),
      h("div", { class: "table-scroll" }, h("table", { class: "static" },
        h("thead", null, h("tr", null, h("th", { class: "l" }, "#"), h("th", { class: "l" }, "Index"), h("th", { class: "l" }, "Status"),
          h("th", { title: "Index return from the market's peak to its low, minus Nifty 500's. Positive = fell less." }, "Fall vs market"),
          h("th", { title: "Return since the market's low, minus Nifty 500's" }, "Since low vs market"),
          h("th", { title: "Relative-strength line vs its own 52-week high; 0% = at the high" }, "RS line vs high"),
          h("th", { title: "Strength-score rank at the market's peak, and now" }, "Rank: peak → now"),
          h("th", { class: "l" }, "Quadrant"))),
        h("tbody", null, rows.map((r) => h("tr", { tabindex: 0, onclick: () => { location.hash = `#/sector/${r.key}`; } },
          h("td", { class: "l muted" }, fmtNum(r.nl_rank)),
          h("td", { class: "l name" }, sec.names[r.key]),
          h("td", { class: "l" }, statusChip(r.status)),
          h("td", { class: sign(r.held_up_pct) }, fmtPct(r.held_up_pct)),
          h("td", { class: dc.off_low_valid ? sign(r.since_low_pct) : "muted" }, dc.off_low_valid ? fmtPct(r.since_low_pct) : "–"),
          h("td", null, fmtPct(r.rs_vs_high)),
          h("td", null, `${fmtNum(r.rank_at_peak)} → ${fmtNum(r.rank_now)}`),
          h("td", { class: "l" }, quadChip(r.quadrant))))))),
      h("div", { class: "legend status-legend" }, Object.keys(STATUS_HELP).map((k) => h("span", null, statusChip(k), " ", STATUS_HELP[k]))),
      h("p", { class: "note" }, "How these statuses did in past corrections: ", h("a", { href: "#/record" }, "track record"), ". Few corrections have been tested so far, so treat the statuses as leads, not rules.")));
}

function nextLeadersSection(ld, st, sec) {
  if (!ld) return null;
  const dc = ld.decline;
  const setupSyms = new Set((st.setups || []).map((x) => x.symbol));
  let rows = (ld.stocks || []).map((x, i) => ({ ...x, n: i + 1, info: st.stocks[x.symbol] || {} }));
  if (state.fnoOnly) rows = rows.filter((x) => x.info.fno);
  rows = rows.slice(0, 25);
  return h("section", null,
    h("div", { class: "section-head" }, h("h2", null, "Next leaders"),
      h("p", null, "Stocks that fell least and are first off the low: candidates to lead the next rally")),
    h("div", { class: "panel" },
      h("p", { class: "sub" }, declineSentence(dc), dc.in_correction ? " Use this as the watchlist; buy when one forms a setup above or the market regime improves."
        : " With no correction under way, the strength ranking below matters more than this list."),
      rows.length ? h("div", { class: "table-scroll" }, h("table", { class: "static" },
        h("thead", null, h("tr", null, h("th", { class: "l" }, "#"), h("th", { class: "l" }, "Stock"), h("th", { class: "l" }, "Sector"),
          h("th", null, "Next-leader score"),
          h("th", { title: "Return from the market's peak to its low, minus Nifty 500's. Positive = fell less." }, "Fall vs market"),
          h("th", { title: "Return since the market's low, minus Nifty 500's" }, "Since low vs market"),
          h("th", { title: "Relative-strength line vs its own 52-week high; 0% = at the high" }, "RS line vs high"),
          h("th", null, "Price vs high"),
          h("th", { title: "Volume on up days ÷ volume on down days since the peak; above 1 = accumulation" }, "Up/down volume"),
          h("th", { class: "l" }, "Flags"))),
        h("tbody", null, rows.map((x) => h("tr", null,
          h("td", { class: "l muted" }, x.n),
          h("td", { class: "l name" }, x.symbol, h("small", null, x.info.company || x.info.industry || "")),
          h("td", { class: "l small" }, (x.info.sectors || []).map((k) => sec.names[k]).filter(Boolean).slice(0, 2).join(", ") || "–"),
          h("td", null, meter(x.score)),
          h("td", { class: sign(x.held_up_pct) }, fmtPct(x.held_up_pct)),
          h("td", { class: sign(x.since_low_pct) }, dc.off_low_valid ? fmtPct(x.since_low_pct) : "–"),
          h("td", null, fmtPct(x.rs_vs_high)),
          h("td", null, fmtPct(x.from_high)),
          h("td", null, fmtNum(x.updown_volume, 2)),
          h("td", { class: "l" }, resultsFlag(st.results?.[x.symbol]),
            x.rs_leads_price ? h("span", { class: "flag", title: "RS line at a new high while the price is still 5%+ below its high" }, "RS leads price") : null,
            setupSyms.has(x.symbol) ? h("span", { class: "flag fno" }, "Setup today") : null,
            x.info.fno ? h("span", { class: "flag fno" }, "F&O") : null)))))) : h("p", { class: "empty" }, "No stocks match."),
      h("p", { class: "note" }, `Score: fell least ${Math.round(ld.weights.held_up * 100)}%, since the low ${Math.round(ld.weights.off_low * 100)}%, RS line ${Math.round(ld.weights.rs_line * 100)}%, accumulation ${Math.round(ld.weights.accumulation * 100)}% (percentile ranks). Stocks more than 30% below their high are left out. How it did in past corrections: `,
        h("a", { href: "#/record" }, "track record"), ".")));
}

// ------------------------------------------------------------------ positional setups
const SETUP_HELP = {
  Breakout: "Closed above its 40-session high on 1.5x+ normal volume. Buy near the close, but not more than 5% above the pivot.",
  "Tight base": "Coiling near its highs on drying volume. Buy only if it trades above the trigger price within the next 10 sessions.",
  Pullback: "A recent leader that pulled back to its rising 50-day average on light volume and turned up. Buy near the close.",
};
const SETUP_NAME = { breakout: "Breakout", tight: "Tight base", pullback: "Pullback" };

function positionSize(entry, stop) {
  const risk = entry - stop;
  if (!(risk > 0)) return { qty: null };
  let qty = Math.floor((state.capital * state.riskPct / 100) / risk);
  let capped = false;
  const maxValue = state.capital * state.maxPos / 100;
  if (qty * entry > maxValue) { qty = Math.floor(maxValue / entry); capped = true; }
  return { qty, value: qty * entry, pct: (qty * entry / state.capital) * 100, capped };
}

function setupsSection(st, sec, rg) {
  const box = h("section", null);
  const rules = st.setup_rules || {};
  box.refresh = () => {
    let rows = (st.setups || []).map((x) => ({ ...x, ...st.stocks[x.symbol], sym: x.symbol, name: SETUP_NAME[x.setup] }));
    const total = rows.length, aCount = rows.filter((x) => x.grade === "A").length;
    if (state.aOnly) rows = rows.filter((x) => x.grade === "A");
    if (state.fnoOnly) rows = rows.filter((x) => x.fno);
    const num = (label, key, value, attrs) => h("label", { class: "field" }, h("span", null, label),
      h("input", { type: "number", value, inputmode: "decimal", ...attrs,
        onchange: (e) => { const v = parseFloat(e.target.value); if (v > 0) { state[key] = v; store({ capital: "ss-capital", riskPct: "ss-risk", maxPos: "ss-maxpos" }[key], v); box.refresh(); } } }));
    const table = h("table", null,
      h("thead", null, h("tr", null,
        h("th", { class: "l" }, "Grade"), h("th", { class: "l" }, "Stock"), h("th", { class: "l" }, "Setup"),
        h("th", { class: "l" }, "Sector"), h("th", null, "Close"), h("th", null, "Buy"), h("th", null, "Stop"),
        h("th", null, "Risk"), h("th", null, "Qty"), h("th", null, "Position"),
        h("th", { title: "RS rating 1–99 across ~750 stocks" }, "RS"), h("th", null, "Score"), h("th", { class: "l" }, "Flags"), h("th", null, ""))),
      h("tbody", null, rows.map((x) => {
        const entry = x.trigger ?? x.entry_ref;
        const ps = positionSize(entry, x.stop);
        const secs = (x.sectors || []).map((k) => sec.names[k]).filter(Boolean);
        return h("tr", { style: "cursor:default" },
          h("td", { class: "l" }, h("span", { class: `grade g${x.grade}` }, x.grade)),
          h("td", { class: "l name" }, x.sym, h("small", null, x.company || x.industry || "")),
          h("td", { class: "l", title: SETUP_HELP[x.name] }, x.name),
          h("td", { class: "l small" }, secs.slice(0, 2).join(", ") || "–"),
          h("td", null, fmtNum(x.close, 2)),
          h("td", null, x.trigger ? h("span", null, h("span", { class: "muted" }, "above "), fmtNum(x.trigger, 2)) : fmtNum(x.entry_ref, 2)),
          h("td", null, fmtNum(x.stop, 2)),
          h("td", null, fmtPct(x.risk_pct, 1, false)),
          h("td", null, ps.qty != null ? fmtNum(ps.qty) : "–"),
          h("td", { title: ps.capped ? `Capped at ${state.maxPos}% of capital; the risk is then below ${state.riskPct}%` : null },
            ps.qty != null ? [`₹${fmtCompact(ps.value)} · ${ps.pct.toFixed(0)}%`, ps.capped ? h("sup", null, " cap") : null] : "–"),
          h("td", null, fmtNum(x.rs_rating)),
          h("td", null, fmtNum(x.score)),
          h("td", { class: "l" }, resultsFlag(st.results?.[x.sym]), x.rs_at_high ? h("span", { class: "flag" }, "RS at high") : null,
            x.fno ? h("span", { class: "flag fno" }, "F&O") : null,
            (x.flags || []).includes("Extended") ? h("span", { class: "flag" }, "Extended") : null),
          h("td", null, h("button", { class: "btn small", type: "button", onclick: () => takeTrade({
            symbol: x.sym, entry: +entry.toFixed(2), stop: +x.stop.toFixed(2), qty: ps.qty || null, exit_rule: "system",
            setup: x.name, grade: x.grade, sector: secs[0] || null, source: "setup",
            notes: `${x.name} setup on ${fmtDate(st.as_of)}${x.trigger ? `; buy above ${fmtNum(x.trigger, 2)}` : ""}.` }) }, "I took this trade")));
      })));
    box.replaceChildren(
      h("div", { class: "section-head" }, h("h2", null, "Positional setups today"),
        h("p", null, `For holding weeks to months · ${fmtDate(st.as_of)}`)),
      h("div", { class: "panel" },
        rg && rg.light ? h("p", { class: "regime-line" }, lightChip(rg.light), ` ${rg.guidance} `, h("a", { href: "#/" }, "Market regime")) : null,
        h("div", { class: "controls" },
          h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: state.aOnly || null,
            onchange: (e) => { state.aOnly = e.target.checked; store("ss-aonly", state.aOnly ? "1" : "0"); box.refresh(); } }),
            `A-grade only (${aCount} of ${total})`),
          num("Capital ₹", "capital", state.capital, { min: 1000, step: 1000 }),
          num("Risk per trade %", "riskPct", state.riskPct, { min: 0.1, max: 10, step: 0.1 }),
          num("Max per stock %", "maxPos", state.maxPos, { min: 1, max: 100, step: 1 })),
        rows.length ? h("div", { class: "table-scroll" }, table)
          : h("p", { class: "empty" }, total ? "No setups match these filters. Untick A-grade only to see the rest." : "No stock formed a positional setup today."),
        h("p", { class: "note" }, `Qty risks ${state.riskPct}% of your capital (₹${fmtCompact(state.capital * state.riskPct / 100)}) between the buy price and the stop, with no stock above ${state.maxPos}% of capital ("cap" marks a trimmed position). Grade A = RS rating ${rules.a_grade_rs ?? 90}+ or relative strength at a 52-week high; in the `,
          h("a", { href: "#/record" }, "track record"), " only A-grade setups made money."),
        h("p", { class: "note" }, "An amber “Results” flag means quarterly results are due within 7 days (NSE board-meeting calendar). Buying just before results is close to a coin toss: the price can gap straight through the stop. Many traders wait for the results, or take a smaller position."),
        h("details", { class: "rules" }, h("summary", null, "Setup, stop and exit rules"),
          h("ul", null,
            h("li", null, h("b", null, "All setups: "), `long-term uptrend (above the 200-day average, 50-day above 200-day, 200-day rising), within ${rules.trend?.near_high_pct ?? 25}% of the 52-week high, RS rating ${rules.trend?.min_rs_rating ?? 70}+.`),
            Object.entries(SETUP_HELP).map(([k, v]) => h("li", null, h("b", null, `${k}: `), v)),
            h("li", null, h("b", null, "Stop: "), `below the recent swing low (10 sessions; 5 sessions or the 50-day average for a pullback), never more than ${rules.stop?.max_risk ?? 8}% below the buy price.`),
            h("li", null, h("b", null, "Exit: "), `the stop, or the first close below the 50-day average, or after ${rules.exit?.max_days ?? 120} sessions. No fixed target, so winners can run for months.`)))));
  };
  box.refresh();
  return box;
}



// ------------------------------------------------------------------ track record (Phase 6)
const fmtX = (v) => (isNum(v) ? v.toFixed(2) : "–");
function aggCells(a) {
  return a && a.n ? [h("td", { class: sign(a.avg) }, fmtPct(a.avg)), h("td", null, `${Math.round(a.hit)}%`)]
    : [h("td", { class: "muted" }, "–"), h("td", { class: "muted" }, "–")];
}
function fwdTable(firstCol, groups, labels) {
  // groups: {"1M": {label: agg}, "3M": {...}}
  return h("table", { class: "static" },
    h("thead", null,
      h("tr", null, h("th", { class: "l", rowspan: 2 }, firstCol), h("th", { colspan: 2, class: "c" }, "Next 1 month"), h("th", { colspan: 2, class: "c" }, "Next 3 months"), h("th", { rowspan: 2 }, "Samples")),
      h("tr", null, h("th", null, "Avg vs Nifty 500"), h("th", null, "Beat it"), h("th", null, "Avg vs Nifty 500"), h("th", null, "Beat it"))),
    h("tbody", null, labels.map((l) => h("tr", null,
      h("td", { class: "l name" }, l), aggCells(groups["1M"][l]), aggCells(groups["3M"][l]),
      h("td", { class: "muted" }, fmtNum(groups["3M"][l]?.n ?? groups["1M"][l]?.n))))));
}
function setupRows(entries) {
  return h("table", { class: "static" },
    h("thead", null, h("tr", null, h("th", { class: "l" }, "Group"), h("th", null, "Trades"), h("th", null, "Win rate"),
      h("th", null, "Avg win"), h("th", null, "Avg loss"), h("th", { title: "Total gains ÷ total losses; above 1 means it made money" }, "Profit factor"),
      h("th", null, "Avg per trade"), h("th", null, "Avg days held"))),
    h("tbody", null, entries.map(([label, b]) => h("tr", null,
      h("td", { class: "l name" }, label),
      h("td", null, fmtNum(b?.closed)),
      h("td", null, isNum(b?.win_rate) ? `${Math.round(b.win_rate)}%` : "–"),
      h("td", { class: "pos" }, fmtPct(b?.avg_win)), h("td", { class: "neg" }, fmtPct(b?.avg_loss)),
      h("td", { class: isNum(b?.profit_factor) ? (b.profit_factor >= 1 ? "pos" : "neg") : "muted" }, fmtX(b?.profit_factor)),
      h("td", { class: sign(b?.avg_return) }, fmtPct(b?.avg_return)),
      h("td", null, fmtNum(b?.avg_days))))));
}

/* Horizontal bars, one per group, single measure (avg excess return). */
function barList(items, fmt) {
  const max = Math.max(1e-9, ...items.map((x) => Math.abs(x.value || 0)));
  const hasNeg = items.some((x) => x.value < 0);
  return h("div", { class: "bars", role: "list" }, items.map((x) => {
    const w = (Math.abs(x.value || 0) / max) * (hasNeg ? 50 : 100);
    const left = hasNeg ? (x.value >= 0 ? 50 : 50 - w) : 0;
    return h("div", { class: "bar-row", role: "listitem", title: x.tip || "" },
      h("span", { class: "bar-label" }, x.label),
      h("span", { class: "bar-track" }, hasNeg ? h("i", { class: "zero" }) : null,
        h("b", { style: `left:${left}%;width:${Math.max(0.5, w)}%;background:${x.value >= 0 ? css("--up") : css("--down")}` })),
      h("span", { class: `bar-val ${sign(x.value)}` }, fmt(x.value)));
  }));
}


function leadershipSection(L, names) {
  const eps = (L?.episodes || []).slice().reverse();
  if (!eps.length) return null;
  return h("section", null,
    h("div", { class: "section-head" }, h("h2", null, "Leadership change in corrections"),
      h("p", null, `Each time Nifty 500 fell ${L.rules.fall}%+ from its 6-month high and then rose ${L.rules.bounce}% off the low`)),
    eps.map((e) => {
      const G = e.groups || {};
      const order = ["Next leaders (top 20% next-leader score)", "Fell least (top 20%)", "Best off the low (top 20%)",
        "Old leaders (top 20% score at the peak)", "Old leaders not in the top half now", "All stocks"];
      return h("div", { class: "panel", style: "margin-bottom:12px" },
        h("h2", null, `${fmtDate(e.peak, { month: "short", year: "numeric" })} – ${fmtDate(e.low, { month: "short", year: "numeric" })} correction`),
        h("p", { class: "sub" }, `Nifty 500 fell ${Math.abs(e.fall).toFixed(1)}% (high ${fmtDate(e.peak)}, low ${fmtDate(e.low)}). Tested on ${fmtDate(e.eval_date)}, when it was ${e.bounce.toFixed(1)}% off the low; returns over the next ${e.fwd_days} sessions${e.complete ? "" : " so far"}.`),
        h("div", { class: "grid-main" },
          h("div", { class: "table-scroll" }, h("table", { class: "static" },
            h("thead", null, h("tr", null, h("th", { class: "l" }, "Stocks"), h("th", null, "Avg vs Nifty 500"), h("th", null, "Beat it"), h("th", null, "Stocks"))),
            h("tbody", null, order.filter((k) => G[k]).map((k) => h("tr", null, h("td", { class: "l name" }, k),
              h("td", { class: sign(G[k].avg) }, fmtPct(G[k].avg)), h("td", null, `${Math.round(G[k].hit)}%`), h("td", { class: "muted" }, fmtNum(G[k].n))))))),
          h("div", null,
            Object.keys(e.sectors_by_status || {}).length ? h("div", { class: "table-scroll" }, h("table", { class: "static" },
              h("thead", null, h("tr", null, h("th", { class: "l" }, "Sector status that day"), h("th", null, "Avg vs Nifty 500"), h("th", null, "Indices"))),
              h("tbody", null, Object.entries(e.sectors_by_status).map(([k, v]) => h("tr", null, h("td", { class: "l" }, statusChip(k)),
                h("td", { class: sign(v.avg) }, fmtPct(v.avg)), h("td", { class: "muted" }, v.n))))))
              : h("p", { class: "empty" }, "Sector statuses need a year of history before the peak; not available for this correction."),
            isNum(e.sector_corr_old) ? h("p", { class: "note" }, `Link between a sector's rank at the peak and its next-3-month result: ${e.sector_corr_old.toFixed(2)} (rank correlation; negative means the old leaders lagged).`) : null)),
        h("p", { class: "note" }, `Top next leaders that day: ${(e.top_next || []).join(", ")}.`));
    }),
    h("p", { class: "note" }, "Only a few corrections fall inside the stored data. In the 2026 one the next leaders clearly beat the old leaders; in the 2025 one the rally was led by the most beaten-down stocks and the next leaders lagged. More episodes will be added automatically as they happen."));
}

async function viewRecord(app) {
  const v = await load("validation");
  const SB = v.stocks.by_score, SP = v.stocks.picks, SS = v.setups.summary || {}, G = v.setups.by_grade || {};
  const secS = v.sectors.Sectoral, secT = v.sectors.Thematic;
  const R = v.regime;
  const pf = (b) => (isNum(b?.profit_factor) ? b.profit_factor.toFixed(2) : "–");

  // plain-English findings, computed from the numbers
  const find = [];
  const top = SB["3M"]["80+"], low = SB["3M"]["Below 40"];
  if (top && low) find.push(`Stocks scoring 80+ beat Nifty 500 by ${fmtPct(top.avg)} on average over the next 3 months, against ${fmtPct(low.avg)} for stocks scoring below 40. The stock score works, modestly.`);
  if (SP["3M"]) find.push(`The picks beat Nifty 500 by ${fmtPct(SP["3M"].Picks.avg)} over 3 months (${Math.round(SP["3M"].Picks.hit)}% of them beat it), against ${fmtPct(SP["3M"]["All other stocks"].avg)} for all other stocks.`);
  if (G.A && G.B) find.push(`A-grade setups ${G.A.profit_factor >= 1 ? "made" : "lost"} money (profit factor ${pf(G.A)}, ${fmtPct(G.A.avg_return)} per trade); B-grade setups ${G.B.profit_factor >= 1 ? "made" : "lost"} money (${pf(G.B)}, ${fmtPct(G.B.avg_return)}). Only ${Math.round(G.A.win_rate)}% of A-grade trades won, but the average win (${fmtPct(G.A.avg_win)}) was ${(G.A.avg_win / -G.A.avg_loss).toFixed(1)} times the average loss (${fmtPct(G.A.avg_loss)}), so expect several small losses for each big winner.`);
  const t3 = secS["3M"].by_rank["Top 3"], b3 = secS["3M"].by_rank["Bottom 3"];
  find.push(`The top 3 sectoral indices beat Nifty 500 by ${fmtPct(t3.avg)} over 3 months, the bottom 3 by ${fmtPct(b3.avg)}. A small edge. For thematic indices and for the RRG quadrants the edge is not reliable.`);
  find.push(`The regime light did not help in this period: Nifty 500 averaged ${fmtPct(R["3M"].Green.avg, 1)} in the 3 months after Green days and ${fmtPct(R["3M"].Red.avg, 1)} after Red days. The test window has no long bear market, which is when such a filter earns its keep, so treat the light as a sizing guide, not a buy/sell signal.`);

  const quarters = (v.setups.by_quarter || []).map((q) => [q.quarter, q.all, q.A]);
  const recent = v.setups.recent || [];

  app.replaceChildren(
    h("div", { class: "sector-title", style: "margin-top:18px" }, h("h1", null, "Track record")),
    h("p", { class: "lede" }, `How the model's choices did afterwards, using only data available on each test date. Tests run from ${fmtDate(v.period.tests_from)} to ${fmtDate(v.as_of)}; the latest 1–3 months can't be scored yet.`),
    h("div", { class: "panel" }, h("h2", null, "What the test says"),
      h("ul", { class: "findings" }, find.map((f) => h("li", null, f))),
      h("p", { class: "note" }, "Limits: about 17 months of tests, covering one rally, one correction and one recovery but no long bear market. The universe is today's Nifty Total Market list, so stocks that dropped out are missing; that flatters every group equally, which is why the comparisons between groups matter more than the absolute numbers. Past results do not guarantee future ones.")),

    h("section", null, h("div", { class: "section-head" }, h("h2", null, "Stock score"), h("p", null, `Every stock scored on the first session of each month (${v.stocks.rebalances} months)`)),
      h("div", { class: "grid-main" },
        h("div", { class: "panel" }, h("h2", null, "Next 3 months vs Nifty 500, by score"),
          h("p", { class: "sub" }, "Average return minus Nifty 500's"),
          barList(["80+", "60–80", "40–60", "Below 40"].map((b) => ({ label: `Score ${b}`, value: SB["3M"][b]?.avg, tip: `${SB["3M"][b]?.n} samples, ${Math.round(SB["3M"][b]?.hit)}% beat Nifty 500` })), (x) => fmtPct(x))),
        h("div", { class: "panel" }, h("h2", null, "Detail"),
          h("div", { class: "table-scroll" }, fwdTable("Score", SB, ["80+", "60–80", "40–60", "Below 40"])),
          h("div", { class: "table-scroll", style: "margin-top:14px" }, fwdTable("Group", SP, ["Picks", "All other stocks"]))))),

    h("section", null, h("div", { class: "section-head" }, h("h2", null, "Positional setups"),
      h("p", null, SS.first_signal ? `${fmtNum(SS.all?.trades)} setups, ${fmtDate(SS.first_signal)} to ${fmtDate(SS.last_signal)}, walked forward with the stop and exit rules` : "")),
      h("div", { class: "panel" },
        h("div", { class: "table-scroll" }, setupRows([
          ["Grade A", G.A], ["Grade B", G.B], ["All setups", SS.all],
          ...Object.entries(SS.by_setup || {}).map(([k, b]) => [k, b]),
          ...["Green", "Amber", "Red"].map((l) => [`Light ${l} at signal`, SS.by_light?.[l]])])),
        h("p", { class: "note" }, "Profit factor = total gains ÷ total losses. Each trade buys at the next open (tight base: when the price clears the trigger), exits at the stop, the first close below the 50-day average, or after 120 sessions. No costs included; about 0.2–0.3% per round trip for delivery trades."),
        h("h3", { class: "h3" }, "By quarter of the signal"),
        h("div", { class: "table-scroll" }, h("table", { class: "static" },
          h("thead", null, h("tr", null, h("th", { class: "l" }, "Quarter"), h("th", null, "All: trades"), h("th", null, "All: profit factor"), h("th", null, "All: avg"), h("th", null, "A-grade: trades"), h("th", null, "A-grade: profit factor"), h("th", null, "A-grade: avg"))),
          h("tbody", null, quarters.map(([q, a, b]) => h("tr", null, h("td", { class: "l name" }, q),
            h("td", null, fmtNum(a?.closed)), h("td", { class: isNum(a?.profit_factor) ? (a.profit_factor >= 1 ? "pos" : "neg") : "muted" }, pf(a)), h("td", { class: sign(a?.avg_return) }, fmtPct(a?.avg_return)),
            h("td", null, fmtNum(b?.closed)), h("td", { class: isNum(b?.profit_factor) ? (b.profit_factor >= 1 ? "pos" : "neg") : "muted" }, pf(b)), h("td", { class: sign(b?.avg_return) }, fmtPct(b?.avg_return))))))),
        h("p", { class: "note" }, "Results swing with the market: strong after a breadth thrust (2026 Q2), weak in a falling market (2026 Q3–Q4). The latest quarter only holds trades that have already closed, which are mostly losers; the winners are still open."),
        h("h3", { class: "h3" }, "Latest closed trades"),
        h("div", { class: "table-scroll" }, h("table", { class: "static" },
          h("thead", null, h("tr", null, ["Stock", "Setup", "Grade", "Bought", "Sold", "Buy", "Stop", "Exit", "Return", "R", "Days", "Why it closed"].map((c, i) => h("th", { class: i < 3 || i === 11 ? "l" : null }, c)))),
          h("tbody", null, recent.map((x) => h("tr", null,
            h("td", { class: "l name" }, x.symbol), h("td", { class: "l" }, x.setup), h("td", { class: "l" }, h("span", { class: `grade g${x.grade}` }, x.grade)),
            h("td", null, fmtDate(x.entry_date, { day: "numeric", month: "short", year: "2-digit" })), h("td", null, fmtDate(x.exit_date, { day: "numeric", month: "short", year: "2-digit" })),
            h("td", null, fmtNum(x.entry, 2)), h("td", null, fmtNum(x.stop, 2)), h("td", null, fmtNum(x.exit, 2)),
            h("td", { class: sign(x.return_pct) }, fmtPct(x.return_pct)), h("td", { class: sign(x.r) }, fmtX(x.r)),
            h("td", null, fmtNum(x.days)), h("td", { class: "l muted" }, x.exit_reason)))))))),

    leadershipSection(v.leadership),
    h("section", null, h("div", { class: "section-head" }, h("h2", null, "Sector ranking"), h("p", null, "Tested every 5th session")),
      h("div", { class: "grid-main" },
        h("div", { class: "panel" }, h("h2", null, "Sectoral indices"),
          h("div", { class: "table-scroll" }, fwdTable("Rank that day", { "1M": secS["1M"].by_rank, "3M": secS["3M"].by_rank }, ["Top 3", "Middle", "Bottom 3"])),
          h("div", { class: "table-scroll", style: "margin-top:14px" }, fwdTable("RRG quadrant", { "1M": secS["1M"].by_quadrant, "3M": secS["3M"].by_quadrant }, ["Leading", "Improving", "Weakening", "Lagging"]))),
        h("div", { class: "panel" }, h("h2", null, "Thematic indices"),
          h("div", { class: "table-scroll" }, fwdTable("Rank that day", { "1M": secT["1M"].by_rank, "3M": secT["3M"].by_rank }, ["Top 3", "Middle", "Bottom 3"])),
          h("div", { class: "table-scroll", style: "margin-top:14px" }, fwdTable("RRG quadrant", { "1M": secT["1M"].by_quadrant, "3M": secT["3M"].by_quadrant }, ["Leading", "Improving", "Weakening", "Lagging"]))))),

    h("section", null, h("div", { class: "section-head" }, h("h2", null, "Regime light"), h("p", null, "Nifty 500's own return after each light")),
      h("div", { class: "panel" },
        h("div", { class: "table-scroll" }, h("table", { class: "static" },
          h("thead", null, h("tr", null, h("th", { class: "l" }, "Light"), h("th", null, "Days"), h("th", null, "Next 1 month"), h("th", null, "Rose"), h("th", null, "Next 3 months"), h("th", null, "Rose"))),
          h("tbody", null, ["Green", "Amber", "Red"].map((l) => h("tr", null, h("td", { class: "l" }, lightChip(l)), h("td", null, fmtNum(R.days[l])),
            h("td", { class: sign(R["1M"][l]?.avg) }, fmtPct(R["1M"][l]?.avg)), h("td", null, isNum(R["1M"][l]?.hit) ? `${Math.round(R["1M"][l].hit)}%` : "–"),
            h("td", { class: sign(R["3M"][l]?.avg) }, fmtPct(R["3M"][l]?.avg)), h("td", null, isNum(R["3M"][l]?.hit) ? `${Math.round(R["3M"][l].hit)}%` : "–")))))),
        h("p", { class: "note" }, `Here the column is Nifty 500's own return, not the excess over it. With the 5-session buffer the light changed ${R.changes?.buffered ?? "–"} times since ${R.changes?.since ? fmtDate(R.changes.since) : "–"}, against ${R.changes?.raw ?? "–"} times without it.`),
        R.turning_events ? [h("h3", { class: "h3" }, "Turning-point trackers: every stage signal"),
          h("div", { class: "table-scroll" }, h("table", { class: "static" },
            h("thead", null, h("tr", null, h("th", { class: "l" }, "First day"), h("th", { class: "l" }, "Tracker"), h("th", { class: "l" }, "Stage"), h("th", null, "Nifty 500"), h("th", null, "Next 1 month"), h("th", null, "Next 3 months"))),
            h("tbody", null, R.turning_events.map((e) => h("tr", null, h("td", { class: "l" }, fmtDate(e.date)),
              h("td", { class: "l" }, e.side === "bottom" ? "Seller exhaustion" : "Distribution"),
              h("td", { class: "l name" }, `${e.stage}. ${e.name}`), h("td", null, fmtNum(e.n500, 0)),
              h("td", { class: sign(e["1M"]) }, fmtPct(e["1M"])), h("td", { class: sign(e["3M"]) }, fmtPct(e["3M"]))))))),
          h("p", { class: "note" }, "Stage 2 is the early signal and is often wrong on its own (Dec 2025–Feb 2026 had several failed bottoms); stage 3 is slower but more reliable. A bottom signal should be followed by a rise, a top signal by a fall.")] : null,
        R.warnings ? [h("h3", { class: "h3" }, "Early warnings from the internals"),
          h("div", { class: "table-scroll" }, h("table", { class: "static" },
            h("thead", null, h("tr", null, h("th", { class: "l" }, "First day"), h("th", { class: "l" }, "Warning"), h("th", null, "Nifty 500"), h("th", null, "Gauge"), h("th", null, "Next 1 month"), h("th", null, "Next 3 months"))),
            h("tbody", null, R.warnings.map((e) => h("tr", null, h("td", { class: "l" }, fmtDate(e.date)), h("td", { class: "l name" }, e.kind),
              h("td", null, fmtNum(e.n500, 0)), h("td", null, isNum(e.internals) ? Math.round(e.internals) : "–"),
              h("td", { class: sign(e["1M"]) }, fmtPct(e["1M"])), h("td", { class: sign(e["3M"]) }, fmtPct(e["3M"]))))))),
          h("p", { class: "note" }, `For comparison, Nifty 500 averaged ${fmtPct(R.base?.["1M"])} over any 1 month and ${fmtPct(R.base?.["3M"])} over any 3 months in this period. A topping warning is a reason to tighten stops and slow down buying; about half of them came before a real fall.`)] : null)));
}


// ------------------------------------------------------------------ My Trades (private, Supabase)
const CFG = window.SS_CONFIG || {};
const SB_READY = Boolean(CFG.supabaseUrl && CFG.supabaseAnonKey && window.supabase);
const sb = SB_READY ? window.supabase.createClient(CFG.supabaseUrl, CFG.supabaseAnonKey, {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
}) : null;
const COST_PCT = 0.25;              // default delivery costs when no charges are entered
const RULES = {
  system: "Setup rules: stop, target, first close below 50-day, or 120 sessions",
  stop_target: "Stop or target only",
  manual: "I close it myself",
};
const inr = (v) => (isNum(v) ? `${v < 0 ? "−" : ""}₹${Math.abs(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : "–");
const todayISO = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);

async function session() {
  if (!sb) return null;
  const { data } = await sb.auth.getSession();
  return data.session;
}
async function tradesQuery(fn) {
  const { data, error } = await fn(sb.from("cash_trades"));
  if (error) throw new Error(/relation .* does not exist|cash_trades/i.test(error.message)
    ? "the cash_trades table is not set up yet (run supabase/003_cash_trades.sql in Supabase)" : error.message);
  return data;
}
function netOf(t, exit) {
  const qty = +t.qty, entry = +t.entry;
  const cost = isNum(t.charges) ? t.charges : entry * qty * COST_PCT / 100;
  const net = (exit - entry) * qty - cost;
  return { pnl_inr: +net.toFixed(2), net_pct: +((net / (entry * qty)) * 100).toFixed(3) };
}

/* Open the add/edit dialog. If not signed in, remember the trade and go to My Trades. */
async function takeTrade(prefill) {
  if (!(await session())) { state.pendingTrade = prefill; location.hash = "#/trades"; return; }
  tradeDialog(prefill, () => { if (location.hash !== "#/trades") location.hash = "#/trades"; else route(); });
}

function tradeDialog(prefill, onSaved) {
  const dlg = document.getElementById("dlg");
  const t = { exit_rule: "system", entry_date: todayISO(), ...prefill };
  const field = (label, name, attrs = {}, wide = false) =>
    h("label", { class: wide ? "wide" : null }, label, h("input", { name, value: t[name] ?? "", ...attrs }));
  const err = h("p", { class: "err", role: "alert" });
  const warn = h("p", { class: "warn-box", role: "status", hidden: true });
  const checkResults = async (sym) => {
    const st = await load("stocks").catch(() => null);
    const r = st?.results?.[String(sym || "").trim().toUpperCase()];
    if (r && r.days >= 0 && r.days <= 7) {
      warn.textContent = `${String(sym).toUpperCase()} announces quarterly results ${r.days === 0 ? "today" : `on ${fmtDate(r.date)} (in ${r.days} day${r.days > 1 ? "s" : ""})`}. The price can gap through your stop on the news; consider waiting or a smaller position.`;
      warn.hidden = false;
    } else warn.hidden = true;
  };
  const form = h("form", { method: "dialog" },
    h("h2", null, t.id ? `Edit ${t.symbol}` : t.symbol ? `I took this trade: ${t.symbol}` : "Add a trade"),
    warn,
    h("p", { class: "note" }, `Cash-market buy (delivery). P&L = (exit − buy) × quantity − charges; if you leave charges empty, ${COST_PCT}% of the buy value is deducted.`),
    h("div", { class: "form-grid" },
      field("Symbol (NSE)", "symbol", { required: true, autocapitalize: "characters" }),
      field("Buy date", "entry_date", { type: "date", required: true }),
      field("Buy price", "entry", { type: "number", step: "any", min: "0", required: true }),
      field("Quantity", "qty", { type: "number", step: "1", min: "1", required: true }),
      field("Stop", "stop", { type: "number", step: "any", min: "0" }),
      field("Target (optional)", "target", { type: "number", step: "any", min: "0" }),
      h("label", { class: "wide" }, "Exit rule", h("select", { name: "exit_rule" },
        Object.entries(RULES).map(([k, l]) => h("option", { value: k, selected: t.exit_rule === k || null }, l)))),
      field("Setup", "setup", { placeholder: "e.g. Breakout, Pullback" }),
      field("Charges ₹ (optional)", "charges", { type: "number", step: "any", min: "0" }),
      h("label", { class: "wide" }, "Notes", h("textarea", { name: "notes" }, t.notes || ""))),
    err,
    h("div", { class: "btn-row" },
      h("button", { class: "btn primary", type: "submit" }, "Save trade"),
      h("button", { class: "btn", type: "button", onclick: () => dlg.close() }, "Cancel")));
  form.querySelector("input[name=symbol]").addEventListener("change", (e) => checkResults(e.target.value));
  if (t.symbol && t.status !== "closed") checkResults(t.symbol);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const v = Object.fromEntries(new FormData(form).entries());
    const row = {
      symbol: v.symbol.trim().toUpperCase(), entry_date: v.entry_date, entry: +v.entry, qty: +v.qty,
      stop: v.stop ? +v.stop : null, target: v.target ? +v.target : null, exit_rule: v.exit_rule,
      setup: v.setup || null, charges: v.charges !== "" ? +v.charges : null, notes: v.notes || null,
    };
    if (row.stop && row.stop >= row.entry) { err.textContent = "The stop must be below the buy price."; return; }
    try {
      if (t.id) {
        if (t.status === "closed" && isNum(t.exit)) Object.assign(row, netOf({ ...t, ...row }, t.exit));
        await tradesQuery((q) => q.update(row).eq("id", t.id));
      } else {
        await tradesQuery((q) => q.insert({ ...row, status: "open", grade: t.grade || null, sector: t.sector || null, source: t.source || "manual" }));
      }
      dlg.close();
      onSaved && onSaved();
    } catch (ex) { err.textContent = `Could not save: ${ex.message}`; }
  });
  dlg.replaceChildren(form);
  if (!dlg.open) dlg.showModal();
}

function closeTradeDialog(t, onSaved) {
  const dlg = document.getElementById("dlg");
  const err = h("p", { class: "err", role: "alert" });
  const form = h("form", { method: "dialog" },
    h("h2", null, `Sell ${t.symbol}`),
    h("p", { class: "note" }, `Bought ${fmtNum(t.qty)} at ${fmtNum(t.entry, 2)} on ${fmtDate(t.entry_date)}.`),
    h("div", { class: "form-grid" },
      h("label", null, "Sell price", h("input", { name: "exit", type: "number", step: "any", min: "0", required: true, value: t.last_close ?? "" })),
      h("label", null, "Sell date", h("input", { name: "exit_date", type: "date", value: todayISO(), required: true })),
      h("label", { class: "wide" }, "Reason", h("input", { name: "exit_reason", value: "Sold by hand" }))),
    err,
    h("div", { class: "btn-row" }, h("button", { class: "btn primary", type: "submit" }, "Close trade"),
      h("button", { class: "btn", type: "button", onclick: () => dlg.close() }, "Cancel")));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const v = Object.fromEntries(new FormData(form).entries());
    const exit = +v.exit;
    try {
      await tradesQuery((q) => q.update({ exit, exit_date: v.exit_date, exit_reason: v.exit_reason, status: "closed", alert: null, ...netOf(t, exit) }).eq("id", t.id));
      dlg.close(); onSaved && onSaved();
    } catch (ex) { err.textContent = ex.message; }
  });
  dlg.replaceChildren(form);
  dlg.showModal();
}

function signInView(app, message) {
  const email = h("input", { type: "email", value: CFG.email || "", required: true, autocomplete: "username" });
  const pass = h("input", { type: "password", required: true, autocomplete: "current-password" });
  const msg = h("p", { class: "err", role: "status" }, message || "");
  const btn = h("button", { class: "btn primary", type: "submit" }, "Sign in");
  const form = h("form", { class: "panel signin" },
    h("h1", null, "My Trades"),
    h("p", { class: "sub" }, "Your trade log is private. Sign in with the same email and password as the F&O Desk; you stay signed in on this device."),
    h("label", null, "Email", email), h("div", { style: "height:10px" }),
    h("label", null, "Password", pass),
    h("label", { class: "toggle", style: "margin-top:8px;display:inline-flex" },
      h("input", { type: "checkbox", onchange: (e) => { pass.type = e.target.checked ? "text" : "password"; } }), "Show password"),
    h("div", { style: "height:14px" }), btn, msg);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    btn.disabled = true; msg.textContent = "";
    const { error } = await sb.auth.signInWithPassword({ email: email.value.trim(), password: pass.value });
    btn.disabled = false;
    if (error) msg.textContent = /invalid/i.test(error.message) ? "Email or password is wrong." : `Could not sign in: ${error.message}`;
    else route();
  });
  app.replaceChildren(form);
}

function bigStat(k, v, d, cls) {
  return h("div", { class: "stat" }, h("div", { class: "k" }, k), h("div", { class: `v ${cls || ""}` }, v), d ? h("div", { class: "d" }, d) : null);
}

async function viewTrades(app) {
  if (!SB_READY) { app.replaceChildren(h("p", { class: "empty" }, "My Trades needs the database settings in config.js.")); return; }
  const ses = await session();
  if (!ses) return signInView(app);
  if (CFG.email && ses.user.email.toLowerCase() !== CFG.email.toLowerCase()) return signInView(app, `${ses.user.email} does not have access.`);
  if (state.pendingTrade) { const p = state.pendingTrade; state.pendingTrade = null; setTimeout(() => takeTrade(p), 0); }

  const [rows, st] = await Promise.all([
    tradesQuery((q) => q.select("*").order("entry_date", { ascending: false }).order("id", { ascending: false })),
    load("stocks").catch(() => null)]);
  const rerender = () => route();
  const open = rows.filter((t) => t.status === "open"), closed = rows.filter((t) => t.status === "closed");

  // latest price: the evening check's close, or the site's own close if that is newer
  const price = (t) => {
    const s = st?.stocks?.[t.symbol];
    if (s && isNum(s.close) && (!t.last_date || st.as_of > t.last_date)) return { px: s.close, date: st.as_of };
    return { px: t.last_close, date: t.last_date };
  };
  let invested = 0, openPnl = 0;
  for (const t of open) {
    const { px } = price(t);
    invested += t.entry * t.qty;
    if (isNum(px)) openPnl += (px - t.entry) * t.qty;
  }
  const pcts = closed.map((t) => t.net_pct).filter(isNum);
  const wins = pcts.filter((v) => v > 0), losses = pcts.filter((v) => v <= 0);
  const sum = (a) => a.reduce((x, y) => x + y, 0);
  const inrClosed = closed.map((t) => t.pnl_inr).filter(isNum);
  const invClosed = sum(closed.map((t) => t.entry * t.qty));
  const pf = losses.length ? sum(wins) / Math.abs(sum(losses)) : null;
  const stats = h("div", { class: "stats six" },
    bigStat("Closed trades", fmtNum(closed.length), `${open.length} open`),
    bigStat("Win rate", pcts.length ? `${Math.round((wins.length / pcts.length) * 100)}%` : "–", `${wins.length} won, ${losses.length} lost`),
    bigStat("Net P&L in ₹", inrClosed.length ? inr(sum(inrClosed)) : "–", "Closed trades, after charges", sign(sum(inrClosed))),
    bigStat("Net P&L in %", invClosed ? fmtPct((sum(inrClosed) / invClosed) * 100, 2) : "–", "Of the money put into closed trades", sign(sum(inrClosed))),
    bigStat("Avg win / loss", wins.length || losses.length ? `${fmtPct(wins.length ? sum(wins) / wins.length : null)} / ${fmtPct(losses.length ? sum(losses) / losses.length : null)}` : "–",
      isNum(pf) ? `Profit factor ${pf.toFixed(2)}` : "Net % per trade"),
    bigStat("Open positions", inr(invested), open.length ? h("span", { class: sign(openPnl) }, `Unrealised ${inr(openPnl)} (${fmtPct(invested ? (openPnl / invested) * 100 : null)})`) : "Nothing open"));

  // month by month, by the month the trade was closed
  const months = {};
  for (const t of closed) {
    const m = String(t.exit_date || t.entry_date).slice(0, 7);
    const g = (months[m] ||= { n: 0, w: 0, inr: 0, inv: 0, pcts: [] });
    g.n += 1; g.inv += t.entry * t.qty;
    if (isNum(t.net_pct)) { g.pcts.push(t.net_pct); if (t.net_pct > 0) g.w += 1; }
    if (isNum(t.pnl_inr)) g.inr += t.pnl_inr;
  }
  const monthTable = h("table", { class: "static" },
    h("thead", null, h("tr", null, ["Month", "Trades", "Won / lost", "Win rate", "Net ₹", "Net %", "Avg per trade"].map((c, i) => h("th", { class: i ? null : "l" }, c)))),
    h("tbody", null, Object.keys(months).sort().reverse().map((m) => {
      const g = months[m];
      return h("tr", null, h("td", { class: "l name" }, fmtDate(`${m}-01`, { month: "short", year: "numeric" })), h("td", null, g.n),
        h("td", null, `${g.w} / ${g.n - g.w}`), h("td", null, g.pcts.length ? `${Math.round((g.w / g.pcts.length) * 100)}%` : "–"),
        h("td", { class: sign(g.inr) }, inr(g.inr)), h("td", { class: sign(g.inr) }, g.inv ? fmtPct((g.inr / g.inv) * 100, 2) : "–"),
        h("td", { class: sign(sum(g.pcts)) }, g.pcts.length ? fmtPct(sum(g.pcts) / g.pcts.length, 2) : "–"));
    })));

  const actions = (t, isOpen) => h("td", { class: "l" }, h("div", { class: "btn-row" },
    isOpen ? h("button", { class: "btn small", type: "button", onclick: () => closeTradeDialog(t, rerender) }, "Sell") : null,
    h("button", { class: "btn small", type: "button", onclick: () => tradeDialog(t, rerender) }, "Edit"),
    h("button", { class: "btn small", type: "button", onclick: async () => {
      if (confirm(`Delete the ${t.symbol} trade? This cannot be undone.`)) { await tradesQuery((q) => q.delete().eq("id", t.id)); rerender(); }
    } }, "Delete")));
  const nameCell = (t) => h("td", { class: "l name" }, t.symbol,
    h("small", null, [t.setup, t.grade ? `grade ${t.grade}` : null, t.sector].filter(Boolean).join(" · ") || "manual"));

  const openTable = h("table", { class: "static" },
    h("thead", null, h("tr", null, ["Bought", "Stock", "Qty", "Buy", "Last close", "P&L ₹", "P&L %", "Stop", "To stop", "50-day avg", "Held", "Exit rule", ""].map((c, i) =>
      h("th", { class: [0, 1, 11, 12].includes(i) ? "l" : null }, c)))),
    h("tbody", null, open.map((t) => {
      const { px, date } = price(t);
      const p = isNum(px) ? (px - t.entry) * t.qty : null;
      return h("tr", null,
        h("td", { class: "l" }, fmtDate(t.entry_date, { day: "numeric", month: "short", year: "2-digit" })),
        nameCell(t), h("td", null, fmtNum(t.qty)), h("td", null, fmtNum(t.entry, 2)),
        h("td", { title: date ? `Close on ${fmtDate(date)}` : null }, fmtNum(px, 2)),
        h("td", { class: sign(p) }, inr(p)), h("td", { class: sign(p) }, isNum(px) ? fmtPct((px / t.entry - 1) * 100, 2) : "–"),
        h("td", null, fmtNum(t.stop, 2)),
        h("td", null, isNum(px) && isNum(t.stop) ? fmtPct((t.stop / px - 1) * 100, 1) : "–"),
        h("td", { class: isNum(px) && isNum(t.sma50) && px < t.sma50 ? "neg" : null }, fmtNum(t.sma50, 2)),
        h("td", null, isNum(t.sessions_held) ? `${t.sessions_held}d` : "–"),
        h("td", { class: "l" }, h("span", { class: "rule" }, { system: "Setup rules", stop_target: "Stop/target", manual: "Manual" }[t.exit_rule] || "–"),
          t.alert ? h("span", { class: "alert" }, t.alert) : null,
          (() => { const r = st?.results?.[t.symbol]; return r && r.days >= 0 ? h("span", { class: r.days <= 7 ? "alert" : "rule" }, `Results ${fmtDate(r.date, { day: "numeric", month: "short" })}`) : null; })()),
        actions(t, true));
    })));
  const closedTable = h("table", { class: "static" },
    h("thead", null, h("tr", null, ["Bought", "Sold", "Stock", "Qty", "Buy", "Sell", "Net ₹", "Net %", "Days", "Why", ""].map((c, i) =>
      h("th", { class: [0, 1, 2, 9, 10].includes(i) ? "l" : null }, c)))),
    h("tbody", null, closed.map((t) => {
      const days = t.exit_date ? Math.round((new Date(t.exit_date) - new Date(t.entry_date)) / 86400000) : null;
      return h("tr", null,
        h("td", { class: "l" }, fmtDate(t.entry_date, { day: "numeric", month: "short", year: "2-digit" })),
        h("td", { class: "l" }, fmtDate(t.exit_date, { day: "numeric", month: "short", year: "2-digit" })),
        nameCell(t), h("td", null, fmtNum(t.qty)), h("td", null, fmtNum(t.entry, 2)), h("td", null, fmtNum(t.exit, 2)),
        h("td", { class: sign(t.pnl_inr) }, inr(t.pnl_inr)), h("td", { class: sign(t.net_pct) }, fmtPct(t.net_pct, 2)),
        h("td", null, isNum(days) ? fmtNum(days) : "–"), h("td", { class: "l muted" }, t.exit_reason || "–"),
        actions(t, false));
    })));

  app.replaceChildren(
    h("div", { class: "page-head" }, h("h1", null, "My Trades"),
      h("div", { class: "who" }, h("span", null, ses.user.email),
        h("button", { class: "btn small", type: "button", onclick: async () => { await sb.auth.signOut(); route(); } }, "Sign out"))),
    h("p", { class: "sub", style: "color:var(--muted);font-size:13px;margin:0 0 10px" },
      "Cash-market positional trades, saved privately. Every weekday evening open trades get the latest close and 50-day average, and are closed automatically when their exit rule says so."),
    h("div", { class: "filters" },
      h("button", { class: "btn primary", type: "button", onclick: () => tradeDialog({}, rerender) }, "Add a trade"),
      h("button", { class: "btn", type: "button", onclick: () => exportTrades(rows) }, "Export CSV"),
      h("span", { class: "note", style: "margin:0" }, "Or use “I took this trade” on a setup in Stock picks.")),
    stats,
    h("section", null, h("div", { class: "section-head" }, h("h2", null, `Open (${open.length})`)),
      open.length ? h("div", { class: "panel" }, h("div", { class: "table-scroll" }, openTable)) : h("p", { class: "empty" }, "No open trades.")),
    Object.keys(months).length ? h("section", null, h("div", { class: "section-head" }, h("h2", null, "Month by month"), h("p", null, "Closed trades, by the month they were sold")),
      h("div", { class: "panel" }, h("div", { class: "table-scroll" }, monthTable))) : null,
    h("section", null, h("div", { class: "section-head" }, h("h2", null, `Closed (${closed.length})`)),
      closed.length ? h("div", { class: "panel" }, h("div", { class: "table-scroll" }, closedTable)) : h("p", { class: "empty" }, "No closed trades yet.")));
}

function exportTrades(rows) {
  const cols = ["symbol", "entry_date", "entry", "qty", "stop", "target", "exit_rule", "setup", "grade", "sector", "charges",
    "status", "exit_date", "exit", "exit_reason", "pnl_inr", "net_pct", "last_close", "last_date", "notes"];
  const esc = (v) => (v == null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  const csv = [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
  const a = h("a", { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: "my_trades_cash.csv" });
  document.body.append(a); a.click(); a.remove();
}

// ------------------------------------------------------------------ routing
async function route() {
  const app = document.getElementById("app");
  const hash = location.hash || "#/";
  const m = hash.match(/^#\/sector\/([A-Z0-9]+)/);
  const page = m ? "sector" : hash.startsWith("#/picks") ? "picks" : hash.startsWith("#/record") ? "record" : hash.startsWith("#/trades") ? "trades" : "overview";
  document.querySelectorAll(".nav a").forEach((a) => a.toggleAttribute("aria-current", a.dataset.page === page));
  document.querySelectorAll(".nav a").forEach((a) => { if (a.dataset.page === page) a.setAttribute("aria-current", "page"); });
  try {
    const sec = await load("sectors");
    document.getElementById("asof").textContent = `NSE end-of-day data, ${fmtDate(sec.as_of)}`;
    if (page === "sector") await viewSector(app, m[1]);
    else if (page === "picks") await viewPicks(app);
    else if (page === "record") await viewRecord(app);
    else if (page === "trades") await viewTrades(app);
    else await viewOverview(app);
  } catch (err) {
    app.replaceChildren(h("p", { class: "empty" }, page === "trades"
      ? `Your trades could not be loaded: ${err.message}. Refresh to try again.`
      : `The data could not be loaded (${err.message}). Refresh the page; if it persists, the daily update may have failed.`));
  }
}
window.addEventListener("hashchange", () => { window.scrollTo(0, 0); route(); });

document.getElementById("theme").addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  const next = dark ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  store("ss-theme", next);
  route();   // redraw charts with the new colours
});

route();
