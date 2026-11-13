import { el, fmtAgo, getJSON, mediaURL, subscribe, thumbURL } from "/ui/lib.js";

const THEME_KEY = "backlot.theme";
const SEL_KEY = "backlot.gallery.selected";
const FORM_KEY = "backlot.gallery.form";

const listEl = document.getElementById("list");
const detailEl = document.getElementById("detail");
const searchEl = document.getElementById("search");

let videos = [];
let options = { platforms: [], languages: [], model: "" };
let selectedKey = storageGet(SEL_KEY);
let busy = false;

function storageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function storageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } }

document.documentElement.dataset.theme = storageGet(THEME_KEY) === "light" ? "light" : "dark";

const keyOf = (v) => `${v.project_id}/${v.path}`;
const fmtMB = (b) => `${(b / 1048576).toFixed(1)} MB`;

async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = el("textarea", { style: "position:fixed;opacity:0" });
    ta.value = text;
    document.body.append(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  if (btn) {
    const old = btn.textContent;
    btn.textContent = "Đã copy";
    btn.classList.add("done");
    setTimeout(() => { btn.textContent = old; btn.classList.remove("done"); }, 1400);
  }
}

function copyBtn(getText, label = "Copy") {
  const b = el("button", { class: "g-btn", type: "button" }, label);
  b.addEventListener("click", () => copyText(getText(), b));
  return b;
}

// ---------------------------------------------------------------- list

function renderList() {
  const q = searchEl.value.trim().toLowerCase();
  const shown = videos.filter((v) => !q || `${v.project_title} ${v.project_id} ${v.path}`.toLowerCase().includes(q));
  document.getElementById("count").textContent = `${videos.length} video`;
  document.getElementById("empty").style.display = videos.length ? "none" : "block";
  listEl.innerHTML = "";
  for (const v of shown) {
    const item = el("button", {
      class: "g-item", type: "button", "aria-selected": keyOf(v) === selectedKey ? "true" : "false",
      onclick: () => select(keyOf(v)),
    },
      el("div", { class: "g-thumb" }, el("img", { src: thumbURL(v.project_id, v.path, 320), loading: "lazy", alt: "" })),
      el("div", {},
        el("h3", {}, v.project_title),
        el("div", { class: "g-sub" }, v.path),
        el("div", { class: "g-chips" },
          el("span", { class: "chip" }, v.kind === "render" ? "render" : "clip"),
          v.social ? el("span", { class: "chip ok" }, "có caption") : null,
          v.prompt ? null : el("span", { class: "chip warn" }, "không có prompt"),
          el("span", { class: "chip" }, fmtAgo(v.modified)),
        ),
      ),
    );
    listEl.append(item);
  }
}

function select(key) {
  selectedKey = key;
  storageSet(SEL_KEY, key);
  for (const node of listEl.querySelectorAll(".g-item")) node.setAttribute("aria-selected", "false");
  renderList();
  renderDetail();
}

// ---------------------------------------------------------------- detail

function renderDetail() {
  const v = videos.find((x) => keyOf(x) === selectedKey);
  detailEl.innerHTML = "";
  if (!v) {
    detailEl.append(el("p", { class: "hint" }, "Chọn một video ở bên trái."));
    return;
  }

  const video = el("video", { controls: "", preload: "metadata", playsinline: "", src: mediaURL(v.project_id, v.path) });
  const durChip = el("span", { class: "chip" }, "…");
  video.addEventListener("loadedmetadata", () => {
    durChip.textContent = `${video.duration.toFixed(1)}s · ${video.videoWidth}×${video.videoHeight}`;
  });

  detailEl.append(
    el("div", { class: "g-player" }, video),
    el("div", { class: "g-head" },
      el("h2", {}, v.project_title),
      el("a", { class: "g-sub", href: mediaURL(v.project_id, v.path), download: v.name }, `${v.path} ↓`),
    ),
    el("div", { class: "g-meta" },
      durChip,
      el("span", { class: "chip" }, fmtMB(v.size_bytes)),
      v.model ? el("span", { class: "chip" }, v.model) : null,
      v.cost_usd != null ? el("span", { class: "chip" }, `$${Number(v.cost_usd).toFixed(2)}`) : null,
      el("a", { class: "chip", href: `/p/${encodeURIComponent(v.project_id)}`, style: "text-decoration:none" }, "Mở board ↗"),
    ),
    promptCard(v),
    socialCard(v),
  );
}

function promptCard(v) {
  const card = el("div", { class: "g-card" });
  const head = el("div", { class: "g-card-h" }, el("h3", {}, "Prompt đã dùng"),
    v.prompt_source ? el("span", { class: "g-stamp" }, v.prompt_source) : null,
    el("span", { class: "spacer" }));
  card.append(head);
  if (!v.prompt) {
    card.append(el("p", { class: "hint" },
      "Không tìm thấy prompt cho video này. Thêm file ",
      el("code", {}, v.path.replace(/\.[^.]+$/, ".meta.json")),
      " với {\"prompt\": \"…\"} hoặc {\"prompt_file\": \"artifacts/…\"}."));
    return card;
  }
  const pre = el("pre", { class: "g-prompt" }, v.prompt);
  const toggle = el("button", { class: "g-btn", type: "button" }, "Mở rộng");
  toggle.addEventListener("click", () => {
    pre.classList.toggle("expanded");
    toggle.textContent = pre.classList.contains("expanded") ? "Thu gọn" : "Mở rộng";
  });
  head.append(toggle, copyBtn(() => v.prompt, "Copy prompt"));
  card.append(pre);
  return card;
}

