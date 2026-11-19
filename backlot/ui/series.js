import { el, fmtAgo, getJSON } from "/ui/lib.js";
import { renderMarkdown } from "/ui/markdown.js";

const THEME_KEY = "backlot.theme";
const SEL_KEY = "backlot.series.selected";
const TAB_KEY = "backlot.series.tab";
const listEl = document.getElementById("list");
const detailEl = document.getElementById("detail");

let all = [];            // series summaries
let statuses = { series: [], episode: [] };
let characters = [];     // library characters
let current = null;      // full series
let selected = storageGet(SEL_KEY);
let tab = storageGet(TAB_KEY) || "wiki";
let pageSlug = null;
let editing = false;
let editingEp = null;

function storageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function storageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* ignore */ } }
document.documentElement.dataset.theme = storageGet(THEME_KEY) === "light" ? "light" : "dark";

async function post(url, body = {}, action = "series") {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Backlot-Action": action },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

const api = (path = "") => `/api/series/${encodeURIComponent(current.id)}${path}`;
const errBox = () => el("div", { class: "g-error", role: "alert" });
const label = (list, id) => (list.find((s) => s.id === id) || {}).label || id;
const charImg = (c) => (c && c.primary_image ? `/character-media/${encodeURIComponent(c.id)}/${encodeURIComponent(c.primary_image)}` : null);
const nf = new Intl.NumberFormat("vi-VN");

// Same rules as lib/backlog.slugify so [[Thế giới]] resolves to the-gioi.
function slugify(text) {
  return text.replace(/đ/g, "d").replace(/Đ/g, "D").normalize("NFKD").replace(/[̀-ͯ]/g, "")
    .toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64);
}

// ---------------------------------------------------------------- list

function renderList() {
  document.getElementById("count").textContent = `${all.length} series`;
  document.getElementById("empty").style.display = all.length ? "none" : "block";
  listEl.innerHTML = "";
  for (const sr of all) {
    const pct = sr.episode_count ? Math.round((sr.done_count / sr.episode_count) * 100) : 0;
    listEl.append(el("button", {
      class: "g-item sr-item", type: "button", "aria-selected": sr.id === selected ? "true" : "false",
      onclick: () => select(sr.id),
    }, el("div", {},
      el("h3", {}, sr.title),
      sr.logline ? el("div", { class: "sr-logline" }, sr.logline) : null,
      el("div", { class: "g-chips" },
        el("span", { class: "chip" }, sr.status_label),
        el("span", { class: "chip" }, `${sr.done_count}/${sr.episode_count} tập xong`),
        sr.characters.slice(0, 3).map((id) => el("span", { class: "chip" }, (characters.find((c) => c.id === id) || {}).name || id))),
      sr.episode_count ? el("div", { class: "sr-progress", "aria-hidden": "true" }, el("i", { style: `width:${pct}%` })) : null,
    )));
  }
}

async function select(id) {
  selected = id; storageSet(SEL_KEY, id || "");
  pageSlug = null; editing = false; editingEp = null;
  renderList();
  await loadCurrent();
}

// ---------------------------------------------------------------- series form

function seriesForm(sr = {}, onSave, saveLabel) {
  const err = errBox();
  const title = el("input", { type: "text", id: "s-title", placeholder: "Ví dụ: Sasa — Đêm không ngủ" });
  const logline = el("textarea", { id: "s-logline", placeholder: "Một câu: ai, muốn gì, điều gì cản họ" });
  const status = el("select", { id: "s-status" }, statuses.series.map((s) => el("option", { value: s.id }, s.label)));
  const tags = el("input", { type: "text", id: "s-tags", placeholder: "hành động, shorts" });
  title.value = sr.title || ""; logline.value = sr.logline || ""; status.value = sr.status || "planning";
  tags.value = (sr.tags || []).join(", ");
  const picked = new Set(sr.characters || []);
  const cast = el("div", { class: "sr-check", role: "group", "aria-label": "Nhân vật" },
    characters.length ? characters.map((c) => {
      const box = el("input", { type: "checkbox", value: c.id });
      box.checked = picked.has(c.id);
      return el("label", {}, box, c.name);
    }) : el("span", { class: "hint" }, "Thư viện Characters đang trống."));
  const save = el("button", { class: "g-btn primary", type: "button" }, saveLabel);
  save.addEventListener("click", async () => {
    err.textContent = ""; save.disabled = true;
    try {
      await onSave({
        title: title.value, logline: logline.value, status: status.value,
        tags: tags.value.split(",").map((t) => t.trim()).filter(Boolean),
        characters: [...cast.querySelectorAll("input:checked")].map((b) => b.value),
      });
    } catch (e) { err.textContent = e.message; save.disabled = false; }
  });
  const form = el("div", { class: "g-form" },
    el("label", { class: "full", for: "s-title" }, "Tên series", title),
    el("label", { class: "full", for: "s-logline" }, "Logline", logline),
    el("label", { for: "s-status" }, "Trạng thái", status),
    el("label", { for: "s-tags" }, "Tag", tags),
    el("div", { class: "full" }, el("div", { class: "g-stamp", style: "margin-bottom:6px" }, "Nhân vật (từ thư viện Characters)"), cast));
  return { node: el("div", {}, form, el("div", { class: "g-actions" }, save), err), focus: () => title.focus() };
}

