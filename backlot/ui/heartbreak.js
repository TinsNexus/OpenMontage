// Xưởng Heartbreak — wordless-heartbreak reel studio (steps 1–3; M3–M5 come later).
import { el, fmtAgo, getJSON } from "/ui/lib.js";

const THEME_KEY = "backlot.theme";
const $ = (id) => document.getElementById(id);

function storageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
document.documentElement.dataset.theme = storageGet(THEME_KEY) === "light" ? "light" : "dark";

const SLOT_ORDER = ["HERO", "CRUSH", "RIVAL", "BUDDY1", "BUDDY2", "BARD", "NEW"];
const SLOT_LABELS = {
  HERO: "Kẻ si tình", CRUSH: "Người mình thích", RIVAL: "Đối thủ",
  BUDDY1: "Bạn thân 1", BUDDY2: "Bạn thân 2", BARD: "Ca sĩ", NEW: "Nhân vật mới",
};
const STEPS = ["Ý tưởng", "Prompt", "Chọn model", "Clip", "Ghép", "Caption"];
const LEN_LABELS = { short: "Ngắn · 25–45 giây", long: "Dài · 70–85 giây" };
const STAGE_LABELS = {
  proposal: "Chưa viết prompt", scene_plan: "Đã có prompt",
  assets: "Đang tạo clip", compose: "Đã ghép", publish: "Đã đăng",
};

const usd = (v) => `${Number(v || 0).toLocaleString("vi-VN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USD`;
const usdRate = (v) => `${Number(v || 0).toLocaleString("vi-VN", { minimumFractionDigits: 0, maximumFractionDigits: 3 })} USD/giây`;
const imgURL = (id, file) => `/character-media/${encodeURIComponent(id)}/${encodeURIComponent(file)}`;

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

/* ---------------- state ---------------- */
let eps = [];
let chars = [];
let slug = null;
let ep = null;
let prices = null;
let pricesErr = null;
let pricesLoading = false;
let step = 1;
let creating = false;
let action = false;   // a POST is in flight — freeze re-renders

// Re-render is only safe when nothing is being typed into / sent.
function busy() {
  if (creating || action || pricesLoading) return true;
  const a = document.activeElement;
  return !!(a && ["INPUT", "TEXTAREA", "SELECT"].includes(a.tagName) && a.closest("#panel"));
}

/* ---------------- episode list ---------------- */
function renderStat() {
  const total = eps.reduce((s, e) => s + Number(e.spent_usd || 0), 0);
  $("stat").textContent = `${eps.length} tập · đã chi ${usd(total)}`;
}

function renderList() {
  const box = $("epList");
  box.replaceChildren();
  if (!eps.length) {
    box.append(el("p", { class: "hint" }, "Chưa có tập nào — bấm “+ Tập mới” để bắt đầu."));
    return;
  }
  for (const e of eps) {
    box.append(el("article", { class: `hb-ep${e.slug === slug && !creating ? " active" : ""}`,
      tabindex: "0", role: "button", "aria-label": `Mở tập ${e.title}`,
      onclick: () => select(e.slug),
      onkeydown: (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); select(e.slug); } } },
      el("h3", {}, e.title),
      el("div", { class: "meta" },
        el("span", { class: "hb-chip" }, LEN_LABELS[e.length] || e.length),
        el("span", { class: `hb-chip ${e.clip_count ? "green" : "amber"}` },
          e.clip_count ? `${e.clip_count} clip` : "chưa có prompt"),
        el("span", {}, `💸 ${usd(e.spent_usd)}`),
        el("span", { title: e.idea }, e.idea && e.idea.length > 40 ? e.idea.slice(0, 40) + "…" : e.idea || ""))));
  }
}

/* ---------------- stepper ---------------- */
function maxStep() {
  if (creating) return 1;
  if (!ep) return 1;
  return ep.clips && ep.clips.length ? 3 : 2;
}

function renderStepper() {
  const box = $("stepper");
  box.replaceChildren();
  const max = maxStep();
  STEPS.forEach((name, i) => {
    const n = i + 1;
    const locked = n > max;
    const mark = n === step || locked ? String(n) : "✓";
    const btn = el("button", {
      class: `hb-step${n === step ? " is-active" : ""}${n < max ? " done" : ""}`,
      type: "button", role: "tab", "aria-selected": String(n === step),
      title: locked ? "Các bước này có ở milestone sau (M3–M5)" : name,
      onclick: () => { if (!locked) { step = n; render(); } },
    }, el("span", { class: "no" }, mark), name);
    if (locked) btn.disabled = true;
    box.append(btn);
  });
}

