import { copyBtn, el, fmtAgo, getJSON, mediaURL, subscribe, thumbURL } from "/ui/lib.js";

const THEME_KEY = "backlot.theme";
const FORM_KEY = "backlot.images.form";
const CAP_KEY = "backlot.images.caption";
const formEl = document.getElementById("form");
const resultsEl = document.getElementById("results");
const filterEl = document.getElementById("filter");

let opts = null;
let images = [];
let busy = false;
const state = loadState();
const pending = { refs: [], uploads: [] };   // refs: {project_id, path}; uploads: {file_name, data_base64}

function storageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function storageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* ignore */ } }
document.documentElement.dataset.theme = storageGet(THEME_KEY) === "light" ? "light" : "dark";

function loadState() {
  try { return { model: "nano-banana-2.1", aspect: "16:9", resolution: "1K", n: 1, project: "", characters: [],
    character_refs: "set", prompt: "", ...JSON.parse(storageGet(FORM_KEY) || "{}") }; }
  catch { return { model: "nano-banana-2.1", aspect: "16:9", resolution: "1K", n: 1, project: "", characters: [],
    character_refs: "set", prompt: "" }; }
}
function saveState() { storageSet(FORM_KEY, JSON.stringify(state)); }

async function post(url, body) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-Backlot-Action": "image" },
    body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

const model = () => opts.models.find((m) => m.id === state.model) || opts.models[0];
function unitPrice() {
  const m = model();
  return m.pricing["*"] ?? m.pricing[state.resolution] ?? 0;
}

// ---------------------------------------------------------------- form

