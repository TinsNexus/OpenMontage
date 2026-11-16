import { copyBtn, el, getJSON, mediaURL, thumbURL } from "/ui/lib.js";
import { renderMarkdown } from "/ui/markdown.js";

const THEME_KEY = "backlot.theme";
const SEL_KEY = "backlot.formulas.selected";
const listEl = document.getElementById("list");
const detailEl = document.getElementById("detail");

function storageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function storageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* ignore */ } }
document.documentElement.dataset.theme = storageGet(THEME_KEY) === "light" ? "light" : "dark";

let formulas = [];
let selected = storageGet(SEL_KEY);

function card(title, ...children) {
  return el("div", { class: "g-card" }, el("div", { class: "g-card-h" }, el("h3", {}, title)), ...children);
}

function renderList() {
  document.getElementById("count").textContent = `${formulas.length} công thức`;
  document.getElementById("empty").style.display = formulas.length ? "none" : "block";
  listEl.innerHTML = "";
  for (const f of formulas) {
    const ex = f.example || {};
    listEl.append(el("button", {
      class: "g-item", type: "button", "aria-selected": f.id === selected ? "true" : "false",
      onclick: () => select(f.id),
    },
      el("div", { class: "g-thumb" },
        f.example_exists ? el("img", { src: thumbURL(ex.project, ex.video, 320), loading: "lazy", alt: "" }) : null),
      el("div", {},
        el("h3", {}, f.name),
        el("div", { class: "g-sub" }, f.file),
        el("div", { class: "g-chips" }, ...(f.specs || []).slice(0, 2).map((s) => el("span", { class: "chip" }, s))),
      ),
    ));
  }
}

function renderDetail() {
  const f = formulas.find((x) => x.id === selected);
  detailEl.innerHTML = "";
  if (!f) { detailEl.append(el("p", { class: "hint" }, "Chọn một công thức ở bên trái.")); return; }
  const ex = f.example || {};
  if (f.example_exists) {
    detailEl.append(el("div", { class: "g-player" },
      el("video", { controls: "", preload: "metadata", playsinline: "", src: mediaURL(ex.project, ex.video) })));
  } else if (ex.project) {
    detailEl.append(el("p", { class: "hint" }, `Chưa có video mẫu trên máy này (${ex.project}/${ex.video}).`));
  }
  detailEl.append(
    el("div", { class: "g-head" }, el("h2", {}, f.name),
      ex.label ? el("span", { class: "chip" }, `Mẫu: ${ex.label}`) : null),
    el("div", { class: "g-meta" }, ...(f.specs || []).map((s) => el("span", { class: "chip" }, s))),
    el("p", { style: "margin:0 0 18px;line-height:1.6;max-width:70ch" }, f.pitch || ""),
    card("Diễn biến", el("div", { style: "display:grid;gap:6px" },
      ...(f.timeline || []).map(([t, d]) => el("div", { style: "display:grid;grid-template-columns:5.5em 1fr;gap:10px" },
        el("span", { style: "font-family:var(--mono);color:var(--amber, #f0a83c)" }, t), el("span", {}, d))))),
    card("Bạn cần đưa", el("ul", { style: "margin:0;padding-left:1.2em;display:grid;gap:4px" },
      ...(f.inputs || []).map((s) => el("li", {}, s)))),
    card("Hợp với", el("ul", { style: "margin:0;padding-left:1.2em;display:grid;gap:4px" },
      ...(f.good_for || []).map((s) => el("li", {}, s)))),
  );
  const order = el("div", { class: "g-card" },
    el("div", { class: "g-card-h" }, el("h3", {}, "Gọi món"), el("div", { class: "spacer" }), copyBtn(() => f.order)),
    el("pre", { class: "g-prompt" }, f.order || ""));
  detailEl.append(order);
  if (f.markdown) {
    const body = el("div", {});
    body.append(renderMarkdown(f.markdown));
    detailEl.append(el("details", { class: "g-card" },
      el("summary", { style: "cursor:pointer;font-family:var(--mono);font-size:11px;letter-spacing:.1em;text-transform:uppercase" },
        `Công thức đầy đủ · ${f.file}`), body));
  }
}

function select(id) {
  selected = id;
  storageSet(SEL_KEY, id);
  renderList();
  renderDetail();
}

async function load() {
  formulas = await getJSON("/api/formulas");
  if (!formulas.some((f) => f.id === selected)) selected = formulas[0]?.id || null;
  renderList();
  renderDetail();
}

load().catch((err) => { detailEl.innerHTML = ""; detailEl.append(el("p", { class: "hint" }, `Không tải được công thức: ${err.message}`)); });
