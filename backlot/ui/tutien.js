import { el, fmtAgo, getJSON } from "/ui/lib.js";

const THEME_KEY = "backlot.theme";
const OPEN_KEY = "backlot.tutien.editing";
const PL = ["facebook", "tiktok", "youtube"];
const $ = (id) => document.getElementById(id);

function storageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
document.documentElement.dataset.theme = storageGet(THEME_KEY) === "light" ? "light" : "dark";

let plan = null;
let jobs = [];
let editing = null; // episode number being edited

async function post_(url, body, action) { return post(url, body, action); }
async function post(url, body, action) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Backlot-Action": action },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}
const fmt = (n) => Number(n || 0).toLocaleString("vi-VN");

/* ---------------- realms + counts ---------------- */
function renderRealms() {
  const box = $("realms");
  box.replaceChildren();
  const grid = el("div", { class: "tt-realms" });
  for (const p of PL) {
    const meta = plan.platforms[p];
    const r = plan.realms[p];
    const pct = Math.min(100, (r.count / r.next) * 100);
    const input = el("input", { type: "number", min: "0", step: "1", value: String(r.count), "aria-label": `${meta.label} — số ${meta.unit}`, "data-p": p });
    grid.append(el("div", { class: "tt-realm" },
      el("div", { class: "pl" }, `${meta.label} · ${meta.channel}`),
      el("div", { class: "rn" }, r.realm),
      el("label", {}, input, meta.unit),
      el("div", { class: "tt-bar" }, el("i", { style: `width:${pct.toFixed(1)}%` })),
      el("div", { class: "nx" }, `Mốc kế tiếp: ${fmt(r.next)} ${meta.unit}`),
    ));
  }
  const err = el("span", { class: "tt-err", role: "alert" });
  const save = el("button", { class: "g-btn primary", type: "button", onclick: async () => {
    const counts = {};
    grid.querySelectorAll("input[data-p]").forEach((i) => { counts[i.dataset.p] = Number(i.value || 0); });
    save.disabled = true; err.textContent = "";
    try { plan = await post("/api/tutien/counts", counts, "tutien"); render(); }
    catch (e) { err.textContent = e.message; save.disabled = false; }
  } }, "Lưu số follow");
  box.append(el("h2", {}, "Cảnh giới từng kênh"), grid,
    el("div", { class: "tt-realms-foot" }, err, el("span", { class: "hint" }, "Lần render sau sẽ dùng số này"), save));
}

/* ---------------- episodes ---------------- */
function versionBox(ep, p) {
  const meta = plan.platforms[p];
  const v = ep.videos[p];
  const style = (ep.versions[p] || {}).style || "chưa chọn style";
  const media = v
    ? el("video", { src: `/media/${plan.project_id}/${v.light || v.file}`, controls: "", preload: "metadata", playsinline: "" })
    : el("div", { class: "none" }, "Chưa có video");
  const btn = el("button", { class: "g-btn", type: "button", onclick: () => doRender(ep.n, p, btn) },
    ep.rendering_now ? "Đang render…" : v ? "Render lại" : "Render");
  btn.disabled = !ep.can_render || ep.rendering_now;
  if (!ep.can_render) btn.title = "Tập này chưa có script render";
  const info = v ? `${fmt(v.count)} ${meta.unit} · ${fmtAgo(v.mtime)}` : "";
  return el("div", { class: "tt-ver" },
    el("div", { class: "h" }, el("b", {}, meta.label), el("span", {}, info)),
    el("div", { class: "sty", title: style }, style),
    media, btn, postBox(ep, p));
}

/* ---------------- captions + hashtags ---------------- */
const postText = (post, p) => {
  const title = p === "youtube" && post.titles && post.titles[0] ? post.titles[0] + "\n\n" : "";
  return `${title}${post.caption}\n\n${(post.hashtags || []).join(" ")}`.trim();
};
async function copyToClipboard(text, btn) {
  try { await navigator.clipboard.writeText(text); }
  catch {
    const ta = el("textarea", {}, text); document.body.append(ta); ta.select();
    try { document.execCommand("copy"); } finally { ta.remove(); }
  }
  const old = btn.textContent; btn.textContent = "Đã chép ✓"; setTimeout(() => { btn.textContent = old; }, 1400);
}
const openPosts = new Set();   // "n:platform" boxes the user expanded or is editing
const editingPost = new Set();

