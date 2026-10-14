"""Живое состояние репо проекта: ветка, последний коммит, незапушенное, незакоммиченное, открытые MR и PR.
git - локально, раз в минуту; MR и PR - через gh и glab с их входом, раз в 10 минут."""
import json
import os
import re
import subprocess
import threading
import time

GIT_EVERY, REVIEWS_EVERY = 60, 600
TOOLS = {"github": "gh", "gitlab": "glab"}


def git(root, *args):
    try:
        r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


_roots = {}


def roots(path):
    """Репо папки проекта: то, в котором она лежит, или репо прямо в ней (папка с ios/ и android/)."""
    path = os.path.realpath(os.path.expanduser(path)) if path else ""
    at, found = _roots.get(path, (0, None))
    if time.time() - at < GIT_EVERY:
        return found
    found = []
    if os.path.isdir(path):
        top = git(path, "rev-parse", "--show-toplevel")
        found = [os.path.realpath(top)] if top else \
            sorted(os.path.join(path, d) for d in os.listdir(path) if os.path.exists(os.path.join(path, d, ".git")))[:5]
    _roots[path] = (time.time(), found)
    return found


def web(url):
    """(github|gitlab|None, адрес репо в браузере) по адресу origin."""
    m = re.match(r"^(?:[a-z+]+://)?(?:[^@/]+@)?([^/:]+)[:/](.+?)(?:\.git)?/?$", url or "")
    if not m or "." not in m.group(1):
        return None, None
    host, path = m.group(1), m.group(2).lstrip("/")
    kind = "github" if "github" in host else "gitlab" if "gitlab" in host else None
    return kind, f"https://{host}/{path}"


def state(root):
    head = (git(root, "log", "-1", "--format=%h%x00%s%x00%ct") or "").split("\x00")
    branches = (git(root, "for-each-ref", "--sort=-committerdate", "--format=%(committerdate:unix)", "refs/heads") or "").split()
    origin = git(root, "remote", "get-url", "origin")
    unpushed = git(root, "rev-list", "--count", "HEAD", "--not", "--remotes") if git(root, "remote") else None
    kind, url = web(origin)
    return {"root": root, "name": os.path.basename(root), "branch": git(root, "branch", "--show-current") or "",
            "head": {"hash": head[0], "subject": head[1], "ts": int(head[2])} if len(head) == 3 else None,
            "latest": int(branches[0]) if branches else None, "branches": len(branches),
            "unpushed": int(unpushed) if unpushed and unpushed.isdigit() else None,
            "dirty": len((git(root, "status", "--porcelain") or "").splitlines()), "kind": kind, "web": url}


def reviews(kind, root, run=subprocess.run):
    """(открытые MR или PR, ошибка): не спросилось (нет входа, нет сети) - ошибка, а не пустой список."""
    tool = TOOLS.get(kind)
    if not tool:
        return None, None
    cmd = [tool, "pr", "list", "--state", "open", "--limit", "5", "--json", "number,title,url,isDraft,headRefName"] \
        if tool == "gh" else [tool, "mr", "list", "--per-page", "5", "--output", "json"]
    try:
        r = run(cmd, cwd=root, capture_output=True, text=True, timeout=20)
        if r.returncode:
            lines = (r.stderr or r.stdout).strip().splitlines()
            return None, f"{tool}: {lines[-1] if lines else 'ошибка'}"[:200]
        items = json.loads(r.stdout or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        return None, f"{tool}: {e}"[:200]
    if tool == "gh":
        return [{"n": x.get("number"), "title": x.get("title") or "", "url": x.get("url"), "draft": bool(x.get("isDraft")),
                 "branch": x.get("headRefName") or ""} for x in items], None
    return [{"n": x.get("iid"), "title": x.get("title") or "", "url": x.get("web_url"), "draft": bool(x.get("draft")),
             "branch": x.get("source_branch") or ""} for x in items], None


class Repos:
    """Кэш состояния репо: страница спрашивает раз в 15 с, git и сеть - реже."""

    def __init__(self, state=state, reviews=reviews, clock=time.time):
        self.state, self.reviews, self.clock = state, reviews, clock
        self.items, self.lock = {}, threading.Lock()

    def refresh(self, paths):
        now = self.clock()
        for root in dict.fromkeys(paths):
            with self.lock:
                old = self.items.get(root) or {}
            item = dict(old)
            if now - old.get("git_at", -GIT_EVERY) >= GIT_EVERY:
                item.update(self.state(root), git_at=now)
            if now - old.get("reviews_at", -REVIEWS_EVERY) >= REVIEWS_EVERY:
                prs, err = self.reviews(item.get("kind"), root)
                item.update(prs=prs, prs_error=err, reviews_at=now)
            with self.lock:
                self.items[root] = item
        with self.lock:
            for gone in set(self.items) - set(paths):
                del self.items[gone]

    def get(self, root):
        with self.lock:
            item = self.items.get(root)
        return {k: v for k, v in item.items() if not k.endswith("_at")} if item else None