/* ---------------- slot pickers ---------------- */
function charThumb(value) {
  const c = chars.find((x) => x.id === value);
  if (c && c.primary_image) return el("img", { class: "thumb", src: imgURL(c.id, c.primary_image), alt: "" });
  return el("div", { class: "thumb empty", "aria-hidden": "true" }, "👤");
}

function slotRow(slot, value, onChange) {
  const sel = el("select", { "aria-label": `${slot} — ${SLOT_LABELS[slot]}` },
    el("option", { value: "" }, slot === "HERO" ? "— chọn nhân vật (bắt buộc) —" : "— bỏ trống —"),
    ...chars.map((c) => {
      const o = el("option", { value: c.id }, `${c.name} (${c.id})`);
      if (c.id === value) o.selected = true;
      return o;
    }));
  const thumb = charThumb(value);
  sel.addEventListener("change", () => {
    onChange(sel.value);
    const fresh = charThumb(sel.value);
    thumb.replaceWith(fresh);
  });
  return el("div", { class: "hb-slot" }, thumb,
    el("div", { class: "who" },
      el("span", { class: "lb" }, el("b", {}, slot), ` · ${SLOT_LABELS[slot]}`), sel));
}

/* ---------------- step 1: idea ---------------- */
function createPanel() {
  const draft = { slots: {} };
  const title = el("input", { type: "text", required: "", placeholder: "Ví dụ: Hái hoa cho cô ấy", "aria-label": "Tên tập" });
  const idea = el("input", { type: "text", required: "", placeholder: "Một dòng: kẻ si tình hái hoa tặng crush thì bị bỏ rơi", "aria-label": "Ý tưởng" });
  const lenShort = el("input", { type: "radio", name: "hb-len", value: "short", checked: "" });
  const lenLong = el("input", { type: "radio", name: "hb-len", value: "long" });
  const slots = el("div", { class: "hb-slots" },
    ...SLOT_ORDER.map((s) => slotRow(s, draft.slots[s], (v) => { draft.slots[s] = v || null; })));
  const err = el("p", { class: "hb-err", role: "alert" });
  const submit = el("button", { class: "g-btn primary", type: "submit" }, "Tạo tập");

  const form = el("form", { class: "hb-form" },
    el("label", { class: "full" }, "Tên tập", title),
    el("label", { class: "full" }, "Ý tưởng (1 dòng)", idea),
    el("label", { class: "full" }, "Độ dài",
      el("div", { class: "hb-radios" },
        el("label", {}, lenShort, "Ngắn — 2–4 clip (25–45 giây)"),
        el("label", {}, lenLong, "Dài — 5–12 clip (70–85 giây)"))),
    el("span", { class: "full", style: "font-size:calc(11px * var(--fs-scale));color:var(--text-3);text-transform:uppercase;letter-spacing:.07em" },
      "Nhân vật (dùng thư viện Characters)"),
    slots,
    el("div", { class: "hb-actions" }, submit,
      el("button", { class: "g-btn", type: "button", onclick: () => { creating = false; render(); } }, "Hủy"), err));

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!title.value.trim()) { err.textContent = "Nhập tên tập trước đã."; return; }
    if (!idea.value.trim()) { err.textContent = "Nhập ý tưởng (1 dòng) trước đã."; return; }
    if (!draft.slots.HERO) { err.textContent = "Phải chọn HERO (kẻ si tình)."; return; }
    action = true;
    submit.disabled = true;
    submit.textContent = "Đang tạo…";
    err.textContent = "";
    try {
      const created = await post("/api/heartbreak/episodes", {
        title: title.value.trim(), idea: idea.value.trim(),
        length: lenLong.checked ? "long" : "short", slots: draft.slots,
      }, "heartbreak");
      creating = false;
      slug = created.slug;
      ep = created;
      step = 2;
      prices = null; pricesErr = null;
      await loadList();
      render();
    } catch (e) {
      err.textContent = e.message;
      submit.disabled = false;
      submit.textContent = "Tạo tập";
    } finally {
      action = false;
    }
  });
  return el("section", { class: "hb-card" },
    el("h2", {}, "Bước 1 — Ý tưởng"),
    el("p", {}, "Điền tên tập, một dòng ý tưởng, độ dài và chọn nhân vật cho các slot. HERO là bắt buộc."),
    form);
}

