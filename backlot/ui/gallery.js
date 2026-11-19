import { cartView, el, fmtAgo, getJSON, mediaURL, productPicker, subscribe, thumbURL } from "/ui/lib.js";

const THEME_KEY = "backlot.theme";
const SEL_KEY = "backlot.gallery.selected";
const FORM_KEY = "backlot.gallery.form";

const listEl = document.getElementById("list");
const detailEl = document.getElementById("detail");
const searchEl = document.getElementById("search");

let videos = [];
let options = { platforms: [], languages: [], model: "" };
let channels = [];   // /api/channels: accounts a video can be marked as posted to

const channelLabel = (id) => {
  const c = channels.find((x) => x.id === id);
  return c ? `${c.account} · ${c.platform}` : id;
};
const postedChips = (v) => (v.posted || []).map((id) => el("span", { class: "chip ok" }, `✓ ${channelLabel(id)}`));

function postedCard(v) {
  const status = el("span", { class: "g-sub" });
  const boxes = channels.map((c) => {
    const id = `posted-${c.id}`;
    const box = el("input", { type: "checkbox", id });
    box.checked = (v.posted || []).includes(c.id);
    box.addEventListener("change", async () => {
      const chosen = channels.filter((x) => document.getElementById(`posted-${x.id}`)?.checked).map((x) => x.id);
      for (const b of boxes) b.querySelector("input").disabled = true;
      status.textContent = "Đang lưu…";
      try {
        const res = await postJSON(`/api/posted/${encodeURIComponent(v.project_id)}`, "posted", { video: v.path, channels: chosen });
        v.posted = res.posted;
        status.textContent = "Đã lưu";
        renderList();
      } catch (e) {
        box.checked = !box.checked;
        status.textContent = `Không lưu được: ${e.message}`;
      } finally {
        for (const b of boxes) b.querySelector("input").disabled = false;
      }
    });
    return el("label", { for: id, style: "display:flex;align-items:center;gap:8px;cursor:pointer" },
      box, el("span", {}, el("b", {}, c.account), ` · ${c.platform}`));
  });
  return el("div", { class: "g-card" },
    el("div", { class: "g-card-h" }, el("h3", {}, "Đã đăng lên"), el("div", { class: "spacer" }), status),
    channels.length ? el("div", { style: "display:flex;flex-wrap:wrap;gap:10px 22px" }, ...boxes)
      : el("p", { class: "hint", style: "margin:0" }, "Chưa có kênh nào trong backlot/channels.json."));
}
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
        el("h3", {}, v.uploaded ? (v.original_name || v.name) : v.project_title),
        el("div", { class: "g-sub" }, v.uploaded ? "Video tải lên" : v.path),
        el("div", { class: "g-chips" },
          v.uploaded ? el("span", { class: "chip" }, "tải lên")
            : el("span", { class: "chip" }, v.kind === "render" ? "render" : "clip"),
          ...postedChips(v),
          v.social ? el("span", { class: "chip" }, "có caption") : null,
          v.prompt || v.uploaded ? null : el("span", { class: "chip warn" }, "không có prompt"),
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

  let delBtn = null;
  if (v.uploaded) {
    delBtn = el("button", { class: "g-btn", type: "button" }, "Xoá video tải lên");
    delBtn.addEventListener("click", async () => {
      if (!confirm(`Xoá “${v.original_name || v.name}” và caption đã tạo? Không hoàn tác được.`)) return;
      delBtn.disabled = true;
      try {
        await postJSON("/api/social-upload/delete", "upload", { video: v.path });
        selectedKey = null;
        await load();
      } catch (e) {
        delBtn.disabled = false;
        alert(`Không xoá được: ${e.message}`);
      }
    });
  }

  detailEl.append(
    el("div", { class: "g-player" }, video),
    el("div", { class: "g-head" },
      el("h2", {}, v.uploaded ? (v.original_name || v.name) : v.project_title),
      el("a", { class: "g-sub", href: mediaURL(v.project_id, v.path), download: v.name }, `${v.path} ↓`),
    ),
    el("div", { class: "g-meta" },
      durChip,
      el("span", { class: "chip" }, fmtMB(v.size_bytes)),
      v.model ? el("span", { class: "chip" }, v.model) : null,
      v.cost_usd != null ? el("span", { class: "chip" }, `$${Number(v.cost_usd).toFixed(2)}`) : null,
      v.uploaded ? delBtn
        : el("a", { class: "chip", href: `/p/${encodeURIComponent(v.project_id)}`, style: "text-decoration:none" }, "Mở board ↗"),
    ),
    postedCard(v),
    v.prompt ? promptCard(v) : readingCard(v),
    socialCard(v),
    thumbCard(v, video),
  );
}

