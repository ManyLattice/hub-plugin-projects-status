"""Доска Jira для вида «Jira»: процесс плагина только читает Jira REST (GET) своим токеном и отдаёт странице поля задач.

Настройки у каждого свои (шестерёнка вида): адрес Jira (по умолчанию - раздел jira.url настроек хаба), email, доска
(из списка досок, которые видит токен), проект (ключ, необязательно). Лежат в `<state>/projects-status/jira.json`;
токен - только в связке ключей (keystore). Адрес вида https://<сайт>.atlassian.net: классический токен ходит прямо на
сайт, токен с правами (scopes) - через шлюз api.atlassian.com/ex/jira/<cloudId>; какой путь сработал, процесс помнит
до перезапуска."""
import base64
import datetime
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import keystore

GATEWAY = os.environ.get("PST_JIRA_GATEWAY", "https://api.atlassian.com")
EVERY = 120            # задачи доски
CONFIG_EVERY = 1800    # колонки доски
SPRINT_EVERY = 600
DONE_DAYS = 14         # последняя колонка («Готово») - только сдвинутые за 14 дней
COMMENTS_PER_CYCLE = 40
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,19}$")
SCOPES = {
    "myself": "read:jira-user",
    "boards": "read:board-scope:jira-software, read:project:jira",
    "config": "read:board-scope.admin:jira-software, read:project:jira",
    "issues": "read:board-scope:jira-software, read:issue-details:jira",
    "sprints": "read:sprint:jira-software",
    "comments": "read:jira-work (или read:comment:jira)",
}


class JiraError(RuntimeError):
    def __init__(self, status, text):
        super().__init__(text)
        self.status = status


def why(status, what=""):
    if status == 401:
        return "токен не подходит: истёк, отозван или выдан другому email"
    if status == 403:
        return "у токена нет прав" + (f": нужно {SCOPES[what]}" if what in SCOPES else "")
    if status == 404:
        return "не найдено: нет такой доски или у токена нет к ней доступа"
    if status == 429:
        return "Jira просит реже: лимит запросов"
    if status is None:
        return "Jira не отвечает"
    return f"Jira ответила {status}"


def site_of(url):
    u = urllib.parse.urlsplit((url or "").strip())
    if u.scheme not in ("https", "http") or not u.netloc:
        return None
    if u.scheme == "http" and u.hostname not in ("127.0.0.1", "localhost"):
        return None
    return f"{u.scheme}://{u.netloc}"


# --- настройки -------------------------------------------------------------------------------------------------------
def settings_path(state):
    return os.path.join(state, "projects-status", "jira.json")


def load_settings(state):
    try:
        with open(settings_path(state), encoding="utf-8") as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(state, s):
    p = settings_path(state)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    os.replace(p + ".tmp", p)


def clean(form, default_url=""):
    """Форма шестерёнки -> настройки без токена; плохое поле - ValueError с причиной."""
    url = site_of(form.get("url") or default_url)
    if not url:
        raise ValueError("адрес Jira - https://<сайт>.atlassian.net")
    email = str(form.get("email") or "").strip()
    if not re.fullmatch(r"[^\s@\"'\\]+@[^\s@\"'\\]+", email):
        raise ValueError("email - тот, с которым создан токен")
    board = form.get("board")
    if board not in (None, ""):
        board = int(board) if str(board).isdigit() else None
        if board is None:
            raise ValueError("доска - номер из списка")
    project = str(form.get("project") or "").strip().upper()
    if project and not KEY_RE.fullmatch(project):
        raise ValueError("проект - ключ Jira, например ABC")
    return {"url": url, "email": email, "board": board or None, "board_name": str(form.get("board_name") or "")[:120],
            "project": project}


# --- REST -----------------------------------------------------------------------------------------------------------
def _open(req, timeout):
    return urllib.request.urlopen(req, timeout=timeout)


