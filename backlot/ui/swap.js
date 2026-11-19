import { el, fmtAgo, fmtDuration, fmtMoney, getJSON, mediaURL } from "/ui/lib.js";

const THEME_KEY = "backlot.theme";
const SEL_KEY = "backlot.swap.selected";
const listEl = document.getElementById("list");
const detailEl = document.getElementById("detail");
const countEl = document.getElementById("count");

function storageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function storageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* ignore */ } }
document.documentElement.dataset.theme = storageGet(THEME_KEY) === "light" ? "light" : "dark";

let jobs = [];
let options = { modes: {}, characters: [], price_per_frame: 0.01, character_image_cost: 0.03 };
let selected = storageGet(SEL_KEY);
let job = null;
let busy = "";          // name of the action in flight ("" = idle)
let errorMsg = "";
let videoTab = "link";
let charTab = "upload";
let pollTimer = null;
const drafts = { url: "", prompt: "", name: "", libName: "", start: null, end: null, previewAt: null };

const STATUS_VI = { none: "Chưa có", pending: "Chờ duyệt", approved: "Đã duyệt", rejected: "Không duyệt" };
const RUN_VI = { running: "Đang chạy", done: "Xong", failed: "Lỗi", cancelled: "Đã huỷ",
  interrupted: "Bị gián đoạn (server khởi động lại)" };