function renderForm() {
  formEl.innerHTML = "";
  const m = model();
  if (!m.aspects.includes(state.aspect)) state.aspect = m.aspects.includes("16:9") ? "16:9" : m.aspects[0];
  if (m.resolutions.length && !m.resolutions.includes(state.resolution)) state.resolution = m.resolutions[0];

  const prompt = el("textarea", { id: "i-prompt", style: "min-height:140px",
    placeholder: "Mô tả ảnh muốn tạo. Có thể dùng tiếng Việt hoặc tiếng Anh." });
  prompt.value = state.prompt;
  prompt.addEventListener("input", () => { state.prompt = prompt.value; saveState(); });

  const sel = (id, values, current, onChange, label = (v) => v) => {
    const s = el("select", { id }, values.map((v) => el("option", { value: v }, label(v))));
    s.value = current;
    s.addEventListener("change", () => { onChange(s.value); saveState(); renderForm(); });
    return s;
  };
  const modelSel = sel("i-model", opts.models.map((x) => x.id), state.model, (v) => { state.model = v; });
  const aspectSel = sel("i-aspect", m.aspects, state.aspect, (v) => { state.aspect = v; });
  const resSel = m.resolutions.length
    ? sel("i-res", m.resolutions, state.resolution, (v) => { state.resolution = v; })
    : el("select", { id: "i-res", disabled: "" }, el("option", {}, "cố định"));
  const nSel = sel("i-n", ["1", "2", "3", "4"], String(state.n), (v) => { state.n = Number(v); });

  const NEW = "__new__";
  const projSel = sel("i-project", [...opts.projects.map((p) => p.project_id), NEW],
    state.project || (opts.projects[0]?.project_id ?? NEW), (v) => { state.project = v; },
    (v) => v === NEW ? "+ Dự án mới…" : (opts.projects.find((p) => p.project_id === v)?.title || v));
  const newName = el("input", { id: "i-newproj", type: "text", placeholder: "Tên dự án mới, ví dụ: Sasa Posters" });
  const isNew = projSel.value === NEW;

  // characters
  const charBox = el("div", { class: "g-chips", style: "gap:8px" },
    opts.characters.length ? opts.characters.map((c) => {
      const on = state.characters.includes(c.id);
      return el("button", { type: "button", class: `g-btn${on ? " done" : ""}`, "aria-pressed": on ? "true" : "false",
        onclick: () => {
          state.characters = on ? state.characters.filter((x) => x !== c.id) : [...state.characters, c.id];
          saveState(); renderForm();
        } }, on ? `✓ ${c.name}` : c.name);
    }) : el("span", { class: "g-cost" }, "Chưa có nhân vật nào trong thư viện."));
  const refsMode = sel("i-crefs", ["set", "full", "primary"], state.character_refs, (v) => { state.character_refs = v; },
    (v) => ({ set: "Bộ chuẩn (3 ảnh)", full: "Đầy đủ (tối đa 6)", primary: "Chỉ ảnh chính" })[v]);

  // reference images
  const refList = el("div", { class: "g-chips", style: "gap:6px" },
    [...pending.refs.map((r, i) => el("span", { class: "chip" }, `${r.project_id}/${r.path.split("/").pop()} `,
      el("button", { type: "button", class: "g-btn", style: "padding:0 6px", "aria-label": "Bỏ ảnh tham chiếu",
        onclick: () => { pending.refs.splice(i, 1); renderForm(); } }, "×"))),
     ...pending.uploads.map((u, i) => el("span", { class: "chip" }, `${u.file_name} `,
      el("button", { type: "button", class: "g-btn", style: "padding:0 6px", "aria-label": "Bỏ ảnh tải lên",
        onclick: () => { pending.uploads.splice(i, 1); renderForm(); } }, "×")))]);
  const upload = el("input", { id: "i-upload", type: "file", multiple: "", accept: "image/png,image/jpeg,image/webp" });
  upload.addEventListener("change", () => {
    const files = [...(upload.files || [])];
    Promise.all(files.map((f) => new Promise((ok) => {
      const r = new FileReader();
      r.onload = () => ok({ file_name: f.name, data_base64: r.result });
      r.readAsDataURL(f);
    }))).then((list) => { pending.uploads.push(...list); renderForm(); });
  });

  const count = state.n;
  const cost = unitPrice() * count;
  const err = el("div", { class: "g-error", role: "alert" });
  const go = el("button", { class: "g-btn primary", type: "button" }, busy ? "Đang tạo…" : `Tạo ${count} ảnh`);
  if (busy) go.disabled = true;
  go.addEventListener("click", async () => {
    if (busy) return;
    if (!prompt.value.trim()) { err.textContent = "Cần viết prompt."; return; }
    if (projSel.value === NEW && !newName.value.trim()) { err.textContent = "Đặt tên cho dự án mới."; return; }
    busy = true; renderFormKeep(err);
    try {
      const body = {
        prompt: prompt.value, model: state.model, aspect: state.aspect, resolution: state.resolution, n: state.n,
        characters: state.characters, character_refs: state.character_refs,
        references: pending.refs, uploads: pending.uploads,
        ...(projSel.value === NEW ? { new_project: newName.value } : { project_id: projSel.value }),
      };
      const r = await post("/api/images/generate", body);
      state.project = r.project_id; saveState();
      await load();
    } catch (e) {
      busy = false; renderForm();
      formEl.querySelector(".g-error").textContent = `Không tạo được: ${e.message}`;
      return;
    }
    busy = false; renderForm();
  });

  formEl.append(el("div", { class: "g-card" },
    el("div", { class: "g-card-h" }, el("h3", {}, "Tạo ảnh")),
    el("div", { class: "g-form" },
      el("label", { class: "full", for: "i-prompt" }, "Prompt", prompt),
      el("label", { for: "i-model" }, "Model", modelSel),
      el("label", { for: "i-aspect" }, "Khung", aspectSel),
      el("label", { for: "i-res" }, "Độ phân giải", resSel),
      el("label", { for: "i-n" }, "Số ảnh", nSel),
      el("label", { class: "full", for: "i-project" }, "Lưu vào dự án", projSel),
      isNew ? el("label", { class: "full", for: "i-newproj" }, "Tên dự án mới", newName) : null,
    ),
    el("h4", { class: "g-cost", style: "margin:16px 0 6px" }, "Nhân vật trong thư viện (giữ đúng ngoại hình)"),
    charBox,
    state.characters.length ? el("div", { class: "g-form", style: "margin-top:8px" },
      el("label", { class: "full", for: "i-crefs" }, "Ảnh nhân vật gửi kèm", refsMode)) : null,
    el("h4", { class: "g-cost", style: "margin:16px 0 6px" }, "Ảnh tham chiếu khác"),
    refList,
    el("div", { class: "g-form", style: "margin-top:6px" },
      el("label", { class: "full", for: "i-upload" }, "Tải ảnh từ máy", upload)),
    el("p", { class: "g-cost", style: "margin:6px 0 0" }, "Hoặc bấm “Dùng làm tham chiếu” trên một ảnh bên phải."),
    el("div", { class: "g-actions", style: "margin-top:16px" }, go,
      el("span", { class: "g-cost" },
        `${state.model} qua PiAPI · ${count} × $${unitPrice().toFixed(3).replace(/0$/, "")} = $${cost.toFixed(2)}`)),
    err,
  ));
}

