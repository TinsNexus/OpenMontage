// Shared helpers for the Backlot UI.

export async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  return res.json();
}

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child == null) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function fmtDuration(seconds) {
  const n = Number(seconds);
  if (seconds == null || !Number.isFinite(n)) return "";
  const s = Math.max(0, Math.round(n));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

export function fmtMoney(v) {
  const n = Number(v);
  if (v == null || !Number.isFinite(n)) return "—";
  return `$${n.toFixed(2)}`;
}

export function fmtAgo(epochSeconds) {
  if (!epochSeconds) return "";
  const diff = Date.now() / 1000 - epochSeconds;
  if (diff < 90) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

export function fmtClock(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return "";
  }
}

export function mediaURL(projectId, relPath) {
  return `/media/${encodeURIComponent(projectId)}/${relPath.split("/").map(encodeURIComponent).join("/")}`;
}

// Downscaled cached JPEG for images (full media only in players/lightbox).
export function thumbURL(projectId, relPath, w = 640) {
  return `/thumb/${encodeURIComponent(projectId)}/${relPath.split("/").map(encodeURIComponent).join("/")}?w=${w}`;
}

// Subscribe to a server-sent change feed; call onChange (debounced) per burst.
export function subscribe(url, onChange) {
  let timer = null;
  const source = new EventSource(url);
  source.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data);
      if (data.type !== "change") return;
    } catch {
      return;
    }
    clearTimeout(timer);
    timer = setTimeout(onChange, 250);
  };
  source.onerror = () => { /* EventSource auto-reconnects */ };
  return source;
}

// Deterministic pseudo-waveform bars (seeded by a string).
export function waveBars(container, seedStr, count = 26, maxH = 14) {
  let seed = 0;
  for (const c of seedStr || "wave") seed = (seed * 31 + c.charCodeAt(0)) % 2147483647;
  seed = seed || 7;
  container.innerHTML = "";
  for (let i = 0; i < count; i++) {
    seed = (seed * 16807) % 2147483647;
    const h = 3 + ((seed % 100) / 100) * maxH * (0.55 + 0.45 * Math.sin(i / 5));
    const bar = document.createElement("i");
    bar.style.height = `${Math.max(3, h)}px`;
    container.append(bar);
  }
}

export const STAGE_ICONS = {
  completed: "✓",
  in_progress: "◉",
  awaiting_human: "◈",
  failed: "✕",
};

// Copy text to the clipboard; the button briefly reads "Đã copy".
export async function copyText(text, btn) {
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

export function copyBtn(getText, label = "Copy") {
  const b = el("button", { class: "g-btn", type: "button" }, label);
  b.addEventListener("click", () => copyText(getText(), b));
  return b;
}

// Toggle chips choosing which products a caption promotes. Returns {node, value()}.
export function productPicker(all, initial) {
  const chosen = new Set(initial || []);
  const node = el("div", { class: "g-chips", style: "gap:6px" });
  const draw = () => {
    node.innerHTML = "";
    if (!all.length) {
      node.append(el("span", { class: "g-cost" }, "Chưa có sản phẩm — thêm ở trang ", el("a", { href: "/products" }, "Products"), "."));
      return;
    }
    for (const p of all) {
      const on = chosen.has(p.id);
      node.append(el("button", { type: "button", class: `g-btn${on ? " done" : ""}`, "aria-pressed": on ? "true" : "false",
        title: p.affiliate_url || "chưa có link", onclick: () => { on ? chosen.delete(p.id) : chosen.add(p.id); draw(); } },
        `${on ? "✓ " : ""}🛒 ${p.name}${p.affiliate_url ? "" : " (chưa có link)"}`));
    }
  };
  draw();
  return { node, value: () => [...chosen] };
}

// Shopping-cart lines saved with a caption (appended verbatim by the server).
export function cartView(s) {
  const links = (s.products || []).filter((p) => p.url);
  if (!s.cart && !links.length) return null;
  return el("div", {},
    el("h4", {}, "Link giỏ hàng (thêm nguyên văn, AI không sửa)"),
    s.cart ? el("div", { class: "g-row" }, el("div", { class: "g-title", style: "white-space:pre-wrap" }, s.cart),
      copyBtn(() => s.cart)) : null,
    links.map((p) => el("div", { class: "g-row", style: "margin-top:6px" },
      el("div", { class: "g-sub" }, `${p.name}: ${p.url}`), copyBtn(() => p.url, "Copy link"))));
}

// Warn when the server process runs older Python code than what is on disk
// (new pages then 404 until it restarts). Runs once per page load.
(async function staleServerBanner() {
  try {
    const res = await fetch("/api/health", { cache: "no-store" });
    const info = await res.json();
    if (!info || !info.stale || document.getElementById("stale-banner")) return;
    const bar = el("div", {
      id: "stale-banner", role: "status",
      style: "position:sticky;top:0;z-index:100;background:var(--amber-dim);color:var(--text);"
        + "border-bottom:1px solid var(--amber);padding:8px 16px;font-size:13px;line-height:1.5",
    },
      "Backlot đang chạy code cũ nên trang mới có thể chưa mở được. Khởi động lại bằng: ",
      el("code", { style: "font-family:var(--mono)" }, "python -m backlot restart"),
      " rồi tải lại trang.");
    document.body.prepend(bar);
  } catch { /* health check is best-effort */ }
})();
