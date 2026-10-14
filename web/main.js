// «Статус проектов»: все проекты из hub projects - что ждёт вас, что идёт (этап и бэклог направления), что готово,
// что без направления; карточка проекта - его память (этап, цель, что дальше, решения) и живые данные.
// Данные - процесс плагина на порту «страница + 12»; правки памяти владельца - постом в канал плагина.
let hub = null;
const el = (...a) => hub.el(...a);
const PLUGIN = "projects-status";
const STAGES = ["Кандидат", "Разработка", "К релизу", "В сторе", "Пауза", "Готово"];
const KIND = { "Разработка": "work", "К релизу": "rel", "В сторе": "rel", "Пауза": "rest", "Готово": "ok" };
const FILTERS = [["all", "Все"], ["dir", "С направлением"], ["wait", "Ждут вас"], ["nodir", "Без направления"]];

let data = null, error = "", timer = null, filter = "all", open = null, editing = null, saving = false;
let tab = "mem", draft = null, expanded = null;   // вкладка карточки, форма новой задачи, раскрытая задача
const inputs = new Map();   // поле «написать проекту» по проекту ("" - главная): узел живёт между перерисовками
let sent = null;
const typing = () => [...inputs.values()].some((b) => b.node.contains(document.activeElement));
const busy = () => editing || draft || typing();
let rootRef = null;

