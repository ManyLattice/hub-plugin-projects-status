"""Токен Jira - только в связке ключей macOS (утилита security): на странице, в файлах и логах его нет.

Запись идёт через `security -i` с командой на stdin, а не аргументом: аргументы процесса видны всем в `ps`.
Где связки ключей нет (Linux, Windows), хранить токен негде - Unavailable с честной причиной, без файла открытым текстом."""
import re
import shutil
import subprocess
import sys

SERVICE = "hub-jira-read"
TOKEN_RE = re.compile(r"[A-Za-z0-9_=+/.\-]{8,400}")
ACCOUNT_RE = re.compile(r"[^\s\"'\\]{1,200}")


class Unavailable(RuntimeError):
    pass


def available(platform=sys.platform, which=shutil.which):
    return platform == "darwin" and bool(which("security"))


NOSTORE = ("хранить токен негде: на этой системе нет связки ключей macOS (утилита security), "
           "а открытым текстом в файл плагин его не пишет")


def _need(platform, which):
    if not available(platform, which):
        raise Unavailable(NOSTORE)


def account(url, email):
    host = re.sub(r"^https?://", "", url or "").split("/")[0].lower()
    return f"{email.strip().lower()} {host}".strip()


def get(acct, run=subprocess.run, platform=sys.platform, which=shutil.which):
    """Токен или None (нет пункта)."""
    _need(platform, which)
    r = run(["security", "find-generic-password", "-s", SERVICE, "-a", acct, "-w"], capture_output=True, text=True, timeout=10)
    return r.stdout.strip() or None if r.returncode == 0 else None


def put(acct, token, run=subprocess.run, platform=sys.platform, which=shutil.which):
    _need(platform, which)
    if not TOKEN_RE.fullmatch(token or ""):
        raise ValueError("токен - латиница, цифры и знаки _ = + / . - (как выдаёт Atlassian)")
    if not ACCOUNT_RE.fullmatch(acct.replace(" ", "_")):
        raise ValueError("email без пробелов и кавычек")
    cmd = f'add-generic-password -U -s {SERVICE} -a "{acct}" -l "Agents Hub: Jira" -w "{token}"\n'
    r = run(["security", "-i"], input=cmd, capture_output=True, text=True, timeout=10)
    if r.returncode or "error" in (r.stderr or "").lower():
        err = (r.stderr or "").replace(token, "***").strip().splitlines() or ["ошибка"]
        raise Unavailable("связка ключей не приняла токен: " + err[-1][:200])


def delete(acct, run=subprocess.run, platform=sys.platform, which=shutil.which):
    _need(platform, which)
    run(["security", "delete-generic-password", "-s", SERVICE, "-a", acct], capture_output=True, text=True, timeout=10)