function renderNew() {
  selected = null; current = null; renderList();
  detailEl.innerHTML = "";
  const f = seriesForm({}, async (v) => {
    const sr = await post("/api/series", v);
    await loadAll(); await select(sr.id);
  }, "Tạo series");
  detailEl.append(el("div", { class: "g-card" },
    el("div", { class: "g-card-h" }, el("h3", {}, "Series mới")),
    el("p", { class: "hint", style: "margin-top:0" }, "Wiki sẽ có sẵn 4 trang mẫu: Tổng quan, Thế giới, Nhân vật, Bối cảnh."),
    f.node));
  f.focus();
}

// ---------------------------------------------------------------- detail

function renderDetail() {
  detailEl.innerHTML = "";
  if (!current) { detailEl.append(el("p", { class: "hint" }, "Chọn một series ở bên trái.")); return; }
  const sr = current;
  const status = el("select", { "aria-label": "Trạng thái series" }, statuses.series.map((s) => el("option", { value: s.id }, s.label)));
  status.value = sr.status;
  status.addEventListener("change", async () => {
    try { await post(api(), { status: status.value }); await loadAll(); await loadCurrent(); }
    catch (e) { alert(e.message); status.value = sr.status; }
  });
  const editBtn = el("button", { class: "g-btn", type: "button" }, "Sửa thông tin");
  editBtn.addEventListener("click", () => { tab = "info"; renderDetail(); });

  const parts = [
    el("div", { class: "g-head" }, el("h2", {}, sr.title), el("span", { class: "g-sub" }, `series/${sr.id}`)),
    el("div", { class: "g-meta bl-head-row" }, status, (sr.tags || []).map((t) => el("span", { class: "chip" }, t)),
      el("span", { class: "chip" }, `cập nhật ${fmtAgo(sr.updated_at)}`), editBtn),
    sr.logline ? el("p", { class: "sr-logline-big" }, sr.logline) : null,
    sr.characters && sr.characters.length ? el("div", { class: "sr-cast" }, sr.characters.map((id) => {
      const c = characters.find((x) => x.id === id);
      const src = charImg(c);
      return el("a", { href: "/characters", title: "Mở thư viện Characters" },
        src ? el("img", { src, alt: "", loading: "lazy" }) : el("span", { class: "ph" }), c ? c.name : id);
    })) : null,
    tabs(),
  ];
  detailEl.append(...parts.filter(Boolean));  // native append would print null as text
  if (tab === "episodes") detailEl.append(episodesView());
  else if (tab === "info") detailEl.append(infoView());
  else detailEl.append(wikiView());
}

function tabs() {
  const items = [["wiki", `Wiki (${current.pages.length})`], ["episodes", `Tập phim (${current.episodes.length})`], ["info", "Thông tin"]];
  return el("div", { class: "sr-tabs", role: "tablist" }, items.map(([id, text]) => el("button", {
    type: "button", role: "tab", "aria-selected": tab === id ? "true" : "false",
    onclick: () => { tab = id; storageSet(TAB_KEY, id); editing = false; editingEp = null; renderDetail(); },
  }, text)));
}

// ---------------------------------------------------------------- wiki

function resolvePage(target) {
  const t = target.trim().toLowerCase();
  const slug = slugify(target);
  return current.pages.find((p) => p.slug === t || p.slug === slug || p.title.toLowerCase() === t);
}

function wikilink(target, text) {
  const page = resolvePage(target);
  const a = el("a", { class: page ? "wl" : "wl missing", href: "#", title: page ? page.title : `Chưa có trang “${target}”, bấm để tạo` }, text);
  a.addEventListener("click", (e) => {
    e.preventDefault();
    if (page) { pageSlug = page.slug; editing = false; renderDetail(); }
    else newPage(target);
  });
  return a;
}