function summaryPanel() {
  const filled = SLOT_ORDER.filter((s) => ep.slots && ep.slots[s]);
  return el("section", { class: "hb-card" },
    el("h2", {}, "Bước 1 — Ý tưởng"),
    el("h3", {}, ep.title),
    el("p", {}, el("b", {}, "Ý tưởng: "), ep.idea),
    el("p", {}, el("b", {}, "Độ dài: "), LEN_LABELS[ep.length] || ep.length),
    el("div", { class: "hb-slots" },
      ...SLOT_ORDER.map((s) => {
        const v = ep.slots ? ep.slots[s] : null;
        const c = chars.find((x) => x.id === v);
        return el("div", { class: "hb-slot" }, charThumb(v),
          el("div", { class: "who" },
            el("span", { class: "lb" }, el("b", {}, s), ` · ${SLOT_LABELS[s]}`),
            el("span", { style: "font-size:calc(12px * var(--fs-scale));color:var(--text-2)" },
              v ? `${c ? c.name : v}` : "— trống —")));
      })),
    el("p", { class: "hint" }, `Tạo lúc ${fmtAgo(ep.created_at)} · cập nhật ${fmtAgo(ep.updated_at)}`),
    filled.length === 0 ? el("p", { class: "hb-err" }, "Tập này chưa có nhân vật nào.") : null);
}

/* ---------------- step 2: prompts ---------------- */
function clipCard(clip) {
  const area = el("textarea", { "aria-label": `Prompt clip ${clip.id}`, rows: "6" }, clip.prompt || "");
  const err = el("span", { class: "hb-err" });
  const save = el("button", { class: "g-btn primary", type: "button" }, "Lưu");
  save.addEventListener("click", async () => {
    const text = area.value.trim();
    if (!text) { err.textContent = "Prompt trống."; return; }
    action = true;
    save.disabled = true;
    err.textContent = "";
    try {
      await post(`/api/heartbreak/${slug}/prompts/${encodeURIComponent(clip.id)}`, { prompt: text }, "heartbreak");
      await refreshEp();
      render();
    } catch (e) {
      err.textContent = e.message;
      save.disabled = false;
    } finally {
      action = false;
    }
  });
  return el("article", { class: "hb-clip" },
    el("div", { class: "head" },
      el("span", { class: "id" }, `CLIP ${clip.id}`),
      ...(clip.beats || []).map((b) => el("span", { class: "hb-chip" }, b)),
      el("span", { class: "hb-chip" }, `${clip.duration}s`),
      el("span", { style: "flex:1" }),
      el("span", { class: "hb-chip" }, "chưa tạo video")),
    area,
    el("div", { class: "row" }, save, err));
}

function infoPanel() {
  const co = ep.cold_open;
  const music = ep.music_plan || [];
  return el("div", { class: "hb-info" },
    el("div", { class: "box" }, el("b", {}, "Cold open"),
      el("div", { class: "big" }, co ? co.text : "—"),
      co ? el("div", {}, `từ clip ${co.from_clip} · giây ${co.at}`) : null),
    el("div", { class: "box" }, el("b", {}, "Nhạc theo beat"),
      music.length
        ? el("div", { class: "hb-music" }, ...music.map((m) =>
            el("span", {}, `${m.at}s${m.cue ? " " + m.cue : ""} · ${m.action}`)))
        : "—"),
    el("div", { class: "box" }, el("b", {}, "Gợi ý caption"),
      ep.caption_hint || "—"));
}

