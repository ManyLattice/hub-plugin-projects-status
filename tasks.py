"""Задачи проекта - файлы Backlog.md (`backlog/tasks/task-N - <заголовок>.md`): их читают утилита backlog, доска
направления и `hub direction <slug> task …`. У проекта с живым направлением это бэклог направления, без него - свой
бэклог проекта рядом с его памятью. Задачи без проекта (project "-") - в общем бэклоге владельца.

Правка - пост в канал плагина, как правка памяти: {"task": "create", "project", "title", ["direction", "description",
"type", "priority", "assignee", "due"]}, {"task": "status", "project", "id", "status", ["direction"]}, {"task": "edit",
"project", "id", ["direction"] + любые поля create и status (пустая строка стирает поле)} или {"task": "delete", "project",
"id", ["direction"]} - задача уходит в архив бэклога (archive/tasks, как `backlog task archive`). direction - в какой
бэклог: направление проекта или "" (свой); нет его - бэклог по умолчанию (data.task_homes)."""
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


FIELDS = ("title", "description", "type", "priority", "assignee", "due")
NAMES = {"title": "название", "description": "описание", "type": "тип", "priority": "приоритет", "assignee": "исполнитель",
         "due": "срок", "status": "статус"}


def task_id(op):
    if not re.fullmatch(r"(?i)task-\d+", str(op.get("id") or "")):
        raise Invalid("id - вида TASK-12")
    return op["id"].upper()


def fields(op, allowed):
    extra = set(op) - {"task", "project", "direction", *allowed}
    if extra:
        raise Invalid(f"неизвестные поля: {', '.join(sorted(extra))}")
    if not all(isinstance(op.get(k, ""), str) for k in ("direction", *allowed)):
        raise Invalid("поля задачи - строки")
    if "title" in op:
        op = {**op, "title": " ".join(op["title"].split())}
        if not op["title"]:
            raise Invalid("у задачи нет названия")
    if op.get("status") and op["status"] not in STATUSES or "status" in op and not op["status"]:
        raise Invalid(f"статус - один из: {', '.join(STATUSES)}")
    if op.get("priority") and op["priority"] not in PRIORITIES:
        raise Invalid(f"приоритет - один из: {', '.join(PRIORITIES)}")
    if op.get("type") and op["type"] not in TYPES:
        raise Invalid(f"тип - один из: {', '.join(TYPES)}")
    if op.get("due") and not re.fullmatch(r"\d{4}-\d\d-\d\d", op["due"]):
        raise Invalid("срок - ГГГГ-ММ-ДД")
    if op.get("assignee") and not re.fullmatch(r"[\w.-]+", op["assignee"]):
        raise Invalid("исполнитель - имя сессии или owner")
    return op


def parse(op):
    """Пост {"task": …} -> проверенная правка; не годится - Invalid с причиной."""
    kind = op.get("task")
    if kind == "create":
        return fields({**op, "title": op.get("title", "")}, FIELDS)
    if kind == "status":
        if set(op) - {"task", "project", "direction", "id", "status"}:
            raise Invalid("status: только project, direction, id, status")
        return {**fields({**op, "status": op.get("status") or ""}, ("id", "status")), "id": task_id(op)}
    if kind == "edit":
        op = {**fields(op, ("id", "status", *FIELDS)), "id": task_id(op)}
        if not set(op) & {"status", *FIELDS}:
            raise Invalid("edit: нечего менять")
        return op
    if kind == "delete":
        if set(op) - {"task", "project", "direction", "id"}:
            raise Invalid("delete: только project, direction, id")
        return {**fields(op, ("id",)), "id": task_id(op)}
    raise Invalid("task - create, status, edit или delete")


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


def _put(lines, key, new):
    """Поле шапки key (со строками списка под ним) -> строки new на его месте; нет поля - перед ordinal или в конец."""
    at = next((i for i, ln in enumerate(lines) if ln.startswith(f"{key}:")), None)
    if at is None:
        at = next((i for i, ln in enumerate(lines) if ln.startswith("ordinal:")), len(lines))
    else:
        end = at + 1
        while end < len(lines) and re.match(r"[ \t]+- ", lines[end]):
            end += 1
        del lines[at:end]
    lines[at:at] = new


DESC = re.compile(r"\n?## Description\n\n<!-- SECTION:DESCRIPTION:BEGIN -->\n.*?\n<!-- SECTION:DESCRIPTION:END -->\n", re.S)


def edit(base, tid, op):
    """Правка полей задачи: есть ключ - поле переписано, пустая строка - поле стёрто; описание - в своей секции."""
    path = path_of(base, tid)
    _, head, body = read(path).split("---\n", 2)
    lines = head.splitlines()
    for key, field_, make in (("title", "title", lambda v: [f"title: {quote(v)}"]),
                              ("status", "status", lambda v: [f"status: {v}"]),
                              ("assignee", "assignee", lambda v: ["assignee:", f"  - '@{v}'"] if v else ["assignee: []"]),
                              ("due", "due_date", lambda v: [f"due_date: '{v}'"] if v else []),
                              ("priority", "priority", lambda v: [f"priority: {v}"] if v else []),
                              ("type", "type", lambda v: [f"type: {v}"] if v else [])):
        if key in op:
            _put(lines, field_, make(op[key]))
    _put(lines, "updated_date", [])
    at = next((i for i, ln in enumerate(lines) if ln.startswith("created_date:")), len(lines) - 1)
    lines.insert(at + 1, f"updated_date: '{now()}'")
    if "description" in op:
        text = op["description"].strip()
        section = f"\n## Description\n\n<!-- SECTION:DESCRIPTION:BEGIN -->\n{text}\n<!-- SECTION:DESCRIPTION:END -->\n" if text else ""
        body = DESC.sub(lambda _: section, body, count=1) if DESC.search(body) else section + body
    with open(path, "w", encoding="utf-8") as f:
        f.write("---\n" + "\n".join(lines) + "\n---\n" + body)


def set_status(base, tid, status):
    edit(base, tid, {"status": status})


def delete(base, tid):
    """В архив бэклога: из доски уходит, файл и номер остаются."""
    path = path_of(base, tid)
    os.makedirs(os.path.join(base, "archive", "tasks"), exist_ok=True)
    os.replace(path, os.path.join(base, "archive", "tasks", os.path.basename(path)))


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