function postBox(ep, p) {
  const key = `${ep.n}:${p}`;
  const post = (ep.posts || {})[p];
  const det = el("details", { class: "tt-post" });
  if (openPosts.has(key) || editingPost.has(key)) det.open = true;
  det.addEventListener("toggle", () => { det.open ? openPosts.add(key) : openPosts.delete(key); });
  det.append(el("summary", {}, post ? "Caption & hashtag" : "Caption & hashtag (chưa có)"));
  const err = el("p", { class: "tt-err" });
  const gen = el("button", { class: "g-btn", type: "button", onclick: async () => {
    gen.disabled = true; gen.textContent = "Đang viết…"; err.textContent = "";
    try { const r = await post_(`/api/tutien/posts/generate`, { episode: ep.n, platform: p }, "tutien-social"); applyPosts(ep.n, r.posts); }
    catch (e) { err.textContent = e.message; }
    gen.disabled = false; gen.textContent = post ? "Viết lại bằng AI" : "Tạo bằng AI";
  } }, post ? "Viết lại bằng AI" : "Tạo bằng AI");
  gen.title = "Viết qua PiAPI chat (~0,01 USD)";

  if (editingPost.has(key)) {
    const titles = el("input", { type: "text", value: (post?.titles || []).join(" | "), "aria-label": "Tiêu đề (cách nhau bằng |)" });
    const cap = el("textarea", { rows: "6", "aria-label": "Caption" }, post?.caption || "");
    const tags = el("input", { type: "text", value: (post?.hashtags || []).join(" "), "aria-label": "Hashtag" });
    const save = el("button", { class: "g-btn primary", type: "button", onclick: async () => {
      save.disabled = true; err.textContent = "";
      try {
        const saved = await post_(`/api/tutien/posts/${ep.n}/${p}`, {
          titles: titles.value.split("|").map((t) => t.trim()).filter(Boolean),
          caption: cap.value, hashtags: tags.value.split(/[\s,]+/).filter(Boolean),
        }, "tutien");
        editingPost.delete(key); applyPosts(ep.n, { [p]: saved });
      } catch (e) { err.textContent = e.message; save.disabled = false; }
    } }, "Lưu");
    det.append(el("div", { class: "tt-post-edit" },
      el("label", {}, "Tiêu đề (cách nhau bằng |)", titles), el("label", {}, "Caption", cap), el("label", {}, "Hashtag", tags),
      el("div", { class: "row" }, save, el("button", { class: "g-btn", type: "button", onclick: () => { editingPost.delete(key); renderEpisodes(); } }, "Hủy")), err));
    return det;
  }
  if (post) {
    const copy = el("button", { class: "g-btn primary", type: "button", onclick: () => copyToClipboard(postText(post, p), copy) }, "Sao chép");
    det.append(...[
      p === "youtube" && post.titles?.length ? el("div", { class: "ttl" }, post.titles[0]) : null,
      el("div", { class: "cap" }, post.caption),
      el("div", { class: "tags" }, (post.hashtags || []).join(" ")),
      el("div", { class: "row" }, copy,
        el("button", { class: "g-btn", type: "button", onclick: () => { editingPost.add(key); renderEpisodes(); } }, "Sửa"), gen),
      el("div", { class: "meta" }, `${post.source === "ai" ? "AI" : "Viết tay"} · ${fmtAgo(post.created_at)}`),
      err].filter(Boolean));
  } else {
    det.append(el("div", { class: "row" }, gen,
      el("button", { class: "g-btn", type: "button", onclick: () => { editingPost.add(key); renderEpisodes(); } }, "Tự viết")), err);
  }
  return det;
}
function applyPosts(n, posts) {
  const ep = plan.episodes.find((e) => e.n === n);
  ep.posts = Object.assign({}, ep.posts || {}, posts);
  renderEpisodes();
}

