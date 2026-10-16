"""Процесс плагина «Статус проектов»: сворачивает правки памяти проектов из канала плагина в файл и отдаёт данные
вида странице на порту «порт страницы + 12» (только своей странице: проверка Origin)."""
import http.server
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import data  # noqa: E402
import memory  # noqa: E402
import repo  # noqa: E402
import tasks  # noqa: E402

PLUGIN = "projects-status"
WEB_PORT = int(os.environ.get("HUB_WEB_PORT", "8787"))
PORT = WEB_PORT + 12
STATE = os.environ.get("HUB_STATE_DIR") or os.path.expanduser("~/.hub-core")
HOME = os.path.join(STATE, "projects-memory")   # memory.json и <проект>.md - читают сессии
HERE = os.path.dirname(os.path.abspath(__file__))
lock = threading.Lock()
REPOS = repo.Repos()


def projects():
    from core import catalog
    return catalog.load_config(STATE).get("projects") or {}


def load():
    try:
        with open(os.path.join(HOME, "memory.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"last": 0, "projects": {}, "refused": []}


def save(st, touched, cfg):
    os.makedirs(HOME, exist_ok=True)
    tmp = os.path.join(HOME, "memory.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(HOME, "memory.json"))
    for name in touched - {tasks.GENERAL}:
        text = memory.render_md(name, (cfg.get(name) or {}).get("about"), st["projects"][name]).replace("{plugin}", HERE)
        with open(os.path.join(HOME, f"{name}.md"), "w", encoding="utf-8") as f:
            f.write(text)


def fold(st, posts, known, homes=None):
    """Новые посты канала (номер больше уже свёрнутого) -> память и задачи; плохой пост - в refused с причиной."""
    touched = set()
    for p in posts:
        n = int(p["id"][1:])
        if n <= st["last"]:
            continue
        st["last"] = n
        try:
            op = json.loads(p["text"])
            if isinstance(op, dict) and "task" in op:
                name = op.get("project")
                if name != tasks.GENERAL and name not in known:
                    raise tasks.Invalid(f"нет проекта {name!r} (hub projects)")
                op, h = tasks.parse(op), homes[name]
                key = op.get("direction", h["default"])
                if key not in h["paths"]:
                    raise tasks.Invalid(f"у проекта {name} нет направления {key}")
                what = task(op, h["paths"][key])
                log = st.setdefault("general", []) if name == tasks.GENERAL else \
                    st["projects"].setdefault(name, memory.empty())["history"]
                log.append({"ts": p["ts"], "by": p["by"], "what": what})
                del log[:-50]
                touched.add(name)
                continue
            upd = memory.parse(p["text"], known)
        except (ValueError, OSError) as e:
            why = "не JSON" if type(e) is json.JSONDecodeError else str(e)
            st["refused"] = (st.get("refused") or [])[-19:] + [{"id": p["id"], "by": p["by"], "why": why, "ts": p["ts"]}]
            continue
        mem = st["projects"].setdefault(upd["project"], memory.empty())
        if memory.apply(mem, upd, p["by"], p["ts"]):
            touched.add(upd["project"])
    return touched


def task(op, base):
    """Правка задачи -> строка истории карточки."""
    if op["task"] == "create":
        tid = tasks.create(base, op)
        who = memory.who(op.get("assignee")) if op.get("assignee") else ""
        return f"задача {tid} «{op['title'][:80]}» заведена" + (f", исполнитель - {who}" if who else "")
    if op["task"] == "status":
        tasks.set_status(base, op["id"], op["status"])
        return f"задача {op['id']}: {tasks.STATUSES[op['status']]}"
    if op["task"] == "delete":
        title = next((t["title"] for t in tasks.read_all(base) if t["id"] == op["id"]), "")
        tasks.delete(base, op["id"])
        return f"задача {op['id']} «{title[:80]}» удалена (лежит в архиве бэклога)"
    tasks.edit(base, op["id"], op)
    return f"задача {op['id']} изменена: " + ", ".join(tasks.NAMES[k] for k in tasks.NAMES if k in op)


def follow(st):
    from core.tail import Tail
    tail = Tail(os.path.join(STATE, "journal.jsonl"))
    while True:
        try:
            tail.poll()
            posts = (tail.reader.state.get("feeds") or {}).get(PLUGIN) or []
            cfg = projects()
            fresh = [p for p in posts if int(p["id"][1:]) > st["last"]]
            known = data.known(STATE, cfg) if fresh else set()
            with lock:
                mems = json.loads(json.dumps(st["projects"])) if fresh else {}
            homes = data.task_homes(STATE, cfg, None, mems) if fresh else {}
            with lock:
                touched = fold(st, fresh, known, homes)
                if touched or not os.path.exists(os.path.join(HOME, "memory.json")):
                    save(st, touched, cfg)
        except Exception as e:  # noqa: BLE001 - журнал на ротации, настройки на записи: попробуем снова
            print(f"{PLUGIN}: {e!r}", flush=True)
        time.sleep(2)


def watch_repos(st):
    """Состояние репо проектов в кэш: страница читает его, а не git на каждый запрос."""
    while True:
        try:
            with lock:
                mems = json.loads(json.dumps(st["projects"]))
            got = data.collect(STATE, projects(), mems)["projects"]
            REPOS.refresh([r for p in got for r in p["roots"]])
        except Exception as e:  # noqa: BLE001 - настройки на записи, репо переезжает: попробуем снова
            print(f"{PLUGIN}: репо: {e!r}", flush=True)
        time.sleep(15)


def handler(st):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            origin = self.headers.get("Origin") or ""
            if origin not in (f"http://127.0.0.1:{WEB_PORT}", f"http://localhost:{WEB_PORT}"):
                self.send_response(403)
                self.end_headers()
                return
            with lock:
                mems = json.loads(json.dumps(st["projects"]))
                refused = list(st.get("refused") or [])
            body = json.dumps({**data.collect(STATE, projects(), mems, REPOS.get), "refused": refused[-5:], "at": time.time(), "plugin": HERE},
                              ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    return H


def main():
    st = load()
    threading.Thread(target=follow, args=(st,), daemon=True).start()
    threading.Thread(target=watch_repos, args=(st,), daemon=True).start()
    print(f"{PLUGIN}: страница - 127.0.0.1:{PORT}, память - {HOME}", flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler(st)).serve_forever()


if __name__ == "__main__":
    main()