const port = () => Number(location.port || 80) + 12;
async function load() {
  try {
    const r = await fetch(`http://${location.hostname}:${port()}/`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    data = await r.json();
    error = "";
  } catch (e) {
    error = `Процесс плагина не отвечает (${e.message}): hub restart ext:${PLUGIN}`;
  }
  if (rootRef) draw(rootRef, hub.snapshot());
}

// --- время -------------------------------------------------------------------------------------------------------
function ago(ts) {
  if (!ts) return "";
  const s = Date.now() / 1000 - ts, d = new Date(ts * 1000), now = new Date();
  const hm = d.toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit" });
  if (s < 90) return "сейчас";
  if (s < 3600) return `${Math.round(s / 60)} мин`;
  if (d.toDateString() === now.toDateString()) return hm;
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return `вчера ${hm}`;
  return d.toLocaleDateString("ru", { day: "2-digit", month: "2-digit" });
}
const at = (ts) => new Date(ts * 1000).toLocaleString("ru", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).replace(",", "");
const who = (by) => (by === "owner" ? "владелец" : by || "-");

// --- сессии проекта ------------------------------------------------------------------------------------------------
const under = (cwd, path) => !!(cwd && path) && (cwd === path || cwd.startsWith(path.replace(/\/$/, "") + "/"));
const lives = (p) => (p.directions || []).filter((d) => !d.board.archived);
function leadsOf(snap, slugs) {   // кто ведёт эти направления
  return (snap.sessions || []).filter((s) => s.state !== "removed" && (slugs.includes(s.name) || slugs.includes(s.backlog)));
}
function leads(snap, p) {   // кто ведёт направления проекта (живые; нет их - последнее)
  const sl = lives(p).map((d) => d.slug);
  return leadsOf(snap, sl.length ? sl : p.direction ? [p.direction] : []);
}
const dirNames = (p) => (lives(p).length ? lives(p).map((d) => d.slug) : [p.direction]).filter(Boolean).join(" · ");
function question(s) {
  const q = (s.pending || []).find((r) => r.tool === "AskUserQuestion");
  if (q) return { text: ((q.input || {}).questions || []).map((x) => x.question).join(" · ") || "вопрос формой", since: q.since || s.since };
  const r = (s.requests || []).find((x) => x.state === "needs-owner");
  if (r) return { text: `просит ${r.tool}`, since: r.since || s.since };
  if (s.attention && (s.attention.ask || s.attention.text)) return { text: s.attention.ask || s.attention.text, since: s.since };
  return null;
}
function waiting(snap, p) {
  for (const s of leads(snap, p)) { const q = question(s); if (q) return { ...q, session: s.name, dir: s.backlog || s.name }; }
  return null;
}

// --- разбор по группам -------------------------------------------------------------------------------------------
function groups(snap) {
  const out = { wait: [], go: [], done: [], rest: [], mine: [] };
  for (const p of data.projects) {
    const stage = (p.memory || {}).stage;
    const live = p.board && !p.board.archived;
    p.wait = live ? waiting(snap, p) : null;
    if (p.wait) out.wait.push(p);
    for (const t of p.tasks || []) if (t.assignee === "owner" && t.status !== "Done") out.mine.push([p, t]);
    if (live && stage !== "Готово") out.go.push(p);
    else if (p.board || stage === "Готово") out.done.push(p);
    else out.rest.push(p);
  }
  for (const t of data.general || []) if (t.assignee === "owner" && t.status !== "Done") out.mine.push([general(), t]);
  const changed = (p) => Math.max((p.board || {}).changed || 0, (p.memory || {}).updated || 0);
  out.go.sort((a, b) => (!!b.wait - !!a.wait) || ((a.memory || {}).stage === "Пауза") - ((b.memory || {}).stage === "Пауза") || changed(b) - changed(a));
  out.done.sort((a, b) => changed(b) - changed(a));
  out.mine.sort(([, a], [, b]) => (a.due || "9") < (b.due || "9") ? -1 : (a.due || "9") > (b.due || "9") ? 1 : 0);
  return out;
}

// --- куски ---------------------------------------------------------------------------------------------------------
function phase(stage) {
  const c = el("span", "ph", stage ? stage.toLowerCase() : "этап -");
  if (KIND[stage]) c.dataset.k = KIND[stage];
  return c;
}
function bar(b) {
  const n = b.counts, all = n["Done"] + n["In Progress"] + n["To Do"] || 1;
  const box = el("div", "pbar");
  for (const [k, c] of [["d", "Done"], ["p", "In Progress"], ["t", "To Do"]]) {
    if (!n[c]) continue;
    const i = el("i", k); i.style.width = `${(100 * n[c]) / all}%`; box.append(i);
  }
  const cnt = el("div", "cnt");
  cnt.append(el("span", "d", `${n["Done"]} готово`), el("span", "p", `${n["In Progress"]} в работе`), el("span", "t", `${n["To Do"]} осталось`));
  return [box, cnt];
}
const goSession = (name) => { location.hash = `#/s/${encodeURIComponent(name)}`; };
const GENERAL = "-";   // задачи без проекта: общий бэклог владельца
const general = () => ({ name: GENERAL, general: true, about: "", tasks: data.general || [], tasks_home: null });
const find = (name) => (name === GENERAL ? general() : data.projects.find((x) => x.name === name));
const openCard = (p, to = "mem") => { open = p.name; sent = null; editing = draft = expanded = null; tab = to; draw(rootRef, hub.snapshot()); rootRef.scrollTop = 0; };
const title = (p) => {
  if (p.general) return "Без проекта";
  const m = /^([^:]+):/.exec(p.about || "");
  return m && m[1].length <= 30 ? m[1].trim() : p.name;
};
const about = (p) => (p.about || "").replace(/^[^:]{1,30}:\s*/, "");

function sec(text, n, ...more) {
  const h = el("h2", "sec-h"); h.append(text, el("span", "n", String(n)), ...more); return h;
}

// --- список ----------------------------------------------------------------------------------------------------------
function listView(snap) {
  const g = groups(snap), box = el("div", "ps");
  const head = el("div", "ps-head"), top = el("div", "ps-top"), h = el("div");
  h.append(el("h1", null, "Статус проектов"));
  const sum = el("div", "sum");
  const b = (n, cls) => { const x = el("b", cls, String(n)); return x; };
  const nw = g.wait.length + g.mine.length;
  sum.append(b(g.go.length), " в работе · ", b(nw, nw ? "w" : null), nw ? el("span", "w", " ждут вас") : " ждут вас",
    ` · ${data.projects.filter((p) => p.board && !p.board.archived).length} направлений · ${g.rest.length} без направления · обновлено ${ago(data.at)}`);
  h.append(sum);
  const add = el("button", "btn-s pr", "Новая задача"); add.type = "button";
  add.addEventListener("click", () => { draft = newDraft(snap, null); draw(rootRef, snap); rootRef.querySelector(".nf input")?.focus(); });
  top.append(h, el("span", "ps-sp"));
  if (!draft) top.append(add);
  const chips = el("div", "chips");
  const counts = { all: data.projects.length, dir: g.go.length + g.done.filter((p) => p.board).length, wait: g.wait.length + g.mine.length, nodir: g.rest.length };
  for (const [k, t] of FILTERS) {
    const c = el("button", "pchip", t); c.type = "button"; c.setAttribute("aria-pressed", String(filter === k));
    c.append(el("span", "n", String(counts[k])));
    c.addEventListener("click", () => { filter = k; draw(rootRef, snap); });
    chips.append(c);
  }
  head.append(top, ask(snap, null), chips);
  box.append(head);
  if (error) box.append(el("p", "err", error));
  if (draft) box.append(taskForm(snap, true));
  const show = (k) => filter === "all" || filter === k;

  if ((g.wait.length || g.mine.length) && (show("wait") || show("dir"))) {
    const w = el("div", "wb");
    for (const [p, t] of g.mine) {
      const row = el("div", "wi mine"), nm = el("div", "p", title(p));
      nm.append(el("span", "dirn", t.id));
      const btn = el("button", "btn-s", "Готово"); btn.type = "button";
      btn.addEventListener("click", (e) => { e.stopPropagation(); setStatus(p, t, "Done"); });
      row.append(el("span", "dot"), nm, el("div", "t", t.title), el("div", "c" + (overdue(t) ? " late" : ""), t.due ? `до ${dmy(t.due)}` : "ваша задача"), btn);
      row.addEventListener("click", () => openCard(p, "tasks"));
      w.append(row);
    }
    for (const p of g.wait) {
      const row = el("div", "wi"), nm = el("div", "p", title(p));
      nm.append(el("span", "dirn", p.wait.dir || p.direction));
      const btn = el("button", "btn-s pr", "Ответить"); btn.type = "button";
      btn.addEventListener("click", () => goSession(p.wait.session));
      row.append(el("span", "dot"), nm, el("div", "t", p.wait.text), el("div", "c", ago(p.wait.since)), btn);
      w.append(row);
    }
    box.append(sec("Ждёт вас", g.wait.length + g.mine.length), w);
  }
  const gen = data.general || [], genOpen = gen.filter((t) => t.status !== "Done").length;
  if (gen.length && filter === "all") {
    const list = el("div", "wb"), row = el("div", "fin");
    row.append(el("span", "nm", "Без проекта"), el("span", null, `${genOpen} открыто · ${gen.length - genOpen} готово`),
      el("span", "ps-sp"), el("span", "mut", "доска →"));
    row.addEventListener("click", () => openCard(general(), "tasks"));
    list.append(row);
    box.append(sec("Задачи без проекта", genOpen), list);
  }
  if (g.go.length && show("dir")) {
    const cards = el("div", "cards");
    for (const p of g.go) cards.append(card(p));
    box.append(sec("Идут", g.go.length), cards);
  }
  if (g.done.length && show("dir")) {
    const list = el("div", "wb");
    for (const p of g.done) {
      const m = p.memory || {}, row = el("div", "fin");
      row.append(el("span", "nm", title(p)), phase(m.stage || (p.board && p.board.archived ? "Готово" : null)),
        el("span", null, m.note || ""), el("span", "ps-sp"), el("span", "dirn", p.direction || ""),
        el("span", "mut num", ago(Math.max((p.board || {}).changed || 0, m.updated || 0))));
      row.addEventListener("click", () => openCard(p));
      list.append(row);
    }
    box.append(sec("Готово", g.done.length), list);
  }
  if (g.rest.length && show("nodir")) {
    const rest = el("div", "rest"), by = new Map();
    for (const p of g.rest) {
      const k = (p.memory || {}).stage || "Без этапа";
      if (!by.has(k)) by.set(k, []);
      by.get(k).push(p);
    }
    for (const k of [...STAGES, "Без этапа"].filter((x) => by.has(x))) {
      const row = el("div", "rest-g"), v = el("div", "v");
      for (const p of by.get(k)) {
        const t = el("button", "tag go", title(p)); t.type = "button"; t.title = p.about || p.name;
        t.addEventListener("click", () => openCard(p));
        v.append(t);
      }
      row.append(el("span", "k", k), v);
      rest.append(row);
    }
    box.append(sec("Без направления", g.rest.length, el("span", "ps-sp"), el("span", "newdir", "направление заводит хаб по вашему слову")), rest);
  }
  if ((data.refused || []).length) {
    const r = data.refused[data.refused.length - 1];
    box.append(el("p", "refused", `Последняя правка памяти не принята: ${who(r.by)}, ${at(r.ts)} - ${r.why}`));
  }
  return box;
}

function card(p) {
  const m = p.memory || {}, c = el("div", "card");
  if (p.wait) c.classList.add("wait");
  if (m.stage === "Пауза") c.classList.add("dim");
  const top = el("div", "top"), t = el("div");
  t.append(el("div", "nm", title(p)), el("div", "ab", about(p)));
  top.append(t, el("span", "ps-sp"), phase(m.stage));
  c.append(top);
  c.append(el("div", "stg", m.note || (m.stage ? "" : "этап не записан")));
  c.append(...bar(p.board));
  if (p.board.doing.length) {
    const ul = el("ul"); for (const d of p.board.doing.slice(0, 2)) ul.append(el("li", null, d)); c.append(ul);
  }
  if (p.board.done.length) {
    const ul = el("ul", "did"), last = p.board.done[0];
    ul.append(el("li", null, `сделано ${day(last.date)}: ${short(last.title)}`));
    c.append(ul);
  }
  const ft = el("div", "ft");
  ft.append(el("span", "dirn", dirNames(p)), el("span", "ps-sp"));
  if (p.wait) ft.append(el("span", "wtag", "ждёт вас"), " · ");
  ft.append(el("span", "num", ago(Math.max(p.board.changed || 0, m.updated || 0))));
  c.append(ft);
  c.addEventListener("click", () => openCard(p));
  return c;
}

// --- карточка проекта ------------------------------------------------------------------------------------------------
function cardView(snap, p) {
  const m = p.memory || { next: [], history: [] }, box = el("div", "pc");
  const back = el("button", "pc-back", "← Статус проектов"); back.type = "button";
  back.addEventListener("click", () => { open = null; editing = null; draft = null; sent = null; draw(rootRef, snap); });
  box.append(back);
  if (p.general) {
    const head = el("div", "pc-head"), h = el("div");
    h.append(el("h1", null, "Задачи без проекта"), el("div", "ab", "ваши и общие дела, не привязанные к проекту"));
    head.append(h);
    box.append(head, ...tasksView(snap, p));
    return box;
  }

  const head = el("div", "pc-head"), h = el("div");
  h.append(el("h1", null, title(p)), el("div", "ab", about(p)));
  const meta = el("div", "pc-meta");
  meta.append(phase(m.stage));
  const ls = leads(snap, p);
  if (p.direction) meta.append(el("span", "dirn", dirNames(p)), el("span", null, ls.length ? `· ${ls[0].label || ls[0].state}` : "· сессии нет"));
  meta.append(el("span", "mono", p.exists ? `· ${p.path.replace(/^\/Users\/[^/]+/, "~")}` : "· папки проекта ещё нет"));
  h.append(meta);
  head.append(h, el("span", "ps-sp"));
  for (const s of ls.slice(0, 3)) {
    const o = el("button", "btn-s", `Открыть ${s.name}`); o.type = "button";
    o.addEventListener("click", () => goSession(s.name));
    head.append(o);
  }
  box.append(head, ask(snap, p));

  const open_ = (p.tasks || []).filter((t) => t.status !== "Done").length, tabs = el("div", "chips");
  for (const [k, t, n] of [["mem", "Память", null], ["tasks", "Задачи", open_]]) {
    const c = el("button", "pchip", t); c.type = "button"; c.setAttribute("aria-pressed", String(tab === k));
    if (n) c.append(el("span", "n", String(n)));
    c.addEventListener("click", () => { tab = k; editing = draft = null; draw(rootRef, snap); });
    tabs.append(c);
  }
  box.append(tabs);
  if (tab === "tasks") { box.append(...tasksView(snap, p)); return box; }

  const grid = el("div", "pc-grid");
  grid.append(memoryBox(snap, p, m, ls));
  const side = el("div", "wb");
  side.style.gap = "16px";
  side.append(...boardBox(snap, p), doneBox(p, m), historyBox(m), linksBox(snap, p));
  grid.append(side);
  box.append(grid);
  return box;
}

function memoryBox(snap, p, m, ls) {
  const box = el("div", "box mem"), h = el("h3", null, "Память проекта");
  const by = [...new Set(ls.map((s) => s.name))];
  h.append(el("span", "ps-sp"), el("span", "src", [by.length ? `ведут ${by.join(", ")} и хаб` : "ведёт хаб", m.updated ? `правка ${ago(m.updated)}` : ""].filter(Boolean).join(" · ")));
  if (editing) {
    const cancel = el("button", "btn-s", "Отмена"), save = el("button", "btn-s pr", saving ? "Сохраняю…" : "Сохранить");
    cancel.type = save.type = "button"; save.disabled = saving;
    cancel.addEventListener("click", () => { editing = null; draw(rootRef, snap); });
    save.addEventListener("click", () => submit(p, m));
    h.append(cancel, save);
  } else {
    const e = el("button", "btn-s", "Править"); e.type = "button";
    e.addEventListener("click", () => {
      editing = { stage: m.stage || null, note: m.note || "", goal: m.goal || "", questions: m.questions || "",
        next: (m.next || []).map((x) => x.text).join("\n") };
      draw(rootRef, snap);
      rootRef.querySelector(".mem textarea, .mem input")?.focus();
    });
    h.append(e);
  }
  box.append(h);

  const fld = (k, ...v) => { const f = el("div", "fld"); f.append(el("div", "k", k), ...v); return f; };
  const seg = el("div", "stseg");
  for (const s of STAGES) {
    const b = el("button", null, s); b.type = "button";
    const cur = editing ? editing.stage : m.stage;
    if (cur === s) b.classList.add("on");
    if (editing) b.addEventListener("click", () => { editing.stage = s; draw(rootRef, snap); });
    else b.disabled = true;
    seg.append(b);
  }
  if (editing) {
    const inp = (k, area) => {
      const x = el(area ? "textarea" : "input"); x.value = editing[k]; if (area) x.rows = area;
      x.addEventListener("input", () => { editing[k] = x.value; });
      x.addEventListener("keydown", (e) => { if (e.key === "Escape") { editing = null; draw(rootRef, snap); } });
      return x;
    };
    box.append(fld("Этап", seg, inp("note")), fld("Цель", inp("goal", 3)),
      fld("Что дальше", inp("next", 5), el("div", "hint", "по пункту в строке; отметки «сделано» сохраняются у тех же пунктов")),
      fld("Открытые вопросы", inp("questions", 2)));
  } else {
    const fill = (v) => { const d = el("div", "v"); d.append(v || el("span", "fill", "Заполнить")); return d; };
    box.append(fld("Этап", seg, fill(m.note)), fld("Цель", fill(m.goal)));
    const ul = el("ul", "next");
    for (const x of m.next || []) {
      const li = el("li", "tick" + (x.done ? " done" : ""), x.text);
      li.title = x.done ? "Снять отметку" : "Отметить сделанным";
      li.addEventListener("click", () => post(snap, { project: p.name, [x.done ? "undone" : "done"]: [x.text] }));
      ul.append(li);
    }
    box.append(fld("Что дальше", (m.next || []).length ? ul : fill("")));
    if (m.questions) box.append(fld("Открытые вопросы", el("div", "v", m.questions)));
  }
  if (p.board && p.board.decisions.length) {
    const ul = el("ul", "dec");
    for (const d of p.board.decisions) {
      const li = el("li"); li.append(el("span", "d", (d.date || "").slice(5, 10).split("-").reverse().join(".")), el("span", null, d.title));
      ul.append(li);
    }
    const more = p.board.decisions_total - p.board.decisions.length;
    if (more > 0) { const li = el("li"); li.append(el("span"), el("span", "more", `ещё ${more} в бэклоге направления`)); ul.append(li); }
    box.append(fld("Ключевые решения", ul));
  }
  const foot = el("div", "foot");
  foot.append(el("span", null, "Память хранится у хаба: её видят все сессии проекта и хаб"));
  box.append(foot);
  return box;
}

function boardBox(snap, p) {
  const out = [], live = lives(p);
  for (const d of live) {
    const box = el("div", "box"), h = el("h3", null, live.length > 1 ? "Направление" : "Бэклог");
    const a = el("a", "src", d.slug); a.href = `#/board/${encodeURIComponent(d.slug)}`;
    h.append(el("span", "ps-sp"), a);
    if (d.linked) {
      const u = el("button", "btn-s", "отвязать"); u.type = "button"; u.title = "направление с другим репо привязано к проекту вручную";
      u.addEventListener("click", () => post(snap, { project: p.name, unlink: d.slug }));
      h.append(u);
    }
    const ls = leadsOf(snap, [d.slug]);
    box.append(h, ...bar(d.board), el("div", "hint", ls.length ? `ведёт ${ls[0].name} · ${ls[0].label || ls[0].state}` : "сессии нет"));
    if (d.board.doing.length) { const ul = el("ul", "tasks"); for (const x of d.board.doing) ul.append(el("li", null, x)); box.append(ul); }
    out.push(box);
  }
  if (!live.length) {
    const box = el("div", "box");
    box.append(el("h3", null, p.board ? "Направление в архиве" : "Направления нет"));
    const e = el("div", "empty-dir");
    e.append(p.board ? `${p.direction}: закрыто, бэклог в архиве` : "Долгой сессии с бэклогом у проекта нет.");
    const hubS = (snap.sessions || []).find((s) => s.kind === "hub");
    const b = el("button", "btn-s pr", "Завести направление"); b.type = "button";
    b.addEventListener("click", async () => {
      b.disabled = true;
      await hub.post("/api/send", { session: hubS ? hubS.name : "hub", text: `Заведи направление для проекта ${p.name} (${p.path})`, action: true });
      b.textContent = "Хаб получил просьбу";
    });
    e.append(b);
    box.append(e);
    out.push(box);
  }
  if (!p.unlisted && (data.free || []).length) {
    const box = el("div", "box link"), sel = el("select");
    for (const [v, t] of [["", "Привязать направление с другим репо…"], ...data.free.map((x) => [x, x])]) { const o = el("option", null, t); o.value = v; sel.append(o); }
    sel.addEventListener("change", () => { if (sel.value) post(snap, { project: p.name, link: sel.value }); });
    box.append(sel);
    out.push(box);
  }
  return out;
}

const day = (date) => (date || "").slice(5, 10).split("-").reverse().join(".");
const short = (t) => t.replace(/\s*\(§[^)]*\)\s*$/, "");

