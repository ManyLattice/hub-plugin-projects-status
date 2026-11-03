// Вид «Jira»: доска Jira по колонкам со строкой хаба на каждой карточке (кто ведёт, что сейчас, чего ждёт).
// Данные Jira и задачи хаба по ключу - процесс плагина (/jira), живые сессии - снимок ядра. Плагин в Jira не пишет.
import * as J from "./jirapure.js";

let c = null;   // от main.js: hub, el, data(), redraw(), askBox, rich, title, goSession, hubName, leads
let jd = null, jerr = "", loading = false;
let sprint = null, proj = "all", mine = false, col = null, unfold = false;
let panel = null, gear = null;
const opened = new Set(), inputs = new Map();
const el = (...a) => c.hub.el(...a);
const port = () => Number(location.port || 80) + 12;
const base = () => `http://${location.hostname}:${port()}`;

export function init(ctx) { c = ctx; }
export async function load() {
  if (loading) return;
  loading = true;
  try {
    const r = await fetch(`${base()}/jira`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    jd = await r.json();
    jerr = "";
  } catch (e) {
    jerr = `Процесс плагина не отвечает (${e.message})`;
  }
  loading = false;
  c.redraw();
}
async function call(path, body) {
  try {
    const r = await fetch(`${base()}${path}`, { method: "POST", body: JSON.stringify(body) });
    return await r.json();
  } catch (e) {
    return { ok: false, error: `процесс плагина не отвечает (${e.message})` };
  }
}
export const busy = () => !!gear || [...inputs.values()].some((b) => b.node.contains(document.activeElement));
export const hide = () => { panel = gear = null; };

// --- время -------------------------------------------------------------------------------------------------------
const age = (ts) => {
  if (!ts) return "";
  const s = Math.max(0, Date.now() / 1000 - ts);
  return s < 90 ? "сейчас" : s < 3600 ? `${Math.round(s / 60)} мин` : s < 86400 ? `${Math.round(s / 3600)} ч` : `${Math.floor(s / 86400)} дн`;
};
const dm = (ts) => (ts ? new Date(ts * 1000).toLocaleDateString("ru", { day: "2-digit", month: "2-digit" }) : "");
const hm = (ts) => {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toDateString() === new Date().toDateString() ? d.toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit" }) : dm(ts);
};
const many = (n, one, few, lots) => { const t = n % 10, h = n % 100; return `${n} ${t === 1 && h !== 11 ? one : t >= 2 && t <= 4 && (h < 12 || h > 14) ? few : lots}`; };
const btn = (cls, text, fn, title) => { const b = el("button", cls, text); b.type = "button"; if (title) b.title = title; b.addEventListener("click", (e) => { e.stopPropagation(); fn(e); }); return b; };

// --- разбор: строка хаба и проект каждой задачи -------------------------------------------------------------------
function model(snap) {
  const data = c.data() || { projects: [] }, j = (jd || {}).jira || {}, hub = (jd || {}).hub || {};
  const index = J.projectIndex(data.projects), lines = new Map(), pj = new Map(), why = new Map();
  const lineOf = (key) => {
    if (!lines.has(key)) lines.set(key, J.hubLine(hub[key], snap, J.hintsOf(key, data.projects, snap)));
    return lines.get(key);
  };
  const issues = (j.issues || []).map((it) => {
    const line = lineOf(it.key);
    if (!pj.has(it.key)) { const l = J.projectLink(it, index, line, snap); pj.set(it.key, l ? l.name : null); why.set(it.key, l ? l.by : ""); }
    return it;
  });
  return { data, j, hub, issues, lineOf, projOf: (k) => pj.get(k), whyOf: (k) => why.get(k), index };
}
const projName = (name, m) => { if (!name) return "Общие"; const p = m.data.projects.find((x) => x.name === name); return p ? c.title(p) : name; };

// --- куски ---------------------------------------------------------------------------------------------------------
function typeIcon(t) { const i = el("span", `jty ${t || "task"}`); i.setAttribute("aria-hidden", "true"); return i; }
// строка хаба (макет v2): шапка - состояние, сессия, возраст, метки; ниже - текст; ниже - «Ответить»
function hubLineNode(line, it, opts = {}) {
  const box = el("div", `jhl ${line.state}`), hh = el("div", "hh");
  hh.append(el("i"), el("span", "st", J.STATES[line.state]));
  let text = "";
  if (line.state === "none") text = line.hint || "";
  else {
    hh.append(el("code", "who", line.session));
    if (line.under) hh.append(el("span", "ag", `под ${line.under}`));
    hh.append(el("span", "ag", line.state === "done" ? hm(line.ts) : line.state === "work" ? `${age(line.ts)} назад`.replace("сейчас назад", "только что") : age(line.ts)));
    if (line.state === "done" && it && !it.status_last) hh.append(el("span", "gap", `в Jira ещё «${it.status.name}»`));
    text = line.state === "you" ? `«${line.text}»` : line.text;
  }
  const st = it ? J.staleDays(it, (jd.hub || {})[it.key]) : 0;
  if (st) hh.append(el("span", "jstale", `нет движения ${st} дн`));
  box.append(hh);
  if (text) box.append(c.rich("div", "ht", text));
  if (line.state === "you" && opts.answer) { const b = el("div", "hb"); b.append(btn("btn-s jred", "Ответить", () => openPanel(it.key))); box.append(b); }
  return box;
}
function codeLine(key, m) {
  const x = J.codeOf(key, m.data.projects), parts = [];
  if (x.branches[0]) parts.push(el("span", "mono", x.branches[0]));
  for (const p of x.prs.slice(0, 1)) {
    const a = el("a", "ext", `${p.kind === "gitlab" ? "MR !" : "PR #"}${p.n} открыт`); a.href = p.url; a.target = "_blank"; a.rel = "noopener";
    a.addEventListener("click", (e) => e.stopPropagation());
    parts.push(a);
  }
  if (!parts.length) return null;
  const d = el("div", "jcode seps");
  parts.forEach((p, i) => { if (i) p.classList.add("sep"); d.append(p); });
  return d;
}
function foot(it, m) {
  const f = el("div", "jfoot"), code = codeLine(it.key, m), cm = (it.comments || [])[0];
  if (code) f.append(code);
  if (cm) f.append(el("div", "jcm", `${cm.author}, ${age(cm.ts)}: ${cm.text}`));
  if (it.since) f.append(el("div", null, `в колонке с ${dm(it.since)}`));
  return f.childNodes.length ? f : null;
}
function meta(it, m) {
  const l1 = el("div", "jl1");
  l1.append(typeIcon(it.type), el("span", "jkey", it.key));
  if (it.sp != null) l1.append(el("span", "jsp", `${it.sp} SP`));
  const me = ((m.j.me || {}).id) || "";
  if (it.assignee && me && it.assignee.id !== me) l1.append(el("span", "jas", it.assignee.name));
  const pn = m.projOf(it.key), tag = el("span", "jtag", pn ? projName(pn, m) : ["Общие", ...(it.labels || []).slice(0, 1)].join(" · "));
  tag.title = tag.textContent;
  l1.append(tag);
  return l1;
}
function card(it, m, opts = {}) {
  const line = m.lineOf(it.key), box = el("div", `jca ${line.state}`);
  box.tabIndex = 0; box.setAttribute("role", "button"); box.dataset.key = it.key;
  box.addEventListener("click", () => openPanel(it.key));
  box.addEventListener("keydown", (e) => { if (e.key === "Enter") openPanel(it.key); });
  const l1 = meta(it, m);
  if (opts.status) { l1.querySelector(".jtag")?.remove(); l1.append(el("span", "jst", it.status.name)); }
  box.append(l1, el("div", "jtt", it.summary));
  const band = el("div", "jband");
  band.append(hubLineNode(line, it, { answer: true }));
  box.append(band);
  const f = opts.foot === false ? null : foot(it, m);
  if (f) box.append(f);
  return box;
}
function mini(it, m) {
  const line = m.lineOf(it.key), r = el("button", `jmini ${line.state}`);
  r.type = "button"; r.dataset.key = it.key; r.title = `${it.key} ${it.summary}`;
  r.append(el("i"), el("span", "jkey", it.key), el("span", "t", it.summary));
  r.addEventListener("click", () => openPanel(it.key));
  return r;
}
function column(cl, m, narrow) {
  const box = el("section", "jcol" + (cl.last && !unfold ? " fold" : "") + (narrow === cl.name ? " sel" : ""));
  box.dataset.col = cl.name;
  const sp = cl.items.reduce((a, x) => a + (x.sp || 0), 0);
  const h = el("h3");
  h.append(el("span", "nm", cl.name), el("span", "n", String(cl.items.length)), el("span", "spx", sp ? `${sp} SP` : ""));
  box.append(h);
  if (cl.last) {
    box.title = unfold ? "Свернуть" : "Показать: сдвинутые сюда за 14 дн";
    h.classList.add("tog");
    (unfold ? h : box).addEventListener("click", () => { unfold = !unfold; c.redraw(); });
    if (!unfold) box.append(el("span", "fn", String(cl.items.length)), el("span", "fd", "за 14 дн"));
  }
  if (!cl.items.length) { box.append(el("div", "jnote", "пусто")); return box; }
  if (cl.items.length < J.COMPACT_FROM) { for (const it of cl.items) box.append(card(it, m)); return box; }
  box.append(el("div", "jnote", `${many(cl.items.length, "задача", "задачи", "задач")}: компактно, по строке хаба`));
  for (const g of J.compactGroups(cl.items, (it) => m.lineOf(it.key))) {
    const k = `${cl.name}:${g.state}`, on = opened.has(k);
    const sh = el("button", `jsub ${g.state}` + (g.folded ? (on ? " open" : " closed") : ""));
    sh.type = "button";
    sh.append(el("span", null, J.STATES[g.state]), el("span", "n", String(g.items.length)));
    if (g.folded) sh.addEventListener("click", () => { if (on) opened.delete(k); else opened.add(k); c.redraw(); });
    else sh.disabled = true;
    box.append(sh);
    if (g.folded && !on) continue;
    const lim = g.folded || on ? Infinity : g.shown;
    for (const it of g.items.slice(0, lim)) box.append(g.state === "you" ? card(it, m) : mini(it, m));
    if (g.items.length > lim) box.append(btn("jmore", `ещё ${g.items.length - lim}`, () => { opened.add(k); c.redraw(); }));
  }
  return box;
}

// --- шапка и фильтры -------------------------------------------------------------------------------------------------
function sumNode(m, shown, sprintName) {
  const n = J.summary(shown, (it) => m.lineOf(it.key)), s = el("div", "sum");
  const b = (x, cls) => el("b", cls, String(x));
  s.append(b(shown.length), ` ${many(shown.length, "задача", "задачи", "задач").replace(/^\d+ /, "")}` + (sprintName ? ` в ${sprintName}` : " на доске"));
  if (n.you) s.append(" · ", el("span", "r", `${n.you} ждут вас`));
  if (n.wait) s.append(` · ${n.wait} ждут других`);
  if (n.work) s.append(` · ${n.work} ${n.work === 1 ? "работает" : "работают"}`);
  if (n.none) s.append(` · ${n.none} в хабе не ${n.none === 1 ? "ведётся" : "ведутся"}`);
  return s;
}
function fresh(m) {
  const j = m.j, f = el("span", "jfresh" + (j.state === "ok" ? "" : " bad"));
  f.textContent = j.state === "ok" ? `Jira · ${age(j.at) === "сейчас" ? "только что" : age(j.at) + " назад"}`
    : j.state === "error" ? `Jira не ответила ${hm(j.failed)}` : "Jira не подключена";
  return f;
}
function gearBtn() {
  const g = btn("jgear", "⚙", () => openGear(), "Настройки Jira: адрес, email, токен, доска");
  g.setAttribute("aria-label", "Настройки Jira");
  return g;
}
function filters(m, shownProjects, waitMine) {
  const row = el("div", "jflt");
  const opts = J.sprintOptions(m.j.sprints);
  if (opts.length) {
    const lab = el("label", "jsel");
    lab.append(el("span", "k", "Спринт"));
    const s = el("select");
    for (const [v, t] of opts) { const o = el("option", null, t); o.value = v; s.append(o); }
    s.value = sprint; s.addEventListener("change", () => { sprint = s.value; col = null; c.redraw(); });
    lab.append(s);
    row.append(lab);
  }
  const chips = el("div", "jpj");
  chips.append(el("span", "k", "Проект"));
  const chip = (v, t) => { const x = btn("pchip", t, () => { proj = v; c.redraw(); }); x.setAttribute("aria-pressed", String(proj === v)); return x; };
  chips.append(chip("all", "Все"), ...shownProjects.map((p) => chip(p, projName(p, m))), chip("-", "Общие"));
  const ps = el("select", "jpj-s");
  for (const [v, t] of [["all", "Все проекты"], ...shownProjects.map((p) => [p, projName(p, m)]), ["-", "Общие"]]) { const o = el("option", null, t); o.value = v; ps.append(o); }
  ps.value = proj; ps.addEventListener("change", () => { proj = ps.value; c.redraw(); });
  ps.setAttribute("aria-label", "Проект");
  const me = btn("pchip jme", "Ждёт меня", () => { mine = !mine; c.redraw(); });
  me.append(el("span", "n", String(waitMine)));
  me.setAttribute("aria-pressed", String(mine));
  row.append(chips, ps, me, el("span", "ps-sp"), fresh(m), gearBtn());
  return row;
}
function waitBlock(list, m) {
  const box = el("div", "jwy");
  box.append(el("h3", null, `Ждёт вас · ${list.length}`));
  for (const it of list) {
    const line = m.lineOf(it.key), r = el("div", "jwr");
    const t = el("div", "t");
    t.append(el("b", null, it.summary), el("span", null, ` · ${line.session} · `), c.rich("span", null, `«${line.text}»`));
    r.append(el("span", "jkey", it.key), t, btn("btn-s jred", "Ответить", () => openPanel(it.key)));
    r.addEventListener("click", () => openPanel(it.key));
    box.append(r);
  }
  return box;
}

// --- состояния без доски -------------------------------------------------------------------------------------------
function skeleton() {
  const b = el("div", "jboard jskel");
  b.style.gridTemplateColumns = "repeat(4, minmax(0, 1fr)) 64px";
  for (let i = 0; i < 4; i++) { const cl = el("section", "jcol" + (i ? "" : " sel")); cl.append(el("h3", "sk"), el("div", "jca sk"), el("div", "jca sk"), ...(i % 2 ? [] : [el("div", "jca sk")])); b.append(cl); }
  b.append(el("section", "jcol fold sk"));
  return b;
}
function banner(title, text, action) {
  const b = el("div", "jban");
  const t = el("div", "t");
  t.append(el("b", null, title), el("div", null, text));
  b.append(el("span", "ic", "!"), t);
  if (action) b.append(action);
  return b;
}
function offline(m, snap) {
  // задачи хаба с ключом: видны и без Jira, без статуса и спринта
  const keys = Object.keys(m.hub).filter((k) => (m.hub[k] || []).some((t) => t.role === "lead"));
  const rows = keys.map((k) => ({ key: k, line: m.lineOf(k), t: J.pickLead(m.hub[k], J.openIds(snap)).lead }))
    .filter((x) => !mine || x.line.state === "you")
    .sort((a, b) => J.ORDER.indexOf(a.line.state) - J.ORDER.indexOf(b.line.state) || (b.t.at || 0) - (a.t.at || 0));
  const box = el("div", "jlist");
  const h = el("h3");
  h.append("Статус Jira неизвестен", el("span", "n", String(rows.length)));
  box.append(h);
  for (const x of rows.slice(0, 60)) {
    const r = el("div", `jrow ${x.line.state}`);
    const k1 = el("div", "k1"); k1.append(el("span", "jkey", x.key));
    const tt = el("div", "jtt", x.t.title);
    r.append(k1, tt, hubLineNode(x.line, null), el("div", "jcode mut", x.t.id));
    box.append(r);
  }
  if (rows.length > 60) box.append(el("div", "jnote", `ещё ${rows.length - 60}`));
  if (!rows.length) box.append(el("div", "jnote", "В записях задач хаба нет ключей этого проекта Jira"));
  return box;
}

// --- страница -------------------------------------------------------------------------------------------------------
export function page(snap, top, extra = []) {
  const box = el("div", "ps jv"), head = el("div", "ps-head");
  const sumSlot = top.querySelector(".sum");
  head.append(top);
  box.append(head, ...extra);
  if (!jd) {
    if (sumSlot) sumSlot.replaceChildren(jerr || "Загружаю доску Jira…");
    if (jerr) box.append(el("p", "err", jerr));
    box.append(skeleton());
    return box;
  }
  const m = model(snap), j = m.j;
  if (!jd.store || j.state === "nostore") {
    if (sumSlot) sumSlot.replaceChildren(`${many(Object.keys(m.hub).length, "задача", "задачи", "задач")} с ключом в хабе · Jira не подключена`);
    box.append(banner("Хранить токен негде", j.why || "На этой системе нет связки ключей macOS: токен Jira плагин хранит только в ней.", null), offline(m, snap));
    return box;
  }
  // токен не подходит (401/403) - доска на старый момент вводила бы в заблуждение; сбой сети - старая доска с пометкой
  if (j.state === "off" || (j.state === "error" && ([401, 403].includes(j.status) || !(j.issues || []).length))) {
    const n = Object.keys(m.hub).filter((k) => m.hub[k].some((t) => t.role === "lead")).length;
    if (sumSlot) { sumSlot.replaceChildren(el("b", null, String(n)), ` ${many(n, "задача", "задачи", "задач").replace(/^\d+ /, "")} с ключом в хабе · ${j.state === "off" ? "Jira не подключена" : "нет доступа к Jira"}`); }
    const go = btn("btn-s pr", j.state === "off" ? "Подключить Jira" : "Проверить доступ", () => openGear());
    const why = j.state === "off" ? (j.why === "не выбрана доска" ? "Выберите доску в настройках." : "Вставьте свой токен только на чтение в настройках.")
      : `Jira ответила с ошибкой: ${j.why}.`;
    box.append(banner(j.state === "off" ? "Jira не подключена" : j.status ? "Нет доступа к Jira" : "Jira не отвечает", `${why} Пока видны только задачи с ключом из хаба, без статуса и спринта Jira.`, go));
    const fl = el("div", "jflt");
    const me = btn("pchip jme", "Ждёт меня", () => { mine = !mine; c.redraw(); }); me.setAttribute("aria-pressed", String(mine));
    fl.append(el("span", "mut", `Задачи из хаба`), me, el("span", "ps-sp"), fresh(m), gearBtn());
    box.append(fl, offline(m, snap));
    return box;
  }
  if (sprint === null) sprint = (J.sprintOptions(j.sprints)[0] || ["all"])[0];
  const lastIds = new Set(((j.columns || []).slice(-1)[0] || { statuses: [] }).statuses);
  for (const it of m.issues) it.status_last = lastIds.has(it.status.id);
  const inS = m.issues.filter((it) => J.inSprint(it, sprint));
  const projects = [...new Set(inS.map((it) => m.projOf(it.key)).filter(Boolean))].sort((a, b) => projName(a, m).localeCompare(projName(b, m)));
  if (proj !== "all" && proj !== "-" && !projects.includes(proj)) proj = "all";
  const inP = inS.filter((it) => proj === "all" || (proj === "-" ? !m.projOf(it.key) : m.projOf(it.key) === proj));
  const waitMine = inP.filter((it) => m.lineOf(it.key).state === "you");
  const shown = mine ? waitMine : inP;
  const sname = (J.sprintOptions(j.sprints).find(([v]) => v === sprint) || [, ""])[1].replace(/ · .*$/, "");
  if (sumSlot) sumSlot.replaceWith(sumNode(m, shown, sprint === "all" || sprint === "none" ? "" : sname));
  box.append(filters(m, projects, waitMine.length));
  if (j.state === "error") box.append(el("p", "jwarn", `Jira не ответила в ${hm(j.failed)}: ${j.why}. Доска - на ${hm(j.at)}.`));
  if (waitMine.length && !mine) box.append(waitBlock(waitMine, m));
  const cols = J.columns(j.columns, shown);
  if (!shown.length) {
    const e = el("div", "jempty");
    e.append(el("b", null, inS.length ? "Фильтр ничего не нашёл" : "В спринте нет задач"),
      el("div", "mut", inS.length ? "Снимите фильтр проекта или «Ждёт меня»." : "Выберите другой спринт или «Все задачи доски»."));
    if (inS.length) e.append(btn("btn-s", "Сбросить фильтры", () => { proj = "all"; mine = false; c.redraw(); }));
    else e.append(btn("btn-s", "Все задачи доски", () => { sprint = "all"; c.redraw(); }));
    box.append(e);
    return box;
  }
  // узкий экран: колонки - чипами, видна одна
  const pickCol = cols.find((x) => x.name === col) ? col
    : (cols.find((x) => x.items.some((it) => m.lineOf(it.key).state === "you")) || [...cols].filter((x) => !x.last).sort((a, b) => b.items.length - a.items.length)[0] || cols[0]).name;
  const cc = el("div", "jcc");
  for (const cl of cols) {
    const x = btn("pchip", cl.name, () => { col = cl.name; c.redraw(); });
    x.append(el("span", "n", String(cl.items.length)));
    x.setAttribute("aria-pressed", String(cl.name === pickCol));
    cc.append(x);
  }
  box.append(cc);
  const board = el("div", "jboard");
  const n = cols.filter((x) => !x.last || unfold).length;
  board.style.gridTemplateColumns = `repeat(${n}, minmax(0, 1fr))` + (unfold ? "" : " 64px");
  for (const cl of cols) board.append(column(cl, m, pickCol));
  box.append(board);
  return box;
}

// --- блок «Jira» в карточке проекта: счётчики по колонкам, задачи активного спринта, переход на доску ---------------
export function toBoard(name, opts = {}) {
  proj = name; mine = false; col = null;
  if (opts.sprint) sprint = opts.sprint;
  if (opts.done) { unfold = true; col = (((jd || {}).jira || {}).columns || []).slice(-1).map((x) => x.name)[0] || null; }
}
export function projectBlock(snap, p, cls) {
  if (!jd || ((jd.jira || {}).state !== "ok" && !((jd.jira || {}).issues || []).length)) return null;
  const m = model(snap), j = m.j, mine_ = m.issues.filter((it) => m.projOf(it.key) === p.name);
  if (!mine_.length) return null;
  const lastIds = new Set(((j.columns || []).slice(-1)[0] || { statuses: [] }).statuses);
  for (const it of mine_) it.status_last = lastIds.has(it.status.id);
  const hasSprints = !!(j.sprints || []).length, act = mine_.filter((it) => !hasSprints || J.inSprint(it, "active"));
  const box = el("div", `box jpb ${cls}`), h = el("h3");
  const keys = [...new Set(mine_.map((it) => it.key.split("-")[0]))].join(", ");
  h.append(`Jira · ${keys}`, el("span", "ps-sp"), btn("jlink", "На доске", () => c.toBoard(p.name)));
  const sub = el("div", "jpb-sub");
  const whys = [...new Set(mine_.map((it) => m.whyOf(it.key)).filter(Boolean))];
  sub.append(el("span", null, whys.slice(0, 2).join(", ")));
  const sp = (j.sprints || []).find((x) => x.state === "active");
  if (sp) sub.append(el("span", null, sp.name));
  sub.append(btn("jlink", "Привязка", () => c.editJira(p), "Метки и эпики Jira этого проекта (поле памяти «Jira»)"));
  const cols = J.columns(j.columns, act), st = el("div", "jpb-st");
  st.style.gridTemplateColumns = `repeat(${cols.length}, minmax(0, 1fr))`;
  const short = (n) => n.replace(/^Контроль качества$/, "Контроль");
  for (const cl of cols) {
    const x = el("span", cl.items.length ? "" : "z");
    x.append(el("b", null, String(cl.items.length)), el("span", null, short(cl.name)));
    st.append(x);
  }
  const list = el("div", "jpb-l");
  const live = act.filter((it) => !it.status_last).sort((a, b) => J.ORDER.indexOf(m.lineOf(a.key).state) - J.ORDER.indexOf(m.lineOf(b.key).state));
  for (const it of live.slice(0, 8)) list.append(card(it, m, { foot: false, status: true }));
  if (live.length > 8) list.append(btn("jmore", `ещё ${live.length - 8} на доске`, () => c.toBoard(p.name)));
  if (!live.length) list.append(el("div", "hint", hasSprints ? "В активном спринте открытых задач нет" : "Открытых задач нет"));
  const more = el("div", "jpb-more");
  const out = hasSprints ? mine_.filter((it) => !J.inSprint(it, "active") && !it.status_last).length : 0;
  const done = mine_.filter((it) => it.status_last).length;
  if (out) more.append(btn("jlink", `Вне спринта · ${out}`, () => c.toBoard(p.name, { sprint: "all" })));
  more.append(el("span", "ps-sp"));
  if (done) more.append(btn("jlink", `Готово за 14 дн · ${done}`, () => c.toBoard(p.name, { done: true, sprint: "all" })));
  box.append(h, sub, st, list);
  if (out || done) box.append(more);
  return box;
}

// --- окно задачи (слой на body) ------------------------------------------------------------------------------------
function openPanel(key) { panel = { key, to: null }; c.redraw(); }
const closePanel = () => { panel = null; c.redraw(); };
function addressees(snap, it, line, m) {
  const out = [], by = new Map((snap.sessions || []).map((s) => [s.name, s]));
  const add = (name, why) => { if (name && by.has(name) && !out.some((x) => x[0] === name)) out.push([name, why]); };
  if (line.task && line.open) add(line.session, "ведёт задачу");
  add(line.under, "ведущий исполнителя");
  const pn = m.projOf(it.key), p = pn && m.data.projects.find((x) => x.name === pn);
  if (p) for (const s of c.leads(snap, p)) add(s.name, `направление ${projName(pn, m)}`);
  if (line.task) add(line.session, "вёл задачу");
  add("jira", "агент Jira");
  add(c.hubName(snap), "хаб решит сам");
  return out;
}
function panelNodes(snap) {
  const m = model(snap), it = m.issues.find((x) => x.key === panel.key);
  if (!it) { panel = null; return []; }
  const line = m.lineOf(it.key), back = el("div", "jback"), box = el("aside", "jpanel");
  box.setAttribute("role", "dialog"); box.setAttribute("aria-label", `${it.key} ${it.summary}`);
  back.addEventListener("click", (e) => { if (e.target === back) closePanel(); });
  back.addEventListener("keydown", (e) => { if (e.key === "Escape") closePanel(); });
  const head = el("div", "jp-head");
  const l1 = meta(it, m);
  l1.insertBefore(el("span", "jst", it.status.name), l1.querySelector(".jtag"));
  const x = btn("td-x", "✕", closePanel); x.setAttribute("aria-label", "Закрыть");
  head.append(l1, x);
  const scroll = el("div", "jp-body");
  scroll.append(el("h2", "jtt", it.summary), hubLineNode(line, it));
  if (line.card && line.card.asks) {
    for (const a of line.card.asks) {
      const q = el("div", "jask");
      const qh = el("div", "qh");
      qh.append(el("b", null, `${line.card.session} спрашивает`), el("span", null, age(a.since || line.ts)));
      q.append(qh, c.askBox(line.card.session, a));
      scroll.append(q);
    }
  } else if (line.state === "you") {
    scroll.append(btn("btn-s", `В сессию ${line.session}`, () => c.goSession(line.session)));
  }
  const dl = el("dl", "jkv");
  const row = (k, ...v) => { const d = el("dd"); d.append(...v); dl.append(el("dt", null, k), d); };
  if (line.task) {
    const ses = el("span"); ses.append(el("code", "who", line.session));
    if (line.under) ses.append(` · под ${line.under}`);
    row("Сессия", ses);
    const t = el("span");
    t.append(el("code", "who", line.task.id), line.open ? " открыта" : line.task.handed ? " сдана" : " закрыта");
    if (line.others.length) t.append(" · ещё ", ...line.others.slice(0, 4).flatMap((o, i) => [i ? ", " : "", el("code", "who", o.id)]));
    row("Задача хаба", t);
  } else {
    row("Хаб", el("span", "mut", line.hint || "задач хаба с этим ключом нет"));
  }
  const code = codeLine(it.key, m);
  if (code) row("Ветка, MR", code);
  const me = ((m.j.me || {}).id) || "";
  row("Jira", el("span", null, [it.assignee ? (it.assignee.id === me ? "исполнитель вы" : `исполнитель ${it.assignee.name}`) : "без исполнителя",
    `«${it.status.name}» с ${dm(it.since)}`, it.sprint ? it.sprint.name : "вне спринта", it.epic && it.epic.key ? `эпик ${it.epic.key}` : ""].filter(Boolean).join(" · ")));
  scroll.append(dl);
  if (line.task && line.task.log.length) {
    scroll.append(el("h4", null, `Ход ${line.task.id}`));
    const lg = el("div", "jlog");
    for (const ln of [...line.task.log].reverse()) { const r = el("div"); r.append(el("span", "tm", hm(ln.ts)), c.rich("span", null, `${ln.who}: ${ln.text}`)); lg.append(r); }
    scroll.append(lg);
  }
  if (line.mentions.length) scroll.append(el("div", "hint", `Упоминается: ${line.mentions.slice(0, 6).map((t) => t.id).join(", ")}`));
  if ((it.comments || []).length) {
    scroll.append(el("h4", null, "Комментарии Jira"));
    for (const cm of it.comments) { const d = el("div", "jcmt"); const h = el("div"); h.append(el("b", null, cm.author), " ", el("span", "mut", age(cm.ts))); d.append(h, c.rich("div", null, cm.text)); scroll.append(d); }
  }
  const links = el("div", "jlinks");
  const a = el("a", "btn-s", "Открыть в Jira"); a.href = it.url; a.target = "_blank"; a.rel = "noopener"; links.append(a);
  if (line.session) links.append(btn("btn-s", `Сессия ${line.session}`, () => c.goSession(line.session)));
  for (const p of J.codeOf(it.key, m.data.projects).prs) { const l = el("a", "btn-s", `${p.kind === "gitlab" ? "MR !" : "PR #"}${p.n}`); l.href = p.url; l.target = "_blank"; l.rel = "noopener"; links.append(l); }
  const to = addressees(snap, it, line, m);
  if (to.some(([n]) => n === "jira")) links.append(btn("btn-s", "Обновить статус в Jira", () => { panel.to = "jira"; c.redraw(); }));
  scroll.append(links);

  const pick = panel.to && to.some(([n]) => n === panel.to) ? panel.to : (to[0] || [c.hubName(snap)])[0];
  const bottom = el("div", "jp-foot"), who = el("label", "jto");
  who.append("Кому: ");
  const sel = el("select");
  for (const [n, w] of to) { const o = el("option", null, `${n} · ${w}`); o.value = n; sel.append(o); }
  sel.value = pick; sel.addEventListener("change", () => { panel.to = sel.value; c.redraw(); });
  who.append(sel);
  const ik = `${it.key}:${pick}`;
  if (!inputs.has(ik)) {
    inputs.set(ik, c.hub.input({ to: pick, key: `projects-status:jira:${ik}`, placeholder: pick === "jira" ? `Что сделать в Jira по ${it.key}…` : `Написать по ${it.key}…`,
      prefix: (w) => `[Jira ${it.key} «${it.summary}», статус «${it.status.name}»${line.task ? `; задача хаба ${line.task.id}, ведёт ${line.session}` : ""}] ${w}`,
      onSent: () => c.redraw() }));
  }
  bottom.append(who, inputs.get(ik).node);
  box.append(head, scroll, bottom);
  back.append(box);
  return [back];
}

// --- шестерёнка: адрес, email, токен, доска, проект; «Проверить» - те же запросы, что у процесса ------------------
function openGear() {
  const s = ((jd || {}).jira || {}).settings || {};
  gear = { url: s.url || ((c.hub.snapshot() || {}).jira || {}).url || "", email: s.email || "", token: "", board: s.board || "", board_name: s.board_name || "",
    project: s.project || "", boards: s.board ? [{ id: s.board, name: s.board_name || `доска ${s.board}` }] : [], res: null, msg: "", busy: false };
  c.redraw();
  setTimeout(() => document.querySelector(".jgear-dlg input")?.focus());
}
const form = () => ({ url: gear.url, email: gear.email, token: gear.token, board: gear.board, board_name: gear.board_name, project: gear.project });
async function check() {
  gear.busy = true; gear.msg = "Проверяю…"; gear.res = null; c.redraw();
  const r = await call("/jira/check", form());
  if (!gear) return;
  gear.busy = false;
  if (!r.ok) { gear.msg = r.error || "не вышло"; c.redraw(); return; }
  gear.res = r; gear.msg = "";
  if ((r.boards || []).length) {
    gear.boards = r.boards;
    if (!gear.board && r.boards.length === 1) { gear.board = r.boards[0].id; gear.board_name = r.boards[0].name; }
  }
  c.redraw();
}
async function save() {
  gear.busy = true; gear.msg = "Сохраняю…"; c.redraw();
  const r = await call("/jira/save", form());
  if (!gear) return;
  gear.busy = false;
  if (!r.ok) { gear.msg = r.error || "не вышло"; c.redraw(); return; }
  gear = null; jd = null; c.redraw();
  setTimeout(load, 1500);
}
async function forget() {
  gear.busy = true; c.redraw();
  const r = await call("/jira/forget", {});
  gear = r.ok ? null : { ...gear, busy: false, msg: r.error || "не вышло" };
  jd = null; c.redraw(); setTimeout(load, 800);
}
function gearNodes() {
  const back = el("div", "jback center"), box = el("div", "jgear-dlg");
  box.setAttribute("role", "dialog"); box.setAttribute("aria-label", "Настройки Jira");
  back.addEventListener("click", (e) => { if (e.target === back) { gear = null; c.redraw(); } });
  box.addEventListener("keydown", (e) => { if (e.key === "Escape") { gear = null; c.redraw(); } });
  const head = el("div", "jp-head");
  head.append(el("b", null, "Jira: доступ только на чтение"), el("span", "ps-sp"), btn("td-x", "✕", () => { gear = null; c.redraw(); }));
  const has = !!(((jd || {}).jira || {}).settings || {}).email && ((jd || {}).jira || {}).state !== "off";
  const fld = (k, node, hint) => { const d = el("label", "fld"); d.append(el("span", "k", k), node); if (hint) d.append(el("span", "hint", hint)); return d; };
  const inp = (k, type, ph) => { const x = el("input"); x.type = type; x.value = gear[k]; x.placeholder = ph; x.autocomplete = "off"; x.spellcheck = false;
    x.addEventListener("input", () => { gear[k] = x.value; }); return x; };
  const tok = inp("token", "password", has ? "сохранён в связке ключей; новый - вставьте сюда" : "токен Atlassian");
  const bsel = el("select");
  bsel.append(Object.assign(el("option", null, gear.boards.length ? "выберите доску" : "сначала «Проверить»"), { value: "" }));
  for (const b of gear.boards) { const o = el("option", null, `${b.name}${b.project ? ` · ${b.project}` : ""}${b.type ? ` · ${b.type}` : ""}`); o.value = String(b.id); bsel.append(o); }
  bsel.value = String(gear.board || "");
  bsel.addEventListener("change", () => { gear.board = bsel.value; gear.board_name = (gear.boards.find((b) => String(b.id) === bsel.value) || {}).name || ""; });
  const body = el("div", "jg-body");
  body.append(
    fld("Адрес Jira", inp("url", "url", "https://<сайт>.atlassian.net")),
    fld("Email", inp("email", "email", "email аккаунта Atlassian")),
    fld("Токен", tok, "API token with scopes, только чтение - как создать, в README плагина. Хранится в связке ключей этого Mac."),
    fld("Проект", inp("project", "text", "ключ, например ABC (необязательно)"), "пусто - все задачи доски"),
    fld("Доска", bsel));
  if (gear.res) {
    const r = gear.res, ul = el("ul", "jcheck");
    if (r.me) ul.append(el("li", "ok", `Подключено как ${r.me.name}${r.via ? ` · ${r.via}` : ""}`));
    if (r.warn) ul.append(el("li", "skip", r.warn));
    for (const s of r.steps) {
      const li = el("li", s.ok ? "ok" : s.ok === null ? "skip" : "bad");
      li.append(el("b", null, s.label), s.ok ? " - есть" : ` - ${s.why}`);
      if (s.ok === false && s.need) li.append(el("div", "hint", `права: ${s.need}`));
      ul.append(li);
    }
    if (r.columns) ul.append(el("li", "ok", `Колонки: ${r.columns.join(" → ")}`));
    if (r.issues != null) ul.append(el("li", "ok", `Задач на доске сейчас: ${r.issues}`));
    if ((r.sprints || []).length) ul.append(el("li", "ok", `Активный спринт: ${r.sprints.join(", ")}`));
    body.append(ul);
  }
  if (gear.msg) body.append(el("div", gear.busy ? "hint" : "err", gear.msg));
  const acts = el("div", "acts");
  const ch = btn("btn-s", "Проверить", check); ch.disabled = gear.busy;
  const sv = btn("btn-s pr", "Сохранить", save); sv.disabled = gear.busy || !gear.board;
  sv.title = gear.board ? "" : "Сначала «Проверить» и выберите доску";
  acts.append(sv, ch);
  if (has) acts.append(el("span", "ps-sp"), btn("btn-s", "Отключить", forget, "Убрать токен из связки ключей"));
  box.append(head, body, acts);
  back.append(box);
  return [back];
}

export function layer(snap) {
  if (gear) return gearNodes();
  if (panel && jd) return panelNodes(snap);
  return [];
}
