"""Задачи проекта - файлы Backlog.md (`backlog/tasks/task-N - <заголовок>.md`): их читают утилита backlog, доска
направления и `hub direction <slug> task …`. У проекта с живым направлением это бэклог направления, без него - свой
бэклог проекта рядом с его памятью. Задачи без проекта (project "-") - в общем бэклоге владельца.

Правка - пост в канал плагина, как правка памяти: {"task": "create", "project", "title", ["description", "type",
"priority", "assignee", "due"]} или {"task": "status", "project", "id", "status"}."""
import datetime
import glob
import os
import re

GENERAL = "-"
STATUSES = {"To Do": "К работе", "In Progress": "В работе", "Done": "Готово"}
PRIORITIES = ("high", "medium", "low")
TYPES = ("story", "task", "bug")
CONFIG = ('project_name: "{name}"\ndefault_status: "To Do"\nstatuses: ["To Do", "In Progress", "Done"]\nlabels: []\n'
          'date_format: yyyy-mm-dd\nmax_column_width: 20\nauto_open_browser: false\ndefault_port: 6420\n'
          'remote_operations: false\nauto_commit: false\nfilesystem_only: true\nbypass_git_hooks: false\n'
          'check_active_branches: false\nactive_branch_days: 30\ntask_prefix: "task"\n')


class Invalid(ValueError):
    pass


def parse(op):
    """Пост {"task": …} -> проверенная правка; не годится - Invalid с причиной."""
    kind = op.get("task")
    if kind == "create":
        extra = set(op) - {"task", "project", "title", "description", "type", "priority", "assignee", "due"}
        if extra:
            raise Invalid(f"неизвестные поля: {', '.join(sorted(extra))}")
        if not all(isinstance(op.get(k, ""), str) for k in ("title", "description", "type", "priority", "assignee", "due")):
            raise Invalid("поля задачи - строки")
        op = {**op, "title": " ".join(op.get("title", "").split())}
        if not op["title"]:
            raise Invalid("у задачи нет названия")
        if op.get("priority") and op["priority"] not in PRIORITIES:
            raise Invalid(f"приоритет - один из: {', '.join(PRIORITIES)}")
        if op.get("type") and op["type"] not in TYPES:
            raise Invalid(f"тип - один из: {', '.join(TYPES)}")
        if op.get("due") and not re.fullmatch(r"\d{4}-\d\d-\d\d", op["due"]):
            raise Invalid("срок - ГГГГ-ММ-ДД")
        if op.get("assignee") and not re.fullmatch(r"[\w.-]+", op["assignee"]):
            raise Invalid("исполнитель - имя сессии или owner")
        return op
    if kind == "status":
        if set(op) - {"task", "project", "id", "status"}:
            raise Invalid("status: только project, id, status")
        if op.get("status") not in STATUSES:
            raise Invalid(f"статус - один из: {', '.join(STATUSES)}")
        if not re.fullmatch(r"(?i)task-\d+", str(op.get("id") or "")):
            raise Invalid("id - вида TASK-12")
        return {**op, "id": op["id"].upper()}
    raise Invalid("task - create или status")


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def quote(v):
    return "'" + v.replace("'", "''") + "'" if re.search(r"[:#'\"\[\]{}&*!|>%@`,]|^\s|\s$|^-", v) else v


def ensure(base, name):
    for sub in ("tasks", "completed", "drafts", "decisions", "docs"):
        os.makedirs(os.path.join(base, sub), exist_ok=True)
    cfg = os.path.join(base, "config.yml")
    if not os.path.exists(cfg):
        with open(cfg, "w", encoding="utf-8") as f:
            f.write(CONFIG.format(name=name))


def next_number(base):
    seen = [int(m.group(1)) for f in glob.glob(os.path.join(base, "**", "*.md"), recursive=True)
            for m in [re.match(r"(?i)task-(\d+)\b", os.path.basename(f))] if m]
    return max(seen, default=0) + 1


def create(base, op, name=None):
    ensure(base, name or os.path.basename(os.path.dirname(base)))
    n = next_number(base)
    who = op.get("assignee")
    head = [f"id: TASK-{n}", f"title: {quote(op['title'])}", "status: To Do"]
    head += ["assignee:", f"  - '@{who}'"] if who else ["assignee: []"]
    head.append(f"created_date: '{now()}'")
    if op.get("due"):
        head.append(f"due_date: '{op['due']}'")
    head += ["labels: []", "dependencies: []"]
    head += [f"{k}: {op[k]}" for k in ("priority", "type") if op.get(k)]
    head.append(f"ordinal: {n * 1000}")
    body = ""
    if (op.get("description") or "").strip():
        body = f"\n## Description\n\n<!-- SECTION:DESCRIPTION:BEGIN -->\n{op['description'].strip()}\n<!-- SECTION:DESCRIPTION:END -->\n"
    safe = re.sub(r"[^\w-]+", "-", op["title"]).strip("-")[:60] or "task"
    with open(os.path.join(base, "tasks", f"task-{n} - {safe}.md"), "w", encoding="utf-8") as f:
        f.write("---\n" + "\n".join(head) + "\n---\n" + body)
    return f"TASK-{n}"


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def path_of(base, tid):
    n = tid.split("-")[1]
    found = glob.glob(os.path.join(base, "tasks", f"task-{n} *.md")) + glob.glob(os.path.join(base, "tasks", f"task-{n}.md"))
    if not found:
        raise Invalid(f"нет задачи {tid}")
    return found[0]


def set_status(base, tid, status):
    path = path_of(base, tid)
    text = read(path)
    _, head, body = text.split("---\n", 2)
    lines = [ln for ln in head.splitlines() if not ln.startswith("updated_date:")]
    lines = [f"status: {status}" if ln.startswith("status:") else ln for ln in lines]
    at = next((i for i, ln in enumerate(lines) if ln.startswith("created_date:")), len(lines) - 1)
    lines.insert(at + 1, f"updated_date: '{now()}'")
    with open(path, "w", encoding="utf-8") as f:
        f.write("---\n" + "\n".join(lines) + "\n---\n" + body)


def _list(head, key):
    m = re.search(rf"^{key}:[ \t]*(.*)$((?:\n[ \t]+- .*)*)", head, re.M)
    if not m:
        return []
    inline = m.group(1).strip()
    items = re.findall(r"^[ \t]+- (.*)$", m.group(2), re.M) if not inline or inline == "[]" else inline.strip("[]").split(",")
    return [x.strip().strip("'\"").lstrip("@") for x in items if x.strip()]


def read_all(base):
    """Задачи в работе бэклога (папка tasks): поля для доски, описание - для раскрытой карточки."""
    from data import field
    out = []
    for f in glob.glob(os.path.join(base, "tasks", "*.md")):
        try:
            text = read(f)
        except OSError:
            continue
        head = text.split("---\n")[1] if text.startswith("---\n") else ""
        desc = re.search(r"SECTION:DESCRIPTION:BEGIN -->\n(.*?)\n<!-- SECTION:DESCRIPTION:END", text, re.S)
        who = _list(head, "assignee")
        out.append({"id": (field(head, "id") or "").upper(), "title": field(head, "title") or os.path.basename(f),
                    "status": field(head, "status") or "To Do", "assignee": who[0] if who else None,
                    "priority": field(head, "priority"), "type": field(head, "type"), "due": field(head, "due_date"),
                    "created": field(head, "created_date"), "updated": field(head, "updated_date"),
                    "ordinal": float(field(head, "ordinal") or 0), "description": desc.group(1).strip() if desc else ""})
    return out