function renderFormKeep(err) {
  renderForm();
  if (err?.textContent) formEl.querySelector(".g-error").textContent = err.textContent;
}

// ---------------------------------------------------------------- results

function renderFilter() {
  const current = filterEl.value || "__all__";
  filterEl.innerHTML = "";
  filterEl.append(el("option", { value: "__all__" }, "Tất cả dự án"));
  for (const p of opts.projects) filterEl.append(el("option", { value: p.project_id }, p.title || p.project_id));
  filterEl.value = [...filterEl.options].some((o) => o.value === current) ? current : "__all__";
}

function renderResults() {
  const f = filterEl.value;
  const shown = images.filter((i) => f === "__all__" || i.project_id === f);
  document.getElementById("count").textContent = `${images.length} ảnh`;
  document.getElementById("empty").style.display = shown.length ? "none" : "block";
  resultsEl.innerHTML = "";
  for (const img of shown) {
    const charSel = opts.characters.length ? el("select", { class: "g-role", "aria-label": "Chọn nhân vật để lưu" },
      opts.characters.map((c) => el("option", { value: c.id }, c.name))) : null;
    const saveBtn = charSel ? el("button", { class: "g-btn", type: "button" }, "Lưu vào nhân vật") : null;
    saveBtn?.addEventListener("click", async () => {
      try {
        const res = await fetch(`/api/characters/${encodeURIComponent(charSel.value)}/images`, {
          method: "POST", headers: { "Content-Type": "application/json", "X-Backlot-Action": "character" },
          body: JSON.stringify({ project_id: img.project_id, path: img.path, note: img.prompt?.slice(0, 300) || "" }),
        });
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.status);
        saveBtn.textContent = "Đã lưu"; saveBtn.classList.add("done");
      } catch (e) { alert(`Không lưu được: ${e.message}`); }
    });
    resultsEl.append(el("figure", { class: "g-thumb-tile" },
      el("a", { href: mediaURL(img.project_id, img.path), target: "_blank", rel: "noopener" },
        el("img", { src: thumbURL(img.project_id, img.path, 640), loading: "lazy", alt: img.prompt || img.name })),
      el("figcaption", { style: "flex-direction:column;align-items:stretch" },
        el("div", { class: "g-chips" },
          el("span", { class: "chip" }, img.project_id),
          img.model ? el("span", { class: "chip" }, `${img.model}${img.resolution ? " · " + img.resolution : ""}`) : null,
          img.aspect_ratio ? el("span", { class: "chip" }, img.aspect_ratio) : null,
          img.cost_usd != null ? el("span", { class: "chip" }, `$${Number(img.cost_usd).toFixed(2)}`) : null,
          (img.characters || []).map((c) => el("span", { class: "chip ok" }, c)),
          el("span", { class: "chip" }, fmtAgo(img.modified))),
        img.prompt ? el("p", { class: "g-sub", style: "margin:6px 0;max-height:4.5em;overflow:hidden" }, img.prompt) : null,
        el("div", { class: "g-actions", style: "margin:4px 0 0;gap:6px" },
          img.prompt ? el("button", { class: "g-btn", type: "button", onclick: () => {
            Object.assign(state, { prompt: img.prompt, model: img.model || state.model,
              aspect: img.aspect_ratio || state.aspect, resolution: img.resolution || state.resolution,
              characters: img.characters || [], project: img.project_id });
            saveState(); renderForm(); window.scrollTo({ top: 0, behavior: "smooth" });
          } }, "Dùng lại prompt") : null,
          el("button", { class: "g-btn", type: "button", onclick: () => {
            if (!pending.refs.some((r) => r.project_id === img.project_id && r.path === img.path)) {
              pending.refs.push({ project_id: img.project_id, path: img.path });
            }
            renderForm(); window.scrollTo({ top: 0, behavior: "smooth" });
          } }, "Dùng làm tham chiếu"),
          el("a", { class: "g-btn", href: mediaURL(img.project_id, img.path), download: img.name }, "Tải"),
          el("button", { class: img.social ? "g-btn done" : "g-btn", type: "button", onclick: () => openCaption(img) },
            img.social ? "✓ Caption" : "Viết caption"),
        ),
        charSel ? el("div", { class: "g-actions", style: "margin:6px 0 0;gap:6px" }, charSel, saveBtn) : null,
      ),
    ));
  }
}