function doneBox(p, m) {
  const box = el("div", "box"), h = el("h3", null, "Сделано");
  const mine = (p.tasks || []).filter((t) => !t.home);
  const own = mine.filter((t) => t.status === "Done").map((t) => ({ title: t.title, date: t.updated || t.created || "" }));
  const tasks = [...own, ...((p.board && p.board.done) || [])].sort((a, b) => (a.date < b.date ? 1 : -1)).slice(0, 8);
  const ticked = tasks.length ? [] : (m.next || []).filter((x) => x.done);
  const total = (p.board && !p.board.archived ? p.board.counts.Done : 0) + own.length;
  const rest = (p.board && !p.board.archived ? p.board.counts["In Progress"] + p.board.counts["To Do"] : 0) + mine.length - own.length;
  if (total) h.append(el("span", "ps-sp"), el("span", "src", `${total} из ${total + rest} задач бэклога`));
  box.append(h);
  if (!tasks.length && !ticked.length) { box.append(el("div", "hint", "Закрытых задач и отмеченных пунктов пока нет")); return box; }
  const ul = el("ul", "dec");
  for (const d of tasks) { const li = el("li"); li.append(el("span", "d", day(d.date)), el("span", null, short(d.title))); ul.append(li); }
  if (total > tasks.length) { const li = el("li"); li.append(el("span"), el("span", "more", `ещё ${total - tasks.length} в бэклоге направления`)); ul.append(li); }
  for (const x of ticked) { const li = el("li"); li.append(el("span", "d", "✓"), el("span", null, x.text)); ul.append(li); }
  box.append(ul);
  return box;
}