function editForm(ep) {
  const f = (name, label, value, type = "text", full = false) =>
    el("label", { class: full ? "full" : "" }, label, type === "textarea"
      ? el("textarea", { name, rows: "2" }, value || "")
      : el("input", { name, type, value: value || "" }));
  const status = el("select", { name: "status" }, ...plan.statuses.map((s) => {
    const o = el("option", { value: s.id }, s.label); if (s.id === ep.status) o.selected = true; return o;
  }));
  const form = el("form", { class: "tt-edit" },
    f("title", "Tên tập", ep.title, "text", true),
    f("lesson", "Công pháp (bài học thật)", ep.lesson, "textarea", true),
    f("cliffhanger", "Cliffhanger", ep.cliffhanger, "textarea", true),
    el("label", {}, "Trạng thái", status),
    f("post_date", "Ngày đăng", ep.post_date, "date"),
    ...PL.map((p) => f(`goal_${p}`, `Mục tiêu ${plan.platforms[p].label}`, String(ep.goals[p] ?? ""), "number")),
    ...PL.map((p) => f(`style_${p}`, `Style ${plan.platforms[p].label}`, (ep.versions[p] || {}).style || "")),
    f("kpi", "KPI", ep.kpi, "text", true),
    f("gate", "Điều kiện đăng", ep.gate, "text", true),
    f("notes", "Ghi chú", ep.notes, "textarea", true),
  );
  const err = el("p", { class: "tt-err full", role: "alert" });
  const save = el("button", { class: "g-btn primary", type: "submit" }, "Lưu");
  form.append(el("div", { class: "tt-ep-actions full" }, save,
    el("button", { class: "g-btn", type: "button", onclick: () => { editing = null; renderEpisodes(); } }, "Hủy"), err));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const d = new FormData(form);
    const body = { title: d.get("title"), lesson: d.get("lesson"), cliffhanger: d.get("cliffhanger"), status: d.get("status"),
      post_date: d.get("post_date"), kpi: d.get("kpi"), gate: d.get("gate"), notes: d.get("notes"), goals: {}, styles: {} };
    for (const p of PL) { body.goals[p] = Number(d.get(`goal_${p}`) || 0); body.styles[p] = d.get(`style_${p}`) || ""; }
    save.disabled = true; err.textContent = "";
    try { plan = await post(`/api/tutien/episodes/${ep.n}`, body, "tutien"); editing = null; render(); }
    catch (ex) { err.textContent = ex.message; save.disabled = false; }
  });
  return form;
}

function renderEpisodes() {
  const box = $("episodes");
  box.replaceChildren();
  for (const ep of plan.episodes) {
    const goals = el("div", { class: "tt-goals" }, ...PL.map((p) => {
      const goal = ep.goals[p], have = plan.counts[p];
      return el("span", { class: `tt-goal${have >= goal ? " hit" : ""}`, title: "Mục tiêu sau tập này" },
        `${plan.platforms[p].label}: ${fmt(have)} → ${fmt(goal)}`);
    }));
    const card = el("article", { class: `tt-ep${ep.gate ? " gate" : ""}`, id: `ep-${ep.n}` },
      el("div", { class: "tt-ep-head" },
        el("span", { class: "no" }, `TẬP ${ep.n}`),
        el("h3", {}, ep.title),
        el("span", { class: "sp" }),
        el("span", { class: "hint", style: "padding:0" }, ep.post_date ? `Đăng ${ep.post_date.split("-").reverse().join("/")}` : ""),
        el("span", { class: `tt-st ${ep.status}` }, ep.status_label)),
      el("p", {}, el("b", {}, "Công pháp: "), ep.lesson),
      el("p", {}, el("b", {}, "Cliffhanger: "), ep.cliffhanger),
      goals,
      ep.gate ? el("p", {}, el("b", {}, "Điều kiện: "), ep.gate) : null,
      el("p", {}, el("b", {}, "KPI: "), ep.kpi || ""),
      ep.notes ? el("p", {}, el("b", {}, "Ghi chú: "), ep.notes) : null,
    );
    if (editing === ep.n) {
      card.append(editForm(ep));
    } else {
      card.append(el("div", { class: "tt-vers" }, ...PL.map((p) => versionBox(ep, p))));
      const all = el("button", { class: "g-btn primary", type: "button", onclick: () => doRender(ep.n, "all", all) }, "Render cả 3 bản");
      all.disabled = !ep.can_render || ep.rendering_now;
      const cmd = el("button", { class: "g-btn", type: "button", onclick: () => {
        $("cmdEp").value = String(ep.n); $("cmdText").focus(); window.scrollTo({ top: 0, behavior: "smooth" });
      } }, "Ra lệnh cho tập này");
      const capAll = el("button", { class: "g-btn", type: "button", title: "Viết caption + hashtag cho cả 3 kênh qua PiAPI chat (~0,03 USD)", onclick: async () => {
        capAll.disabled = true; capAll.textContent = "Đang viết caption…";
        try { const r = await post("/api/tutien/posts/generate", { episode: ep.n, platform: "all" }, "tutien-social"); PL.forEach((p) => openPosts.add(`${ep.n}:${p}`)); applyPosts(ep.n, r.posts); }
        catch (e) { alert(e.message); capAll.disabled = false; capAll.textContent = "Tạo caption 3 kênh"; }
      } }, "Tạo caption 3 kênh");
      card.append(el("div", { class: "tt-ep-actions" }, all, capAll, cmd,
        el("button", { class: "g-btn", type: "button", onclick: () => { editing = ep.n; renderEpisodes(); } }, "Sửa kế hoạch"),
        ep.can_render ? null : el("span", { class: "hint" }, "Chưa dựng — ra lệnh để Claude dựng tập này")));
    }
    box.append(card);
  }
}

