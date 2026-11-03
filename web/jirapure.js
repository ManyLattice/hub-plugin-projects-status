// Вид «Jira» без DOM: строка хаба у задачи, колонки доски, фильтры, привязка к проекту. Склейка - по ключу, без модели.
export const STATES = { you: "Ждёт вас", wait: "Ждёт", work: "Работает", done: "Сдано", none: "В хабе не ведётся" };
export const ORDER = ["you", "wait", "work", "done", "none"];
export const STALE_DAYS = 7;
export const COMPACT_FROM = 12;
const ACTIVE = ["busy", "starting"];
const NOBODY = new Set(["", "владелец", "owner"]);

export function asks(s) {
  const q = (s.pending || []).find((r) => r.tool === "AskUserQuestion");
  if (q) {
    const qs = ((q.input || {}).questions || []);
    return { text: qs.map((x) => x.question || x.header).filter(Boolean).join(" · ") || "вопрос формой", since: q.since || s.since, asks: s.pending };
  }
  const perm = (s.pending || []).find((r) => r.request_id);
  if (perm) return { text: `просит разрешение: ${perm.tool}`, since: perm.since || s.since, asks: s.pending };
  if (s.attention && s.attention.ask) return { text: s.attention.ask, since: s.attention.since || s.since, asks: null };
  return null;
}

export function openIds(snap) {
  return new Set((snap.delegations || []).filter((d) => d.state !== "closed").map((d) => d.id));
}

export function pickLead(tasks, open) {
  const leads = (tasks || []).filter((t) => t.role === "lead");
  const byAt = (a, b) => (b.at || 0) - (a.at || 0);
  const live = leads.filter((t) => open.has(t.id)).sort(byAt);
  const lead = live[0] || [...leads].sort(byAt)[0] || null;
  return { lead, others: leads.filter((t) => t !== lead), mentions: (tasks || []).filter((t) => t.role === "mention") };
}

// Строка хаба: первая подходящая из «Ждёт вас», «Ждёт», «Работает», «Сдано», «В хабе не ведётся».
// Кто ведёт - сессия последней ведущей записи; у исполнителя - и его ведущий (raised_by, «Поставил»).
export function hubLine(tasks, snap, hints = {}) {
  const open = openIds(snap), by = new Map((snap.sessions || []).filter((s) => s.state !== "removed").map((s) => [s.name, s]));
  const { lead, others, mentions } = pickLead(tasks, open);
  if (!lead) {
    const hint = (hints.memory || [])[0] ? `есть в памяти проекта ${hints.memory[0]}`
      : (hints.backlog || [])[0] ? `есть в бэклоге ${hints.backlog[0]}`
      : mentions[0] ? `упоминается в ${mentions[0].id}` : "";
    return { state: "none", hint, mentions, others: [] };
  }
  const doer = by.get(lead.doer);
  const bossName = (doer && doer.raised_by) || (!NOBODY.has(lead.by) ? lead.by : "");
  const boss = by.get(bossName);
  const people = [doer, boss].filter((s) => s && s.kind !== "hub");
  const under = doer && boss && boss.kind !== "hub" ? bossName : "";
  const base = { task: lead, others, mentions, open: open.has(lead.id) };
  // сначала сам исполнитель (карточка, ожидание, работа), затем его ведущий
  for (const s of people) {
    const sub = s === doer ? under : "";
    const q = asks(s);
    if (q) return { ...base, state: "you", session: s.name, under: sub, text: q.text, ts: q.since, card: { session: s.name, asks: q.asks } };
    if (s.waiting && s.waiting.text) return { ...base, state: "wait", session: s.name, under: sub, text: s.waiting.text, ts: s.waiting.ts };
    if (ACTIVE.includes(s.state)) {
      const recap = s.recap || null, step = s === doer ? lead.last : null;
      const useStep = step && (!recap || (step.ts || 0) >= (recap.ts || 0));
      return { ...base, state: "work", session: s.name, under: sub,
        text: useStep ? step.text : recap ? recap.text : "работает", ts: useStep ? step.ts : recap ? recap.ts : s.since };
    }
  }
  return { ...base, state: "done", session: lead.doer, under, text: lead.last ? lead.last.text : lead.title, ts: (lead.last && lead.last.ts) || lead.at };
}

export function staleDays(issue, tasks, now = Date.now() / 1000) {
  if (!issue || (issue.status || {}).cat !== "indeterminate") return 0;
  const last = (tasks || []).length ? Math.max(...tasks.map((t) => t.at || 0)) : issue.updated || 0;
  const d = Math.floor((now - last) / 86400);
  return last && d >= STALE_DAYS ? d : 0;
}