function historyBox(m) {
  const box = el("div", "box");
  box.append(el("h3", null, "История карточки"));
  const hist = (m.history || []).slice(-8).reverse();
  if (!hist.length) { box.append(el("div", "hint", "Правок ещё не было")); return box; }
  const ul = el("ul", "tl");
  for (const x of hist) { const li = el("li"); const t = el("span"); t.append(el("b", null, who(x.by)), `: ${x.what}`); li.append(el("span", "num", at(x.ts)), t); ul.append(li); }
  box.append(ul);
  return box;
}

function linksBox(snap, p) {
  const box = el("div", "box"), l = el("div", "links");
  box.append(el("h3", null, "Ссылки"));
  const row = (k, v) => { const d = el("div"); d.append(el("span", "k", k), v); l.append(d); };
  row("Папка", el("span", "mono", p.exists ? p.path.replace(/^\/Users\/[^/]+/, "~") : "ещё нет"));
  if (lives(p).length) {
    const v = el("span");
    lives(p).forEach((d, i) => { const a = el("a", "mono", d.slug); a.href = `#/board/${encodeURIComponent(d.slug)}`; v.append(...(i ? [", ", a] : [a])); });
    row(lives(p).length > 1 ? "Доски" : "Доска", v);
  }
  const slugs = lives(p).map((d) => d.slug).concat(p.direction ? [p.direction] : []);
  const ses = (snap.sessions || []).filter((s) => s.state !== "removed" && s.kind !== "hub" && (under(s.cwd, p.path) || slugs.includes(s.backlog)));
  if (ses.length) {
    const v = el("span");
    ses.forEach((s, i) => { const a = el("a", null, s.name); a.href = `#/s/${encodeURIComponent(s.name)}`; v.append(...(i ? [", ", a] : [a])); });
    row("Сессии", v);
  }
  box.append(l);
  return box;
}

