import { el, fmtAgo, getJSON, thumbURL } from "/ui/lib.js";

const THEME_KEY = "backlot.theme";
const SEL_KEY = "backlot.characters.selected";
const listEl = document.getElementById("list");
const detailEl = document.getElementById("detail");

let chars = [];
let roles = [];
let selected = storageGet(SEL_KEY);
const SET_ROLES = ["face", "back", "face_34", "side", "face_profile"];
const ROLE_VI = { full_body: "Toàn thân", face: "Mặt trước", face_34: "Mặt chéo 3/4", face_profile: "Mặt nghiêng",
  back: "Sau lưng", side: "Nghiêng", action: "Hành động", front_34: "Chéo 3/4", sheet: "Sheet", other: "Khác" };
// Generation settings per preset role (sheet: wide, high-res, whole reference set).
const PRESET_OPTS = { sheet: { aspect: "16:9", resolution: "2K" }, face_sheet: { aspect: "16:9", resolution: "2K" } };
const PRESET_ROLE = { face_sheet: "sheet" };   // preset key -> stored role
const PRESET_LABEL = { face_sheet: "Sheet mặt" };
const PRESETS = {
  face: "Head-and-shoulders face close-up of the same character, looking straight at the camera, neutral expression, "
    + "face fully visible and unobstructed, soft even studio light, plain light grey seamless backdrop, photorealistic.",
  back: "Full-body back view of the same character standing upright, seen from directly behind, whole outfit and hairstyle "
    + "visible from head to boots, plain light grey seamless studio backdrop, soft even light, photorealistic.",
  side: "Full-body side profile of the same character facing left, standing upright, whole outfit visible from head to boots, "
    + "plain light grey seamless studio backdrop, soft even light, photorealistic.",
  sheet: "Professional character turnaround model sheet of this same character on one plain light grey seamless studio "
    + "backdrop. Five panels in a single row, left to right, evenly spaced with clear empty grey gaps between them, every "
    + "figure at the same scale with feet on the same baseline: (1) full-body front view, (2) full-body three-quarter front "
    + "view, (3) full-body side profile facing left, (4) full-body back view, (5) large head-and-shoulders face close-up "
    + "looking at the camera. Neutral relaxed standing pose, arms at her sides, neutral expression, identical outfit, hair "
    + "and proportions in every panel, soft even studio lighting, photorealistic, sharp detail. No text, no labels, no "
    + "numbers, no arrows, no borders, no props.",
  face_sheet: "Professional face reference sheet of this same character on one plain light grey seamless studio backdrop. "
    + "Three head-and-shoulders close-ups in a single row, left to right, evenly spaced, each head the same size and at "
    + "the same height: (1) face straight on, looking at the camera, (2) three-quarter view, head turned about 45 degrees, "
    + "(3) full side profile. Neutral expression, mouth closed, soft even studio lighting, photorealistic skin texture, "
    + "sharp focus. No text, no labels, no numbers, no borders.",
};

// Mirrors lib/characters.reference_set: primary first, then one face / back / side.
function referenceSet(c, size = 3) {
  if (!c.primary_image) return [];
  const out = [c.images.find((i) => i.file === c.primary_image) || { file: c.primary_image, role: "full_body" }];
  for (const role of SET_ROLES) {
    if (out.length >= size) break;
    const m = c.images.find((i) => i.role === role && i.file !== c.primary_image);
    if (m) out.push(m);
  }
  return out;
}
let busy = false;

function storageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function storageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* ignore */ } }
document.documentElement.dataset.theme = storageGet(THEME_KEY) === "light" ? "light" : "dark";

const imgURL = (id, file) => `/character-media/${encodeURIComponent(id)}/${encodeURIComponent(file)}`;