class Client:
    def __init__(self, url, email, token, opener=_open, base=None):
        self.site = site_of(url)
        self.auth = "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()
        self.opener = opener
        self.base = base

    def _get(self, base, path, params=None):
        q = ("?" + urllib.parse.urlencode(params)) if params else ""
        req = urllib.request.Request(base + path + q, headers={"Authorization": self.auth, "Accept": "application/json"})
        try:
            with self.opener(req, 30) as r:
                return json.loads(r.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as e:
            raise JiraError(e.code, f"{path}: {e.code}") from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise JiraError(None, f"{path}: {type(e).__name__}") from None

    def cloud_id(self):
        req = urllib.request.Request(self.site + "/_edge/tenant_info", headers={"Accept": "application/json"})
        try:
            with self.opener(req, 15) as r:
                return (json.loads(r.read().decode("utf-8")) or {}).get("cloudId")
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def connect(self):
        """Кто вы (/myself): сначала прямо на сайт (классический токен), на 401 - через шлюз (токен с правами)."""
        if self.base:
            return self._get(self.base, "/rest/api/2/myself")
        try:
            me = self._get(self.site, "/rest/api/2/myself")
            self.base = self.site
            return me
        except JiraError as e:
            if e.status not in (401, 403, 404):
                raise
            cid = self.cloud_id()
            if not cid:
                raise
            gw = f"{GATEWAY}/ex/jira/{cid}"
            me = self._get(gw, "/rest/api/2/myself")
            self.base = gw
            return me

    def get(self, path, params=None):
        if not self.base:
            self.connect()
        return self._get(self.base, path, params)

    def boards(self, project=""):
        out, start = [], 0
        while True:
            p = {"startAt": start, "maxResults": 50, **({"projectKeyOrId": project} if project else {})}
            page = self.get("/rest/agile/1.0/board", p) or {}
            vals = page.get("values") or []
            out += [{"id": b.get("id"), "name": b.get("name") or "", "type": b.get("type") or "",
                     "project": ((b.get("location") or {}).get("projectKey") or "")} for b in vals]
            start += len(vals)
            if page.get("isLast", True) or not vals or start >= 500:
                return out

    def config(self, board):
        c = self.get(f"/rest/agile/1.0/board/{board}/configuration") or {}
        cols = [{"name": col.get("name") or "", "statuses": [str(s.get("id")) for s in col.get("statuses") or []]}
                for col in ((c.get("columnConfig") or {}).get("columns") or [])]
        cols = [x for x in cols if x["statuses"]]
        est = ((c.get("estimation") or {}).get("field") or {})
        return {"name": c.get("name") or "", "columns": cols, "sp_field": est.get("fieldId") or "",
                "sp_name": est.get("displayName") or ""}

    def sprints(self, board):
        try:
            page = self.get(f"/rest/agile/1.0/board/{board}/sprint", {"state": "active,future", "maxResults": 50}) or {}
        except JiraError as e:
            if e.status == 400:   # канбан: у доски нет спринтов
                return None
            raise
        return [{"id": s.get("id"), "name": s.get("name") or "", "state": s.get("state") or "",
                 "end": s.get("endDate") or "", "start": s.get("startDate") or ""} for s in page.get("values") or []]

    def issues(self, board, cfg, project=""):
        last = cfg["columns"][-1]["statuses"] if cfg["columns"] else []
        jql = (f"status not in ({','.join(last)}) OR updated >= -{DONE_DAYS}d") if last else f"updated >= -{DONE_DAYS}d"
        if project:
            jql = f"project = {project} AND ({jql})"
        fields = ["summary", "status", "issuetype", "assignee", "labels", "updated", "created", "statusCategoryChangedDate",
                  "parent", "sprint", "epic", "priority"] + ([cfg["sp_field"]] if cfg.get("sp_field") else [])
        out, start = [], 0
        while True:
            page = self.get(f"/rest/agile/1.0/board/{board}/issue",
                            {"jql": jql, "fields": ",".join(fields), "startAt": start, "maxResults": 100}) or {}
            vals = page.get("issues") or []
            out += vals
            start += len(vals)
            if not vals or start >= (page.get("total") or 0) or start >= 1000:
                return out

    def comments(self, key, n=5):
        page = self.get(f"/rest/api/2/issue/{urllib.parse.quote(key)}/comment", {"orderBy": "-created", "maxResults": n}) or {}
        out = [{"author": ((c.get("author") or {}).get("displayName") or ""), "ts": ts(c.get("created")),
                "text": plain(c.get("body"))} for c in page.get("comments") or []]
        return sorted(out, key=lambda c: -(c["ts"] or 0))[:n]


# --- разбор ---------------------------------------------------------------------------------------------------------
def ts(s):
    if not s:
        return None
    try:
        return datetime.datetime.strptime(re.sub(r"(\.\d+)?([+-]\d\d):?(\d\d)$", r"\2\3", s), "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except ValueError:
        try:
            return datetime.datetime.strptime(s[:10], "%Y-%m-%d").timestamp()
        except ValueError:
            return None


def plain(body):
    """Текст комментария (вики-разметка v2 или ADF v3) -> одна строка без разметки."""
    if isinstance(body, dict):
        parts = []

        def walk(n):
            if isinstance(n, dict):
                if n.get("type") == "text":
                    parts.append(n.get("text") or "")
                elif n.get("type") == "mention":
                    parts.append((n.get("attrs") or {}).get("text") or "")
                for c in n.get("content") or []:
                    walk(c)
                if n.get("type") in ("paragraph", "heading", "listItem"):
                    parts.append(" ")
        walk(body)
        body = "".join(parts)
    s = str(body or "")
    s = re.sub(r"\[~accountid:[^\]]+\]", "@", s)
    s = re.sub(r"\[([^|\]]+)\|[^\]]+\]", r"\1", s)
    s = re.sub(r"\{(code|noformat|quote|color)[^}]*\}", "", s)
    s = re.sub(r"(^|\s)[*_+-]([^\s*_+-][^*_+]*?)[*_+-](?=[\s.,;:!?)]|$)", r"\1\2", s)
    s = re.sub(r"^h\d\.\s*", "", s, flags=re.M)
    return " ".join(s.split())[:400]


def kind(issuetype):
    n = (issuetype.get("name") or "").lower()
    if issuetype.get("hierarchyLevel", 0) and issuetype.get("hierarchyLevel", 0) >= 1 or n in ("epic", "эпик"):
        return "epic"
    if n in ("story", "история", "user story"):
        return "story"
    if n in ("bug", "ошибка", "баг", "defect"):
        return "bug"
    if issuetype.get("subtask") or n in ("sub-task", "subtask", "подзадача"):
        return "sub"
    return "task"


def issue(raw, sp_field=""):
    f = raw.get("fields") or {}
    st, ty, a = f.get("status") or {}, f.get("issuetype") or {}, f.get("assignee") or {}
    sp = f.get(sp_field) if sp_field else None
    sprint = f.get("sprint") or None
    parent, epic = f.get("parent") or {}, f.get("epic") or {}
    ep = epic or (parent if ((parent.get("fields") or {}).get("issuetype") or {}).get("hierarchyLevel", 0) == 1 else {})
    return {
        "key": raw.get("key") or "", "summary": f.get("summary") or "", "type": kind(ty), "type_name": ty.get("name") or "",
        "status": {"id": str(st.get("id") or ""), "name": st.get("name") or "",
                   "cat": ((st.get("statusCategory") or {}).get("key") or "")},
        "sp": sp if isinstance(sp, (int, float)) else None,
        "assignee": {"id": a.get("accountId") or "", "name": a.get("displayName") or ""} if a else None,
        "labels": [x for x in f.get("labels") or [] if isinstance(x, str)][:12],
        "sprint": {"id": sprint.get("id"), "name": sprint.get("name") or "", "state": sprint.get("state") or ""} if sprint else None,
        "epic": {"key": ep.get("key") or "", "name": ep.get("name") or (ep.get("fields") or {}).get("summary") or ""} if ep else None,
        "parent": parent.get("key") or "",
        "updated": ts(f.get("updated")), "created": ts(f.get("created")), "cat_changed": ts(f.get("statusCategoryChangedDate")),
    }


# --- проверка из шестерёнки -----------------------------------------------------------------------------------------
def check(s, token, opener=_open):
    """Те же запросы, что у процесса: что прошло, чего не хватает. Токен не уходит наружу ни в одном поле."""
    steps, c = [], Client(s["url"], s["email"], token, opener)

    def step(what, label, fn):
        try:
            v = fn()
            steps.append({"what": what, "label": label, "ok": True})
            return v
        except JiraError as e:
            steps.append({"what": what, "label": label, "ok": False, "status": e.status, "why": why(e.status, what),
                          "need": SCOPES.get(what, "")})
            return None
    me = step("myself", "Кто вы", c.connect)
    out = {"steps": steps, "me": None, "boards": [], "via": None}
    if me is None:
        return out
    out["me"] = {"name": me.get("displayName") or "", "id": me.get("accountId") or ""}
    out["via"] = "шлюз api.atlassian.com (токен с правами)" if c.base != c.site else "сайт Jira (классический токен)"
    if c.base == c.site and urllib.parse.urlsplit(c.site).hostname not in ("127.0.0.1", "localhost"):
        out["warn"] = ("Это классический токен: у него все права вашего аккаунта, в том числе на запись. Плагин только читает, "
                       "но надёжнее токен с правами только на чтение (API token with scopes, README).")
    out["boards"] = step("boards", "Доски", lambda: c.boards(s.get("project") or "")) or []
    board = s.get("board") or (out["boards"][0]["id"] if len(out["boards"]) == 1 else None)
    if not board:
        steps.append({"what": "config", "label": "Колонки доски", "ok": None, "why": "выберите доску"})
        return out
    cfg = step("config", "Колонки доски", lambda: c.config(board))
    if cfg:
        out["columns"] = [x["name"] for x in cfg["columns"]]
        got = step("issues", "Задачи доски", lambda: c.issues(board, cfg, s.get("project") or ""))
        if got is not None:
            out["issues"] = len(got)
    sp = step("sprints", "Спринты", lambda: c.sprints(board))
    if sp is not None:
        out["sprints"] = [x["name"] for x in sp if x["state"] == "active"]
    return out


# --- опрос ----------------------------------------------------------------------------------------------------------
class Board:
    """Состояние доски в памяти процесса; cycle() - один опрос, run() - раз в EVERY с."""

    def __init__(self, state, default_url=lambda: "", opener=_open, store=keystore, clock=time.time):
        self.state, self.default_url, self.opener, self.store, self.clock = state, default_url, opener, store, clock
        self.lock = threading.Lock()
        self.wake = threading.Event()
        saved = load_settings(state)
        self.data = {"state": "connecting" if saved.get("email") and saved.get("board") else "off", "at": None}
        self.client, self.cfg, self.sprints, self.me = None, None, None, None
        self.cfg_at = self.sprint_at = 0
        self.issues, self.comments, self.seen = {}, {}, self._load_seen()
        self.sig = None

    def _seen_path(self):
        return os.path.join(self.state, "projects-status", "jira-seen.json")

    def _load_seen(self):
        try:
            with open(self._seen_path(), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_seen(self):
        os.makedirs(os.path.dirname(self._seen_path()), exist_ok=True)
        with open(self._seen_path() + ".tmp", "w", encoding="utf-8") as f:
            json.dump(self.seen, f)
        os.replace(self._seen_path() + ".tmp", self._seen_path())

    def settings(self):
        s = load_settings(self.state)
        if not s.get("url"):
            s["url"] = site_of(self.default_url()) or ""
        return s

    def token(self, s):
        if not (s.get("url") and s.get("email")):
            return None
        return self.store.get(keystore.account(s["url"], s["email"]))

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.data))

    def _set(self, **kw):
        with self.lock:
            self.data = {**self.data, **kw}

    def reconnect(self):
        self._set(state="connecting", why="", status=None, failed=None)
        self.wake.set()

    def cycle(self):
        s = self.settings()
        public = {"url": s.get("url") or "", "email": s.get("email") or "", "board": s.get("board"),
                  "board_name": s.get("board_name") or "", "project": s.get("project") or ""}
        if not self.store.available():
            self._set(state="nostore", why=keystore.NOSTORE, settings=public, at=self.clock())
            return
        try:
            token = self.token(s)
        except (keystore.Unavailable, OSError) as e:
            self._set(state="nostore", why=str(e), settings=public, at=self.clock())
            return
        if not token or not s.get("board"):
            self._set(state="off", why="нет токена" if not token else "не выбрана доска", settings=public, at=self.clock(),
                      issues=[], columns=[], sprints=None)
            return
        sig = (s["url"], s["email"], s["board"], s.get("project") or "", token)
        if sig != self.sig:
            self.client, self.cfg, self.me, self.sig = Client(s["url"], s["email"], token, self.opener), None, None, sig
            self.cfg_at = self.sprint_at = 0
            self.issues, self.comments = {}, {}
        now, stage = self.clock(), "myself"
        try:
            if self.me is None:
                me = self.client.connect()
                self.me = {"id": me.get("accountId") or "", "name": me.get("displayName") or ""}
            stage = "config"
            if not self.cfg or now - self.cfg_at > CONFIG_EVERY:
                self.cfg, self.cfg_at = self.client.config(s["board"]), now
            stage = "sprints"
            if now - self.sprint_at > SPRINT_EVERY:
                self.sprints, self.sprint_at = self.client.sprints(s["board"]), now
            stage = "issues"
            raw = self.client.issues(s["board"], self.cfg, s.get("project") or "")
        except JiraError as e:
            self._set(state="error", status=e.status, why=why(e.status, stage), settings=public, failed=now)
            return
        got = {}
        for r in raw:
            i = issue(r, self.cfg.get("sp_field"))
            if i["key"] and i["type"] != "epic":
                got[i["key"]] = i
        last = set(self.cfg["columns"][-1]["statuses"]) if self.cfg["columns"] else set()
        out, budget, changed_seen = [], COMMENTS_PER_CYCLE, False
        for k, i in got.items():
            if i["status"]["id"] in last and max(i["cat_changed"] or 0, i["updated"] or 0) < now - DONE_DAYS * 86400:
                continue
            was = self.seen.get(k)
            if not was or was[0] != i["status"]["id"]:
                since = (i["cat_changed"] or i["updated"]) if not was else (i["updated"] or now)
                self.seen[k] = [i["status"]["id"], since]
                changed_seen = True
            i["since"] = self.seen[k][1]
            old = self.issues.get(k)
            if (not old or old["updated"] != i["updated"] or k not in self.comments) and budget > 0:
                budget -= 1
                try:
                    self.comments[k] = self.client.comments(k)
                except JiraError:
                    self.comments.setdefault(k, [])
            i["comments"] = self.comments.get(k, [])
            out.append(i)
        self.issues = got
        if changed_seen:
            for k in [k for k in self.seen if k not in got]:
                del self.seen[k]
            try:
                self._save_seen()
            except OSError:
                pass
        site = s["url"]
        for i in out:
            i["url"] = f"{site}/browse/{i['key']}"
        self._set(state="ok", why="", status=None, settings=public, at=now, failed=None, me=self.me,
                  board={"id": s["board"], "name": self.cfg.get("name") or s.get("board_name") or ""},
                  columns=self.cfg["columns"], sp_name=self.cfg.get("sp_name") or "", sprints=self.sprints, issues=out)

    def keys(self):
        """Ключи проектов Jira для склейки с задачами хаба: из задач доски, иначе из настроек."""
        d = self.snapshot()
        ks = {i["key"].split("-")[0] for i in d.get("issues") or []}
        p = (d.get("settings") or {}).get("project")
        return sorted(ks | ({p} if p else set()))

    def run(self):
        while True:
            try:
                self.cycle()
            except Exception as e:  # noqa: BLE001 - один сбой опроса не гасит поток
                self._set(state="error", why=f"сбой опроса: {type(e).__name__}", failed=self.clock())
                print(f"projects-status: jira: {type(e).__name__}", flush=True)
            self.wake.wait(EVERY)
            self.wake.clear()
