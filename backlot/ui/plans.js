// Plans block on the Backlog page: one card per content plan (backlog/plans/*/plan.json)
// with a time bar, view progress, episode timeline and the markdown schedule.

import { el, getJSON } from "/ui/lib.js";
import { renderMarkdown } from "/ui/markdown.js";

const OPEN_KEY = "backlot.plans.open";
const root = document.getElementById("plans");
const WEEKDAYS = ["CN", "T2", "T3", "T4", "T5", "T6", "T7"];
const DAY = 86400000;

function storageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function storageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* ignore */ } }

const parseDate = (s) => { const [y, m, d] = String(s || "").split("-").map(Number); return y ? new Date(y, m - 1, d) : null; };
const today = () => { const n = new Date(); return new Date(n.getFullYear(), n.getMonth(), n.getDate()); };
const fmtDay = (d) => `${WEEKDAYS[d.getDay()]} ${d.getDate()}/${d.getMonth() + 1}`;
const fmtViews = (n) => {
  const v = Number(n) || 0;
  if (v >= 1e6) return `${(v / 1e6).toFixed(v % 1e6 ? 1 : 0)}M`;
  if (v >= 1e3) return `${Math.round(v / 1e3)}K`;
  return String(v);
};

function episodeStatus(ep, now) {
  const post = parseDate(ep.post_date);
  if (ep.posted) return { cls: "done", label: ep.views != null ? `Đã đăng · ${fmtViews(ep.views)} view` : "Đã đăng" };
  if (ep.awaiting_human) return { cls: "wait", label: `Chờ duyệt · ${ep.active_stage}` };
  if (ep.active_stage) return { cls: "run", label: `Đang làm · ${ep.active_stage}` };
  if (ep.project_exists && ep.stage_total && ep.completed_count === ep.stage_total) return { cls: "ready", label: "Sẵn sàng đăng" };
  if (ep.project_exists) return { cls: "run", label: `${ep.completed_count || 0}/${ep.stage_total || "?"} giai đoạn` };
  if (post && post < now) return { cls: "late", label: "Trễ lịch" };
  return { cls: "todo", label: ep.optional ? "Dự phòng" : "Chưa bắt đầu" };
}

function renderPlan(plan) {
  const now = today();
  const start = parseDate(plan.start);
  const end = parseDate(plan.end);
  const total = start && end ? Math.max(1, (end - start) / DAY) : 1;
  const elapsed = start ? Math.min(total, Math.max(0, (now - start) / DAY)) : 0;
  const daysLeft = end ? Math.max(0, Math.round((end - now) / DAY)) : null;
  const target = Number(plan.target_views) || 0;
  const views = Number(plan.views) || 0;
  const pct = target ? Math.min(100, (views / target) * 100) : 0;
  const nextMs = (plan.milestones || []).find((m) => parseDate(m.date) >= now);

  const timeline = el("ol", { class: "pl-eps" });
  const next = plan.episodes.find((e) => !e.posted && parseDate(e.post_date) >= now);
  for (const ep of plan.episodes) {
    const st = episodeStatus(ep, now);
    const post = parseDate(ep.post_date);
    const body = [
      el("div", { class: "pl-ep-top" },
        el("span", { class: "pl-ep-id" }, ep.id),
        post ? el("span", { class: "pl-ep-date" }, fmtDay(post)) : null),
      el("div", { class: "pl-ep-title" }, ep.title),
      el("span", { class: `pl-st pl-st-${st.cls}` }, st.label),
    ];
    const attrs = { class: `pl-ep${ep === next ? " is-next" : ""}${ep.optional ? " is-optional" : ""}` };
    timeline.append(el("li", attrs,
      ep.project_exists
        ? el("a", { href: `/p/${encodeURIComponent(ep.project)}`, class: "pl-ep-link", title: `Mở dự án ${ep.project}` }, body)
        : el("div", { class: "pl-ep-link" }, body)));
  }

  const card = el("article", { class: "pl-card", "aria-label": plan.title });
  card.append(
    el("div", { class: "pl-head" },
      el("div", {},
        el("div", { class: "pl-kicker" }, "Kế hoạch"),
        el("h2", {}, plan.title),
        el("div", { class: "pl-sub" }, [plan.account, start && end ? `${fmtDay(start)} → ${fmtDay(end)}` : null].filter(Boolean).join(" · "))),
      el("div", { class: "pl-stats" },
        daysLeft != null ? el("div", { class: "pl-stat" }, el("b", {}, String(daysLeft)), el("span", {}, "ngày còn lại")) : null,
        el("div", { class: "pl-stat" }, el("b", {}, `${fmtViews(views)} / ${fmtViews(target)}`), el("span", {}, "view")),
        nextMs ? el("div", { class: "pl-stat" }, el("b", {}, fmtViews(nextMs.views)), el("span", {}, `mốc ${fmtDay(parseDate(nextMs.date))}`)) : null)),
    el("div", { class: "pl-bars" },
      el("div", { class: "pl-bar", title: `Đã qua ${Math.round(elapsed)}/${Math.round(total)} ngày` },
        el("span", { class: "pl-bar-label" }, "Thời gian"),
        el("div", { class: "pl-track" }, el("div", { class: "pl-fill time", style: `width:${(elapsed / total) * 100}%` }))),
      el("div", { class: "pl-bar", title: `${views.toLocaleString("vi-VN")} / ${target.toLocaleString("vi-VN")} view` },
        el("span", { class: "pl-bar-label" }, "View"),
        el("div", { class: "pl-track" }, el("div", { class: "pl-fill views", style: `width:${pct}%` })))),
    timeline,
  );
  if (plan.views_updated) card.append(el("p", { class: "pl-note" }, `View cập nhật ngày ${plan.views_updated.split("-").reverse().join("/")}.`));

  if (plan.schedule_markdown) {
    const key = `${OPEN_KEY}.${plan.id}`;
    const det = el("details", { class: "pl-details" });
    if (storageGet(key) === "1") det.open = true;
    det.addEventListener("toggle", () => storageSet(key, det.open ? "1" : "0"));
    const md = el("div", { class: "bl-script pl-md" });
    md.append(renderMarkdown(plan.schedule_markdown));
    det.append(el("summary", {}, "Lịch chi tiết"), md);
    card.append(det);
  }
  return card;
}

async function load() {
  if (!root) return;
  try {
    const { plans } = await getJSON("/api/plans");
    root.innerHTML = "";
    root.hidden = !plans.length;
    for (const p of plans) root.append(renderPlan(p));
  } catch (e) {
    root.hidden = false;
    root.innerHTML = "";
    root.append(el("div", { class: "g-error", role: "alert" }, `Không tải được kế hoạch: ${e.message}`));
  }
}

load();