function wikiView() {
  if (pageSlug !== "__new__" && (!pageSlug || !current.pages.some((p) => p.slug === pageSlug))) {
    pageSlug = current.pages[0] ? current.pages[0].slug : null;
  }
  const addBtn = el("button", { class: "g-btn", type: "button" }, "+ Trang mới");
  addBtn.addEventListener("click", () => newPage(""));
  const nav = el("nav", { class: "sr-pages", "aria-label": "Trang wiki" },
    current.pages.map((p) => el("button", {
      type: "button", "aria-current": p.slug === pageSlug ? "page" : null,
      onclick: () => { pageSlug = p.slug; editing = false; renderDetail(); },
    }, p.title)),
    addBtn);
  const body = el("div", {});
  if (pageSlug === "__new__") body.append(pageEditor(null, newPageDraft));
  else if (pageSlug) loadPage(pageSlug, body);
  else body.append(el("p", { class: "hint" }, "Wiki chưa có trang nào."));
  return el("div", { class: "sr-wiki" }, nav, el("div", { class: "g-card" }, body));
}

let newPageDraft = "";
function newPage(title) {
  newPageDraft = `# ${title || "Tên trang"}\n\n`;
  pageSlug = "__new__"; editing = true; tab = "wiki";
  renderDetail();
}

async function loadPage(slug, body) {
  body.append(el("p", { class: "hint" }, "Đang tải…"));
  try {
    const page = await getJSON(api(`/pages/${encodeURIComponent(slug)}`));
    if (pageSlug !== slug) return;
    body.innerHTML = "";
    body.append(editing ? pageEditor(page, page.text) : pageView(page));
  } catch (e) { body.innerHTML = ""; body.append(el("p", { class: "g-error" }, e.message)); }
}

function pageView(page) {
  const edit = el("button", { class: "g-btn", type: "button" }, "Sửa");
  edit.addEventListener("click", () => { editing = true; renderDetail(); });
  const content = el("div", { class: "bl-script expanded" });
  content.append(renderMarkdown(page.text, { wikilink }));
  return el("div", {},
    el("div", { class: "sr-page-bar" }, el("span", { class: "spacer" }),
      el("span", { class: "g-stamp" }, `sửa ${fmtAgo(page.updated_at)}`), edit),
    content);
}

function pageEditor(page, text) {
  const err = errBox();
  const area = el("textarea", { class: "sr-editor", "aria-label": "Nội dung trang (markdown)", spellcheck: "false" });
  area.value = text;
  const save = el("button", { class: "g-btn primary", type: "button" }, page ? "Lưu trang" : "Tạo trang");
  save.addEventListener("click", async () => {
    err.textContent = ""; save.disabled = true;
    try {
      const saved = await post(api("/pages"), { text: area.value, slug: page ? page.slug : null });
      editing = false; pageSlug = saved.slug;
      await loadCurrent();
    } catch (e) { err.textContent = `Không lưu được: ${e.message}`; save.disabled = false; }
  });
  const cancel = el("button", { class: "g-btn", type: "button" }, "Huỷ");
  cancel.addEventListener("click", () => { editing = false; if (!page) pageSlug = null; renderDetail(); });
  const del = page && page.slug !== "tong-quan" ? el("button", { class: "g-btn danger", type: "button" }, "Xoá trang") : null;
  if (del) del.addEventListener("click", async () => {
    if (!window.confirm(`Xoá trang “${page.title}”? Trang sẽ được chuyển vào series/_trash/.`)) return;
    try { await post(api(`/pages/${encodeURIComponent(page.slug)}/delete`)); editing = false; pageSlug = null; await loadCurrent(); }
    catch (e) { err.textContent = e.message; }
  });
  area.addEventListener("keydown", (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "s") { e.preventDefault(); save.click(); } });
  setTimeout(() => area.focus(), 0);
  return el("div", {},
    area,
    el("p", { class: "sr-help" }, "Markdown. Dòng “# …” đầu tiên là tên trang. Link sang trang khác: [[Tên trang]] hoặc [[Tên trang|chữ hiển thị]]. Lưu nhanh: ⌘/Ctrl+S."),
    el("div", { class: "g-actions" }, save, cancel, el("span", { style: "flex:1" }), del),
    err);
}

// ---------------------------------------------------------------- episodes

