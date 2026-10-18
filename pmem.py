"""Память проекта из сессии.

  pmem.py show [<проект>]          память проекта (без имени - проект текущей папки; не нашёлся - все этапы)
  pmem.py set <проект> [--stage Разработка] [--note "<пояснение этапа>"] [--goal "<цель>"]
                       [--add "<пункт>"]… [--done "<пункт или его начало>"]… [--undone "<пункт>"]…
                       [--questions "<открытые вопросы>"] [--kind app|site|legal|invite|sandbox|research|other]
                       [--store "<загрузки и выручка из магазина, коротко>"]
  pmem.py set <проект> --link <направление> | --unlink <направление>   привязать к проекту направление с другим репо
  pmem.py task list <проект> [--direction <направление>|""]   задачи проекта по бэклогам: свой и каждого живого
                                   направления; проект «-» - задачи без проекта (общий бэклог владельца)
  pmem.py task new <проект> "<название>" [-d "<описание>"] [--type story|task|bug] [--priority high|medium|low]
                       [--to <сессия>|owner] [--due ГГГГ-ММ-ДД] [--direction <направление>|""]
  pmem.py task status <проект> <TASK-N> "To Do"|"In Progress"|Done [--direction <направление>|""]
У проекта с несколькими направлениями номер задачи - внутри бэклога: укажи --direction ("" - свой бэклог проекта);
без него - бэклог по умолчанию (единственного живого направления, иначе свой).
Этапы: Кандидат, Разработка, К релизу, В сторе, Пауза, Готово. Тип: на доске по этапам - только приложения (app, без
отметки - тоже app). Правка уходит постом в канал плагина от имени сессии
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


def memories(state):
    try:
        with open(os.path.join(state, "projects-memory", "memory.json"), encoding="utf-8") as f:
            return json.load(f)["projects"]
    except (OSError, ValueError, KeyError):
        return {}


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
              f"У {name} памяти ещё нет. Этап и что дальше: python3 {HERE}/pmem.py set {name} --stage … --note … --add …"
              " (цель - только со слов владельца)")
        return
    mems = memories(state)
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
    if a.project != tasks.GENERAL and a.project not in known:
        sys.exit(f"нет проекта {a.project} (hub projects)")
    if a.op == "list":
        import data
        h = data.task_homes(state, {k: v for k, v in known.items() if v}, None, memories(state))[a.project]
        for key, home in h["paths"].items():
            if a.direction is not None and key != a.direction:
                continue
            items = tasks.read_all(home)
            where = f"направление {key}" if key else "без проекта" if a.project == tasks.GENERAL else "свой бэклог проекта"
            print(f"== {where}{' (по умолчанию)' if key == h['default'] and len(h['paths']) > 1 else ''}: {home}")
            for st, name in tasks.STATUSES.items():
                mine = sorted((t for t in items if t["status"] == st), key=lambda t: t["ordinal"])
                print(f"{name} ({len(mine)})")
                for t in mine:
                    extra = ", ".join(x for x in (t["priority"], t["assignee"] and "@" + t["assignee"], t["due"] and "до " + t["due"]) if x)
                    print(f"  {t['id']:9} {t['title']}" + (f"  [{extra}]" if extra else ""))
            print()
        return
    op = {"task": "create", "project": a.project, "title": " ".join(a.rest)} if a.op == "new" else \
        {"task": "status", "project": a.project, "id": (a.rest or [""])[0], "status": " ".join(a.rest[1:])}
    if a.direction is not None:
        op["direction"] = a.direction
    elif a.project != tasks.GENERAL:
        import data
        dirs = [k for k in data.task_homes(state, {k: v for k, v in known.items() if v}, None, memories(state))[a.project]["paths"] if k]
        if len(dirs) > 1:
            sys.exit(f"у {a.project} несколько направлений ({', '.join(dirs)}): укажи --direction <направление> или --direction \"\" (свой бэклог)")
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
    for k in ("stage", "note", "goal", "questions", "link", "unlink", "kind", "store"):
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
    s.add_argument("--kind", choices=memory.KINDS)
    s.add_argument("--store")
    s.add_argument("--add", action="append")
    s.add_argument("--done", action="append")
    s.add_argument("--undone", action="append")
    s.add_argument("--link")
    s.add_argument("--unlink")
    s = sub.add_parser("task")
    s.add_argument("op", choices=["list", "new", "status"])
    s.add_argument("project")
    s.add_argument("rest", nargs="*")
    s.add_argument("-d")
    s.add_argument("--type", choices=tasks.TYPES)
    s.add_argument("--priority", choices=tasks.PRIORITIES)
    s.add_argument("--to")
    s.add_argument("--due")
    s.add_argument("--direction")
    a = p.parse_args()
    {"show": lambda: show(a.project), "set": lambda: set_(a), "task": lambda: task(a)}[a.cmd]()


if __name__ == "__main__":
    main()