function socialCard(v) {
  const saved = (() => { try { return JSON.parse(storageGet(FORM_KEY) || "{}"); } catch { return {}; } })();
  const card = el("div", { class: "g-card" });
  card.append(el("div", { class: "g-card-h" }, el("h3", {}, "Title · Caption · Hashtag"), el("span", { class: "spacer" })));

  const platform = el("select", { id: "f-platform" },
    options.platforms.map((p) => el("option", { value: p.id }, p.label)));
  const language = el("select", { id: "f-language" },
    options.languages.map((l) => el("option", { value: l.id }, l.id === "vi" ? "Tiếng Việt" : l.label)));
  const notes = el("textarea", { id: "f-notes", placeholder: "Ghi chú thêm (không bắt buộc): giọng văn, CTA, tên kênh…" });
  platform.value = v.social?.platform || saved.platform || "facebook_reels";
  language.value = v.social?.language || saved.language || "vi";
  notes.value = v.social?.notes ?? saved.notes ?? "";

  const go = el("button", { class: "g-btn primary", type: "button" }, v.social ? "Tạo lại" : "Tạo caption");
  const err = el("div", { class: "g-error", role: "alert" });
  const out = el("div", { class: "g-out" });

  card.append(
    el("div", { class: "g-form" },
      el("label", { for: "f-platform" }, "Nền tảng", platform),
      el("label", { for: "f-language" }, "Ngôn ngữ", language),
      el("label", { class: "full", for: "f-notes" }, "Ghi chú", notes),
    ),
    el("div", { class: "g-actions" }, go,
      el("span", { class: "g-cost" }, `Gọi ${options.model} qua PiAPI · khoảng $0.01 mỗi lần`)),
    err, out,
  );

  if (v.social) renderCopy(out, v.social);

  go.addEventListener("click", async () => {
    if (busy) return;
    busy = true;
    go.disabled = true;
    go.textContent = "Đang viết…";
    err.textContent = "";
    storageSet(FORM_KEY, JSON.stringify({ platform: platform.value, language: language.value, notes: notes.value }));
    try {
      const res = await fetch(`/api/social/${encodeURIComponent(v.project_id)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Backlot-Action": "social" },
        body: JSON.stringify({ video: v.path, platform: platform.value, language: language.value, notes: notes.value }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
      v.social = body;
      renderCopy(out, body);
      renderList();
    } catch (e) {
      err.textContent = `Không tạo được: ${e.message}`;
    } finally {
      busy = false;
      go.disabled = false;
      go.textContent = "Tạo lại";
    }
  });
  return card;
}

function renderCopy(out, s) {
  out.innerHTML = "";
  const caption = el("textarea", { "aria-label": "Caption" });
  caption.value = s.caption || "";
  const tagsText = (s.hashtags || []).join(" ");
  const platformLabel = options.platforms.find((p) => p.id === s.platform)?.label || s.platform;

  out.append(
    el("div", { class: "g-stamp" },
      `${platformLabel} · ${s.language === "vi" ? "Tiếng Việt" : s.language} · ${s.model} · ${fmtAgo(s.created_at)}`),
    el("div", {}, el("h4", {}, "Title"),
      el("div", { style: "display:flex;flex-direction:column;gap:6px" },
        (s.titles || []).map((t) => el("div", { class: "g-row" }, el("div", { class: "g-title" }, t), copyBtn(() => t))))),
    el("div", {}, el("h4", {}, "Caption"),
      el("div", { class: "g-row" }, caption, copyBtn(() => caption.value))),
    el("div", {}, el("h4", {}, "Hashtag"),
      el("div", { class: "g-row" },
        el("div", { class: "g-tags" }, (s.hashtags || []).map((h) => el("span", { class: "chip" }, h))),
        copyBtn(() => tagsText))),
    el("div", { class: "g-actions" },
      copyBtn(() => `${caption.value}\n\n${tagsText}`, "Copy caption + hashtag")),
  );

  if (s.history?.length) {
    out.append(el("details", { class: "g-history" },
      el("summary", {}, `Các bản trước (${s.history.length})`),
      s.history.slice().reverse().map((h) => el("div", { class: "g-hist-item" },
        el("div", { class: "g-stamp" }, `${h.platform} · ${fmtAgo(h.created_at)}`),
        el("p", {}, (h.titles || [])[0] || ""),
        el("p", {}, h.caption || ""),
        el("p", { class: "g-sub" }, (h.hashtags || []).join(" "))))));
  }
}

// ---------------------------------------------------------------- boot

async function load({ keepDetail = false } = {}) {
  [videos, options] = await Promise.all([getJSON("/api/videos"), getJSON("/api/social/options")]);
  if (!videos.some((v) => keyOf(v) === selectedKey)) selectedKey = videos[0] ? keyOf(videos[0]) : null;
  renderList();
  if (!keepDetail || !detailEl.querySelector("video")) renderDetail();
}

searchEl.addEventListener("input", renderList);
load().catch((e) => { detailEl.textContent = `Lỗi tải danh sách: ${e.message}`; });
// New renders appear live; don't rebuild the open detail (would stop playback).
subscribe("/api/library/events", () => { if (!busy) load({ keepDetail: true }).catch(console.error); });