function episodesView() {
  const wrap = el("div", {});
  const list = el("div", { class: "sr-eps" });
  if (!current.episodes.length) list.append(el("p", { class: "hint" }, "Chưa có tập nào. Thêm tập đầu tiên ở dưới."));
  for (const ep of current.episodes) list.append(ep.id === editingEp ? episodeEditor(ep) : episodeRow(ep));
  wrap.append(list, el("div", { class: "g-card", style: "margin-top:16px" },
    el("div", { class: "g-card-h" }, el("h3", {}, "Thêm tập")), episodeEditor(null)));
  return wrap;
}

function episodeRow(ep) {
  const err = errBox();
  const status = el("select", { "aria-label": `Trạng thái tập ${ep.number}` }, statuses.episode.map((s) => el("option", { value: s.id }, s.label)));
  status.value = ep.status;
  status.addEventListener("change", async () => {
    try { await post(api(`/episodes/${ep.id}`), { status: status.value }); await loadCurrent(); }
    catch (e) { err.textContent = e.message; status.value = ep.status; }
  });
  const edit = el("button", { class: "g-btn", type: "button" }, "Sửa");
  edit.addEventListener("click", () => { editingEp = ep.id; renderDetail(); });

  let backlogLink;
  if (ep.backlog) backlogLink = el("a", { href: "/backlog" }, `Backlog: ${ep.backlog.title}`);
  else {
    backlogLink = el("button", { class: "g-btn", type: "button" }, "+ Tạo mục Backlog");
    backlogLink.addEventListener("click", async () => {
      backlogLink.disabled = true; err.textContent = "";
      try {
        const item = await post("/api/backlog", {
          title: `${current.title} — Tập ${ep.number}: ${ep.title}`, status: ep.status,
          tags: [current.title, `tập ${ep.number}`, ...(current.characters || [])],
          summary: ep.summary, project_id: ep.project_id || "",
          notes: `Từ series wiki: series/${current.id}`,
        }, "backlog");
        await post(api(`/episodes/${ep.id}`), { backlog_id: item.id });
        await loadCurrent();
      } catch (e) { err.textContent = e.message; backlogLink.disabled = false; }
    });
  }
  const st = ep.stats;
  return el("div", { class: "sr-ep" },
    el("div", { class: "num" }, String(ep.number)),
    el("div", {},
      el("h4", {}, ep.title),
      ep.summary ? el("p", {}, ep.summary) : null,
      el("div", { class: "links" },
        backlogLink,
        ep.project_id ? (ep.project_exists
          ? el("a", { href: `/p/${encodeURIComponent(ep.project_id)}` }, `Board: ${ep.project_id}`)
          : el("span", { class: "g-stamp" }, `project ${ep.project_id} chưa có`)) : null,
        st && st.permalink_url ? el("a", { href: st.permalink_url, target: "_blank", rel: "noopener" }, "Xem trên Facebook") : null),
      err),
    el("div", { class: "sr-ep-side" }, status,
      st ? el("div", { class: "sr-stats" },
        el("div", {}, el("b", {}, nf.format(Math.round(st.plays || 0))), " lượt phát"),
        st.retention != null ? el("div", {}, "xem hết ", el("b", {}, `${Math.round(st.retention * 100)}%`)) : null,
        st.follows ? el("div", {}, el("b", {}, String(st.follows)), " follow mới") : null)
        : (ep.project_id ? el("div", { class: "sr-stats" }, "chưa có số liệu") : null),
      edit),
  );
}

