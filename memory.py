"""Память проекта: этап, цель, что дальше, открытые вопросы и история правок с автором.

Правка - пост в канал плагина (`hub post projects-status '<json>'`): автора ставит ядро, подделать нельзя. Процесс
плагина сворачивает посты в файл состояния и пишет каждому проекту `<проект>.md` - его читают сессии."""
import datetime
import json
import re

STAGES = ["Кандидат", "Разработка", "К релизу", "В сторе", "Пауза", "Готово"]
# тип проекта: на доске по этапам - только приложения; без отметки - приложение (кандидаты от ресёрча попадают сами)
KINDS = ["app", "site", "legal", "invite", "sandbox", "research", "other"]
KEYS = {"project", "stage", "note", "goal", "next", "add", "done", "undone", "questions", "link", "unlink", "kind", "store"}
LIMIT = 2000   # пост в канал плагина - до 2000 знаков (core/reducer.py _ext_post)


class Invalid(ValueError):
    pass


def parse(text, projects):
    """Текст поста -> правка {project, ...}; не правка памяти - Invalid с причиной."""
    try:
        upd = json.loads(text)
    except ValueError:
        raise Invalid("не JSON")
    if not isinstance(upd, dict):
        raise Invalid("ждём объект JSON")
    extra = set(upd) - KEYS
    if extra:
        raise Invalid(f"неизвестные поля: {', '.join(sorted(extra))}")
    if upd.get("project") not in projects:
        raise Invalid(f"нет проекта {upd.get('project')!r} (hub projects)")
    if "stage" in upd and upd["stage"] not in STAGES:
        raise Invalid(f"этап - один из: {', '.join(STAGES)}")
    if "kind" in upd and upd["kind"] not in KINDS:
        raise Invalid(f"тип - один из: {', '.join(KINDS)}")
    for k in ("link", "unlink"):
        if k in upd and not (isinstance(upd[k], str) and re.fullmatch(r"[\w.-]+", upd[k])):
            raise Invalid(f"{k} - имя направления")
    for k in ("note", "goal", "questions", "store"):
        if k in upd and not isinstance(upd[k], str):
            raise Invalid(f"{k} - строка")
    for k in ("add", "done", "undone"):
        if k in upd and not (isinstance(upd[k], list) and all(isinstance(x, str) and x.strip() for x in upd[k])):
            raise Invalid(f"{k} - список строк")
    if "next" in upd:
        items = upd["next"]
        if not isinstance(items, list) or not all(isinstance(x, (str, dict)) for x in items):
            raise Invalid("next - список пунктов")
        upd["next"] = [{"text": str(x if isinstance(x, str) else x.get("text") or "").strip(),
                        "done": bool(isinstance(x, dict) and x.get("done"))} for x in items]
        if not all(x["text"] for x in upd["next"]):
            raise Invalid("пустой пункт в next")
    if len(upd) == 1:
        raise Invalid("нечего менять: stage, note, goal, next, add, done, undone, questions, link, unlink, kind, store")
    return upd


def empty():
    return {"stage": None, "kind": None, "note": "", "goal": "", "next": [], "questions": "", "links": [], "store": "",
            "store_at": None, "updated": None, "by": None, "history": []}


def _find(items, text):
    t = text.strip().lower()
    return next((x for x in items if x["text"].lower() == t), None) or \
        next((x for x in items if x["text"].lower().startswith(t)), None)


def apply(mem, upd, by, ts):
    """Правка -> что изменилось (строки для истории); mem меняется на месте."""
    what = []
    if "stage" in upd and upd["stage"] != mem["stage"]:
        what.append(f"этап {mem['stage'] or '-'} → {upd['stage']}")
        mem["stage"] = upd["stage"]
    if "kind" in upd and upd["kind"] != mem.get("kind"):
        mem["kind"] = upd["kind"]
        what.append(f"тип: {upd['kind']}")
    if "store" in upd and upd["store"].strip() != (mem.get("store") or ""):
        mem["store"], mem["store_at"] = upd["store"].strip(), ts
        what.append(f"магазин: {mem['store'][:80]}" if mem["store"] else "магазин снято")
    for k, name in (("note", "пояснение этапа"), ("goal", "цель"), ("questions", "открытые вопросы")):
        if k in upd and upd[k].strip() != mem[k]:
            mem[k] = upd[k].strip()
            what.append(f"{name}: {mem[k][:80]}" if mem[k] else f"{name} снято")
    if "next" in upd and upd["next"] != mem["next"]:
        mem["next"] = upd["next"]
        what.append(f"«Что дальше» переписано, пунктов: {len(mem['next'])}")
    links = mem.setdefault("links", [])
    if upd.get("link") and upd["link"] not in links:
        links.append(upd["link"])
        what.append(f"направление {upd['link']} привязано")
    if upd.get("unlink") in links:
        links.remove(upd["unlink"])
        what.append(f"направление {upd['unlink']} отвязано")
    for t in upd.get("add") or []:
        if not _find(mem["next"], t):
            mem["next"].append({"text": t.strip(), "done": False})
            what.append(f"«Что дальше» + {t.strip()[:80]}")
    for key, flag, word in (("done", True, "сделано"), ("undone", False, "снова в работе")):
        for t in upd.get(key) or []:
            item = _find(mem["next"], t)
            if item and item["done"] != flag:
                item["done"] = flag
                what.append(f"«Что дальше» - {item['text'][:60]}: {word}")
    if what:
        mem["updated"], mem["by"] = ts, by
        mem["history"].append({"ts": ts, "by": by, "what": "; ".join(what)})
        del mem["history"][:-50]
    return what


def who(by):
    return "владелец" if by == "owner" else (by or "-")


def render_md(name, about, mem):
    """Память проекта для сессий: `cat <state>/projects-memory/<проект>.md`."""
    at = lambda ts: datetime.datetime.fromtimestamp(ts).strftime("%d.%m %H:%M")   # noqa: E731
    out = [f"# Память проекта {name}", ""]
    if about:
        out += [about, ""]
    out.append(f"Этап: {mem['stage'] or '-'}" + (f" - {mem['note']}" if mem["note"] else ""))
    if mem.get("kind"):
        out.append(f"Тип: {mem['kind']}")
    if mem.get("store"):
        out.append(f"Магазин ({at(mem['store_at'])}): {mem['store']}" if mem.get("store_at") else f"Магазин: {mem['store']}")
    out += ["", "## Цель", mem["goal"] or "(не заполнена)", "", "## Что дальше"]
    out += [f"- [{'x' if x['done'] else ' '}] {x['text']}" for x in mem["next"]] or ["(пусто)"]
    if mem["questions"]:
        out += ["", "## Открытые вопросы", mem["questions"]]
    if mem["history"]:
        out += ["", "## История"] + [f"- {at(h['ts'])} {who(h['by'])}: {h['what']}" for h in mem["history"][-10:][::-1]]
    out += ["", f"Править: python3 {{plugin}}/pmem.py set {name} --stage … --note … --add … --done … (--goal - только со слов владельца)"]
    return "\n".join(out) + "\n"
