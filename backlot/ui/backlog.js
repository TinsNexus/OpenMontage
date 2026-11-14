import { el, fmtAgo, getJSON } from "/ui/lib.js";

const THEME_KEY = "backlot.theme";
const SEL_KEY = "backlot.backlog.selected";
const FILTER_KEY = "backlot.backlog.status";
const listEl = document.getElementById("list");
const detailEl = document.getElementById("detail");
const qEl = document.getElementById("q");

let items = [];
let statuses = [];
let selected = storageGet(SEL_KEY);
let statusFilter = storageGet(FILTER_KEY) || "all";
const scriptCache = new Map();

function storageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function storageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* ignore */ } }
document.documentElement.dataset.theme = storageGet(THEME_KEY) === "light" ? "light" : "dark";

async function post(url, body = {}) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Backlot-Action": "backlog" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

const statusLabel = (id) => (statuses.find((s) => s.id === id) || {}).label || id;
const statusChip = (id) => el("span", { class: `chip st-${id}` }, statusLabel(id));
const splitTags = (s) => s.split(",").map((t) => t.trim()).filter(Boolean);
function errBox() { return el("div", { class: "g-error", role: "alert" }); }
function select(id) { selected = id; storageSet(SEL_KEY, id || ""); renderList(); renderDetail(); }

// ---------------------------------------------------------------- list

function matches(it, q) {
  if (statusFilter !== "all" && it.status !== statusFilter) return false;
  if (!q) return true;
  const hay = [it.title, it.summary, it.notes, it.id, ...(it.tags || [])].join(" ").toLowerCase();
  return hay.includes(q);
}

function renderFilter() {
  const box = document.getElementById("statusFilter");
  box.innerHTML = "";
  const opts = [{ id: "all", label: "Tất cả" }, ...statuses];
  for (const s of opts) {
    const n = s.id === "all" ? items.length : items.filter((i) => i.status === s.id).length;
    if (s.id !== "all" && !n && statusFilter !== s.id) continue;
    box.append(el("button", {
      type: "button", "aria-pressed": statusFilter === s.id ? "true" : "false",
      onclick: () => { statusFilter = s.id; storageSet(FILTER_KEY, s.id); renderFilter(); renderList(); },
    }, `${s.label} · ${n}`));
  }
}

function renderList() {
  document.getElementById("count").textContent = `${items.length} mục`;
  document.getElementById("empty").style.display = items.length ? "none" : "block";
  const q = qEl.value.trim().toLowerCase();
  const shown = items.filter((it) => matches(it, q));
  listEl.innerHTML = "";
  let group = null;
  for (const it of shown) {
    if (it.status !== group) {
      group = it.status;
      listEl.append(el("div", { class: "bl-group" }, statusLabel(group)));
    }
    listEl.append(el("button", {
      class: "g-item bl-item", type: "button", "aria-selected": it.id === selected ? "true" : "false",
      onclick: () => select(it.id),
    },
      el("div", {},
        el("h3", {}, it.title),
        it.summary ? el("div", { class: "bl-summary" }, it.summary) : null,
        el("div", { class: "g-chips" },
          statusChip(it.status),
          it.priority ? el("span", { class: "chip warn" }, "★".repeat(it.priority)) : null,
          it.script_exists ? el("span", { class: "chip ok" }, "kịch bản") : null,
          (it.tags || []).slice(0, 3).map((t) => el("span", { class: "chip" }, t)),
        ),
      ),
    ));
  }
  if (items.length && !shown.length) listEl.append(el("p", { class: "hint" }, "Không có mục nào khớp bộ lọc."));
}

// ---------------------------------------------------------------- form

function fieldInputs(it = {}) {
  const f = {
    title: el("input", { id: "f-title", type: "text", placeholder: "Ví dụ: Chó phố gặp chó quê" }),
    status: el("select", { id: "f-status" }, statuses.map((s) => el("option", { value: s.id }, s.label))),
    priority: el("input", { id: "f-priority", type: "number", min: "0", max: "3", step: "1" }),
    tags: el("input", { id: "f-tags", type: "text", placeholder: "hài, thú cưng, shorts" }),
    pipeline: el("input", { id: "f-pipeline", type: "text", placeholder: "cinematic, character-animation…" }),
    project_id: el("input", { id: "f-project", type: "text", placeholder: "Thư mục trong projects/" }),
    script_path: el("input", { id: "f-script", type: "text", placeholder: "projects/<id>/script.md" }),
    summary: el("textarea", { id: "f-summary", placeholder: "Tóm tắt ý tưởng trong 1–3 câu" }),
    notes: el("textarea", { id: "f-notes", placeholder: "Ghi chú sản xuất, việc cần làm…" }),
  };
  f.title.value = it.title || "";
  f.status.value = it.status || "idea";
  f.priority.value = String(it.priority || 0);
  f.tags.value = (it.tags || []).join(", ");
  f.pipeline.value = it.pipeline || "";
  f.project_id.value = it.project_id || "";
  f.script_path.value = it.script_path || "";
  f.summary.value = it.summary || "";
  f.notes.value = it.notes || "";
  return f;
}