// --- задачи ----------------------------------------------------------------------------------------------------------
const COLS = [["To Do", "К работе"], ["In Progress", "В работе"], ["Done", "Готово"]];
const PRIO = { high: "высокий", medium: "средний", low: "низкий" };
const TYPES = [["story", "Story"], ["task", "Task"], ["bug", "Bug"]];
const dmy = (d) => (d || "").slice(0, 10).split("-").reverse().join(".").replace(/\.\d{4}$/, "");
const overdue = (t) => t.due && t.status !== "Done" && t.due < new Date().toISOString().slice(0, 10);
const mate = (a) => (a === "owner" ? "вы" : a || "");

function setStatus(p, t, status) {
  if (t.status === status) return;
  t.status = status; t.updated = new Date().toISOString().slice(0, 16).replace("T", " ");
  draw(rootRef, hub.snapshot());
  post(hub.snapshot(), { task: "status", project: p.name, id: t.id, status, ...(p.general ? {} : { direction: t.home || "" }) });
}

const tkey = (t) => `${t.home || ""}|${t.id}`;
const many = (p) => !p.general && ((p.homes || []).length > 1 || (p.tasks || []).some((t) => !t.home) && (p.homes || []).length > 0);
const where = (p, dir) => (p.general ? "общий бэклог без проекта" : dir ? `бэклог направления ${dir}` : "свой бэклог проекта");
const home = (p) => (p.general ? "общий бэклог без проекта" : (p.homes || []).length > 1 ? `бэклоги: ${p.homes.join(", ")} и свой проекта` : p.tasks_home ? `бэклог направления ${p.tasks_home}` : "свой бэклог проекта");
const newDraft = (snap, p) => {
  const ls = p && !p.general ? leads(snap, p) : [];
  return { project: p ? p.name : "", title: "", description: "", type: "task", priority: "medium",
    assignee: ls.length ? ls[0].name : p && !p.general ? "" : "owner", due: "", direction: (p && p.tasks_home) || "" };
};

