import { copyBtn, el, fmtAgo, getJSON, mediaURL, thumbURL } from "/ui/lib.js";

const THEME_KEY = "backlot.theme";
const SEL_KEY = "backlot.products.selected";
const GEN_KEY = "backlot.products.gen";
const listEl = document.getElementById("list");
const detailEl = document.getElementById("detail");
const filterEl = document.getElementById("filter");

let products = [];
let roles = [];
let opts = null;          // /api/images/options (models, projects, characters)
let current = null;       // full product incl. generated images
let busy = false;
let selected = storageGet(SEL_KEY);

const ROLE_VI = { front: "Mặt trước", back: "Mặt sau", side: "Bên hông", detail: "Chi tiết", label: "Nhãn / logo",
  packaging: "Bao bì", in_use: "Đang dùng", scale: "So kích thước", other: "Khác" };
const SET_ROLES = ["label", "back", "side", "packaging", "detail"];
const PRESETS = {
  "Ảnh studio": "Clean e-commerce packshot of the product on a seamless white studio backdrop, soft even light, "
    + "subtle reflection, centred, sharp focus, photorealistic.",
  "Lifestyle": "The product in a cosy, real-life home setting, natural window light, shallow depth of field, "
    + "styled like a premium Instagram product photo, photorealistic.",
  "Người cầm": "A young Vietnamese person holding the product toward the camera and smiling, product clearly "
    + "visible in focus, bright natural light, lifestyle photo, photorealistic.",
  "Flat lay": "Top-down flat lay of the product with a few matching props on a pastel background, soft shadows, "
    + "magazine-style composition, photorealistic.",
  "Khung hình video": "Cinematic first frame for a short vertical video: the product on a table in a moody, "
    + "beautifully lit scene, room for motion, photorealistic, 35mm film look.",
};

function storageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function storageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* ignore */ } }
document.documentElement.dataset.theme = storageGet(THEME_KEY) === "light" ? "light" : "dark";

const imgURL = (id, file) => `/product-media/${encodeURIComponent(id)}/${encodeURIComponent(file)}`;