const formValues = (f) => ({
  title: f.title.value, status: f.status.value, priority: Number(f.priority.value) || 0,
  tags: splitTags(f.tags.value), pipeline: f.pipeline.value, project_id: f.project_id.value,
  script_path: f.script_path.value, summary: f.summary.value, notes: f.notes.value,
});

function formGrid(f) {
  return el("div", { class: "g-form" },
    el("label", { class: "full", for: "f-title" }, "Tên", f.title),
    el("label", { for: "f-status" }, "Trạng thái", f.status),
    el("label", { for: "f-priority" }, "Ưu tiên (0–3)", f.priority),
    el("label", { for: "f-tags" }, "Tag", f.tags),
    el("label", { for: "f-pipeline" }, "Pipeline", f.pipeline),
    el("label", { for: "f-project" }, "Dự án", f.project_id),
    el("label", { for: "f-script" }, "File kịch bản", f.script_path),
    el("label", { class: "full", for: "f-summary" }, "Tóm tắt", f.summary),
    el("label", { class: "full", for: "f-notes" }, "Ghi chú", f.notes),
  );
}

function renderNew() {
  selected = null;
  renderList();
  detailEl.innerHTML = "";
  const f = fieldInputs();
  const err = errBox();
  const save = el("button", { class: "g-btn primary", type: "button" }, "Thêm vào backlog");
  save.addEventListener("click", async () => {
    err.textContent = "";
    save.disabled = true;
    try {
      const it = await post("/api/backlog", formValues(f));
      selected = it.id;
      storageSet(SEL_KEY, it.id);
      await load();
    } catch (e) { err.textContent = `Không thêm được: ${e.message}`; save.disabled = false; }
  });
  detailEl.append(el("div", { class: "g-card" },
    el("div", { class: "g-card-h" }, el("h3", {}, "Ý tưởng mới")),
    formGrid(f),
    el("div", { class: "g-actions" }, save),
    err,
  ));
  f.title.focus();
}

// ---------------------------------------------------------------- detail

function renderDetail() {
  const it = items.find((x) => x.id === selected);
  detailEl.innerHTML = "";
  if (!it) { detailEl.append(el("p", { class: "hint" }, "Chọn một mục ở bên trái.")); return; }

  const quickStatus = el("select", { "aria-label": "Đổi trạng thái" },
    statuses.map((s) => el("option", { value: s.id }, s.label)));
  quickStatus.value = it.status;
  quickStatus.addEventListener("change", async () => {
    try { await post(`/api/backlog/${encodeURIComponent(it.id)}`, { status: quickStatus.value }); await load(); }
    catch (e) { alert(e.message); quickStatus.value = it.status; }
  });

  detailEl.append(
    el("div", { class: "g-head" }, el("h2", {}, it.title), el("span", { class: "g-sub" }, `backlog/${it.id}`)),
    el("div", { class: "g-meta bl-head-row" },
      quickStatus,
      it.pipeline ? el("span", { class: "chip" }, `pipeline: ${it.pipeline}`) : null,
      (it.tags || []).map((t) => el("span", { class: "chip" }, t)),
      el("span", { class: "chip" }, `cập nhật ${fmtAgo(it.updated_at)}`),
      it.project_exists
        ? el("a", { class: "bl-link", href: `/p/${encodeURIComponent(it.project_id)}` }, "Mở board dự án →")
        : null,
    ),
    it.summary ? el("p", { style: "margin:0 0 16px;color:var(--text-2)" }, it.summary) : null,
    scriptCard(it),
    infoCard(it),
  );
}

function scriptCard(it) {
  const body = el("div", { class: "bl-script" });
  const card = el("div", { class: "g-card" });
  if (!it.script_path) {
    card.append(el("div", { class: "g-card-h" }, el("h3", {}, "Kịch bản")),
      el("p", { class: "hint" }, "Chưa gắn file kịch bản. Điền “File kịch bản” ở phần Thông tin."));
    return card;
  }
  const toggle = el("button", { class: "g-btn", type: "button" }, "Mở rộng");
  toggle.addEventListener("click", () => {
    body.classList.toggle("expanded");
    toggle.textContent = body.classList.contains("expanded") ? "Thu gọn" : "Mở rộng";
  });
  card.append(
    el("div", { class: "g-card-h" }, el("h3", {}, "Kịch bản"), el("code", { class: "chip" }, it.script_path),
      el("span", { class: "spacer" }), it.script_exists ? toggle : null),
    body,
  );
  if (!it.script_exists) {
    body.append(el("p", { class: "g-error" }, "Không tìm thấy file kịch bản này."));
    return card;
  }
  const key = `${it.id}|${it.updated_at}|${it.script_path}`;
  const show = (text) => { body.innerHTML = ""; body.append(renderMarkdown(text || "")); };
  if (scriptCache.has(key)) show(scriptCache.get(key));
  else {
    body.append(el("p", { class: "hint" }, "Đang tải kịch bản…"));
    getJSON(`/api/backlog/${encodeURIComponent(it.id)}/script`)
      .then((r) => { scriptCache.set(key, r.text); if (selected === it.id) show(r.text); })
      .catch((e) => { body.innerHTML = ""; body.append(el("p", { class: "g-error" }, e.message)); });
  }
  return card;
}