function promptPanel() {
  if (!ep.clips || !ep.clips.length) {
    const notes = el("textarea", { rows: "3", placeholder: "Ghi chú thêm cho AI (không bắt buộc)…", "aria-label": "Ghi chú" });
    const err = el("p", { class: "hb-err", role: "alert" });
    const go = el("button", { class: "g-btn primary", type: "button" }, "Viết bằng AI (~0,01 USD)");
    go.addEventListener("click", async () => {
      action = true;
      go.disabled = true;
      go.textContent = "Đang viết prompt…";
      err.textContent = "";
      try {
        await post(`/api/heartbreak/${slug}/prompts`, { notes: notes.value }, "heartbreak-paid");
        await refreshEp();
        prices = null; pricesErr = null;
        step = 3;
        render();
      } catch (e) {
        err.textContent = e.message;
        go.disabled = false;
        go.textContent = "Viết bằng AI (~0,01 USD)";
      } finally {
        action = false;
      }
    });
    return el("section", { class: "hb-card" },
      el("h2", {}, "Bước 2 — Prompt"),
      el("p", {}, "Để AI (Claude Sonnet qua PiAPI chat) viết prompt cho từng clip theo công thức wordless-heartbreak: "
        + "timeline beat, cold open ≤ 8 từ, 9:16, mỗi clip 1 hành động + 1 biểu cảm phóng đại."),
      el("p", {}, el("b", {}, "Chi phí: ~0,01 USD"), " mỗi lần viết — chỉ chạy khi bạn bấm nút."),
      el("label", {}, "Ghi chú cho AI", notes),
      el("div", { class: "hb-actions" }, go, err));
  }

  const rewrite = el("button", { class: "g-btn", type: "button" }, "Viết lại bằng AI (~0,01 USD)");
  const err = el("p", { class: "hb-err", role: "alert" });
  rewrite.addEventListener("click", async () => {
    if (!confirm("Viết lại toàn bộ prompt? Các prompt bạn sửa tay sẽ bị thay.")) return;
    action = true;
    rewrite.disabled = true;
    rewrite.textContent = "Đang viết prompt…";
    err.textContent = "";
    try {
      await post(`/api/heartbreak/${slug}/prompts`, { notes: "" }, "heartbreak-paid");
      await refreshEp();
      prices = null; pricesErr = null;
      step = 3;
      render();
    } catch (e) {
      err.textContent = e.message;
      rewrite.disabled = false;
      rewrite.textContent = "Viết lại bằng AI (~0,01 USD)";
    } finally {
      action = false;
    }
  });

  return el("section", { class: "hb-card" },
    el("h2", {}, "Bước 2 — Prompt"),
    el("p", {}, `${ep.clips.length} prompt — sửa tay rồi bấm “Lưu”. Prompt là thứ Seedance/Kling đọc để tạo video.`),
    ...ep.clips.map(clipCard),
    infoPanel(),
    el("div", { class: "hb-actions" }, rewrite, err));
}

