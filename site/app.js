/* Sector Strength - static site.
   Reads JSON produced by analysis/build.py from ./data/ and renders three
   views with hash routing: #/ (overview), #/sector/KEY, #/picks.
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
};
const cache = {};
const QUAD = ["Leading", "Weakening", "Lagging", "Improving"];
const QVAR = { Leading: "--q-leading", Weakening: "--q-weakening", Lagging: "--q-lagging", Improving: "--q-improving" };

function store(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* storage off */ } }
function recall(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
(function restore() {
  const b = recall("ss-bench"); if (b === "NIFTY500" || b === "NIFTY50") state.bench = b;
  const g = recall("ss-group"); if (g === "Sectoral" || g === "Thematic") state.group = g;
  state.fnoOnly = recall("ss-fno") === "1";
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
const fmtPct = (v, d = 1, signed = true) => (isNum(v) ? `${signed && v > 0 ? "+" : ""}${v.toFixed(d)}%` : "–");
const sign = (v) => (isNum(v) ? (v > 0 ? "pos" : v < 0 ? "neg" : "") : "muted");
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

// ------------------------------------------------------------------ views
async function viewOverview(app) {
  const [sec, br, st] = await Promise.all([load("sectors"), load("breadth"), load("stocks")]);
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
        hasAD ? chartCard("Advance–decline line", "Running total of advances minus declines, all NSE stocks. Falling while the index holds up is a warning sign.",
          timeChart({ dates: D, series: [{ name: "A/D line", values: S2.ad_line, color: css("--s1") }], fmt: (v) => fmtNum(v) })) : null,
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

  app.replaceChildren(filtersRow(), lede, main, breadth, focusSec);
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
        (x.flags || []).filter((f) => f !== "F&O").map((f) => h("span", { class: "flag" }, f)),
        x.fno ? h("span", { class: "flag fno" }, "F&O") : null,
        showVia && x.via === "industry" ? h("span", { class: "flag" }, "peer") : null)))));
}

async function viewPicks(app) {
  const [sec, st] = await Promise.all([load("sectors"), load("stocks")]);
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
        h("p", { class: "sub" }, `Up to ${st.picks_per_sector} per sector with score ${st.filters.min_pick_score}+, market cap ₹${st.filters.min_mcap_cr} cr+, traded value ₹${st.filters.min_traded_value_cr} cr+ a day. Focus sectors are those Leading or Improving vs ${B.name}, plus the top 5.`),
        rows.length ? h("div", { class: "table-scroll" }, stockTable(rows, cols, state.pickSort, render, false, lead)) : h("p", { class: "empty" }, "No stocks match these filters.")));
  };
  render();
  app.replaceChildren(
    filtersRow(h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: state.fnoOnly || null,
      onchange: (e) => { state.fnoOnly = e.target.checked; store("ss-fno", state.fnoOnly ? "1" : "0"); render(); } }), "F&O stocks only")),
    h("div", { style: "height:10px" }), holder);
}

// ------------------------------------------------------------------ routing
async function route() {
  const app = document.getElementById("app");
  const hash = location.hash || "#/";
  const m = hash.match(/^#\/sector\/([A-Z0-9]+)/);
  const page = m ? "sector" : hash.startsWith("#/picks") ? "picks" : "overview";
  document.querySelectorAll(".nav a").forEach((a) => a.toggleAttribute("aria-current", a.dataset.page === page));
  document.querySelectorAll(".nav a").forEach((a) => { if (a.dataset.page === page) a.setAttribute("aria-current", "page"); });
  try {
    const sec = await load("sectors");
    document.getElementById("asof").textContent = `NSE end-of-day data, ${fmtDate(sec.as_of)}`;
    if (page === "sector") await viewSector(app, m[1]);
    else if (page === "picks") await viewPicks(app);
    else await viewOverview(app);
  } catch (err) {
    app.replaceChildren(h("p", { class: "empty" }, `The data could not be loaded (${err.message}). Refresh the page; if it persists, the daily update may have failed.`));
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
