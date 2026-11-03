"""Задачи хаба по ключу Jira: записи `<state>/tasks/dN.md` (их пишет ядро и сессии через `hub task note`).

Ключ в заголовке или разделе «Задача» - задача ведёт этот ключ (lead); только в «Ходе» - упоминание. Без модели: регулярки
по тексту; файл перечитывается, только если сменился mtime."""
import datetime
import glob
import os
import re

HEAD = re.compile(r"^# (d\d+) [—-] (.*)$")
BY = re.compile(r"^Поставил: (.+?) · делает: (.+)$")
LINE = re.compile(r"^- (\d\d)\.(\d\d) (\d\d):(\d\d) · ([^:]{1,60}): (.*)$")
CORE = "ядро"
LOG_SHOWN = 10
MANY = 4
BODY_KEYS = 2


def when(day, month, hh, mm, ref):
    """«03.11 08:08» без года -> ts: год записи (по mtime), а дата позже записи на сутки - прошлый год."""
    ref_d = datetime.datetime.fromtimestamp(ref)
    try:
        d = datetime.datetime(ref_d.year, int(month), int(day), int(hh), int(mm))
    except ValueError:
        return None
    if d.timestamp() > ref + 86400:
        d = d.replace(year=d.year - 1)
    return d.timestamp()


def parse(text, mtime):
    """Запись задачи -> {id, title, by, doer, closed, lines: [{ts, who, text}], head, body} или None."""
    lines = text.splitlines()
    m = HEAD.match(lines[0]) if lines else None
    if not m:
        return None
    out = {"id": m.group(1), "title": m.group(2).strip(), "by": "", "doer": "", "closed": False, "lines": [], "body": ""}
    sec, body = None, []
    for ln in lines[1:]:
        b = BY.match(ln)
        if b and sec is None:
            out["by"], out["doer"] = b.group(1).strip(), b.group(2).strip()
            continue
        if ln.startswith("## "):
            sec = ln[3:].strip()
            continue
        if sec == "Задача":
            body.append(ln)
        elif sec == "Ход":
            x = LINE.match(ln)
            if x:
                who, said = x.group(5).strip(), x.group(6).strip()
                if who == CORE and (said.startswith("задача закрыта") or re.match(r"[\w.-]+ сдал и уснул", said)):
                    out["closed"] = True
                elif who == CORE and (said.startswith(("задача поставлена", "задача снова открыта", "задача открыта"))
                                      or re.match(r"[\w.-]+ разбужен", said)):
                    out["closed"] = False
                out["lines"].append({"ts": when(*x.groups()[:4], mtime), "who": who, "text": said})
            elif out["lines"] and ln.strip() and not ln.startswith("("):
                out["lines"][-1]["text"] += " " + ln.strip()
    out["body"] = "\n".join(body)
    return out


def key_re(projects):
    ks = [k for k in projects if re.fullmatch(r"[A-Z][A-Z0-9_]{0,19}", k)]
    return re.compile(rf"\b(?:{'|'.join(sorted(ks, key=len, reverse=True))})-\d+\b") if ks else None


def last_step(t):
    """Последняя строка хода не от ядра (итог - без приставки «итог:»)."""
    for ln in reversed(t["lines"]):
        if ln["who"] != CORE:
            return {**ln, "text": re.sub(r"^итог:\s*", "", ln["text"])[:300]}
    return None


class Index:
    def __init__(self, state):
        self.dir = os.path.join(state, "tasks")
        self.cache = {}   # путь -> (mtime, разбор)

    def scan(self):
        seen = set()
        for path in glob.glob(os.path.join(self.dir, "d*.md")):
            seen.add(path)
            try:
                mt = os.stat(path).st_mtime
            except OSError:
                continue
            if path in self.cache and self.cache[path][0] == mt:
                continue
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    self.cache[path] = (mt, parse(f.read(), mt))
            except OSError:
                continue
        for p in [p for p in self.cache if p not in seen]:
            del self.cache[p]
        return [t for _, t in self.cache.values() if t]

    def by_key(self, projects):
        """{ключ: [задача хаба]} - ведущие и упоминания; у каждой role, последний шаг и до 10 строк хода."""
        rx = key_re(projects)
        if not rx:
            return {}
        out = {}
        for t in self.scan():
            head, body = set(rx.findall(t["title"])), set(rx.findall(t["body"]))
            # ключ в заголовке ведёт; в тексте задачи - только если ключей там один-два, иначе это перечень примеров
            lead = head if head else body if len(body) <= BODY_KEYS else set()
            log = (head | body) - lead
            if len(lead) > MANY:   # задача про доску или сводку с перечнем ключей ни одну из них не ведёт
                log, lead = log | lead, set()
            for ln in t["lines"]:
                log.update(rx.findall(ln["text"]))
            for k in lead | log:
                step = last_step(t)
                out.setdefault(k, []).append({
                    "id": t["id"], "title": t["title"][:160], "by": t["by"], "doer": t["doer"], "closed": t["closed"],
                    "role": "lead" if k in lead else "mention", "last": step,
                    "handed": bool(step and step["who"] == t["doer"] and re.match(r"итог:", next(
                        ln["text"] for ln in reversed(t["lines"]) if ln["who"] != CORE))),
                    "at": max([ln["ts"] or 0 for ln in t["lines"]] or [0]),
                    "log": [{**ln, "text": ln["text"][:240]} for ln in t["lines"] if ln["who"] != CORE][-LOG_SHOWN:]
                    if k in lead else [],
                })
        for k in out:
            out[k].sort(key=lambda x: (x["role"] != "lead", -(x["at"] or 0)))
            out[k] = out[k][:12]
        return out