// --- проект задачи: метка = имя проекта или из поля jira памяти, эпик из того же поля, затем через хаб; иначе «Общие»
export function projectIndex(projects) {
  return (projects || []).map((p) => {
    const toks = String((p.memory || {}).jira || "").split(/[\s,]+/).filter(Boolean);
    const dirs = new Set([p.direction, ...(p.directions || []).map((d) => d.slug)].filter(Boolean));
    return { name: p.name, labels: new Set([p.name.toLowerCase(), ...toks.filter((t) => !/^[A-Z][A-Z0-9_]*-\d+$/.test(t)).map((t) => t.toLowerCase())]),
      epics: new Set(toks.filter((t) => /^[A-Z][A-Z0-9_]*-\d+$/.test(t))), dirs };
  });
}
export function projectLink(issue, index, line, snap) {
  const labels = (issue.labels || []).map((x) => x.toLowerCase());
  for (const p of index) { const l = labels.find((x) => p.labels.has(x)); if (l) return { name: p.name, by: `по метке ${l}` }; }
  const ep = [(issue.epic || {}).key, issue.parent].filter(Boolean);
  for (const p of index) { const k = ep.find((x) => p.epics.has(x)); if (k) return { name: p.name, by: `по эпику ${k}` }; }
  if (line && line.task) {
    const names = [line.session, line.under, line.task.doer, line.task.by].filter(Boolean);
    const by = new Map((snap.sessions || []).map((s) => [s.name, s]));
    const slugs = new Set(names.flatMap((n) => [n, (by.get(n) || {}).backlog]).filter(Boolean));
    for (const p of index) { const d = [...slugs].find((x) => p.dirs.has(x)); if (d) return { name: p.name, by: `через направление ${d}` }; }
  }
  return null;
}
export const projectOf = (issue, index, line, snap) => (projectLink(issue, index, line, snap) || {}).name || null;

// --- доска: колонки по id статусов из раскладки доски; последняя («Готово») свёрнута -------------------------------------
export function columns(cols, issues) {
  const out = (cols || []).map((c, i) => ({ name: c.name, ids: new Set(c.statuses), items: [], last: i === cols.length - 1 }));
  const rest = { name: "Вне колонок доски", ids: new Set(), items: [], last: false };
  for (const it of issues) (out.find((c) => c.ids.has((it.status || {}).id)) || rest).items.push(it);
  if (rest.items.length) out.splice(Math.max(0, out.length - 1), 0, rest);
  return out;
}

export function sprintOptions(sprints) {
  if (!sprints) return [];
  const act = sprints.filter((s) => s.state === "active"), fut = sprints.filter((s) => s.state === "future");
  const end = (s) => (s.end ? ` · до ${s.end.slice(8, 10)}.${s.end.slice(5, 7)}` : "");
  return [
    ...(act.length === 1 ? [["active", act[0].name + end(act[0])]] : act.length ? [["active", `Активные (${act.length})`]] : []),
    ...(act.length > 1 ? act.map((s) => [`s:${s.id}`, s.name + end(s)]) : []),
    ...fut.map((s) => [`s:${s.id}`, `${s.name} · будущий`]),
    ["none", "Вне спринта"], ["all", "Все задачи доски"],
  ];
}
export function inSprint(issue, pick) {
  if (!pick || pick === "all") return true;
  const s = issue.sprint;
  if (pick === "active") return !!s && s.state === "active";
  if (pick === "none") return !s;
  return !!s && `s:${s.id}` === pick;
}

// --- ключ в ветках и MR/PR репо проектов ------------------------------------------------------------------------------
export function keyRx(key) {
  const [p, n] = key.split("-");
  return new RegExp(`(^|[^a-z0-9])${p.toLowerCase()}-?${n}($|[^0-9])`, "i");
}
export function codeOf(key, projects) {
  const rx = keyRx(key), branches = new Set(), prs = [];
  for (const p of projects || []) {
    for (const r of p.repos || []) {
      for (const b of r.names || []) if (rx.test(b)) branches.add(b);
      for (const x of r.prs || []) if (rx.test(x.branch || "") || rx.test(x.title || "")) prs.push({ ...x, kind: r.kind });
    }
  }
  return { branches: [...branches].slice(0, 3), prs: prs.slice(0, 3) };
}

// упоминания ключа вне задач хаба: память проектов и бэклоги направлений
export function hintsOf(key, projects, snap) {
  const rx = new RegExp(`\\b${key}\\b`);
  const memory = (projects || []).filter((p) => {
    const m = p.memory || {};
    return [m.note, m.goal, m.questions, m.jira, ...(m.next || []).map((x) => x.text)].some((t) => t && rx.test(t));
  }).map((p) => p.name);
  const backlog = Object.entries(snap.direction_tasks || {}).filter(([, d]) => (d.tasks || []).some((t) => rx.test(t.title || ""))).map(([k]) => k);
  return { memory, backlog };
}

// компактная колонка: «Ждёт вас» целиком, остальное строками по строке хаба, «Сдано» и «Не ведётся» свёрнуты
export function compactGroups(items, lineOf) {
  const g = Object.fromEntries(ORDER.map((k) => [k, []]));
  for (const it of items) g[lineOf(it).state].push(it);
  return ORDER.filter((k) => g[k].length).map((k) => ({ state: k, items: g[k], folded: k === "done" || k === "none", shown: k === "you" ? Infinity : k === "wait" ? 4 : 5 }));
}

export function summary(issues, lineOf) {
  const n = Object.fromEntries(ORDER.map((k) => [k, 0]));
  for (const it of issues) n[lineOf(it).state]++;
  return n;
}