// ---------------------------------------------------------------- captions

let dialog = null;
function capPrefs() {
  try { return { platform: "facebook_post", language: "vi", ...JSON.parse(storageGet(CAP_KEY) || "{}") }; }
  catch { return { platform: "facebook_post", language: "vi" }; }
}

function captionOutput(s) {
  if (!s || !s.caption) return el("p", { class: "hint" }, "Chưa có caption cho ảnh này.");
  const tagsText = (s.hashtags || []).join(" ");
  const options = (s.captions && s.captions.length ? s.captions : [s.caption]);
  const platformLabel = (opts.caption_platforms.find((p) => p.id === s.platform) || {}).label || s.platform;
  return el("div", { class: "g-out" },
    el("div", {},
      el("h4", {}, `Caption (${options.length} phương án)`),
      options.map((c, i) => {
        const ta = el("textarea", { "aria-label": `Caption phương án ${i + 1}` });
        ta.value = c;
        return el("div", { class: "g-row", style: "margin-bottom:8px" }, ta,
          el("div", { style: "display:flex;flex-direction:column;gap:6px" },
            copyBtn(() => ta.value),
            copyBtn(() => `${ta.value}\n\n${tagsText}`, "Copy + hashtag")));
      })),
    tagsText ? el("div", {}, el("h4", {}, "Hashtag"),
      el("div", { class: "g-row" }, el("div", { class: "g-tags" }, s.hashtags.map((t) => el("span", { class: "chip" }, t))),
        copyBtn(() => tagsText))) : null,
    s.alt_text ? el("div", {}, el("h4", {}, "Alt text (mô tả ảnh cho người khiếm thị)"),
      el("div", { class: "g-row" }, el("div", { class: "g-title" }, s.alt_text), copyBtn(() => s.alt_text))) : null,
    el("p", { class: "g-stamp" },
      `${platformLabel} · ${s.model}${s.vision ? " · đã nhìn ảnh" : " · viết từ prompt (không gửi được ảnh)"} · ${fmtAgo(s.created_at)}`),
    s.history && s.history.length ? el("details", { class: "g-history" },
      el("summary", {}, `Các bản trước (${s.history.length})`),
      s.history.slice().reverse().map((h) => el("div", { class: "g-hist-item" },
        el("p", {}, h.caption), el("p", { class: "g-stamp" }, (h.hashtags || []).join(" "))))) : null,
  );
}