async function post(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Backlot-Action": "character" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

async function copyText(text, btn) {
  try { await navigator.clipboard.writeText(text); } catch { /* ignore */ }
  const old = btn.textContent;
  btn.textContent = "Đã copy";
  btn.classList.add("done");
  setTimeout(() => { btn.textContent = old; btn.classList.remove("done"); }, 1400);
}

function errBox() { return el("div", { class: "g-error", role: "alert" }); }

// ---------------------------------------------------------------- list

function renderList() {
  document.getElementById("count").textContent = `${chars.length} nhân vật`;
  document.getElementById("empty").style.display = chars.length ? "none" : "block";
  listEl.innerHTML = "";
  for (const c of chars) {
    listEl.append(el("button", {
      class: "g-item", type: "button", "aria-selected": c.id === selected ? "true" : "false",
      onclick: () => { selected = c.id; storageSet(SEL_KEY, c.id); renderList(); renderDetail(); },
    },
      el("div", { class: "g-thumb", style: "aspect-ratio:3/4" },
        c.primary_image ? el("img", { src: imgURL(c.id, c.primary_image), loading: "lazy", alt: "" }) : null),
      el("div", {},
        el("h3", {}, c.name),
        el("div", { class: "g-sub" }, c.id),
        el("div", { class: "g-chips" },
          el("span", { class: "chip" }, `${c.images.length} ảnh`),
          (c.tags || []).slice(0, 3).map((t) => el("span", { class: "chip" }, t)),
          c.primary_image ? null : el("span", { class: "chip warn" }, "chưa có ảnh"),
        ),
      ),
    ));
  }
}

// ---------------------------------------------------------------- new character

function renderNew() {
  selected = null;
  renderList();
  detailEl.innerHTML = "";
  const name = el("input", { id: "n-name", type: "text", placeholder: "Ví dụ: Sasa" });
  const desc = el("textarea", { id: "n-desc", placeholder: "Mô tả ngắn cho bạn đọc (tiếng Việt cũng được)" });
  const identity = el("textarea", { id: "n-identity", style: "min-height:96px",
    placeholder: "Mô tả ngoại hình bằng tiếng Anh để đưa vào prompt: tuổi, khuôn mặt, tóc, trang phục, màu chủ đạo…" });
  const tags = el("input", { id: "n-tags", type: "text", placeholder: "Tag, cách nhau bằng dấu phẩy" });
  const err = errBox();
  const save = el("button", { class: "g-btn primary", type: "button" }, "Tạo nhân vật");
  save.addEventListener("click", async () => {
    err.textContent = "";
    try {
      const c = await post("/api/characters", {
        name: name.value, description: desc.value, identity: identity.value,
        tags: tags.value.split(",").map((t) => t.trim()).filter(Boolean),
      });
      selected = c.id;
      storageSet(SEL_KEY, c.id);
      await load();
    } catch (e) { err.textContent = `Không tạo được: ${e.message}`; }
  });
  detailEl.append(el("div", { class: "g-card" },
    el("div", { class: "g-card-h" }, el("h3", {}, "Nhân vật mới")),
    el("div", { class: "g-form" },
      el("label", { for: "n-name" }, "Tên", name),
      el("label", { for: "n-tags" }, "Tag", tags),
      el("label", { class: "full", for: "n-desc" }, "Mô tả", desc),
      el("label", { class: "full", for: "n-identity" }, "Mô tả ngoại hình cho prompt (identity)", identity),
    ),
    el("div", { class: "g-actions" }, save,
      el("span", { class: "g-cost" }, "Sau khi tạo, thêm ảnh tham chiếu từ dự án, tải lên, hoặc tạo bằng AI.")),
    err,
  ));
  name.focus();
}

// ---------------------------------------------------------------- detail

function renderDetail() {
  const c = chars.find((x) => x.id === selected);
  detailEl.innerHTML = "";
  if (!c) { detailEl.append(el("p", { class: "hint" }, "Chọn một nhân vật ở bên trái.")); return; }

  // images
  const set = referenceSet(c);
  const inSet = new Map(set.map((img, i) => [img.file, i + 1]));
  const grid = el("div", { class: "g-thumbs" });
  for (const img of c.images) {
    const primary = img.file === c.primary_image;
    const roleSel = el("select", { "aria-label": `Vai trò của ${img.file}`, class: "g-role" },
      roles.map((r) => el("option", { value: r.id }, ROLE_VI[r.id] || r.label)));
    roleSel.value = img.role || "other";
    roleSel.addEventListener("change", async () => {
      try { await post(`/api/characters/${c.id}/role`, { file: img.file, role: roleSel.value }); await load(); }
      catch (e) { alert(e.message); }
    });
    grid.append(el("figure", { class: `g-thumb-tile${inSet.has(img.file) ? " picked" : ""}` },
      el("a", { href: imgURL(c.id, img.file), target: "_blank", rel: "noopener" },
        el("img", { src: imgURL(c.id, img.file), loading: "lazy", alt: img.note || img.file, style: "aspect-ratio:3/4" })),
      el("figcaption", {},
        primary ? el("span", { class: "chip ok" }, "Ảnh chính")
          : inSet.has(img.file) ? el("span", { class: "chip ok" }, `@image${inSet.get(img.file)}`)
          : el("span", { class: "chip" }, img.file),
        roleSel,
        primary ? null : el("button", { class: "g-btn", type: "button", onclick: async () => {
          try { await post(`/api/characters/${c.id}/primary`, { file: img.file }); await load(); } catch (e) { alert(e.message); }
        } }, "Đặt làm chính"),
        img.role === "sheet" ? el("button", { class: "g-btn", type: "button", onclick: async (ev) => {
          const answer = window.prompt("Sheet có mấy ô? (để trống: tự tìm khoảng trống giữa các hình)", "");
          if (answer === null) return;
          ev.target.disabled = true;
          ev.target.textContent = "Đang cắt…";
          try {
            const r = await post(`/api/characters/${c.id}/split`, { file: img.file, panels: answer.trim() || null });
            await load();
            alert(`Đã cắt ${r.split_panels} ảnh (vai trò "Khác"). Chọn vai trò cho từng ảnh để dùng.`);
          } catch (e) { alert(e.message); ev.target.disabled = false; ev.target.textContent = "Cắt thành từng góc"; }
        } }, "Cắt thành từng góc") : null,
      ),
    ));
  }
  if (!c.images.length) grid.append(el("p", { class: "hint" }, "Chưa có ảnh tham chiếu. Thêm ảnh ở bên dưới."));
  const setNote = set.length
    ? `Khi dùng characters: ["${c.id}"], model nhận ${set.length} ảnh theo thứ tự: `
      + set.map((img, i) => `@image${i + 1} ${ROLE_VI[img.role] || img.role}`).join(" → ")
      + ". Viền cam là ảnh được gửi."
      + (() => {
        const full = referenceSet(c, 6);
        return full.length > set.length
          ? ` Thêm character_refs: "full" để gửi ${full.length} ảnh: `
            + full.map((img, i) => `@image${i + 1} ${ROLE_VI[img.role] || img.role}`).join(" → ") + "."
          : "";
      })()
    : "Cần ít nhất một ảnh chính.";

  const usage = `characters: ["${c.id}"]`;
  const copyUse = el("button", { class: "g-btn", type: "button" }, "Copy cách dùng");
  copyUse.addEventListener("click", () => copyText(usage, copyUse));

  detailEl.append(
    el("div", { class: "g-head" }, el("h2", {}, c.name), el("span", { class: "g-sub" }, `characters/${c.id}`)),
    el("div", { class: "g-meta" },
      el("span", { class: "chip" }, `${c.images.length} ảnh`),
      el("span", { class: "chip" }, `cập nhật ${fmtAgo(c.updated_at)}`),
      el("code", { class: "chip" }, usage), copyUse),
    el("div", { class: "g-card" }, el("div", { class: "g-card-h" }, el("h3", {}, "Ảnh tham chiếu")),
      el("p", { class: "g-stamp", style: "margin:0 0 4px" }, setNote), grid),
    infoCard(c),
    addImageCard(c),
  );
}

function infoCard(c) {
  const name = el("input", { id: "e-name", type: "text" }); name.value = c.name;
  const tags = el("input", { id: "e-tags", type: "text" }); tags.value = (c.tags || []).join(", ");
  const desc = el("textarea", { id: "e-desc" }); desc.value = c.description || "";
  const identity = el("textarea", { id: "e-identity", style: "min-height:110px" }); identity.value = c.identity || "";
  const err = errBox();
  const save = el("button", { class: "g-btn primary", type: "button" }, "Lưu");
  save.addEventListener("click", async () => {
    err.textContent = "";
    try {
      await post(`/api/characters/${c.id}`, { name: name.value, description: desc.value, identity: identity.value,
        tags: tags.value.split(",").map((t) => t.trim()).filter(Boolean) });
      save.textContent = "Đã lưu"; save.classList.add("done");
      await load();
    } catch (e) { err.textContent = `Không lưu được: ${e.message}`; }
  });
  const copyId = el("button", { class: "g-btn", type: "button" }, "Copy identity");
  copyId.addEventListener("click", () => copyText(identity.value, copyId));
  return el("div", { class: "g-card" },
    el("div", { class: "g-card-h" }, el("h3", {}, "Thông tin"), el("span", { class: "spacer" }), copyId),
    el("div", { class: "g-form" },
      el("label", { for: "e-name" }, "Tên", name),
      el("label", { for: "e-tags" }, "Tag", tags),
      el("label", { class: "full", for: "e-desc" }, "Mô tả", desc),
      el("label", { class: "full", for: "e-identity" }, "Mô tả ngoại hình cho prompt (identity)", identity),
    ),
    el("div", { class: "g-actions" }, save), err);
}

function addImageCard(c) {
  const err = errBox();
  const card = el("div", { class: "g-card" }, el("div", { class: "g-card-h" }, el("h3", {}, "Thêm ảnh tham chiếu")));
  const roleSel = el("select", { id: "a-role" }, roles.map((r) => el("option", { value: r.id }, ROLE_VI[r.id] || r.label)));
  let genOpts = {};
  const missing = SET_ROLES.find((r) => !c.images.some((i) => i.role === r));
  roleSel.value = c.primary_image ? (missing || "other") : "full_body";

  // from project
  const sourceSel = el("select", { id: "a-source" }, el("option", { value: "" }, "Đang tải danh sách ảnh…"));
  const fromProject = el("button", { class: "g-btn", type: "button" }, "Thêm ảnh này");
  const preview = el("img", { alt: "", style: "display:none;max-width:160px;border-radius:8px;margin-top:8px" });
  getJSON("/api/characters/sources").then((items) => {
    sourceSel.innerHTML = "";
    sourceSel.append(el("option", { value: "" }, items.length ? "— chọn ảnh trong dự án —" : "Không có ảnh nào trong projects/"));
    for (const it of items) sourceSel.append(el("option", { value: `${it.project_id}|${it.path}` }, `${it.project_id} / ${it.path}`));
  }).catch(() => { sourceSel.innerHTML = ""; sourceSel.append(el("option", { value: "" }, "Không tải được danh sách")); });
  sourceSel.addEventListener("change", () => {
    const [pid, path] = sourceSel.value.split("|");
    preview.style.display = pid ? "block" : "none";
    if (pid) preview.src = thumbURL(pid, path, 320);
  });
  fromProject.addEventListener("click", async () => {
    if (!sourceSel.value) return;
    const [project_id, path] = sourceSel.value.split("|");
    err.textContent = "";
    try { await post(`/api/characters/${c.id}/images`, { project_id, path, role: roleSel.value }); await load(); }
    catch (e) { err.textContent = `Không thêm được: ${e.message}`; }
  });

  // upload
  const file = el("input", { id: "a-file", type: "file", accept: "image/png,image/jpeg,image/webp" });
  file.addEventListener("change", () => {
    const f = file.files?.[0];
    if (!f) return;
    const reader = new FileReader();
    reader.onload = async () => {
      err.textContent = "";
      try {
        await post(`/api/characters/${c.id}/images`, { file_name: f.name, data_base64: reader.result, role: roleSel.value });
        await load();
      }
      catch (e) { err.textContent = `Không tải lên được: ${e.message}`; }
    };
    reader.readAsDataURL(f);
  });

  // AI
  const prompt = el("textarea", { id: "a-prompt", placeholder: c.primary_image
    ? "Ví dụ: full-body turnaround, side view, plain grey studio backdrop"
    : "Ví dụ: full-body character reference photo, plain grey studio backdrop" });
  const gen = el("button", { class: "g-btn primary", type: "button" }, "Tạo ảnh AI");
  gen.addEventListener("click", async () => {
    if (busy || !prompt.value.trim()) return;
    busy = true; gen.disabled = true; gen.textContent = "Đang tạo… (~30-70s)"; err.textContent = "";
    try {
      await post(`/api/characters/${c.id}/generate`,
        { prompt: prompt.value, role: roleSel.value, ...(roleSel.value === "sheet" ? (genOpts.aspect ? genOpts : PRESET_OPTS.sheet) : {}) });
      await load();
    }
    catch (e) { err.textContent = `Không tạo được: ${e.message}`; }
    finally { busy = false; gen.disabled = false; gen.textContent = "Tạo ảnh AI"; }
  });

  const presets = c.primary_image ? el("div", { class: "g-actions", style: "margin-top:8px" },
    el("span", { class: "g-cost" }, "Mẫu nhanh:"),
    Object.keys(PRESETS).map((role) => el("button", { class: "g-btn", type: "button", onclick: () => {
      prompt.value = PRESETS[role];
      roleSel.value = PRESET_ROLE[role] || role;
      genOpts = PRESET_OPTS[role] || {};
    } }, PRESET_LABEL[role] || ROLE_VI[role]))) : null;

  card.append(
    el("div", { class: "g-form" },
      el("label", { for: "a-role" }, "Vai trò của ảnh thêm vào", roleSel),
      el("label", { class: "full", for: "a-source" }, "Từ ảnh trong dự án", sourceSel),
    ),
    preview,
    el("div", { class: "g-actions" }, fromProject),
    el("div", { class: "g-form", style: "margin-top:14px" },
      el("label", { class: "full", for: "a-file" }, "Tải ảnh từ máy (png, jpg, webp)", file)),
    el("div", { class: "g-form", style: "margin-top:14px" },
      el("label", { class: "full", for: "a-prompt" },
        c.primary_image ? "Tạo thêm góc/tư thế bằng AI (giữ đúng nhân vật theo ảnh chính)" : "Tạo ảnh nhân vật bằng AI",
        prompt)),
    presets,
    el("div", { class: "g-actions" }, gen, el("span", { class: "g-cost" }, "nano-banana-2.1 qua PiAPI · $0.03 mỗi ảnh")),
    err,
  );
  return card;
}

// ---------------------------------------------------------------- boot

async function load() {
  [chars, roles] = await Promise.all([getJSON("/api/characters"), roles.length ? roles : getJSON("/api/characters/roles")]);
  if (selected && !chars.some((c) => c.id === selected)) selected = null;
  if (!selected && chars[0]) selected = chars[0].id;
  renderList();
  renderDetail();
}

document.getElementById("newBtn").addEventListener("click", renderNew);
load().catch((e) => { detailEl.textContent = `Lỗi tải nhân vật: ${e.message}`; });
