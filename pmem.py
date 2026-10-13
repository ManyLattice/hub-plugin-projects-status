"""Память проекта из сессии.

  pmem.py show [<проект>]          память проекта (без имени - проект текущей папки; не нашёлся - все этапы)
  pmem.py set <проект> [--stage Разработка] [--note "<пояснение этапа>"] [--goal "<цель>"]
                       [--add "<пункт>"]… [--done "<пункт или его начало>"]… [--undone "<пункт>"]…
                       [--questions "<открытые вопросы>"]
  pmem.py task list <проект>       задачи проекта по статусам (бэклог направления или свой бэклог проекта)
  pmem.py task new <проект> "<название>" [-d "<описание>"] [--type story|task|bug] [--priority high|medium|low]
                       [--to <сессия>|owner] [--due ГГГГ-ММ-ДД]
  pmem.py task status <проект> <TASK-N> "To Do"|"In Progress"|Done
Этапы: Кандидат, Разработка, К релизу, В сторе, Пауза, Готово. Правка уходит постом в канал плагина от имени сессии
(`hub post projects-status`), в истории карточки - с автором."""
import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memory  # noqa: E402
import tasks  # noqa: E402


def hub_code():
    exe = shutil.which("hub")
    if not exe:
        sys.exit("нет команды hub в PATH")
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(exe))))


def state_dir():
    hub_code()
    from core.daemon import default_state_dir
    return default_state_dir()


def projects(state):
    """Проекты из hub projects и живые направления без проекта (у них тоже есть память)."""
    from core import catalog
    import data
    known = catalog.load_config(state).get("projects") or {}
    return {**{n: {} for n in data.known(state, known)}, **known}


def show(name):
    state = state_dir()
    known = projects(state)
    if not name:
        cwd = os.path.realpath(os.getcwd())
        name = next((n for n, p in known.items() if p.get("path") and
                     (cwd + os.sep).startswith(os.path.realpath(os.path.expanduser(p["path"])) + os.sep)), None)
    home = os.path.join(state, "projects-memory")
    if name:
        path = os.path.join(home, f"{name}.md")
        if name not in known:
            sys.exit(f"нет проекта {name} (hub projects)")
        print(open(path, encoding="utf-8").read() if os.path.exists(path) else
              f"У {name} памяти ещё нет. Заполнить: python3 {HERE}/pmem.py set {name} --stage … --goal …")
        return
    try:
        mems = json.load(open(os.path.join(home, "memory.json"), encoding="utf-8"))["projects"]
    except (OSError, ValueError, KeyError):
        mems = {}
    for n in known:
        m = mems.get(n) or {}
        print(f"{n:22} {m.get('stage') or '-':11} {m.get('note') or ''}")


def send(text):
    if len(text) > memory.LIMIT:
        sys.exit(f"правка длиннее {memory.LIMIT} знаков - сократи")
    r = subprocess.run(["hub", "post", "projects-status", text], capture_output=True, text=True)
    print((r.stdout + r.stderr).strip() or "принято")
    sys.exit(r.returncode)


def task(a):
    state = state_dir()
    known = projects(state)
    if a.project not in known:
        sys.exit(f"нет проекта {a.project} (hub projects)")
    if a.op == "list":
        import data
        home = data.task_homes(state, {k: v for k, v in known.items() if v})[a.project]
        items = tasks.read_all(home)
        print(f"{a.project}: {home}")
        for st, name in tasks.STATUSES.items():
            mine = sorted((t for t in items if t["status"] == st), key=lambda t: t["ordinal"])
            print(f"\n{name} ({len(mine)})")
            for t in mine:
                extra = ", ".join(x for x in (t["priority"], t["assignee"] and "@" + t["assignee"], t["due"] and "до " + t["due"]) if x)
                print(f"  {t['id']:9} {t['title']}" + (f"  [{extra}]" if extra else ""))
        return
    op = {"task": "create", "project": a.project, "title": " ".join(a.rest)} if a.op == "new" else \
        {"task": "status", "project": a.project, "id": (a.rest or [""])[0], "status": " ".join(a.rest[1:])}
    for k, v in (("description", a.d), ("type", a.type), ("priority", a.priority), ("assignee", a.to), ("due", a.due)):
        if v and a.op == "new":
            op[k] = v
    try:
        tasks.parse(op)
    except tasks.Invalid as e:
        sys.exit(f"не принято: {e}")
    send(json.dumps(op, ensure_ascii=False))


def set_(a):
    upd = {"project": a.project}
    for k in ("stage", "note", "goal", "questions"):
        if getattr(a, k) is not None:
            upd[k] = getattr(a, k)
    for k in ("add", "done", "undone"):
        if getattr(a, k):
            upd[k] = getattr(a, k)
    text = json.dumps(upd, ensure_ascii=False)
    state = state_dir()
    try:
        memory.parse(text, projects(state))
    except memory.Invalid as e:
        sys.exit(f"не принято: {e}")
    send(text)


def main():
    p = argparse.ArgumentParser(prog="pmem.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show")
    s.add_argument("project", nargs="?")
    s = sub.add_parser("set")
    s.add_argument("project")
    s.add_argument("--stage", choices=memory.STAGES)
    s.add_argument("--note")
    s.add_argument("--goal")
    s.add_argument("--questions")
    s.add_argument("--add", action="append")
    s.add_argument("--done", action="append")
    s.add_argument("--undone", action="append")
    s = sub.add_parser("task")
    s.add_argument("op", choices=["list", "new", "status"])
    s.add_argument("project")
    s.add_argument("rest", nargs="*")
    s.add_argument("-d")
    s.add_argument("--type", choices=tasks.TYPES)
    s.add_argument("--priority", choices=tasks.PRIORITIES)
    s.add_argument("--to")
    s.add_argument("--due")
    a = p.parse_args()
    {"show": lambda: show(a.project), "set": lambda: set_(a), "task": lambda: task(a)}[a.cmd]()


if __name__ == "__main__":
    main()