function tasksView(snap, p) {
  const out = [];
  if (draft) out.push(taskForm(snap, false));
  const box = el("div", "box"), h = el("h3", null, "Доска");
  h.append(el("span", "ps-sp"), el("span", "src", `${home(p)} · перетащите карточку, чтобы сменить статус`));
  if (!draft) {
    const add = el("button", "btn-s pr", "Новая задача"); add.type = "button";
    add.addEventListener("click", () => {
      draft = newDraft(snap, p);
      draw(rootRef, snap); rootRef.querySelector(".nf input")?.focus();
    });
    h.append(add);
  }
  box.append(h);
  const kb = el("div", "kb"), all = p.tasks || [];
  for (const [st, name] of COLS) {
    let list = all.filter((t) => t.status === st || (st === "To Do" && !COLS.some(([k]) => k === t.status)));
    list = st === "Done" ? list.sort((a, b) => ((b.updated || b.created || "") > (a.updated || a.created || "") ? 1 : -1))
      : list.sort((a, b) => (Object.keys(PRIO).indexOf(a.priority || "medium") - Object.keys(PRIO).indexOf(b.priority || "medium")) || a.ordinal - b.ordinal);
    const col = el("div", "col"), hd = el("h4", null, name);
    hd.append(el("span", null, String(list.length)));
    col.append(hd);
    col.addEventListener("dragover", (e) => { e.preventDefault(); col.classList.add("over"); });
    col.addEventListener("dragleave", () => col.classList.remove("over"));
    col.addEventListener("drop", (e) => {
      e.preventDefault(); col.classList.remove("over");
      const t = all.find((x) => tkey(x) === e.dataTransfer.getData("text/plain"));
      if (t) setStatus(p, t, st);
    });
    const shown = st === "Done" ? list.slice(0, 8) : list;
    for (const t of shown) col.append(taskCard(p, t));
    if (list.length > shown.length) col.append(el("div", "hint", `ещё ${list.length - shown.length}`));
    kb.append(col);
  }
  box.append(kb);
  if (!all.length) box.append(el("div", "hint", "Задач пока нет: заведите первую кнопкой «Новая задача»"));
  out.push(box);
  return out;
}