async function post(url, body, action = "product") {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Backlot-Action": action },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

function readFiles(files) {
  return Promise.all([...files].map((f) => new Promise((ok, fail) => {
    const r = new FileReader();
    r.onload = () => ok({ file_name: f.name, data_base64: r.result });
    r.onerror = () => fail(new Error(`không đọc được ${f.name}`));
    r.readAsDataURL(f);
  })));
}

const errBox = () => el("div", { class: "g-error", role: "alert" });
const tagList = (v) => v.split(",").map((t) => t.trim()).filter(Boolean);

function linkChip(p) {
  if (!p.affiliate_url) return el("span", { class: "chip warn" }, "chưa có link");
  return el("span", { class: "chip ok" }, p.is_shopee ? "Shopee" : "có link");
}

// ---------------------------------------------------------------- list

function renderList() {
  const q = (filterEl.value || "").trim().toLowerCase();
  const shown = products.filter((p) => !q || `${p.name} ${p.description || ""} ${(p.tags || []).join(" ")}`
    .toLowerCase().includes(q));
  document.getElementById("count").textContent = `${products.length} sản phẩm`;
  document.getElementById("empty").style.display = products.length ? "none" : "block";
  listEl.innerHTML = "";
  for (const p of shown) {
    listEl.append(el("button", {
      class: "g-item", type: "button", "aria-selected": p.id === selected ? "true" : "false",
      onclick: () => select(p.id),
    },
      el("div", { class: "g-thumb", style: "aspect-ratio:1/1" },
        p.primary_image ? el("img", { src: imgURL(p.id, p.primary_image), loading: "lazy", alt: "" }) : null),
      el("div", {},
        el("h3", {}, p.name),
        el("div", { class: "g-sub" }, p.price || p.id),
        el("div", { class: "g-chips" },
          linkChip(p),
          el("span", { class: "chip" }, `${p.images.length} ảnh`),
          p.projects?.length ? el("span", { class: "chip" }, `${p.projects.length} dự án`) : null,
          p.primary_image ? null : el("span", { class: "chip warn" }, "chưa có ảnh")),
      ),
    ));
  }
}

async function select(id) {
  selected = id;
  storageSet(SEL_KEY, id);
  renderList();
  await loadCurrent();
}

// ---------------------------------------------------------------- new product

function renderNew() {
  selected = null;
  current = null;
  renderList();
  detailEl.innerHTML = "";
  const name = el("input", { id: "n-name", type: "text", placeholder: "Ví dụ: Tai nghe bluetooth X1" });
  const url = el("input", { id: "n-url", type: "text", inputmode: "url", placeholder: "https://s.shopee.vn/..." });
  const price = el("input", { id: "n-price", type: "text", placeholder: "Ví dụ: 199.000đ" });
  const tags = el("input", { id: "n-tags", type: "text", placeholder: "Tag, cách nhau bằng dấu phẩy" });
  const desc = el("textarea", { id: "n-desc", style: "min-height:90px",
    placeholder: "Mô tả sản phẩm: công dụng, điểm nổi bật, đối tượng dùng… (AI dùng để viết caption)" });
  const files = el("input", { id: "n-files", type: "file", multiple: "", accept: "image/png,image/jpeg,image/webp" });
  const err = errBox();
  const save = el("button", { class: "g-btn primary", type: "button" }, "Tạo sản phẩm");
  save.addEventListener("click", async () => {
    err.textContent = "";
    if (!name.value.trim()) { err.textContent = "Cần nhập tên sản phẩm."; return; }
    save.disabled = true; save.textContent = "Đang lưu…";
    try {
      const p = await post("/api/products", { name: name.value, affiliate_url: url.value, price: price.value,
        description: desc.value, tags: tagList(tags.value) });
      const uploads = await readFiles(files.files || []);
      for (const [i, up] of uploads.entries()) {
        await post(`/api/products/${p.id}/images`, { ...up, role: i === 0 ? "front" : "other" });
      }
      selected = p.id; storageSet(SEL_KEY, p.id);
      await load();
    } catch (e) {
      err.textContent = `Không tạo được: ${e.message}`;
      save.disabled = false; save.textContent = "Tạo sản phẩm";
    }
  });
  detailEl.append(el("div", { class: "g-card" },
    el("div", { class: "g-card-h" }, el("h3", {}, "Sản phẩm mới")),
    el("div", { class: "g-form" },
      el("label", { for: "n-name" }, "Tên sản phẩm", name),
      el("label", { for: "n-price" }, "Giá (không bắt buộc)", price),
      el("label", { class: "full", for: "n-url" }, "Link affiliate Shopee", url),
      el("label", { class: "full", for: "n-desc" }, "Mô tả", desc),
      el("label", { class: "full", for: "n-tags" }, "Tag", tags),
      el("label", { class: "full", for: "n-files" }, "Ảnh sản phẩm (ảnh đầu tiên là ảnh chính; nên có ảnh rõ nhãn/logo)", files),
    ),
    el("div", { class: "g-actions" }, save,
      el("span", { class: "g-cost" }, "Ảnh và thông tin lưu trong products/ trên máy bạn, không đưa lên git.")),
    err,
  ));
  name.focus();
}

// ---------------------------------------------------------------- detail

function renderDetail() {
  const p = current;
  detailEl.innerHTML = "";
  if (!p) { detailEl.append(el("p", { class: "hint" }, "Chọn một sản phẩm ở bên trái.")); return; }
  const usage = `products: ["${p.id}"]`;
  detailEl.append(
    el("div", { class: "g-head" }, el("h2", {}, p.name), p.price ? el("span", { class: "chip" }, p.price) : null,
      el("span", { class: "g-sub" }, `products/${p.id}`)),
    el("div", { class: "g-meta" },
      linkChip(p),
      p.affiliate_url ? el("a", { class: "g-btn", href: p.affiliate_url, target: "_blank", rel: "noopener noreferrer" }, "Mở link") : null,
      p.affiliate_url ? copyBtn(() => p.affiliate_url, "Copy link") : null,
      el("span", { class: "chip" }, `cập nhật ${fmtAgo(p.updated_at)}`),
      el("code", { class: "chip" }, usage), copyBtn(() => usage, "Copy cách dùng")),
    photosCard(p),
    generateCard(p),
    generatedCard(p),
    projectsCard(p),
    infoCard(p),
  );
}

function referenceSet(p, size = 3) {
  if (!p.primary_image) return [];
  const out = [p.images.find((i) => i.file === p.primary_image)];
  for (const role of SET_ROLES) {
    if (out.length >= size) break;
    const m = p.images.find((i) => i.role === role && i.file !== p.primary_image);
    if (m) out.push(m);
  }
  return out;
}

function photosCard(p) {
  const set = new Set(referenceSet(p).map((i) => i.file));
  const grid = el("div", { class: "g-thumbs" });
  for (const img of p.images) {
    const primary = img.file === p.primary_image;
    const roleSel = el("select", { class: "g-role", "aria-label": `Loại ảnh ${img.file}` },
      roles.map((r) => el("option", { value: r.id }, ROLE_VI[r.id] || r.label)));
    roleSel.value = img.role || "other";
    roleSel.addEventListener("change", async () => {
      try { await post(`/api/products/${p.id}/role`, { file: img.file, role: roleSel.value }); await load(); }
      catch (e) { alert(e.message); }
    });
    grid.append(el("figure", { class: `g-thumb-tile${set.has(img.file) ? " picked" : ""}` },
      el("a", { href: imgURL(p.id, img.file), target: "_blank", rel: "noopener" },
        el("img", { src: imgURL(p.id, img.file), loading: "lazy", alt: `${p.name} — ${ROLE_VI[img.role] || ""}`,
          style: "aspect-ratio:1/1" })),
      el("figcaption", {},
        primary ? el("span", { class: "chip ok" }, "Ảnh chính") : null,
        roleSel,
        primary ? null : el("button", { class: "g-btn", type: "button", onclick: async () => {
          try { await post(`/api/products/${p.id}/primary`, { file: img.file }); await load(); } catch (e) { alert(e.message); }
        } }, "Đặt làm chính"),
        el("button", { class: "g-btn", type: "button", "aria-label": `Xoá ảnh ${img.file}`, onclick: async () => {
          if (!confirm("Xoá ảnh này? (chuyển vào products/_trash)")) return;
          try { await post(`/api/products/${p.id}/images/delete`, { file: img.file }); await load(); } catch (e) { alert(e.message); }
        } }, "Xoá"),
      ),
    ));
  }
  if (!p.images.length) grid.append(el("p", { class: "hint" }, "Chưa có ảnh. Tải ảnh sản phẩm lên ở dưới."));

  const err = errBox();
  const roleSel = el("select", { id: "u-role" }, roles.map((r) => el("option", { value: r.id }, ROLE_VI[r.id] || r.label)));
  roleSel.value = p.primary_image ? (SET_ROLES.find((r) => !p.images.some((i) => i.role === r)) || "other") : "front";
  const files = el("input", { id: "u-files", type: "file", multiple: "", accept: "image/png,image/jpeg,image/webp" });
  files.addEventListener("change", async () => {
    err.textContent = "";
    try {
      for (const up of await readFiles(files.files || [])) {
        await post(`/api/products/${p.id}/images`, { ...up, role: roleSel.value });
      }
      await load();
    } catch (e) { err.textContent = `Không tải lên được: ${e.message}`; }
  });
  return el("div", { class: "g-card" },
    el("div", { class: "g-card-h" }, el("h3", {}, "Ảnh sản phẩm")),
    el("p", { class: "g-stamp", style: "margin:0 0 4px" },
      set.size ? `Viền cam: ${set.size} ảnh được gửi cho AI khi tạo ảnh (ảnh chính, rồi nhãn/logo, mặt sau, bên hông…). `
        + "Ảnh chụp rõ chữ trên nhãn giúp AI giữ đúng logo." : "Cần ít nhất một ảnh để tạo ảnh AI."),
    grid,
    el("div", { class: "g-form", style: "margin-top:12px" },
      el("label", { for: "u-role" }, "Loại ảnh tải lên", roleSel),
      el("label", { for: "u-files" }, "Tải ảnh từ máy", files)),
    err);
}

function genState() {
  try { return { aspect: "9:16", n: 1, project: "", characters: [], prompt: "", ...JSON.parse(storageGet(GEN_KEY) || "{}") }; }
  catch { return { aspect: "9:16", n: 1, project: "", characters: [], prompt: "" }; }
}

function generateCard(p) {
  const st = genState();
  const save = () => storageSet(GEN_KEY, JSON.stringify(st));
  const model = opts.models.find((m) => m.id === opts.default_model) || opts.models[0];
  const unit = model.pricing["*"] ?? model.pricing["1K"] ?? 0;
  const err = errBox();
  if (!p.primary_image) {
    return el("div", { class: "g-card" }, el("div", { class: "g-card-h" }, el("h3", {}, "Tạo ảnh AI với sản phẩm")),
      el("p", { class: "hint" }, "Tải ít nhất một ảnh sản phẩm trước."));
  }
  const prompt = el("textarea", { id: "g-prompt", style: "min-height:110px",
    placeholder: "Mô tả bối cảnh muốn đặt sản phẩm vào. Ví dụ: cô gái cầm sản phẩm trong quán cà phê, ánh sáng chiều." });
  prompt.value = st.prompt;
  prompt.addEventListener("input", () => { st.prompt = prompt.value; save(); });
  const presets = el("div", { class: "g-actions", style: "margin-top:8px;gap:6px" },
    el("span", { class: "g-cost" }, "Mẫu nhanh:"),
    Object.entries(PRESETS).map(([label, text]) => el("button", { class: "g-btn", type: "button", onclick: () => {
      prompt.value = text; st.prompt = text;
      if (label === "Khung hình video") st.aspect = "9:16";
      save(); aspect.value = st.aspect;
    } }, label)));

  const aspects = model.aspects;
  if (!aspects.includes(st.aspect)) st.aspect = aspects.includes("1:1") ? "1:1" : aspects[0];
  const aspect = el("select", { id: "g-aspect" }, aspects.map((a) => el("option", { value: a }, a)));
  aspect.value = st.aspect;
  aspect.addEventListener("change", () => { st.aspect = aspect.value; save(); });
  const n = el("select", { id: "g-n" }, ["1", "2", "3", "4"].map((v) => el("option", { value: v }, v)));
  n.value = String(st.n);
  const costEl = el("span", { class: "g-cost" });
  const showCost = () => { costEl.textContent = `${model.id} qua PiAPI · ${n.value} × $${unit} = $${(unit * Number(n.value)).toFixed(2)}`; };
  n.addEventListener("change", () => { st.n = Number(n.value); save(); showCost(); });
  showCost();

  const NEW = "__new__";
  const projects = opts.projects.filter((x) => !x.project_id.startsWith("_"));
  const proj = el("select", { id: "g-project" },
    [...(p.projects || []).filter((id) => projects.some((x) => x.project_id === id)).map((id) => ({ project_id: id, attached: true })),
      ...projects.filter((x) => !(p.projects || []).includes(x.project_id))]
      .map((x) => el("option", { value: x.project_id },
        `${x.attached ? "★ " : ""}${(projects.find((y) => y.project_id === x.project_id) || {}).title || x.project_id}`)),
    el("option", { value: NEW }, "+ Dự án mới…"));
  proj.value = [...proj.options].some((o) => o.value === st.project) ? st.project
    : ((p.projects || [])[0] && [...proj.options].some((o) => o.value === p.projects[0]) ? p.projects[0] : NEW);
  const newName = el("input", { id: "g-newproj", type: "text", value: `${p.name} — ảnh sản phẩm` });
  const newWrap = el("label", { class: "full", for: "g-newproj" }, "Tên dự án mới", newName);
  const syncNew = () => { newWrap.style.display = proj.value === NEW ? "" : "none"; };
  proj.addEventListener("change", () => { st.project = proj.value; save(); syncNew(); });
  syncNew();

  const chosen = new Set((st.characters || []).filter((id) => opts.characters.some((c) => c.id === id)));
  const chars = el("div", { class: "g-chips", style: "gap:6px" });
  const drawChars = () => {
    chars.innerHTML = "";
    if (!opts.characters.length) { chars.append(el("span", { class: "g-cost" }, "Chưa có nhân vật.")); return; }
    for (const c of opts.characters) {
      const on = chosen.has(c.id);
      chars.append(el("button", { type: "button", class: `g-btn${on ? " done" : ""}`, "aria-pressed": on ? "true" : "false",
        onclick: () => { on ? chosen.delete(c.id) : chosen.add(c.id); st.characters = [...chosen]; save(); drawChars(); } },
        on ? `✓ ${c.name}` : c.name));
    }
  };
  drawChars();

  const go = el("button", { class: "g-btn primary", type: "button" }, "Tạo ảnh");
  go.addEventListener("click", async () => {
    if (busy) return;
    err.textContent = "";
    if (!prompt.value.trim()) { err.textContent = "Cần viết mô tả bối cảnh (hoặc bấm một mẫu nhanh)."; return; }
    if (proj.value === NEW && !newName.value.trim()) { err.textContent = "Đặt tên cho dự án mới."; return; }
    busy = true; go.disabled = true; go.textContent = "Đang tạo… (~30-70s)";
    try {
      const r = await post("/api/images/generate", {
        prompt: prompt.value, model: model.id, aspect: aspect.value, resolution: "1K", n: Number(n.value),
        products: [p.id], characters: [...chosen], name: p.id,
        ...(proj.value === NEW ? { new_project: newName.value } : { project_id: proj.value }),
      }, "image");
      st.project = r.project_id; save();
      opts = await getJSON("/api/images/options");
      await load();
    } catch (e) {
      err.textContent = `Không tạo được: ${e.message}`;
    } finally {
      busy = false; go.disabled = false; go.textContent = "Tạo ảnh";
    }
  });

  return el("div", { class: "g-card" },
    el("div", { class: "g-card-h" }, el("h3", {}, "Tạo ảnh AI với sản phẩm")),
    el("p", { class: "g-stamp", style: "margin:0 0 8px" },
      "AI nhận ảnh sản phẩm làm tham chiếu và được dặn giữ nguyên hình dáng, màu, logo và chữ trên nhãn. "
      + "Ảnh lưu vào dự án đã chọn và dự án đó được gắn sản phẩm này (caption sẽ có link giỏ hàng)."),
    el("div", { class: "g-form" },
      el("label", { class: "full", for: "g-prompt" }, "Bối cảnh", prompt)),
    presets,
    el("div", { class: "g-form", style: "margin-top:10px" },
      el("label", { for: "g-aspect" }, "Khung", aspect),
      el("label", { for: "g-n" }, "Số ảnh", n),
      el("label", { class: "full", for: "g-project" }, "Lưu vào dự án", proj),
      newWrap),
    el("h4", { class: "g-cost", style: "margin:12px 0 6px" }, "Thêm nhân vật vào ảnh (không bắt buộc)"),
    chars,
    el("div", { class: "g-actions", style: "margin-top:14px" }, go, costEl),
    err);
}

function generatedCard(p) {
  const imgs = p.generated || [];
  const grid = el("div", { class: "g-thumbs" });
  for (const img of imgs) {
    grid.append(el("figure", { class: "g-thumb-tile" },
      el("a", { href: mediaURL(img.project_id, img.path), target: "_blank", rel: "noopener" },
        el("img", { src: thumbURL(img.project_id, img.path, 480), loading: "lazy", alt: img.prompt || img.name })),
      el("figcaption", {},
        el("span", { class: "chip" }, img.project_id),
        img.social ? el("span", { class: "chip ok" }, "✓ caption") : null,
        el("a", { class: "g-btn", href: mediaURL(img.project_id, img.path), download: img.name }, "Tải"),
        copyBtn(() => `projects/${img.project_id}/${img.path}`, "Copy đường dẫn")),
    ));
  }
  return el("div", { class: "g-card" },
    el("div", { class: "g-card-h" }, el("h3", {}, `Ảnh AI đã tạo (${imgs.length})`), el("span", { class: "spacer" }),
      el("a", { class: "g-btn", href: "/images" }, "Viết caption ở Images")),
    imgs.length ? grid : el("p", { class: "hint" }, "Chưa có ảnh nào tạo với sản phẩm này."),
    el("details", { class: "g-history", style: "margin-top:12px" },
      el("summary", {}, "Đưa sản phẩm vào video"),
      el("p", { class: "g-stamp" },
        "1) Tạo ảnh với mẫu “Khung hình video” (khung 9:16), có thể thêm nhân vật. "
        + "2) Nhờ agent tạo clip image-to-video từ ảnh đó (Kling: image_path = đường dẫn ảnh) — sản phẩm giữ đúng hình vì "
        + "khung hình đầu đã có sản phẩm thật. 3) Video lưu trong cùng dự án nên ở Gallery, caption tự gắn link giỏ hàng."),
      el("p", { class: "g-stamp" }, "Ví dụ yêu cầu: “Làm video 5s từ ảnh projects/…/img_….png, sản phẩm "
        + p.name + ", camera đẩy chậm vào”.")));
}

function projectsCard(p) {
  const err = errBox();
  const rows = (p.projects || []).map((id) => {
    const info = opts.projects.find((x) => x.project_id === id);
    return el("div", { class: "g-row", style: "align-items:center;margin-bottom:6px" },
      el("div", {}, el("a", { href: `/p/${encodeURIComponent(id)}` }, info?.title || id),
        el("span", { class: "g-sub" }, ` · ${id}`)),
      el("button", { class: "g-btn", type: "button", onclick: async () => {
        try { await post(`/api/products/${p.id}/projects`, { remove: [id] }); await load(); }
        catch (e) { err.textContent = e.message; }
      } }, "Bỏ gắn"));
  });
  const others = opts.projects.filter((x) => !(p.projects || []).includes(x.project_id));
  const sel = el("select", { id: "pj-add" },
    el("option", { value: "" }, others.length ? "— chọn dự án —" : "Không còn dự án nào"),
    others.map((x) => el("option", { value: x.project_id }, x.project_id.startsWith("_uploads") ? "Video tải lên (_uploads)" : (x.title || x.project_id))));
  const add = el("button", { class: "g-btn", type: "button" }, "Gắn vào dự án");
  add.addEventListener("click", async () => {
    if (!sel.value) return;
    try { await post(`/api/products/${p.id}/projects`, { add: [sel.value] }); await load(); }
    catch (e) { err.textContent = `Không gắn được: ${e.message}`; }
  });
  return el("div", { class: "g-card" },
    el("div", { class: "g-card-h" }, el("h3", {}, "Dự án quảng bá sản phẩm này")),
    el("p", { class: "g-stamp", style: "margin:0 0 8px" },
      "Video và ảnh trong các dự án này sẽ được gợi ý sản phẩm khi viết caption (Gallery, Images), và link giỏ hàng "
      + "được thêm nguyên văn vào cuối caption. Instagram/TikTok không bấm được link trong caption nên sẽ ghi “link ở bio”."),
    rows.length ? rows : el("p", { class: "hint" }, "Chưa gắn dự án nào."),
    el("div", { class: "g-form", style: "margin-top:8px" }, el("label", { for: "pj-add" }, "Thêm dự án", sel)),
    el("div", { class: "g-actions" }, add),
    err);
}

function infoCard(p) {
  const f = (id, value, tag = "input") => {
    const node = el(tag, tag === "input" ? { id, type: "text" } : { id });
    node.value = value || "";
    return node;
  };
  const name = f("e-name", p.name);
  const price = f("e-price", p.price);
  const url = f("e-url", p.affiliate_url);
  const cta = f("e-cta", p.cta);
  cta.placeholder = "Ví dụ: 👉 Săn deal tại";
  const tags = f("e-tags", (p.tags || []).join(", "));
  const desc = f("e-desc", p.description, "textarea");
  desc.style.minHeight = "90px";
  const look = f("e-look", p.look, "textarea");
  look.placeholder = "Mô tả hình dáng bằng tiếng Anh cho AI (không bắt buộc): matte black over-ear headphones, silver logo…";
  const err = errBox();
  const save = el("button", { class: "g-btn primary", type: "button" }, "Lưu");
  save.addEventListener("click", async () => {
    err.textContent = "";
    try {
      await post(`/api/products/${p.id}`, { name: name.value, price: price.value, affiliate_url: url.value, cta: cta.value,
        tags: tagList(tags.value), description: desc.value, look: look.value });
      save.textContent = "Đã lưu"; save.classList.add("done");
      await load();
    } catch (e) { err.textContent = `Không lưu được: ${e.message}`; }
  });
  const del = el("button", { class: "g-btn", type: "button" }, "Xoá sản phẩm");
  del.addEventListener("click", async () => {
    if (!confirm(`Xoá “${p.name}”? Thư mục được chuyển vào products/_trash, ảnh đã tạo trong dự án vẫn giữ.`)) return;
    try { await post(`/api/products/${p.id}/delete`); selected = null; await load(); }
    catch (e) { err.textContent = e.message; }
  });
  return el("div", { class: "g-card" },
    el("div", { class: "g-card-h" }, el("h3", {}, "Thông tin")),
    el("div", { class: "g-form" },
      el("label", { for: "e-name" }, "Tên", name),
      el("label", { for: "e-price" }, "Giá", price),
      el("label", { class: "full", for: "e-url" }, "Link affiliate Shopee", url),
      el("label", { class: "full", for: "e-desc" }, "Mô tả (cho caption)", desc),
      el("label", { class: "full", for: "e-look" }, "Mô tả hình dáng cho AI tạo ảnh", look),
      el("label", { for: "e-cta" }, "Lời kêu gọi trước link", cta),
      el("label", { for: "e-tags" }, "Tag", tags)),
    el("div", { class: "g-actions" }, save, el("span", { class: "spacer", style: "flex:1" }), del),
    err);
}

// ---------------------------------------------------------------- boot

async function loadCurrent() {
  if (!selected) { current = null; renderDetail(); return; }
  try { current = await getJSON(`/api/products/${encodeURIComponent(selected)}`); }
  catch { current = null; }
  renderDetail();
}

async function load() {
  [products, roles, opts] = await Promise.all([
    getJSON("/api/products"),
    roles.length ? roles : getJSON("/api/products/roles"),
    opts || getJSON("/api/images/options"),
  ]);
  if (selected && !products.some((p) => p.id === selected)) selected = null;
  if (!selected && products[0]) selected = products[0].id;
  renderList();
  if (!products.length) { renderNew(); return; }
  await loadCurrent();
}

document.getElementById("newBtn").addEventListener("click", renderNew);
filterEl.addEventListener("input", renderList);
load().catch((e) => { detailEl.textContent = `Lỗi tải sản phẩm: ${e.message}`; });