function infoCard(it) {
  const f = fieldInputs(it);
  const err = errBox();
  const save = el("button", { class: "g-btn primary", type: "button" }, "Lưu");
  save.addEventListener("click", async () => {
    err.textContent = "";
    try {
      await post(`/api/backlog/${encodeURIComponent(it.id)}`, formValues(f));
      save.textContent = "Đã lưu"; save.classList.add("done");
      await load();
    } catch (e) { err.textContent = `Không lưu được: ${e.message}`; }
  });
  const del = el("button", { class: "g-btn danger", type: "button" }, "Xóa khỏi backlog");
  del.addEventListener("click", async () => {
    if (!window.confirm(`Xóa “${it.title}” khỏi backlog? File kịch bản và dự án vẫn được giữ nguyên.`)) return;
    try { await post(`/api/backlog/${encodeURIComponent(it.id)}/delete`); selected = null; await load(); }
    catch (e) { err.textContent = `Không xóa được: ${e.message}`; }
  });
  return el("div", { class: "g-card" },
    el("div", { class: "g-card-h" }, el("h3", {}, "Thông tin")),
    formGrid(f),
    el("div", { class: "g-actions" }, save, el("span", { class: "spacer", style: "flex:1" }), del),
    err,
  );
}

// ---------------------------------------------------------------- markdown (safe: DOM nodes only)

function inline(text) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) out.push(el("strong", {}, inline(tok.slice(2, -2))));
    else if (tok.startsWith("`")) out.push(el("code", {}, tok.slice(1, -1)));
    else out.push(el("em", {}, inline(tok.slice(1, -1))));
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const cells = (row) => row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

function renderMarkdown(src) {
  const root = document.createDocumentFragment();
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) { root.append(el(`h${Math.min(h[1].length, 4)}`, {}, inline(h[2]))); i++; continue; }
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) { root.append(el("hr")); i++; continue; }
    if (/^\s*>/.test(line)) {
      const quote = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) { quote.push(lines[i].replace(/^\s*>\s?/, "")); i++; }
      const bq = el("blockquote");
      bq.append(renderMarkdown(quote.join("\n")));
      root.append(bq);
      continue;
    }
    if (/^\s*\|/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const head = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) { rows.push(cells(lines[i])); i++; }
      root.append(el("div", { class: "bl-table-wrap" }, el("table", {},
        el("thead", {}, el("tr", {}, head.map((c) => el("th", {}, inline(c))))),
        el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c) => el("td", {}, inline(c)))))),
      )));
      continue;
    }
    const listRe = /^\s*([-*]|\d+\.)\s+(.*)$/;
    if (listRe.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const list = el(ordered ? "ol" : "ul");
      while (i < lines.length && listRe.test(lines[i])) { list.append(el("li", {}, inline(lines[i].match(listRe)[2]))); i++; }
      root.append(list);
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|\s*>|\s*\||\s*([-*]|\d+\.)\s|\s*-{3,}\s*$)/.test(lines[i])) {
      para.push(lines[i].trim()); i++;
    }
    if (!para.length) { para.push(line.trim()); i++; }
    const p = el("p");
    para.forEach((t, n) => { if (n) p.append(el("br")); p.append(...inline(t)); });
    root.append(p);
  }
  return root;
}

// ---------------------------------------------------------------- boot

async function load() {
  const data = await getJSON("/api/backlog");
  items = data.items;
  statuses = data.statuses;
  if (statusFilter !== "all" && !statuses.some((s) => s.id === statusFilter)) statusFilter = "all";
  if (selected && !items.some((x) => x.id === selected)) selected = null;
  if (!selected && items[0]) selected = items[0].id;
  renderFilter();
  renderList();
  renderDetail();
}

document.getElementById("newBtn").addEventListener("click", renderNew);
qEl.addEventListener("input", renderList);
load().catch((e) => { detailEl.textContent = `Lỗi tải backlog: ${e.message}`; });