/* ---------------- step 3: price table ---------------- */
async function loadPrices() {
  const res = await fetch(`/api/heartbreak/${slug}/prices`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { prices = null; pricesErr = data.detail || `HTTP ${res.status}`; return; }
  prices = data;
  pricesErr = null;
}

function pricePanel() {
  if (pricesErr) {
    return el("section", { class: "hb-card" },
      el("h2", {}, "Bước 3 — Chọn model"),
      el("div", { class: "hb-todo" }, el("div", { class: "big" }, "🧮"), pricesErr));
  }
  if (!prices) {
    return el("section", { class: "hb-card" },
      el("h2", {}, "Bước 3 — Chọn model"),
      el("div", { class: "hb-todo" }, el("div", { class: "big" }, "⏳"), "Đang tính bảng giá…"));
  }
  const currentId = ep.model_id || (prices.rows.find((r) => r.default) || {}).id;
  const radios = [];
  const table = el("table", { class: "hb-prices" },
    el("thead", {}, el("tr", {},
      el("th", { scope: "col" }, "Chọn"),
      el("th", { scope: "col" }, "Model"),
      el("th", { scope: "col" }, "Đơn giá"),
      el("th", { scope: "col" }, "Độ dài clip"),
      el("th", { scope: "col" }, "Tổng"))),
    el("tbody", {}, ...prices.rows.map((r) => {
      const radio = el("input", { type: "radio", name: "hb-model", value: r.id, "aria-label": r.model });
      if (r.id === currentId) radio.checked = true;
      radios.push(radio);
      const cls = [
        "hb-row",
        r.default ? "default" : "",
        ep.model_id === r.id ? "picked" : "",
      ].filter(Boolean).join(" ");
      const tr = el("tr", { class: cls },
        el("td", {}, radio),
        el("td", { class: "model" }, r.model,
          r.default ? el("span", { class: "tag" }, "Mặc định") : null,
          ep.model_id === r.id ? el("span", { class: "tag now" }, "Đang dùng") : null),
        el("td", {}, usdRate(r.price_per_second)),
        el("td", {}, r.clip_length),
        el("td", { class: "total" }, usd(r.total_usd)));
      radio.addEventListener("change", () => { pickBtn.disabled = false; });
      return tr;
    })));

  const err = el("span", { class: "hb-err" });
  const pickBtn = el("button", { class: "g-btn primary", type: "button" }, "Chọn model này");
  pickBtn.disabled = !ep.model_id;   // nothing picked yet until the user confirms a row
  pickBtn.addEventListener("click", async () => {
    const picked = radios.find((r) => r.checked);
    if (!picked) { err.textContent = "Chọn một dòng trong bảng giá trước."; return; }
    action = true;
    pickBtn.disabled = true;
    err.textContent = "";
    try {
      ep = await post(`/api/heartbreak/${slug}/model`, { model_id: picked.value }, "heartbreak");
      await refreshEp();
      render();
    } catch (e) {
      err.textContent = e.message;
      pickBtn.disabled = false;
    } finally {
      action = false;
    }
  });

  const m = ep.model || {};
  const modelName = m.tool === "kling_piapi"
    ? `Kling ${m.version || ""} ${m.mode || ""}`.trim()
    : `Seedance ${m.model_variant || "fast"} ${m.resolution || ""}`.trim();

  return el("section", { class: "hb-card" },
    el("h2", {}, "Bước 3 — Chọn model"),
    el("p", {}, `Bảng giá tính theo đúng ${prices.total_seconds}s clip của tập này. Chưa bấm tạo clip ở đây — chọn model trước, bước “Clip” (M3) mới tính tiền.`),
    el("div", { class: "hb-table-wrap" }, table),
    el("div", { class: "hb-actions" }, pickBtn,
      el("span", { class: "hint" }, ep.model_id ? `Đang dùng: ${modelName}` : "Chưa chọn — dòng Mặc định được gợi ý."), err));
}

/* ---------------- placeholder steps (M3–M5) ---------------- */
function todoPanel(n) {
  const copy = {
    4: ["🎬", "Tạo clip sẽ có ở milestone M3: chạy Seedance/Kling nền, xem từng bản, chọn bản đẹp."],
    5: ["✂️", "Ghép video sẽ có ở milestone M4: cold open, chữ hook, nhạc theo beat, xuất 9:16 + .srt."],
    6: ["📝", "Caption sẽ có ở milestone M5: viết caption Facebook kèm nhãn AI, đánh dấu đã đăng."],
  }[n];
  return el("section", { class: "hb-card" },
    el("h2", {}, `Bước ${n} — ${STEPS[n - 1]}`),
    el("div", { class: "hb-todo" }, el("div", { class: "big" }, copy[0]), copy[1]));
}

/* ---------------- render ---------------- */
function renderPanel() {
  const box = $("panel");
  box.replaceChildren();
  if (creating) { box.append(createPanel()); return; }
  if (!ep) {
    box.append(el("section", { class: "hb-card" },
      el("div", { class: "hb-todo" }, el("div", { class: "big" }, "🎞️"),
        "Chọn một tập bên trái, hoặc bấm “+ Tập mới” để bắt đầu.")));
    return;
  }
  if (step === 1) box.append(summaryPanel());
  else if (step === 2) box.append(promptPanel());
  else if (step === 3) box.append(pricePanel());
  else box.append(todoPanel(step));
}

function render() {
  renderStat();
  renderList();
  renderStepper();
  renderPanel();
  if (step === 3 && !creating && ep && ep.clips && ep.clips.length && !prices && !pricesErr && !pricesLoading) {
    pricesLoading = true;
    loadPrices().finally(() => { pricesLoading = false; render(); });
  }
}

/* ---------------- data ---------------- */
async function loadList() {
  const list = await getJSON("/api/heartbreak");
  eps = list.episodes || [];
}

async function refreshEp() {
  if (!slug) return;
  try { ep = await getJSON(`/api/heartbreak/${slug}`); }
  catch { ep = null; slug = null; }
}

async function select(s) {
  slug = s;
  creating = false;
  prices = null; pricesErr = null;
  try { ep = await getJSON(`/api/heartbreak/${slug}`); }
  catch (e) { $("panel").replaceChildren(el("p", { class: "hb-err" }, `Không mở được tập: ${e.message}`)); return; }
  step = ep.clips && ep.clips.length ? 3 : 2;
  render();
}

async function loadAll() {
  const [list, characters] = await Promise.all([getJSON("/api/heartbreak"), getJSON("/api/characters")]);
  eps = list.episodes || [];
  chars = characters || [];
  if (!slug && eps.length && !creating) {
    slug = eps[0].slug;
    try { ep = await getJSON(`/api/heartbreak/${slug}`); } catch { ep = null; }
    step = ep && ep.clips && ep.clips.length ? 3 : 2;
  }
  render();
}

$("newEp").addEventListener("click", () => {
  creating = true;
  step = 1;
  render();
  window.scrollTo({ top: 0, behavior: "smooth" });
});

loadAll().catch((e) => {
  $("panel").replaceChildren(el("p", { class: "hb-err" }, `Không tải được Xưởng Heartbreak: ${e.message}`));
});

// Light polling: refresh list + open episode when idle (page load/refresh never POSTs).
setInterval(async () => {
  if (busy()) return;
  try {
    const before = JSON.stringify([eps, ep]);
    await loadList();
    await refreshEp();
    if (JSON.stringify([eps, ep]) !== before) render();
  } catch { /* transient — try again next tick */ }
}, 4000);
