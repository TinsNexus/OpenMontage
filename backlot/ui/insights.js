import { el, fmtAgo, getJSON } from "/ui/lib.js";

const THEME_KEY = "backlot.theme";
const SEL_KEY = "backlot.insights.selected";
const SORT_KEY = "backlot.insights.reelSort";
const main = document.getElementById("main");
const toolbar = document.getElementById("toolbar");
const tip = document.getElementById("tip");

let meta = null;      // /api/insights
let view = null;      // /api/insights/<page>/<snap>
let sel = parseSel(storageGet(SEL_KEY));
let reelSort = parseSel(storageGet(SORT_KEY)) || { key: "plays", dir: "desc" };

function storageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function storageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* ignore */ } }
function parseSel(s) { try { return s ? JSON.parse(s) : null; } catch { return null; } }
document.documentElement.dataset.theme = storageGet(THEME_KEY) === "light" ? "light" : "dark";

async function post(url, body = {}, action = "insights") {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Backlot-Action": action },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

// ---------------------------------------------------------------- formatting

const nf = new Intl.NumberFormat("vi-VN");
const fmtN = (v) => (v == null || !Number.isFinite(Number(v)) ? "—" : nf.format(Math.round(Number(v))));
const fmtPct = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);
const fmtDate = (iso) => {
  if (!iso) return "";
  const d = new Date(iso.replace("+0000", "Z"));
  return Number.isNaN(d.getTime()) ? iso.slice(0, 10) : d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" });
};
const fmtDateTime = (iso) => {
  if (!iso) return "";
  const d = new Date(iso.replace("+0000", "Z"));
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("vi-VN", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
};
const snapLabel = (s) => `${s.id.slice(0, 10)} ${s.id.slice(11, 13)}:${s.id.slice(13, 15)} · ${s.reels} reels`;
const reelName = (r) => (r.project && r.project.project_title) || r.description.slice(0, 50) || r.id;

// ---------------------------------------------------------------- tooltip

function showTip(evt, nodes) {
  tip.innerHTML = "";
  tip.append(...nodes);
  tip.hidden = false;
  const pad = 14;
  const { innerWidth: w, innerHeight: h } = window;
  const r = tip.getBoundingClientRect();
  let x = evt.clientX + pad;
  let y = evt.clientY + pad;
  if (x + r.width > w - 8) x = evt.clientX - r.width - pad;
  if (y + r.height > h - 8) y = evt.clientY - r.height - pad;
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${Math.max(8, y)}px`;
}
function hideTip() { tip.hidden = true; }

// ---------------------------------------------------------------- svg helpers

const SVGNS = "http://www.w3.org/2000/svg";
function s(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c != null) node.append(c.nodeType ? c : document.createTextNode(String(c)));
  return node;
}
function niceMax(v) {
  if (!v || v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

// Followers over time: single series line, crosshair + tooltip.
function followersChart(points) {
  const W = 560, H = 200, L = 34, R = 16, T = 14, B = 26;
  const pts = points.filter((p) => p.value != null);
  if (pts.length < 2) return el("p", { class: "hint" }, "Chưa đủ dữ liệu follower theo ngày.");
  const maxY = niceMax(Math.max(...pts.map((p) => p.value)));
  const x = (i) => L + (i / (pts.length - 1)) * (W - L - R);
  const y = (v) => T + (1 - v / maxY) * (H - T - B);
  const path = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join("");
  const area = `${path}L${x(pts.length - 1)},${y(0)}L${x(0)},${y(0)}Z`;
  const ticks = Number.isInteger(maxY / 2) ? [0, maxY / 2, maxY] : [0, maxY];
  const last = pts[pts.length - 1];
  const cross = s("line", { class: "cross", y1: T, y2: H - B, visibility: "hidden" });
  const hover = s("circle", { class: "dot", r: 4, visibility: "hidden" });
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": `Follower theo ngày, từ ${pts[0].value} lên ${last.value}` },
    ticks.map((t) => s("g", { class: "axis" },
      s("line", { class: t ? "grid" : "base", x1: L, x2: W - R, y1: y(t), y2: y(t) }),
      s("text", { x: L - 6, y: y(t) + 3, "text-anchor": "end" }, fmtN(t)))),
    s("text", { class: "lab", x: L, y: H - 8 }, fmtDate(pts[0].date)),
    s("text", { class: "lab", x: W - R, y: H - 8, "text-anchor": "end" }, fmtDate(last.date)),
    s("path", { class: "area", d: area }),
    s("path", { class: "line", d: path }),
    s("circle", { class: "dot", cx: x(pts.length - 1), cy: y(last.value), r: 4 }),
    s("text", { class: "lab strong", x: x(pts.length - 1) - 8, y: y(last.value) - 9, "text-anchor": "end" }, fmtN(last.value)),
    cross, hover,
  );
  const overlay = s("rect", { class: "hit", x: L, y: T, width: W - L - R, height: H - T - B });
  overlay.addEventListener("mousemove", (evt) => {
    const box = svg.getBoundingClientRect();
    const px = ((evt.clientX - box.left) / box.width) * W;
    const i = Math.max(0, Math.min(pts.length - 1, Math.round(((px - L) / (W - L - R)) * (pts.length - 1))));
    const p = pts[i];
    cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
    hover.setAttribute("cx", x(i)); hover.setAttribute("cy", y(p.value)); hover.setAttribute("visibility", "visible");
    showTip(evt, [el("b", {}, fmtN(p.value)), " follower", el("div", { class: "mut" }, p.date)]);
  });
  overlay.addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); hover.setAttribute("visibility", "hidden"); hideTip(); });
  svg.append(overlay);
  return svg;
}

// Reel length vs retention: one dot per reel; the top reel is labelled.
function retentionChart(reels) {
  const rs = reels.filter((r) => r.length_s && r.retention != null);
  if (!rs.length) return el("p", { class: "hint" }, "Chưa có reel nào đủ dữ liệu thời lượng xem.");
  const W = 560, H = 220, L = 38, R = 16, T = 14, B = 30;
  const maxX = niceMax(Math.max(...rs.map((r) => r.length_s)));
  const x = (v) => L + (v / maxX) * (W - L - R);
  const y = (v) => T + (1 - v) * (H - T - B);
  const top = rs.reduce((a, b) => ((b.plays || 0) > (a.plays || 0) ? b : a));
  const xt = [0, maxX / 2, maxX];
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Độ dài reel so với tỉ lệ xem hết" },
    [0, 0.5, 1].map((t) => s("g", { class: "axis" },
      s("line", { class: t ? "grid" : "base", x1: L, x2: W - R, y1: y(t), y2: y(t) }),
      s("text", { x: L - 6, y: y(t) + 3, "text-anchor": "end" }, `${t * 100}%`))),
    xt.map((t) => s("text", { class: "lab", x: x(t), y: H - 12, "text-anchor": t ? (t === maxX ? "end" : "middle") : "start" }, `${Math.round(t)}s`)),
    s("text", { class: "lab", x: W - R, y: H, "text-anchor": "end" }, "độ dài reel"),
  );
  for (const r of rs) {
    const cx = x(r.length_s), cy = y(r.retention);
    svg.append(s("circle", { class: r === top ? "dot" : "dot muted", cx, cy, r: 5 }));
    const hit = s("circle", { class: "hit", cx, cy, r: 13, tabindex: "0", "aria-label": `${reelName(r)}: ${r.length_s}s, xem hết ${fmtPct(r.retention)}` });
    const tipNodes = () => [el("b", {}, reelName(r)),
      el("div", { class: "mut" }, `${Math.round(r.length_s)}s · xem TB ${r.avg_watch_s}s · xem hết ${fmtPct(r.retention)}`),
      el("div", { class: "mut" }, `${fmtN(r.plays)} lượt phát`)];
    hit.addEventListener("mousemove", (evt) => showTip(evt, tipNodes()));
    hit.addEventListener("mouseleave", hideTip);
    hit.addEventListener("focus", () => { const b = hit.getBoundingClientRect(); showTip({ clientX: b.right, clientY: b.top }, tipNodes()); });
    hit.addEventListener("blur", hideTip);
    svg.append(hit);
  }
  const tx = x(top.length_s), ty = y(top.retention);
  svg.append(s("text", { class: "lab strong", x: tx + 9, y: ty - 8 }, `${reelName(top).slice(0, 28)} · ${fmtN(top.plays)} lượt`));
  return svg;
}

// Plays per character: horizontal bars, value labels in text ink.
function characterChart(rows) {
  if (!rows.length) return el("p", { class: "hint" }, "Chưa có reel.");
  const W = 420, rowH = 30, L = 70, R = 70, H = rows.length * rowH + 8;
  const max = Math.max(...rows.map((r) => r.plays)) || 1;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Lượt phát reels theo nhân vật" });
  rows.forEach((r, i) => {
    const yy = 4 + i * rowH;
    const w = Math.max(2, (r.plays / max) * (W - L - R));
    svg.append(
      s("text", { class: "lab strong", x: L - 8, y: yy + 16, "text-anchor": "end" }, r.character),
      s("rect", { class: "bar", x: L, y: yy + 6, width: w, height: 14, rx: 4 }),
      s("text", { class: "lab", x: L + w + 6, y: yy + 17 }, fmtN(r.plays)),
    );
    const hit = s("rect", { class: "hit", x: 0, y: yy, width: W, height: rowH });
    hit.addEventListener("mousemove", (evt) => showTip(evt, [el("b", {}, r.character),
      el("div", { class: "mut" }, `${fmtN(r.plays)} lượt phát · ${r.reels} reel · TB ${fmtN(r.avg_plays)}/reel`),
      el("div", { class: "mut" }, `${fmtN(r.follows)} follow mới`)]));
    hit.addEventListener("mouseleave", hideTip);
    svg.append(hit);
  });
  return svg;
}

// ---------------------------------------------------------------- sections

function card(title, ...body) {
  return el("section", { class: "g-card" }, el("div", { class: "g-card-h" }, el("h3", {}, title)), ...body);
}

function kpiTiles() {
  return el("div", { class: "in-kpis" }, view.kpis.map((k) => {
    let delta = null;
    if (k.delta != null) {
      const cls = k.delta > 0 ? "up" : k.delta < 0 ? "down" : "";
      delta = el("div", { class: `delta ${cls}` }, `${k.delta > 0 ? "+" : ""}${fmtN(k.delta)} so với lần trước`);
    } else if (!view.previous_snapshot_id) {
      delta = el("div", { class: "delta" }, "lần lấy đầu tiên");
    }
    return el("div", { class: "in-kpi" }, el("div", { class: "lbl" }, k.label), el("div", { class: "val" }, fmtN(k.value)), delta);
  }));
}

const ICONS = { good: "▲", warn: "!", info: "i" };
function findingsCard() {
  const list = view.findings.length
    ? el("div", { class: "in-findings" }, view.findings.map((f) => el("div", { class: `in-finding ${f.level}` },
      el("span", { class: "ic", "aria-label": f.level }, ICONS[f.level] || "•"),
      el("div", {}, el("h4", {}, f.title), el("p", {}, f.detail)))))
    : el("p", { class: "hint" }, "Chưa có nhận định nào từ dữ liệu này.");
  return card("Nhận định từ số liệu", list,
    el("p", { class: "in-foot", style: "margin:10px 0 0" }, "Tính tự động bằng luật cố định, không gọi AI."));
}

function adviceCard() {
  const a = view.advice;
  const err = el("div", { class: "g-error", role: "alert" });
  const lang = el("select", { "aria-label": "Ngôn ngữ" }, meta.languages.map((l) => el("option", { value: l.id }, l.label)));
  lang.value = (a && a.language) || "vi";
  const notes = el("textarea", { placeholder: "Ghi chú cho AI (không bắt buộc): mục tiêu, kế hoạch sắp tới…", "aria-label": "Ghi chú cho AI" });
  notes.value = (a && a.notes) || "";
  const btn = el("button", { class: "g-btn primary", type: "button" }, a ? "Phân tích lại bằng AI" : "Phân tích bằng AI");
  if (!meta.llm_configured) { btn.disabled = true; err.textContent = "Chưa có PIAPI_API_KEY trong .env nên chưa gọi được AI."; }
  btn.addEventListener("click", async () => {
    err.textContent = ""; btn.disabled = true; btn.textContent = "Đang phân tích…";
    try {
      view.advice = await post(`/api/insights/${encodeURIComponent(view.page_id)}/${encodeURIComponent(view.snapshot_id)}/advice`,
        { language: lang.value, notes: notes.value });
      renderMain();
    } catch (e) { err.textContent = `Không phân tích được: ${e.message}`; btn.disabled = false; btn.textContent = "Thử lại"; }
  });

  const body = [];
  if (a) {
    if (a.summary) body.push(el("p", { class: "in-advice-summary" }, a.summary));
    body.push(el("ol", { class: "in-recs" }, a.recommendations.map((r) => el("li", { class: "in-rec" },
      el("div", { class: "top" }, el("h4", {}, r.title), el("span", { class: `chip p-${r.priority}` }, { high: "ưu tiên cao", medium: "vừa", low: "thấp" }[r.priority])),
      r.why ? el("p", {}, el("b", {}, "Vì sao: "), r.why) : null,
      r.action ? el("p", {}, el("b", {}, "Làm gì: "), r.action) : null))));
    if (a.next_videos && a.next_videos.length) {
      body.push(el("div", { class: "in-sub" }, "Video nên làm tiếp"),
        el("div", { class: "in-videos" }, a.next_videos.map(videoIdea)));
    }
    if (a.caveats && a.caveats.length) {
      body.push(el("div", { class: "in-sub" }, "Lưu ý"), el("ul", { class: "in-caveats" }, a.caveats.map((c) => el("li", {}, c))));
    }
    body.push(el("p", { class: "in-foot", style: "margin:12px 0 0" },
      `${a.model} · ${fmtAgo(a.created_at)}${a.usage && a.usage.total_tokens ? ` · ${fmtN(a.usage.total_tokens)} tokens` : ""}`));
  } else {
    body.push(el("p", { class: "hint" }, "AI đọc số liệu và các nhận định bên trái, rồi đề xuất việc nên làm và video nên làm tiếp. Mỗi lần bấm là một lần gọi API PiAPI (tính phí)."));
  }
  body.push(el("details", { class: "g-history", open: a ? null : "" },
    el("summary", {}, a ? "Phân tích lại" : "Tuỳ chọn"),
    el("div", { class: "g-form", style: "margin-top:10px" },
      el("label", {}, "Ngôn ngữ", lang),
      el("label", {}, "Model", el("span", { class: "g-sub", style: "padding:9px 0" }, meta.model)),
      el("label", { class: "full" }, "Ghi chú", notes)),
    el("div", { class: "g-actions" }, btn), err));
  return card("Đề xuất của AI", ...body);
}

function videoIdea(v) {
  const err = el("div", { class: "g-error", role: "alert" });
  const add = el("button", { class: "g-btn", type: "button" }, "+ Thêm vào Backlog");
  add.addEventListener("click", async () => {
    add.disabled = true; err.textContent = "";
    try {
      await post("/api/backlog", {
        title: v.title, status: "idea",
        tags: [v.character, "insights"].filter(Boolean),
        summary: [v.hook && `Hook: ${v.hook}`, v.length_s && `Độ dài: ${v.length_s}s`].filter(Boolean).join(" · "),
        notes: v.why ? `Từ Insights (${view.page.name}, ${view.snapshot_id}): ${v.why}` : "",
      }, "backlog");
      add.textContent = "✓ Đã thêm"; add.classList.add("done");
    } catch (e) { err.textContent = e.message; add.disabled = false; }
  });
  return el("div", { class: "in-video" },
    el("h4", {}, v.title),
    el("div", { class: "g-chips" }, v.character ? el("span", { class: "chip" }, v.character) : null,
      v.length_s ? el("span", { class: "chip" }, `${v.length_s}s`) : null),
    v.hook ? el("p", {}, el("b", {}, "Hook: "), v.hook) : null,
    v.why ? el("p", {}, v.why) : null,
    add, err);
}

const REEL_COLS = [
  { key: "created_time", label: "Ngày", num: false },
  { key: "description", label: "Reel", num: false },
  { key: "character", label: "Nhân vật", num: false },
  { key: "length_s", label: "Dài", num: true },
  { key: "plays", label: "Lượt phát", num: true },
  { key: "avg_watch_s", label: "Xem TB", num: true },
  { key: "retention", label: "Xem hết", num: true },
  { key: "follows", label: "Follow", num: true },
  { key: "comments", label: "Bình luận", num: true },
];

function reelsTable() {
  const rows = [...view.reels].sort((a, b) => {
    const va = a[reelSort.key], vb = b[reelSort.key];
    const cmp = va == null ? 1 : vb == null ? -1 : (typeof va === "number" ? va - vb : String(va).localeCompare(String(vb)));
    return reelSort.dir === "asc" ? cmp : -cmp;
  });
  const maxRet = 1;
  const thead = el("tr", {}, REEL_COLS.map((c) => {
    const btn = el("button", { type: "button" }, c.label);
    btn.addEventListener("click", () => {
      reelSort = reelSort.key === c.key ? { key: c.key, dir: reelSort.dir === "desc" ? "asc" : "desc" } : { key: c.key, dir: c.num ? "desc" : "asc" };
      storageSet(SORT_KEY, JSON.stringify(reelSort));
      document.getElementById("reels").replaceWith(reelsTable());
    });
    return el("th", { class: c.num ? "num" : null, scope: "col",
      "aria-sort": reelSort.key === c.key ? (reelSort.dir === "desc" ? "descending" : "ascending") : null }, btn);
  }));
  const body = rows.map((r) => el("tr", {},
    el("td", {}, fmtDateTime(r.created_time)),
    el("td", { class: "desc" },
      el("a", { href: r.permalink_url, target: "_blank", rel: "noopener" }, el("span", {}, r.description || r.id)),
      r.project ? el("div", {}, el("a", { href: `/p/${encodeURIComponent(r.project.project_id)}`, class: "g-sub" }, `↳ ${r.project.project_title}`)) : null),
    el("td", {}, r.character || "—"),
    el("td", { class: "num" }, r.length_s ? `${Math.round(r.length_s)}s` : "—"),
    el("td", { class: "num" }, fmtN(r.plays)),
    el("td", { class: "num" }, r.avg_watch_s != null ? `${r.avg_watch_s}s` : "—"),
    el("td", { class: "num" }, r.retention == null ? "—" : el("span", { class: `in-ret ${r.retention < 0.15 ? "low" : ""}` },
      el("i", { style: `width:${Math.round((r.retention / maxRet) * 48)}px` }), fmtPct(r.retention))),
    el("td", { class: "num" }, fmtN(r.follows)),
    el("td", { class: "num" }, fmtN(r.comments)),
  ));
  return el("div", { class: "in-table-wrap", id: "reels" },
    el("table", { class: "in-table" }, el("thead", {}, thead), el("tbody", {}, body)));
}

function postsTable() {
  if (!view.posts.length) return el("p", { class: "hint" }, "Không có bài viết trong khoảng thời gian này.");
  return el("div", { class: "in-table-wrap" }, el("table", { class: "in-table" },
    el("thead", {}, el("tr", {},
      el("th", { scope: "col" }, "Ngày"), el("th", { scope: "col" }, "Bài viết"), el("th", { scope: "col" }, "Loại"),
      el("th", { scope: "col", class: "num" }, "Lượt xem"), el("th", { scope: "col", class: "num" }, "Tương tác"),
      el("th", { scope: "col", class: "num" }, "Click"))),
    el("tbody", {}, view.posts.map((p) => el("tr", { class: p.is_reel ? null : "dim" },
      el("td", {}, fmtDateTime(p.created_time)),
      el("td", { class: "desc" }, el("a", { href: p.permalink_url, target: "_blank", rel: "noopener" }, el("span", {}, p.message || p.id))),
      el("td", {}, p.is_reel ? "reel" : p.media_type || "—"),
      el("td", { class: "num" }, fmtN(p.views)),
      el("td", { class: "num" }, fmtN(p.engagement)),
      el("td", { class: "num" }, fmtN(p.clicks)))))));
}

// ---------------------------------------------------------------- toolbar + main

function renderToolbar() {
  toolbar.innerHTML = "";
  const err = el("div", { class: "g-error", role: "alert" });
  if (meta.pages.length) {
    const pageSel = el("select", { "aria-label": "Page" }, meta.pages.map((p) => el("option", { value: p.page_id }, p.name)));
    pageSel.value = sel.page_id;
    pageSel.addEventListener("change", () => {
      const p = meta.pages.find((x) => x.page_id === pageSel.value);
      choose(p.page_id, p.snapshots[0].id);
    });
    const page = meta.pages.find((p) => p.page_id === sel.page_id);
    const snapSel = el("select", { "aria-label": "Lần lấy số liệu" }, page.snapshots.map((sn) => el("option", { value: sn.id }, snapLabel(sn))));
    snapSel.value = sel.snap_id;
    snapSel.addEventListener("change", () => choose(sel.page_id, snapSel.value));
    toolbar.append(pageSel, snapSel);
  }
  toolbar.append(el("div", { class: "spacer" }));
  const days = el("select", { "aria-label": "Khoảng thời gian" },
    [[28, "28 ngày"], [90, "90 ngày"], [180, "180 ngày"], [365, "365 ngày"]].map(([v, l]) => el("option", { value: v }, l)));
  days.value = "90";
  const btn = el("button", { class: "g-btn primary", type: "button" }, "Lấy số liệu mới");
  if (!meta.token_configured) { btn.disabled = true; err.textContent = "Chưa có FACEBOOK_PAGE_ACCESS_TOKEN trong .env."; }
  btn.addEventListener("click", async () => {
    btn.disabled = true; err.textContent = ""; btn.textContent = "Đang lấy số liệu… (~30s)";
    try {
      const r = await post("/api/insights/refresh", { days: Number(days.value) });
      sel = { page_id: r.page_id, snap_id: r.snapshot_id };
      storageSet(SEL_KEY, JSON.stringify(sel));
      await load();
    } catch (e) { err.textContent = `Không lấy được số liệu: ${e.message}`; btn.disabled = false; btn.textContent = "Thử lại"; }
  });
  toolbar.append(days, btn, err);
}

function renderEmpty() {
  main.innerHTML = "";
  main.append(el("section", { class: "g-card in-empty" },
    el("div", { class: "g-card-h" }, el("h3", {}, "Chưa có số liệu")),
    el("p", {}, "Tab này hiển thị số liệu Facebook Page lấy bằng tool facebook_page_insights."),
    el("ol", {},
      el("li", {}, "Đặt FACEBOOK_PAGE_ACCESS_TOKEN (và FACEBOOK_PAGE_ID nếu dùng User token) trong .env."),
      el("li", {}, "Khởi động lại Backlot."),
      el("li", {}, "Bấm “Lấy số liệu mới” ở trên."))));
}

function renderMain() {
  main.innerHTML = "";
  const p = view.page;
  main.append(
    el("p", { class: "in-period" },
      `${p.name || view.page_id} · ${view.period.since} → ${view.period.until} · lấy lúc ${fmtDateTime(view.fetched_at)}`,
      view.previous_snapshot_id ? ` · so với lần ${view.previous_snapshot_id.slice(0, 10)}` : ""),
    kpiTiles(),
    el("div", { class: "in-grid2" }, findingsCard(), adviceCard()),
    el("div", { class: "in-grid3" },
      card("Follower theo ngày", el("div", { class: "in-chart" }, followersChart(view.followers_daily))),
      card("Độ dài reel và tỉ lệ xem hết", el("div", { class: "in-chart" }, retentionChart(view.reels),
        el("p", { class: "note" }, "Mỗi chấm là một reel. Tỉ lệ xem hết = thời gian xem trung bình / độ dài. Chấm cam: reel nhiều lượt phát nhất."))),
      card("Lượt phát theo nhân vật", el("div", { class: "in-chart" }, characterChart(view.by_character),
        el("p", { class: "note" }, "Nhân vật lấy từ thư viện Characters, nhận theo caption hoặc project gốc.")))),
    card(`Reels (${view.reels.length})`, reelsTable()),
    card(`Tất cả bài viết (${view.posts.length})`, postsTable()),
    el("p", { class: "in-foot" },
      view.warnings.map((w) => el("span", {}, `⚠ ${w}`, el("br"))),
      view.rejected_metrics.length ? `Metric Meta không còn hỗ trợ: ${view.rejected_metrics.join(", ")}.` : ""),
  );
}

async function choose(pageId, snapId) {
  sel = { page_id: pageId, snap_id: snapId };
  storageSet(SEL_KEY, JSON.stringify(sel));
  renderToolbar();
  main.innerHTML = "";
  main.append(el("p", { class: "hint" }, "Đang tải…"));
  try {
    view = await getJSON(`/api/insights/${encodeURIComponent(pageId)}/${encodeURIComponent(snapId)}`);
    renderMain();
  } catch (e) { main.textContent = `Lỗi tải số liệu: ${e.message}`; }
}

async function load() {
  meta = await getJSON("/api/insights");
  const total = meta.pages.reduce((n, p) => n + p.snapshots.length, 0);
  document.getElementById("count").textContent = `${meta.pages.length} page · ${total} lần lấy`;
  if (!meta.pages.length) { sel = null; renderToolbar(); renderEmpty(); return; }
  const page = (sel && meta.pages.find((p) => p.page_id === sel.page_id)) || meta.pages[0];
  const snap = (sel && page.snapshots.find((x) => x.id === sel.snap_id)) || page.snapshots[0];
  await choose(page.page_id, snap.id);
}

window.addEventListener("scroll", hideTip, { passive: true });
load().catch((e) => { main.textContent = `Lỗi tải Insights: ${e.message}`; });