// A video with no generation prompt is read instead: sampled frames + speech transcript.
function readingCard(v) {
  const card = el("div", { class: "g-card", id: "reading-card" });
  card.append(el("div", { class: "g-card-h" }, el("h3", {}, "AI đọc video"), el("span", { class: "spacer" })));
  card.append(el("p", { class: "hint" }, v.uploaded
    ? "Video này không có prompt. Khi tạo caption, AI sẽ xem 4–10 khung hình rải đều trong video và nghe lời thoại (chép lời bằng Whisper ngay trên máy)."
    : "Không tìm thấy prompt cho video này, nên AI sẽ xem các khung hình và nghe lời thoại thay vào đó."));
  if (v.transcript) {
    card.append(el("h4", {}, "Lời thoại đã chép"), el("p", { class: "g-transcript" }, v.transcript));
  } else if (v.transcript === "") {
    card.append(el("p", { class: "hint" }, "Không nghe thấy lời thoại trong video."));
  }
  return card;
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
  const aiMade = el("input", { id: "f-ai", type: "checkbox" });
  aiMade.checked = v.social?.ai_generated ?? !v.uploaded;
  const picker = productPicker(options.all_products || [],
    v.social?.products ? v.social.products.map((p) => p.id) : (options.project_products || {})[v.project_id]);

  const go = el("button", { class: "g-btn primary", type: "button" }, v.social ? "Tạo lại" : "Tạo caption");
  const err = el("div", { class: "g-error", role: "alert" });
  const out = el("div", { class: "g-out" });

  card.append(
    el("div", { class: "g-form" },
      el("label", { for: "f-platform" }, "Nền tảng", platform),
      el("label", { for: "f-language" }, "Ngôn ngữ", language),
      el("label", { class: "full", for: "f-notes" }, "Ghi chú", notes),
      el("label", { class: "full g-check", for: "f-ai" }, aiMade, "Video do AI tạo (thêm dòng ghi chú “video AI” vào caption)"),
      el("div", { class: "full" }, el("div", { class: "g-cost", style: "margin-bottom:6px" },
        "Sản phẩm gắn link giỏ hàng (link được thêm nguyên văn vào cuối caption)"), picker.node),
    ),
    el("div", { class: "g-actions" }, go,
      el("span", { class: "g-cost" }, v.prompt
        ? `Gọi ${options.model} qua PiAPI · khoảng $0.01 mỗi lần`
        : `Gọi ${options.model} qua PiAPI, kèm 4–10 khung hình · khoảng $0.05–0.10 mỗi lần · lần đầu chép lời mất thêm chút thời gian`)),
    err, out,
  );

  if (v.social) renderCopy(out, v.social);

  go.addEventListener("click", async () => {
    if (busy) return;
    busy = true;
    go.disabled = true;
    go.textContent = v.prompt ? "Đang viết…" : "Đang xem video và viết…";
    err.textContent = "";
    storageSet(FORM_KEY, JSON.stringify({ platform: platform.value, language: language.value, notes: notes.value }));
    try {
      const res = await fetch(`/api/social/${encodeURIComponent(v.project_id)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Backlot-Action": "social" },
        body: JSON.stringify({
          video: v.path, platform: platform.value, language: language.value, notes: notes.value,
          ai_generated: aiMade.checked, products: picker.value(),
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
      v.social = body;
      renderCopy(out, body);
      renderList();
      if (!v.prompt) {
        // Show the transcript cached by this run without restarting the player.
        getJSON("/api/videos").then((list) => {
          const fresh = list.find((x) => keyOf(x) === keyOf(v));
          if (!fresh) return;
          v.transcript = fresh.transcript;
          document.getElementById("reading-card")?.replaceWith(readingCard(v));
        }).catch(console.error);
      }
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
    cartView(s),
    el("div", { class: "g-actions" },
      copyBtn(() => [caption.value, s.cart, tagsText].filter(Boolean).join("\n\n"),
        s.cart ? "Copy caption + link + hashtag" : "Copy caption + hashtag")),
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

// ---------------------------------------------------------------- thumbnails

async function postJSON(url, action, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Backlot-Action": action },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

function stripEmoji(text) {
  return (text || "").replace(/\p{Extended_Pictographic}|️/gu, "").replace(/\s+/g, " ").trim();
}

function thumbCard(v, video) {
  v.thumbs = v.thumbs || [];
  let selectedFrame = (v.thumbs.find((t) => t.kind === "frame") || {}).path || null;

  const card = el("div", { class: "g-card" });
  card.append(el("div", { class: "g-card-h" }, el("h3", {}, "Thumbnail"), el("span", { class: "spacer" })));

  const grabBtn = el("button", { class: "g-btn", type: "button" }, "Chụp khung hiện tại");
  const err = el("div", { class: "g-error", role: "alert" });
  const grid = el("div", { class: "g-thumbs" });

  const aspect = el("select", { id: "t-aspect" },
    options.thumb_aspects.map((a) => el("option", { value: a.id }, a.label)));
  aspect.value = "16:9";
  const titleText = el("input", { id: "t-title", type: "text", maxlength: "120",
    placeholder: "Chữ trên thumbnail (để trống nếu không muốn chữ)" });
  titleText.value = stripEmoji(v.social?.titles?.[0]);
  const style = el("textarea", { id: "t-style", placeholder: "Gợi ý phong cách (không bắt buộc): cận mặt, ánh neon đỏ, góc thấp…" });
  const aiBtn = el("button", { class: "g-btn primary", type: "button" }, "Tạo thumbnail AI");

  function updateAi() {
    aiBtn.disabled = !selectedFrame || busy;
    aiBtn.title = selectedFrame ? "" : "Chụp hoặc chọn một khung hình gốc trước";
  }

  function renderGrid() {
    grid.innerHTML = "";
    if (!v.thumbs.length) {
      grid.append(el("p", { class: "hint" }, "Chưa có thumbnail. Tua video tới khung hình đẹp rồi bấm “Chụp khung hiện tại”."));
    }
    for (const t of v.thumbs) {
      const isFrame = t.kind === "frame";
      const picked = isFrame && t.path === selectedFrame;
      const label = isFrame ? `Khung ${Number(t.time_s ?? 0).toFixed(1)}s` : `AI ${t.aspect_ratio || ""}`;
      grid.append(el("figure", { class: `g-thumb-tile${picked ? " picked" : ""}` },
        el("a", { href: mediaURL(v.project_id, t.path), target: "_blank", rel: "noopener" },
          el("img", { src: thumbURL(v.project_id, t.path, 640), loading: "lazy", alt: label })),
        el("figcaption", {},
          el("span", { class: `chip${isFrame ? "" : " ok"}` }, label),
          isFrame ? el("button", {
            class: "g-btn", type: "button", "aria-pressed": picked ? "true" : "false",
            onclick: () => { selectedFrame = t.path; renderGrid(); updateAi(); },
          }, picked ? "Đang chọn" : "Dùng làm gốc") : null,
          el("a", { class: "g-btn", href: mediaURL(v.project_id, t.path), download: t.name }, "Tải"),
        ),
      ));
    }
  }

  grabBtn.addEventListener("click", async () => {
    err.textContent = "";
    grabBtn.disabled = true;
    try {
      video.pause();
      const t = await postJSON(`/api/thumbs/${encodeURIComponent(v.project_id)}/frame`, "thumb",
        { video: v.path, time_s: video.currentTime || 0 });
      v.thumbs = [t, ...v.thumbs.filter((x) => x.path !== t.path)];
      selectedFrame = t.path;
      renderGrid();
      updateAi();
    } catch (e) {
      err.textContent = `Không chụp được: ${e.message}`;
    } finally {
      grabBtn.disabled = false;
    }
  });

  aiBtn.addEventListener("click", async () => {
    if (busy || !selectedFrame) return;
    busy = true;
    aiBtn.disabled = true;
    aiBtn.textContent = "Đang tạo… (~30s)";
    err.textContent = "";
    try {
      const t = await postJSON(`/api/thumbs/${encodeURIComponent(v.project_id)}/ai`, "thumb", {
        video: v.path, frame: selectedFrame, aspect: aspect.value,
        title_text: titleText.value, style_notes: style.value,
      });
      v.thumbs = [t, ...v.thumbs];
      renderGrid();
    } catch (e) {
      err.textContent = `Không tạo được: ${e.message}`;
    } finally {
      busy = false;
      aiBtn.textContent = "Tạo thumbnail AI";
      updateAi();
    }
  });

  card.append(
    el("div", { class: "g-actions" }, grabBtn,
      el("span", { class: "g-cost" }, "Tua video tới khung đẹp rồi bấm · miễn phí")),
    grid,
    el("div", { class: "g-form", style: "margin-top:16px" },
      el("label", { for: "t-aspect" }, "Khung", aspect),
      el("label", { for: "t-title" }, "Chữ trên ảnh", titleText),
      el("label", { class: "full", for: "t-style" }, "Phong cách", style),
    ),
    el("div", { class: "g-actions" }, aiBtn,
      el("span", { class: "g-cost" },
        `Dựa trên khung đang chọn · ${options.thumb_model} qua PiAPI · $${Number(options.thumb_cost_usd).toFixed(2)} mỗi ảnh`)),
    err,
  );
  renderGrid();
  updateAi();
  return card;
}

// ---------------------------------------------------------------- boot

async function load({ keepDetail = false } = {}) {
  [videos, options, channels] = await Promise.all([
    getJSON("/api/videos"), getJSON("/api/social/options"), getJSON("/api/channels").catch(() => [])]);
  if (!videos.some((v) => keyOf(v) === selectedKey)) selectedKey = videos[0] ? keyOf(videos[0]) : null;
  renderList();
  if (!keepDetail || !detailEl.querySelector("video")) renderDetail();
}

// ---------------------------------------------------------------- upload

const dropEl = document.getElementById("drop");
const uploadInput = document.getElementById("upload-input");
const uploadStatus = document.getElementById("upload-status");
const uploadProgress = document.getElementById("upload-progress");
const UPLOAD_HINT = uploadStatus.textContent;
const UPLOAD_EXT = /\.(mp4|mov|webm)$/i;
let uploading = false;

function setUploadStatus(text, isErr = false) {
  uploadStatus.textContent = text;
  uploadStatus.classList.toggle("err", isErr);
}

function uploadFile(file) {
  if (uploading || !file) return;
  if (!UPLOAD_EXT.test(file.name)) { setUploadStatus("Chỉ nhận file .mp4, .mov hoặc .webm", true); return; }
  if (file.size > 1024 ** 3) { setUploadStatus("Video lớn hơn 1 GB", true); return; }
  uploading = true;
  uploadProgress.hidden = false;
  const bar = uploadProgress.firstElementChild;
  bar.style.width = "0";
  setUploadStatus(`Đang tải ${file.name}…`);

  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/social-upload");
  xhr.setRequestHeader("X-Backlot-Action", "upload");
  xhr.setRequestHeader("X-File-Name", encodeURIComponent(file.name));
  xhr.setRequestHeader("Content-Type", "application/octet-stream");
  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    const pct = Math.round((e.loaded / e.total) * 100);
    bar.style.width = `${pct}%`;
    setUploadStatus(`Đang tải ${file.name}… ${pct}%`);
  };
  const done = () => { uploading = false; uploadProgress.hidden = true; uploadInput.value = ""; };
  xhr.onerror = () => { done(); setUploadStatus("Mất kết nối khi tải lên", true); };
  xhr.onload = async () => {
    done();
    let body = {};
    try { body = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
    if (xhr.status >= 400) { setUploadStatus(`Không tải lên được: ${body.detail || `HTTP ${xhr.status}`}`, true); return; }
    setUploadStatus(`Đã tải lên ${file.name}. Chọn nền tảng rồi bấm “Tạo caption”.`);
    selectedKey = `${body.project_id}/${body.path}`;
    storageSet(SEL_KEY, selectedKey);
    searchEl.value = "";
    await load().catch((e) => setUploadStatus(`Lỗi tải danh sách: ${e.message}`, true));
    setTimeout(() => { if (!uploading) setUploadStatus(UPLOAD_HINT); }, 6000);
  };
  xhr.send(file);
}

uploadInput.addEventListener("change", () => uploadFile(uploadInput.files[0]));
for (const ev of ["dragenter", "dragover"]) {
  dropEl.addEventListener(ev, (e) => { e.preventDefault(); dropEl.classList.add("over"); });
}
for (const ev of ["dragleave", "drop"]) {
  dropEl.addEventListener(ev, (e) => { e.preventDefault(); dropEl.classList.remove("over"); });
}
dropEl.addEventListener("drop", (e) => uploadFile(e.dataTransfer?.files?.[0]));

searchEl.addEventListener("input", renderList);
load().catch((e) => { detailEl.textContent = `Lỗi tải danh sách: ${e.message}`; });
// New renders appear live; don't rebuild the open detail (would stop playback).
subscribe("/api/library/events", () => { if (!busy) load({ keepDetail: true }).catch(console.error); });