async function post(url, body, headers = {}) {
  const isJSON = !(body instanceof Blob || body instanceof File);
  const res = await fetch(url, {
    method: "POST",
    headers: { ...(isJSON ? { "Content-Type": "application/json" } : {}), "X-Backlot-Action": "swap", ...headers },
    body: isJSON ? JSON.stringify(body || {}) : body,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

const media = (rel) => mediaURL(job.id, rel);
const charImg = (id, file) => `/character-media/${encodeURIComponent(id)}/${encodeURIComponent(file)}`;

async function act(name, fn) {
  if (busy) return;
  busy = name;
  errorMsg = "";
  render();
  try {
    const out = await fn();
    if (out && out.id) job = out;
  } catch (e) {
    errorMsg = e.message || String(e);
  } finally {
    busy = "";
    await loadList();
    render();
    schedulePoll();
  }
}

// ---------------------------------------------------------------- data

async function loadList() {
  try { jobs = await getJSON("/api/swap"); } catch { jobs = []; }
  countEl.textContent = jobs.length ? `${jobs.length} lượt` : "";
  renderList();
}

async function loadJob() {
  if (!selected) { job = null; return; }
  try { job = await getJSON(`/api/swap/${encodeURIComponent(selected)}`); }
  catch { job = null; selected = null; storageSet(SEL_KEY, ""); }
}

function isActive(j) {
  return j && ((j.download || {}).status === "downloading" || (j.run || {}).status === "running");
}

function schedulePoll() {
  clearTimeout(pollTimer);
  if (!isActive(job)) return;
  pollTimer = setTimeout(async () => {
    await loadJob();
    await loadList();
    render();
    schedulePoll();
  }, 2000);
}

// ---------------------------------------------------------------- list

function jobChip(j) {
  const r = j.run || {};
  if (r.status === "running") return el("span", { class: "chip" }, `${r.done}/${r.total} frame`);
  if (r.status === "done") return el("span", { class: "chip ok" }, "Xong");
  const c = (j.character || {}).status;
  if (c === "pending") return el("span", { class: "chip" }, "Chờ duyệt");
  if (!j.video) return el("span", { class: "chip" }, (j.download || {}).status === "downloading" ? "Đang tải" : "Chưa có video");
  return null;
}

function renderList() {
  listEl.replaceChildren();
  document.getElementById("empty").style.display = jobs.length ? "none" : "";
  for (const j of jobs) {
    const thumb = j.character && j.character.image
      ? el("img", { src: mediaURL(j.id, j.character.image), alt: "", loading: "lazy" }) : null;
    const item = el("div", {
      class: "g-item", role: "button", tabindex: "0", "aria-selected": String(j.id === selected),
      onclick: () => select(j.id),
      onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(j.id); } },
    },
    el("div", { class: "g-thumb" }, thumb),
    el("div", {},
      el("h3", {}, j.title),
      el("div", { class: "g-sub" }, fmtAgo(j.updated_at)),
      el("div", { class: "g-chips" }, jobChip(j))));
    listEl.append(item);
  }
}

async function select(id) {
  selected = id;
  storageSet(SEL_KEY, id);
  errorMsg = "";
  Object.assign(drafts, { start: null, end: null, previewAt: null });
  await loadJob();
  renderList();
  render();
  schedulePoll();
}

// ---------------------------------------------------------------- steps

function card(n, title, { ok = false, locked = false, lockNote = "" } = {}, ...body) {
  return el("section", { class: `g-card sw-step${ok ? " ok" : ""}${locked ? " locked" : ""}` },
    el("div", { class: "g-card-h" }, el("span", { class: "sw-num" }, ok ? "✓" : String(n)), el("h3", {}, title)),
    locked && lockNote ? el("p", { class: "sw-note" }, lockNote) : null,
    el("div", { class: "sw-body" }, ...body));
}

function tabs(current, items, onPick) {
  return el("div", { class: "sw-tabs", role: "tablist" }, items.map(([key, label]) =>
    el("button", { type: "button", role: "tab", "aria-selected": String(current === key), onclick: () => onPick(key) }, label)));
}

function btn(label, onclick, { primary = false, name = "", disabled = false } = {}) {
  return el("button", {
    type: "button", class: `g-btn${primary ? " primary" : ""}`, onclick,
    disabled: busy || disabled ? "" : null,
  }, busy && busy === name ? "Đang xử lý…" : label);
}

function stepVideo() {
  const v = job.video;
  const dl = job.download || {};
  const body = [];
  if (v) {
    body.push(el("div", { class: "sw-video" }, el("video", { src: media(v.path), controls: "", preload: "metadata", playsinline: "" })),
      el("div", { class: "g-meta" },
        el("span", { class: "chip" }, fmtDuration(v.duration)),
        el("span", { class: "chip" }, `${v.width}×${v.height}`),
        el("span", { class: "chip" }, `${Math.round(v.fps)} fps`),
        el("span", { class: "chip" }, v.has_audio ? "có tiếng" : "không tiếng"),
        job.source && job.source.kind === "link" ? el("span", { class: "chip" }, "từ link") : el("span", { class: "chip" }, "tải lên")));
  }
  if (dl.status === "downloading") body.push(el("p", { class: "sw-note" }, "Đang tải video từ link…"));
  if (dl.status === "failed") body.push(el("div", { class: "g-error" }, `Tải link lỗi: ${dl.error || ""}`));
  if (dl.status === "interrupted") body.push(el("div", { class: "g-error" }, "Tải link bị gián đoạn — dán link lại."));

  body.push(el("p", { class: "sw-note" }, v ? "Đổi video khác:" : "Dán link (Facebook, TikTok, YouTube, Instagram…) hoặc tải file lên."));
  body.push(tabs(videoTab, [["link", "Dán link"], ["upload", "Tải video lên"]], (k) => { videoTab = k; render(); }));
  if (videoTab === "link") {
    const input = el("input", { type: "url", placeholder: "https://…", value: drafts.url, "aria-label": "Link video",
      oninput: (e) => { drafts.url = e.target.value; } });
    body.push(el("div", { class: "sw-row" }, el("label", { class: "sw-field" }, "Link video", input),
      btn("Tải video", () => act("link", () => post(`/api/swap/${job.id}/link`, { url: drafts.url })),
        { primary: !v, name: "link", disabled: dl.status === "downloading" })));
  } else {
    const file = el("input", { type: "file", accept: "video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm,.mkv,.m4v",
      "aria-label": "Chọn file video" });
    body.push(el("div", { class: "sw-row" }, el("label", { class: "sw-field" }, "File video (tối đa 500 MB)", file),
      btn("Tải lên", () => {
        const f = file.files && file.files[0];
        if (!f) { errorMsg = "Chọn một file video trước."; render(); return; }
        act("upload", () => post(`/api/swap/${job.id}/upload`, f, { "X-File-Name": encodeURIComponent(f.name) }));
      }, { primary: !v, name: "upload" })));
  }

  if (v) {
    const rng = job.range;
    const start = drafts.start ?? (rng ? rng.start : 0);
    const end = drafts.end ?? (rng ? rng.end : Math.min(v.duration, 5));
    const maxSecs = (options.max_frames || 600) / Math.min(v.fps || 24, 30);
    body.push(el("h4", { class: "sw-sub" }, "Đoạn cần thay"),
      el("div", { class: "sw-row" },
        el("label", { class: "sw-field narrow" }, "Từ giây",
          el("input", { type: "number", min: "0", step: "0.1", value: start, oninput: (e) => { drafts.start = Number(e.target.value); } })),
        el("label", { class: "sw-field narrow" }, "Đến giây",
          el("input", { type: "number", min: "0", step: "0.1", value: end, oninput: (e) => { drafts.end = Number(e.target.value); } })),
        btn(rng ? "Cập nhật đoạn" : "Chọn đoạn này", () => act("range",
          () => post(`/api/swap/${job.id}/range`, { start: drafts.start ?? start, end: drafts.end ?? end })),
        { primary: !rng, name: "range" })),
      el("p", { class: "sw-note" }, `Tối đa ${maxSecs.toFixed(1)} giây mỗi lượt. Giá ${fmtMoney(options.price_per_frame)}/frame.`));
    if (rng) {
      body.push(el("div", { class: "g-meta" },
        el("span", { class: "chip" }, `${rng.start}s → ${rng.end}s`),
        el("span", { class: "chip" }, `${rng.frames} frame`),
        el("span", { class: "chip" }, `ước tính ${fmtMoney(rng.cost_usd)}`)));
    }
  }
  return card(1, "Video gốc", { ok: !!(v && job.range) }, ...body);
}

function stepMode() {
  const rows = Object.entries(options.modes || job.modes || {}).map(([key, m]) => el("label", { class: `sw-mode${m.available ? "" : " off"}` },
    el("input", { type: "radio", name: "mode", value: key, checked: job.mode === key ? "" : null, disabled: m.available ? null : "" }),
    el("span", {}, m.label, el("small", {}, m.available ? `${fmtMoney(m.price_per_frame)}/frame · chỉ thay khuôn mặt, giữ nguyên người, đồ, bối cảnh, chuyển động` : m.reason))));
  return card(2, "Chế độ thay", { ok: true }, el("div", { class: "sw-modes" }, rows));
}

function stepCharacter() {
  const ch = job.character || {};
  const body = [];
  if (ch.image) {
    const status = ch.status || "none";
    const info = el("div", { class: "info" },
      el("span", { class: `sw-badge ${status}` }, STATUS_VI[status] || status),
      el("div", {}, ch.name ? el("strong", {}, ch.name) : null,
        el("div", { class: "sw-note" }, { upload: "Ảnh tải lên", library: "Từ thư viện nhân vật", generate: "Tạo bằng AI (Nano Banana)" }[ch.origin] || "")),
      ch.prompt ? el("div", { class: "sw-note" }, `Mô tả: ${ch.prompt}`) : null);
    if (status === "pending") {
      const save = el("input", { type: "checkbox", id: "saveLib", checked: ch.origin === "generate" ? "" : null });
      const nameIn = el("input", { type: "text", class: "sw-input", placeholder: "Tên nhân vật", value: drafts.libName || ch.name || "",
        oninput: (e) => { drafts.libName = e.target.value; }, "aria-label": "Tên nhân vật để lưu" });
      info.append(
        el("p", { class: "sw-note" }, "Xem kỹ khuôn mặt: rõ nét, nhìn thẳng, không bị che. Duyệt xong mới chạy thay được."),
        el("label", { class: "sw-note", for: "saveLib" }, save, " Lưu vào thư viện nhân vật"), nameIn,
        el("div", { class: "g-actions" },
          btn("Duyệt ảnh này", () => act("approve", () => post(`/api/swap/${job.id}/character/approve`,
            { save_to_library: save.checked, name: nameIn.value })), { primary: true, name: "approve" }),
          btn("Không duyệt", () => act("reject", () => post(`/api/swap/${job.id}/character/reject`)), { name: "reject" })));
    } else if (status === "approved") {
      info.append(el("p", { class: "sw-note" }, ch.char_id ? `Trong thư viện: ${ch.name || ch.char_id}` : "Đã duyệt — dùng ảnh này để thay."));
    } else if (status === "rejected") {
      info.append(el("p", { class: "sw-note" }, "Chọn ảnh khác hoặc tạo lại bên dưới."));
    }
    body.push(el("div", { class: "sw-char" }, el("img", { src: media(ch.image), alt: "Ảnh nhân vật" }), info));
    body.push(el("h4", { class: "sw-sub" }, "Đổi nhân vật"));
  }

  body.push(tabs(charTab, [["upload", "Tải ảnh lên"], ["library", "Chọn từ thư viện"], ["generate", "Tạo nhân vật mới"]],
    (k) => { charTab = k; render(); }));
  if (charTab === "upload") {
    const file = el("input", { type: "file", accept: "image/png,image/jpeg,image/webp", "aria-label": "Chọn ảnh nhân vật" });
    body.push(el("p", { class: "sw-note" }, "Ảnh rõ mặt, nhìn thẳng, ánh sáng đều. Ảnh cắt sát mặt cho kết quả tốt nhất."),
      el("div", { class: "sw-row" }, el("label", { class: "sw-field" }, "Ảnh (png, jpg, webp)", file),
        btn("Tải ảnh lên", () => {
          const f = file.files && file.files[0];
          if (!f) { errorMsg = "Chọn một ảnh trước."; render(); return; }
          act("charUpload", async () => {
            const data = await new Promise((resolve, reject) => {
              const r = new FileReader();
              r.onload = () => resolve(r.result);
              r.onerror = () => reject(new Error("không đọc được file"));
              r.readAsDataURL(f);
            });
            return post(`/api/swap/${job.id}/character/upload`, { file_name: f.name, data_base64: data });
          });
        }, { name: "charUpload" })));
  } else if (charTab === "library") {
    const chars = options.characters || [];
    body.push(chars.length
      ? el("div", { class: "sw-lib" }, chars.map((c) => el("button", {
        type: "button", disabled: busy ? "" : null, title: c.name,
        onclick: () => act("library", () => post(`/api/swap/${job.id}/character/library`, { char_id: c.id, file: c.image })),
      }, el("img", { src: charImg(c.id, c.image), alt: "", loading: "lazy" }), el("span", {}, c.name))))
      : el("p", { class: "hint" }, "Thư viện chưa có nhân vật nào có ảnh."),
    el("p", { class: "sw-note" }, "Nhân vật trong thư viện đã duyệt sẵn; dùng ảnh “Mặt trước” nếu có."));
  } else {
    const prompt = el("textarea", { placeholder: "vd: cô gái Việt 22 tuổi, tóc đen dài buộc cao, mắt to, da sáng…",
      oninput: (e) => { drafts.prompt = e.target.value; }, "aria-label": "Mô tả nhân vật" });
    prompt.value = drafts.prompt;
    const name = el("input", { type: "text", placeholder: "Tên (tuỳ chọn)", value: drafts.name,
      oninput: (e) => { drafts.name = e.target.value; }, "aria-label": "Tên nhân vật" });
    body.push(el("label", { class: "sw-field" }, "Mô tả nhân vật", prompt),
      el("div", { class: "sw-row" }, el("label", { class: "sw-field" }, "Tên", name),
        btn(`Tạo ảnh (~${fmtMoney(options.character_image_cost)})`, () => act("generate",
          () => post(`/api/swap/${job.id}/character/generate`, { prompt: drafts.prompt, name: drafts.name })),
        { primary: true, name: "generate" })),
      el("p", { class: "sw-note" }, "Ảnh tạo ra ở trạng thái “Chờ duyệt”. Không ưng thì bấm Không duyệt rồi tạo lại."));
  }
  return card(3, "Nhân vật thay vào", { ok: ch.status === "approved" }, ...body);
}

function stepRun() {
  const ready = job.video && job.range && (job.character || {}).status === "approved";
  const lockNote = !job.video ? "Cần video ở bước 1." : !job.range ? "Chọn đoạn cần thay ở bước 1."
    : "Cần duyệt ảnh nhân vật ở bước 3.";
  const body = [];
  if (ready) {
    const rng = job.range;
    const at = drafts.previewAt ?? (job.preview ? job.preview.time : rng.start);
    body.push(el("h4", { class: "sw-sub" }, "Xem trước 1 frame"),
      el("div", { class: "sw-row" },
        el("label", { class: "sw-field narrow" }, "Tại giây",
          el("input", { type: "number", min: "0", step: "0.1", value: at, oninput: (e) => { drafts.previewAt = Number(e.target.value); } })),
        btn(`Ghép thử (${fmtMoney(options.price_per_frame)})`, () => act("preview",
          () => post(`/api/swap/${job.id}/preview`, { time: drafts.previewAt ?? at })), { name: "preview" })));
    const p = job.preview;
    if (p) {
      const stale = p.character !== job.character.image;
      body.push(el("div", { class: "sw-compare" },
        el("figure", {}, el("img", { src: media(p.before), alt: "Frame gốc" }), el("figcaption", {}, `Gốc · ${p.time}s`)),
        el("figure", {}, el("img", { src: media(p.after), alt: "Frame đã thay" }),
          el("figcaption", {}, stale ? "Đã thay (nhân vật cũ)" : "Đã thay"))));
    }
    const r = job.run || {};
    const testFrames = rng.end - rng.start <= 1 ? rng.frames : Math.max(1, Math.ceil(rng.fps - 1e-6));
    const running = r.status === "running";
    body.push(el("h4", { class: "sw-sub" }, "Chạy thay"),
      el("div", { class: "g-actions" },
        btn(`Chạy thử 1 giây (~${fmtMoney(testFrames * options.price_per_frame)})`, () => {
          if (confirm(`Chạy thử ${testFrames} frame, tốn khoảng ${fmtMoney(testFrames * options.price_per_frame)}?`)) {
            act("runTest", () => post(`/api/swap/${job.id}/run`, { kind: "test" }));
          }
        }, { name: "runTest", disabled: running }),
        btn(`Chạy cả đoạn (~${fmtMoney(rng.cost_usd)})`, () => {
          if (confirm(`Chạy ${rng.frames} frame (${rng.start}s → ${rng.end}s), tốn khoảng ${fmtMoney(rng.cost_usd)}?`)) {
            act("runFull", () => post(`/api/swap/${job.id}/run`, { kind: "full" }));
          }
        }, { primary: true, name: "runFull", disabled: running }),
        running ? btn("Huỷ", () => act("cancel", () => post(`/api/swap/${job.id}/cancel`)), { name: "cancel" }) : null),
      el("p", { class: "sw-note" }, "Mỗi frame được ghép riêng nên mặt có thể hơi nhấp nháy khi chuyển động nhanh — nên chạy thử 1 giây trước. Chạy lại sau khi bị huỷ/lỗi chỉ tốn tiền cho frame còn thiếu."));
    if (r.status) {
      const pct = r.total ? Math.round(((r.done || 0) + (r.failed || 0)) / r.total * 100) : 0;
      body.push(el("div", { class: "g-meta" },
        el("span", { class: `chip${r.status === "done" ? " ok" : ""}` }, RUN_VI[r.status] || r.status),
        el("span", { class: "chip" }, r.kind === "test" ? "chạy thử" : "cả đoạn"),
        el("span", { class: "chip" }, `${r.done || 0}/${r.total} frame`),
        r.failed ? el("span", { class: "chip" }, `${r.failed} frame lỗi (lấp bằng frame bên cạnh — chạy lại để thử lại)`) : null,
        el("span", { class: "chip" }, `đã tốn ${fmtMoney(r.cost_usd)}`)));
      if (running) body.push(el("div", { class: "sw-progress", role: "progressbar", "aria-valuenow": pct, "aria-valuemin": 0, "aria-valuemax": 100 },
        el("div", { style: `width:${pct}%` })));
      if (r.error) body.push(el("div", { class: "g-error" }, r.error));
    }
    const outs = job.outputs || [];
    if (outs.length) {
      body.push(el("h4", { class: "sw-sub" }, "Kết quả"), el("div", { class: "sw-outputs" }, outs.slice(0, 6).map((o) => el("div", {},
        el("video", { src: media(o.path), controls: "", preload: "metadata", playsinline: "" }),
        el("div", { class: "g-actions" },
          el("span", { class: "chip" }, o.kind === "test" ? "Thử 1 giây" : "Cả đoạn"),
          el("span", { class: "chip" }, `${o.start}s → ${o.end}s`),
          el("span", { class: "g-stamp" }, `${fmtMoney(o.cost_usd)} · ${fmtAgo(o.created_at)}`),
          el("a", { class: "g-btn", href: media(o.path), download: "" }, "Tải về"))))));
    }
  }
  return card(4, "Xem trước & chạy", { ok: (job.run || {}).status === "done", locked: !ready, lockNote }, ...body);
}

function render() {
  if (!job) {
    detailEl.replaceChildren(el("p", { class: "hint" }, "Chọn hoặc tạo một lượt thay ở bên trái."));
    return;
  }
  const head = el("div", { class: "g-head" }, el("h2", {}, job.title),
    el("span", { class: "g-stamp" }, `Đã tốn ${fmtMoney(job.spent_usd || 0)} · ${job.id}`),
    el("div", { class: "spacer" }),
    btn("Xoá", () => {
      if (confirm(`Chuyển “${job.title}” vào thùng rác (projects/_trash)?`)) {
        act("delete", async () => {
          await post(`/api/swap/${job.id}/delete`);
          selected = null; storageSet(SEL_KEY, ""); job = null;
        });
      }
    }, { name: "delete", disabled: isActive(job) }));
  const err = errorMsg ? el("div", { class: "g-error", role: "alert" }, errorMsg) : null;
  const scroll = window.scrollY;
  detailEl.replaceChildren(...[head, err, stepVideo(), stepMode(), stepCharacter(), stepRun()].filter(Boolean));
  window.scrollTo(0, scroll);
}

document.getElementById("newForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = document.getElementById("newTitle");
  act("create", async () => {
    const created = await post("/api/swap", { title: input.value });
    input.value = "";
    selected = created.id;
    storageSet(SEL_KEY, created.id);
    return created;
  });
});

(async function init() {
  try { options = await getJSON("/api/swap/options"); } catch { /* keep defaults */ }
  await loadList();
  if (selected && !jobs.some((j) => j.id === selected)) selected = null;
  await loadJob();
  renderList();
  render();
  schedulePoll();
})();
