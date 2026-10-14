"""Данные вида «Статус проектов»: проекты из настроек хаба, их направления (доски Backlog.md) и память."""
import glob
import os
import re

import tasks

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
    """Доска направления: счёт по статусам, задачи в работе, сделанные и решения (новые первыми), время последней правки."""
    import json
    meta = {}
    try:
        meta = json.loads(read(os.path.join(path, "direction.json")) or "{}")
    except ValueError:
        pass
    counts, doing, done, last = {s: 0 for s in STATUSES}, [], [], 0
    for f in glob.glob(os.path.join(path, "backlog", "tasks", "*.md")):
        text = read(f)
        st = field(text, "status") or "To Do"
        counts[st if st in counts else "To Do"] += 1
        if st == "In Progress":
            doing.append((field(text, "ordinal") or "", field(text, "title") or os.path.basename(f)))
        elif st == "Done":
            done.append({"id": (field(text, "id") or "").upper(), "title": field(text, "title") or os.path.basename(f),
                         "date": field(text, "updated_date") or field(text, "created_date") or "",
                         "ordinal": float(field(text, "ordinal") or 0)})
        last = max(last, os.path.getmtime(f))
    decisions = []
    for f in glob.glob(os.path.join(path, "backlog", "decisions", "*.md")):
        text = read(f)
        decisions.append({"title": field(text, "title") or os.path.basename(f), "date": field(text, "date") or ""})
        last = max(last, os.path.getmtime(f))
    decisions.sort(key=lambda d: d["date"], reverse=True)
    done = [{"id": d["id"], "title": d["title"], "date": d["date"]} for d in sorted(done, key=lambda d: (d["date"], d["ordinal"]), reverse=True)]
    return {"repo": real(meta.get("repo")), "created": meta.get("created"), "counts": counts,
            "doing": [t for _, t in sorted(doing)][:3], "done": done[:8], "decisions": decisions[:5], "decisions_total": len(decisions),
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


def merge(boards):
    """Доска проекта из нескольких живых направлений: счёт сложен, задачи и решения вперемешку, новые первыми."""
    if len(boards) == 1:
        return boards[0]
    done = sorted((d for b in boards for d in b["done"]), key=lambda d: d["date"], reverse=True)
    decisions = sorted((d for b in boards for d in b["decisions"]), key=lambda d: d["date"], reverse=True)
    return {"repo": boards[0]["repo"], "created": boards[0]["created"], "archived": False,
            "counts": {s: sum(b["counts"][s] for b in boards) for s in STATUSES},
            "doing": [t for b in boards for t in b["doing"]][:3], "done": done[:8], "decisions": decisions[:5],
            "decisions_total": sum(b["decisions_total"] for b in boards), "changed": max(b["changed"] or 0 for b in boards) or None}


def owners(dirs, projects, memories):
    """Направление -> проект: привязанное вручную (links в памяти проекта) или по репо (самая глубокая папка проекта)."""
    out = {}
    paths = {name: real(p.get("path")) for name, p in projects.items() if p.get("path")}
    for slug, d in dirs.items():
        repo = d["repo"]
        hits = [n for n, path in paths.items() if repo and (repo == path or repo.startswith(path.rstrip(os.sep) + os.sep))]
        if hits:
            out[slug] = max(hits, key=lambda n: len(paths[n]))
    for name, m in memories.items():
        for slug in (m or {}).get("links") or []:
            if name in projects and slug in dirs:
                out[slug] = name
    return out


def collect(state_dir, projects, memories):
    """-> {projects: [...]} для страницы. Направление - проекта, чью папку оно правит (direction.json repo), или
    привязанное к проекту вручную; живое направление без проекта - само проект."""
    dirs = directions(os.path.join(state_dir, "directions"))
    owner = owners(dirs, projects, memories)
    out = []
    for name, p in projects.items():
        path = real(p.get("path"))
        mine = sorted(((s, d) for s, d in dirs.items() if owner.get(s) == name),
                      key=lambda x: (x[1]["archived"], -(x[1]["changed"] or 0)))
        live = [d for _, d in mine if not d["archived"]]
        slug, d = mine[0] if mine else (None, None)
        out.append({"name": name, "about": p.get("about") or "", "path": p.get("path"),
                    "exists": bool(path and os.path.isdir(path)), "direction": slug, "board": merge(live) if live else d,
                    "directions": [{"slug": s, "linked": s in ((memories.get(name) or {}).get("links") or []),
                                    "board": b} for s, b in mine],
                    "memory": memories.get(name)})
    for slug, d in sorted(dirs.items()):   # живое направление без проекта - тоже проект
        if slug not in owner and not d["archived"] and slug not in projects:
            out.append({"name": slug, "about": "", "path": d["repo"], "exists": bool(d["repo"] and os.path.isdir(d["repo"])),
                        "direction": slug, "board": d, "directions": [{"slug": slug, "linked": False, "board": d}],
                        "memory": memories.get(slug), "unlisted": True})
    homes = task_homes(state_dir, projects, out)
    for o in out:
        h = homes[o["name"]]
        o["tasks"] = [{**t, "home": key or None} for key, path in h["paths"].items() for t in tasks.read_all(path)]
        o["tasks_home"] = h["default"] or None
        o["homes"] = [k for k in h["paths"] if k]
    return {"projects": out, "general": tasks.read_all(homes[tasks.GENERAL]["paths"][""]),
            "free": sorted(s for s, d in dirs.items() if not d["archived"] and s not in owner)}


def task_homes(state_dir, projects, listed=None, memories=None):
    """Куда идут задачи проекта: свой бэклог рядом с памятью проекта ("") и бэклоги его живых направлений; по умолчанию -
    бэклог единственного живого направления, иначе свой."""
    out = {tasks.GENERAL: {"default": "", "paths": {"": os.path.join(state_dir, "projects-memory", "_general", "backlog")}}}
    for p in listed if listed is not None else collect(state_dir, projects, memories or {})["projects"]:
        live = [d["slug"] for d in p["directions"] if not d["board"]["archived"]]
        paths = {"": os.path.join(state_dir, "projects-memory", p["name"], "backlog")}
        paths.update({s: os.path.join(state_dir, "directions", s, "backlog") for s in live})
        out[p["name"]] = {"default": live[0] if len(live) == 1 else "", "paths": paths}
    return out


def known(state_dir, projects):
    """Чью память можно править: проекты из hub projects и живые направления без проекта."""
    names = set(projects)
    for p in collect(state_dir, projects, {})["projects"]:
        names.add(p["name"])
    return names