async function doRender(n, platform, btn) {
  btn.disabled = true;
  try { await post("/api/tutien/render", { episode: n, platform }, "tutien-render"); await refresh(); }
  catch (e) { alert(e.message); btn.disabled = false; }
}

/* ---------------- command ---------------- */
function renderCmdEpisodes() {
  const sel = $("cmdEp");
  const keep = sel.value;
  sel.replaceChildren(el("option", { value: "" }, "Cả series"),
    ...plan.episodes.map((e) => el("option", { value: String(e.n) }, `Tập ${e.n} — ${e.title}`)));
  sel.value = keep;
}
$("cmdSend").addEventListener("click", async () => {
  const text = $("cmdText").value.trim();
  const btn = $("cmdSend");
  $("cmdErr").textContent = "";
  if (!text) { $("cmdErr").textContent = "Nhập lệnh trước đã."; return; }
  btn.disabled = true;
  try {
    await post("/api/tutien/command", { text, episode: $("cmdEp").value ? Number($("cmdEp").value) : null }, "tutien-command");
    $("cmdText").value = "";
    await refresh();
  } catch (e) { $("cmdErr").textContent = e.message; }
  btn.disabled = false;
});

/* ---------------- jobs ---------------- */
const STATUS = { running: "Đang chạy", done: "Xong", failed: "Lỗi", interrupted: "Bị ngắt" };
function renderJobs() {
  const box = $("jobs");
  box.replaceChildren();
  if (!jobs.length) { box.append(el("p", { class: "hint" }, "Chưa có tác vụ nào.")); return; }
  for (const j of jobs.slice(0, 20)) {
    const stop = j.status === "running"
      ? el("button", { class: "g-btn", type: "button", onclick: async () => { try { await post(`/api/tutien/jobs/${j.id}/cancel`, {}, "tutien"); refresh(); } catch (e) { alert(e.message); } } }, "Dừng")
      : null;
    const pre = el("pre", {}, j.log_tail || "");
    box.append(el("div", { class: "tt-job" },
      el("div", { class: "h" }, el("span", {}, j.kind === "command" ? "💬" : "🎬"), el("b", { title: j.title }, j.title), el("span", { class: `s ${j.status}` }, STATUS[j.status] || j.status), stop),
      el("div", { class: "meta" }, `${j.episode ? `Tập ${j.episode} · ` : ""}${fmtAgo(j.started)}${j.ended ? ` · ${Math.round(j.ended - j.started)}s` : ""}`),
      j.hint ? el("p", { class: "tt-err" }, j.hint) : null,
      j.log_tail ? pre : null));
    if (j.status === "running") pre.scrollTop = pre.scrollHeight;
  }
}

/* ---------------- load ---------------- */
function render() {
  $("count").textContent = `${plan.episodes.length} tập · ${plan.episodes.filter((e) => e.videos && Object.keys(e.videos).length).length} đã có video`;
  renderRealms();
  renderCmdEpisodes();
  if (editing === null && !editingPost.size) renderEpisodes();
}

async function refresh() {
  const [p, j] = await Promise.all([getJSON("/api/tutien"), getJSON("/api/tutien/jobs")]);
  const wasRunning = jobs.some((x) => x.status === "running");
  jobs = j.jobs || [];
  const changed = JSON.stringify(p.episodes.map((e) => [e.status, e.rendering_now, Object.values(e.videos || {}).map((v) => v.mtime), Object.values(e.posts || {}).map((x) => x.created_at)])) !==
    JSON.stringify((plan?.episodes || []).map((e) => [e.status, e.rendering_now, Object.values(e.videos || {}).map((v) => v.mtime), Object.values(e.posts || {}).map((x) => x.created_at)]));
  if (!plan || changed || wasRunning !== jobs.some((x) => x.status === "running")) { plan = p; render(); }
  renderJobs();
}

refresh().catch((e) => { $("episodes").append(el("p", { class: "tt-err" }, `Không tải được kế hoạch: ${e.message}`)); });
setInterval(() => { refresh().catch(() => {}); }, 4000);