function taskCard(p, t) {
  const c = el("div", "tk" + (expanded === tkey(t) ? " open" : "") + (t.assignee === "owner" ? " me" : ""));
  c.draggable = true;
  c.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/plain", tkey(t)); c.classList.add("drag"); });
  c.addEventListener("dragend", () => c.classList.remove("drag"));
  c.addEventListener("click", () => { expanded = expanded === tkey(t) ? null : tkey(t); draw(rootRef, hub.snapshot()); });
  c.append(el("div", "tt", t.title));
  const row = el("div", "row");
  row.append(el("span", null, t.id));
  if (many(p)) row.append(el("span", "dirn", t.home || "проект"));
  if (t.type && t.type !== "task") row.append(el("span", null, (TYPES.find(([k]) => k === t.type) || [, t.type])[1]));
  if (t.priority && t.status !== "Done") row.append(el("span", `pr-${t.priority[0]}`, `● ${PRIO[t.priority] || t.priority}`));
  if (t.status === "Done") row.append(el("span", null, dmy(t.updated || t.created)));
  else if (t.due) row.append(el("span", overdue(t) ? "late" : null, `до ${dmy(t.due)}`));
  if (t.assignee) row.append(el("span", "who", mate(t.assignee)));
  c.append(row);
  if (expanded === tkey(t)) {
    if (t.description) c.append(el("div", "desc", t.description));
    const act = el("div", "acts");
    for (const [st, name] of COLS) {
      if (st === t.status) continue;
      const b = el("button", "btn-s", name); b.type = "button";
      b.addEventListener("click", (e) => { e.stopPropagation(); setStatus(p, t, st); });
      act.append(b);
    }
    c.append(act);
  }
  return c;
}

function taskForm(snap, pick) {
  const p = find(draft.project);
  const box = el("div", "box"), h = el("h3", null, "Новая задача");
  h.append(el("span", "ps-sp"), el("span", "src", p ? `уйдёт в ${where(p, draft.direction)}` : "выберите проект"));
  box.append(h);
  const fld = (k, v, cls) => { const f = el("div", "fld" + (cls ? ` ${cls}` : "")); f.append(el("div", "k", k), v); return f; };
  const bind = (x, k) => { x.value = draft[k]; x.addEventListener("input", () => { draft[k] = x.value; });
    x.addEventListener("keydown", (e) => { if (e.key === "Escape") { draft = null; draw(rootRef, snap); } }); return x; };
  const select = (k, opts) => { const s = el("select"); for (const [v, t] of opts) { const o = el("option", null, t); o.value = v; s.append(o); }
    s.addEventListener("change", () => {
      draft[k] = s.value;
      if (k === "project") draft.direction = (find(s.value) || {}).tasks_home || "";
      draw(rootRef, snap);
    }); s.value = draft[k]; return s; };
  const nm = bind(el("input"), "title"); nm.placeholder = "Что сделать";
  const ds = bind(el("textarea"), "description"); ds.rows = 3; ds.placeholder = "Подробности и критерии приёмки";
  const due = bind(el("input"), "due"); due.type = "date";
  const people = (snap.sessions || []).filter((s) => s.state !== "removed" && s.kind !== "hub").map((s) => s.name).sort();
  const nf = el("div", "nf");
  const live = (x) => !!(x.board && !x.board.archived);
  const all = [...data.projects].sort((a, b) => live(b) - live(a) || title(a).localeCompare(title(b), "ru"));
  if (pick) nf.append(fld("Проект", select("project", [["", "выберите проект"], [GENERAL, "Без проекта"], ...all.map((x) => [x.name, title(x)])])), fld("Название", nm, "wide"));
  else nf.append(fld("Название", nm, "full"));
  if (p && (p.homes || []).length) nf.append(fld("Куда", select("direction", [...p.homes.map((x) => [x, `направление ${x}`]), ["", "свой бэклог проекта"]]), "full"));
  nf.append(fld("Описание", ds, "full"),
    fld("Тип", select("type", TYPES)), fld("Приоритет", select("priority", Object.entries(PRIO))),
    fld("Исполнитель", select("assignee", [["", "без исполнителя"], ["owner", "вы"], ...people.map((n) => [n, n])])), fld("Срок", due));
  box.append(nf);
  const foot = el("div", "acts");
  const mk = (t, cls, send) => { const b = el("button", cls, t); b.type = "button"; b.disabled = saving;
    b.addEventListener("click", () => createTask(send)); return b; };
  foot.append(mk(saving ? "Создаю…" : "Создать", "btn-s pr", false));
  if (draft.assignee && draft.assignee !== "owner") foot.append(mk("Создать и отдать исполнителю", "btn-s", true));
  const cancel = el("button", "btn-s", "Отмена"); cancel.type = "button";
  cancel.addEventListener("click", () => { draft = null; error = ""; draw(rootRef, snap); });
  foot.append(cancel);
  foot.append(el("span", "hint", draft.assignee === "owner" ? "ваша задача появится в «Ждёт вас» на главной плагина"
    : draft.assignee ? "«отдать» - исполнитель получит задачу сообщением от вас" : ""));
  box.append(foot);
  return box;
}

