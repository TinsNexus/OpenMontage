// Small, safe markdown renderer for Backlot (builds DOM nodes, never innerHTML).
//
// Supports headings, paragraphs, lists, blockquotes, tables, rules, **bold**,
// *italic*, `code`, [text](https://…) links and — when opts.wikilink is given —
// [[Page]] / [[Page|label]] wiki links rendered by that callback.

import { el } from "/ui/lib.js";

function inline(text, opts) {
  const out = [];
  const re = /(\[\[[^\]\n]+\]\]|\[[^\]\n]+\]\(https?:\/\/[^)\s]+\)|\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("[[")) {
      const [target, label] = tok.slice(2, -2).split("|").map((t) => t.trim());
      out.push(opts.wikilink ? opts.wikilink(target, label || target) : (label || target));
    } else if (tok.startsWith("[")) {
      const mm = tok.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
      out.push(el("a", { href: mm[2], target: "_blank", rel: "noopener" }, mm[1]));
    } else if (tok.startsWith("**")) out.push(el("strong", {}, inline(tok.slice(2, -2), opts)));
    else if (tok.startsWith("`")) out.push(el("code", {}, tok.slice(1, -1)));
    else out.push(el("em", {}, inline(tok.slice(1, -1), opts)));
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const cells = (row) => row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

export function renderMarkdown(src, opts = {}) {
  const root = document.createDocumentFragment();
  const lines = String(src || "").replace(/\r\n?/g, "\n").split("\n");
  const inl = (t) => inline(t, opts);
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) { root.append(el(`h${Math.min(h[1].length, 4)}`, {}, inl(h[2]))); i++; continue; }
    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) { root.append(el("hr")); i++; continue; }
    if (/^\s*>/.test(line)) {
      const quote = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) { quote.push(lines[i].replace(/^\s*>\s?/, "")); i++; }
      const bq = el("blockquote");
      bq.append(renderMarkdown(quote.join("\n"), opts));
      root.append(bq);
      continue;
    }
    if (/^\s*\|/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const head = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) { rows.push(cells(lines[i])); i++; }
      root.append(el("div", { class: "bl-table-wrap" }, el("table", {},
        el("thead", {}, el("tr", {}, head.map((c) => el("th", {}, inl(c))))),
        el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c) => el("td", {}, inl(c)))))),
      )));
      continue;
    }
    const listRe = /^\s*([-*]|\d+\.)\s+(.*)$/;
    if (listRe.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const list = el(ordered ? "ol" : "ul");
      while (i < lines.length && listRe.test(lines[i])) { list.append(el("li", {}, inl(lines[i].match(listRe)[2]))); i++; }
      root.append(list);
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|\s*>|\s*\||\s*([-*]|\d+\.)\s|\s*-{3,}\s*$)/.test(lines[i])) {
      para.push(lines[i].trim()); i++;
    }
    if (!para.length) { para.push(line.trim()); i++; }
    const p = el("p");
    para.forEach((t, n) => { if (n) p.append(el("br")); p.append(...inl(t)); });
    root.append(p);
  }
  return root;
}