function episodeEditor(ep) {
  const err = errBox();
  const id = ep ? ep.id : "new";
  const f = {
    number: el("input", { type: "number", min: "1", id: `e-num-${id}` }),
    title: el("input", { type: "text", id: `e-title-${id}`, placeholder: "Ví dụ: Sân trực thăng" }),
    status: el("select", { id: `e-status-${id}` }, statuses.episode.map((s) => el("option", { value: s.id }, s.label))),
    project_id: el("input", { type: "text", id: `e-proj-${id}`, placeholder: "Thư mục trong projects/" }),
    summary: el("textarea", { id: `e-sum-${id}`, placeholder: "Tóm tắt tập, hook 2 giây đầu, cảnh kết" }),
  };
  const nextNum = Math.max(0, ...current.episodes.map((e) => e.number || 0)) + 1;
  f.number.value = String(ep ? ep.number : nextNum);
  f.title.value = ep ? ep.title : "";
  f.status.value = ep ? ep.status : "idea";
  f.project_id.value = ep ? ep.project_id || "" : "";
  f.summary.value = ep ? ep.summary || "" : "";
  const save = el("button", { class: "g-btn primary", type: "button" }, ep ? "Lưu tập" : "Thêm tập");
  save.addEventListener("click", async () => {
    err.textContent = ""; save.disabled = true;
    const body = { number: Number(f.number.value) || nextNum, title: f.title.value, status: f.status.value,
      project_id: f.project_id.value, summary: f.summary.value };
    try {
      await post(api(ep ? `/episodes/${ep.id}` : "/episodes"), body);
      editingEp = null; await loadCurrent();
    } catch (e) { err.textContent = e.message; save.disabled = false; }
  });
  const actions = [save];
  if (ep) {
    const cancel = el("button", { class: "g-btn", type: "button" }, "Huỷ");
    cancel.addEventListener("click", () => { editingEp = null; renderDetail(); });
    const del = el("button", { class: "g-btn danger", type: "button" }, "Xoá tập");
    del.addEventListener("click", async () => {
      if (!window.confirm(`Xoá tập ${ep.number} “${ep.title}” khỏi series? Mục Backlog và project vẫn được giữ nguyên.`)) return;
      try { await post(api(`/episodes/${ep.id}/delete`)); editingEp = null; await loadCurrent(); }
      catch (e) { err.textContent = e.message; }
    });
    actions.push(cancel, el("span", { style: "flex:1" }), del);
  }
  const form = el("div", {},
    el("div", { class: "g-form" },
      el("label", { for: f.number.id }, "Tập số", f.number),
      el("label", { for: f.status.id }, "Trạng thái", f.status),
      el("label", { class: "full", for: f.title.id }, "Tên tập", f.title),
      el("label", { class: "full", for: f.project_id.id }, "Project (để lấy board và số liệu Insights)", f.project_id),
      el("label", { class: "full", for: f.summary.id }, "Tóm tắt", f.summary)),
    el("div", { class: "g-actions" }, actions), err);
  if (!ep) return form;
  return el("div", { class: "sr-ep editing" }, el("div", { class: "num" }, String(ep.number)), form);
}

// ---------------------------------------------------------------- info

function infoView() {
  const f = seriesForm(current, async (v) => {
    await post(api(), v);
    tab = "wiki"; storageSet(TAB_KEY, tab);
    await loadAll(); await loadCurrent();
  }, "Lưu thông tin");
  const err = errBox();
  const del = el("button", { class: "g-btn danger", type: "button" }, "Xoá series");
  del.addEventListener("click", async () => {
    if (!window.confirm(`Xoá series “${current.title}”? Cả thư mục (wiki và danh sách tập) sẽ được chuyển vào series/_trash/; mục Backlog và project không bị đụng tới.`)) return;
    try { await post(api("/delete")); selected = null; storageSet(SEL_KEY, ""); current = null; await loadAll(); renderDetail(); }
    catch (e) { err.textContent = e.message; }
  });
  return el("div", {},
    el("div", { class: "g-card" }, el("div", { class: "g-card-h" }, el("h3", {}, "Thông tin series")), f.node),
    el("div", { class: "g-card" }, el("div", { class: "g-card-h" }, el("h3", {}, "Xoá")),
      el("p", { class: "hint", style: "margin-top:0" }, "Chuyển series vào series/_trash/, có thể khôi phục bằng tay."), del, err));
}

// ---------------------------------------------------------------- boot

async function loadCurrent() {
  if (!selected) { current = null; renderDetail(); return; }
  try {
    current = await getJSON(`/api/series/${encodeURIComponent(selected)}`);
  } catch (e) {
    current = null; detailEl.textContent = `Lỗi tải series: ${e.message}`; return;
  }
  const summary = all.find((s) => s.id === current.id);
  if (summary) {
    summary.episode_count = current.episodes.length;
    summary.done_count = current.episodes.filter((e) => e.status === "done").length;
    renderList();
  }
  renderDetail();
}

async function loadAll() {
  const data = await getJSON("/api/series");
  all = data.series; statuses = data.statuses; characters = data.characters;
  if (selected && !all.some((s) => s.id === selected)) selected = null;
  if (!selected && all[0]) selected = all[0].id;
  renderList();
}

document.getElementById("newBtn").addEventListener("click", renderNew);
loadAll().then(loadCurrent).catch((e) => { detailEl.textContent = `Lỗi tải series: ${e.message}`; });
