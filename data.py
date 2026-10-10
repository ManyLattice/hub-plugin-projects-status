"""Данные вида «Статус проектов»: проекты из настроек хаба, их направления (доски Backlog.md) и память."""
import glob
import os
import re

STATUSES = ("Done", "In Progress", "To Do")


def field(text, name):
    m = re.search(rf"^{name}:[ \t]*(.*)$", text, re.M)
    if not m:
        return None
    v = m.group(1).strip()
    if v in (">", ">-", "|", "|-"):   # длинный заголовок YAML - строками с отступом ниже
        more = re.match(r"((?:[ \t]+\S.*\n?)+)", text[m.end() + 1:])
        v = " ".join(x.strip() for x in (more.group(1) if more else "").splitlines())
    return v.strip("'\"")


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def real(path):
    return os.path.realpath(os.path.expanduser(path)) if path else None


def board(path):
    """Доска направления: счёт по статусам, задачи в работе, решения (новые первыми), время последней правки."""
    import json
    meta = {}
    try:
        meta = json.loads(read(os.path.join(path, "direction.json")) or "{}")
    except ValueError:
        pass
    counts, doing, last = {s: 0 for s in STATUSES}, [], 0
    for f in glob.glob(os.path.join(path, "backlog", "tasks", "*.md")):
        text = read(f)
        st = field(text, "status") or "To Do"
        counts[st if st in counts else "To Do"] += 1
        if st == "In Progress":
            doing.append((field(text, "ordinal") or "", field(text, "title") or os.path.basename(f)))
        last = max(last, os.path.getmtime(f))
    decisions = []
    for f in glob.glob(os.path.join(path, "backlog", "decisions", "*.md")):
        text = read(f)
        decisions.append({"title": field(text, "title") or os.path.basename(f), "date": field(text, "date") or ""})
        last = max(last, os.path.getmtime(f))
    decisions.sort(key=lambda d: d["date"], reverse=True)
    return {"repo": real(meta.get("repo")), "created": meta.get("created"), "counts": counts,
            "doing": [t for _, t in sorted(doing)][:3], "decisions": decisions[:5], "decisions_total": len(decisions),
            "changed": last or None}


def directions(root):
    out = {}
    for path in glob.glob(os.path.join(root, "*")) + glob.glob(os.path.join(root, "_archive", "*")):
        slug = os.path.basename(path)
        if slug.startswith("_") or not os.path.isdir(os.path.join(path, "backlog")):
            continue
        b = board(path)
        b["archived"] = os.sep + "_archive" + os.sep in path
        out[slug if not b["archived"] or slug not in out else f"{slug} (архив)"] = b
    return out


def collect(state_dir, projects, memories):
    """-> {projects: [...]} для страницы. Проект и направление связаны путём репо (direction.json repo)."""
    dirs = directions(os.path.join(state_dir, "directions"))
    by_repo = {}
    for slug, d in dirs.items():
        if d["repo"]:
            by_repo.setdefault(d["repo"], []).append((slug, d))
    out = []
    for name, p in projects.items():
        path = real(p.get("path"))
        mine = sorted(by_repo.get(path, []), key=lambda x: (x[1]["archived"], -(x[1]["changed"] or 0)))
        slug, d = mine[0] if mine else (None, None)
        out.append({"name": name, "about": p.get("about") or "", "path": p.get("path"),
                    "exists": bool(path and os.path.isdir(path)), "direction": slug, "board": d,
                    "memory": memories.get(name)})
    linked = {o["direction"] for o in out}
    for slug, d in sorted(dirs.items()):   # живое направление, чьей папки нет в hub projects, - тоже проект
        if slug not in linked and not d["archived"] and slug not in projects:
            out.append({"name": slug, "about": "", "path": d["repo"], "exists": bool(d["repo"] and os.path.isdir(d["repo"])),
                        "direction": slug, "board": d, "memory": memories.get(slug), "unlisted": True})
    return {"projects": out}


def known(state_dir, projects):
    """Чью память можно править: проекты из hub projects и живые направления без проекта."""
    names = set(projects)
    for p in collect(state_dir, projects, {})["projects"]:
        names.add(p["name"])
    return names