function openCaption(img) {
  if (!dialog) {
    dialog = el("dialog", { class: "g-dialog", "aria-label": "Viết caption cho ảnh" });
    dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });
    document.body.append(dialog);
  }
  const prefs = capPrefs();
  const platform = el("select", { id: "c-platform" }, opts.caption_platforms.map((p) => el("option", { value: p.id }, p.label)));
  platform.value = prefs.platform;
  const language = el("select", { id: "c-lang" }, opts.caption_languages.map((l) => el("option", { value: l.id }, l.label)));
  language.value = prefs.language;
  const notes = el("textarea", { id: "c-notes", placeholder: "Ghi chú (không bắt buộc): bối cảnh, mục tiêu bài đăng, giọng văn, CTA…" });
  notes.value = (img.social && img.social.notes) || "";
  const aiBox = el("input", { type: "checkbox", id: "c-ai" });
  aiBox.checked = img.social && img.social.ai_generated != null ? img.social.ai_generated : true;
  const out = el("div", {}, captionOutput(img.social));
  const err = el("div", { class: "g-error", role: "alert" });
  const go = el("button", { class: "g-btn primary", type: "button" }, img.social ? "Viết lại" : "Viết caption");
  go.addEventListener("click", async () => {
    err.textContent = ""; go.disabled = true; go.textContent = "Đang viết…";
    storageSet(CAP_KEY, JSON.stringify({ platform: platform.value, language: language.value }));
    try {
      const res = await fetch("/api/images/caption", {
        method: "POST", headers: { "Content-Type": "application/json", "X-Backlot-Action": "social" },
        body: JSON.stringify({ project_id: img.project_id, path: img.path, platform: platform.value,
          language: language.value, notes: notes.value, ai_generated: aiBox.checked }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      img.social = data;
      out.innerHTML = ""; out.append(captionOutput(data));
      renderResults();
    } catch (e) { err.textContent = `Không viết được: ${e.message}`; }
    go.disabled = false; go.textContent = "Viết lại";
  });
  const close = el("button", { class: "g-btn g-dialog-close", type: "button", "aria-label": "Đóng" }, "Đóng");
  close.addEventListener("click", () => dialog.close());

  dialog.innerHTML = "";
  dialog.append(el("div", { class: "g-dialog-body" },
    close,
    el("div", { class: "g-card-h" }, el("h3", {}, "Caption cho ảnh")),
    el("div", { class: "g-dialog-top" },
      el("img", { src: thumbURL(img.project_id, img.path, 640), alt: img.prompt || img.name }),
      el("div", {},
        el("div", { class: "g-form" },
          el("label", { for: "c-platform" }, "Nền tảng", platform),
          el("label", { for: "c-lang" }, "Ngôn ngữ", language),
          el("label", { class: "full", for: "c-notes" }, "Ghi chú cho AI", notes),
          el("label", { class: "full", for: "c-ai", style: "flex-direction:row;align-items:center;gap:8px" },
            aiBox, "Ảnh tạo bằng AI (thêm dòng ghi chú AI vào caption)")),
        el("div", { class: "g-actions" }, go,
          el("span", { class: "g-cost" }, `${opts.caption_model} qua PiAPI · AI nhìn ảnh để viết`)),
        err)),
    out));
  dialog.showModal();
}

// ---------------------------------------------------------------- boot

async function load() {
  [opts, images] = await Promise.all([getJSON("/api/images/options"), getJSON("/api/images")]);
  if (!opts.models.some((m) => m.id === state.model)) state.model = opts.default_model;
  state.characters = state.characters.filter((id) => opts.characters.some((c) => c.id === id));
  renderForm();
  renderFilter();
  renderResults();
}

filterEl.addEventListener("change", renderResults);
load().catch((e) => { formEl.textContent = `Lỗi tải trang: ${e.message}`; });
subscribe("/api/library/events", () => {
  if (busy) return;
  getJSON("/api/images").then((list) => { images = list; renderResults(); }).catch(() => {});
});