async function createTask(send) {
  const d = draft, p = find(d.project);
  if (!p) { error = "Выберите проект"; draw(rootRef, hub.snapshot()); return; }
  const op = { task: "create", project: p.name, title: d.title.trim(), ...((p.homes || []).length ? { direction: d.direction } : {}) };
  if (!op.title) { error = "У задачи нет названия"; draw(rootRef, hub.snapshot()); return; }
  for (const k of ["description", "type", "priority", "assignee", "due"]) if (d[k].trim()) op[k] = d[k].trim();
  if (JSON.stringify(op).length > 2000) { error = "Задача длиннее 2000 знаков: сократите описание"; draw(rootRef, hub.snapshot()); return; }
  saving = true; error = ""; draw(rootRef, hub.snapshot());
  await post(hub.snapshot(), op);
  if (send) {
    const lines = [p.general ? `Задача без проекта: «${op.title}»` : `Задача по проекту ${p.name}: «${op.title}»`];
    if (op.description) lines.push(op.description);
    lines.push([op.priority && `приоритет ${PRIO[op.priority]}`, op.due && `срок ${dmy(op.due)}`].filter(Boolean).join(", "));
    const dirArg = op.direction !== undefined ? ` --direction "${op.direction}"` : "";
    lines.push(`Заведена в ${where(p, op.direction)}. Номер и статус: python3 ${data.plugin}/pmem.py task list ${p.name}${dirArg}; ` +
      `сменить статус: python3 ${data.plugin}/pmem.py task status ${p.name} <TASK-N> "In Progress"${dirArg} (потом Done).`);
    await hub.post("/api/send", { session: d.assignee, text: lines.filter(Boolean).join("\n") });
  }
  saving = false;
  if (open === p.name) { draft = null; draw(rootRef, hub.snapshot()); } else openCard(p, "tasks");
}

// --- написать проекту ------------------------------------------------------------------------------------------------
const hubName = (snap) => ((snap.sessions || []).find((s) => s.kind === "hub") || { name: "hub" }).name;
function context(key, words) {
  return key ? `[проект ${key}] ${words}` : `[по проектам] ${words}`;
}
function ask(snap, p) {
  const key = p ? p.name : "";
  let box = inputs.get(key);
  if (!box) {
    box = hub.input({ to: hubName(snap), key: `${PLUGIN}:${key || "all"}`,
      placeholder: p ? `Написать проекту ${title(p)}…` : "Написать по проектам…",
      hint: p ? "уйдёт Хабу с контекстом проекта: он решит, кому - ведущему направления, агенту или задачей"
        : "уйдёт Хабу: он найдёт проект и решит, кому",
      prefix: (w) => context(key, w),
      onSent: () => { sent = key; draw(rootRef, hub.snapshot()); } });
    inputs.set(key, box);
  }
  const wrap = el("div", "ask");
  wrap.append(box.node);
  if (sent === key) {
    const n = el("div", "hint"), a = el("a", null, "ответ - в чате Хаба →");
    a.href = `#/s/${encodeURIComponent(hubName(snap))}`;
    n.append(a);
    wrap.append(n);
  }
  return wrap;
}

// --- правка ----------------------------------------------------------------------------------------------------------
async function post(snap, upd) {
  const r = await hub.postFeed(JSON.stringify(upd));
  if (r && r.ok === false) error = r.error || "правка не принята";
  setTimeout(load, 2500);   // процесс свернёт пост за пару секунд
}

async function submit(p, m) {
  const e = editing, upd = { project: p.name };
  if (e.stage && e.stage !== m.stage) upd.stage = e.stage;
  for (const k of ["note", "goal", "questions"]) if (e[k].trim() !== (m[k] || "")) upd[k] = e[k].trim();
  const lines = e.next.split("\n").map((x) => x.trim()).filter(Boolean);
  const old = m.next || [];
  if (lines.join("\n") !== old.map((x) => x.text).join("\n")) {
    upd.next = lines.map((t) => ({ text: t, done: !!(old.find((x) => x.text === t) || {}).done }));
  }
  if (Object.keys(upd).length === 1) { editing = null; draw(rootRef, hub.snapshot()); return; }
  const text = JSON.stringify(upd);
  if (text.length > 2000) { error = "Правка длиннее 2000 знаков: сократите цель или «Что дальше»"; draw(rootRef, hub.snapshot()); return; }
  saving = true; draw(rootRef, hub.snapshot());
  await post(hub.snapshot(), upd);
  saving = false; editing = null;
}

// --- вид -------------------------------------------------------------------------------------------------------------
function draw(root, snap) {
  if (!root) return;
  if (!data) { root.replaceChildren(el("div", "pst", error || "Загружаю…")); return; }
  const p = open && find(open);
  if (p) groups(snap);   // ждёт ли он вас - для карточки
  const page = el("div", "pst");
  page.append(p ? cardView(snap, p) : listView(snap));
  root.replaceChildren(page);
}

export default function register(h) {
  hub = h;
  hub.addStyle("web/projects.css");
  hub.addView({
    id: PLUGIN, title: "Статус проектов", subtitle: "этап, бэклог и память проектов", icon: "board",
    render(root, snap) { rootRef = root; if (!busy()) draw(root, snap); },
    show(root) { rootRef = root; load(); timer = setInterval(() => { if (!busy()) load(); }, 15000); },
    hide() { clearInterval(timer); timer = null; },
  });
}
