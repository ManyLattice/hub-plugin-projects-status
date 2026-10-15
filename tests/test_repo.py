import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data  # noqa: E402
import repo  # noqa: E402

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": os.devnull}


def git(path, *args):
    subprocess.run(["git", "-C", path, *args], check=True, capture_output=True, env=ENV)


def commit(path, name, msg):
    with open(os.path.join(path, name), "w") as f:
        f.write(msg)
    git(path, "add", name)
    git(path, "commit", "-m", msg)


class Fake:
    """gh и glab: ответы по имени программы, вызовы записаны."""
    def __init__(self, out=None, fail=()):
        self.out, self.fail, self.calls = out or {}, fail, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        code = 1 if cmd[0] in self.fail else 0
        return subprocess.CompletedProcess(cmd, code, self.out.get(cmd[0], ""), "401 Unauthorized" if code else "")


class Repo(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.remote = os.path.join(self.root, "remote.git")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.remote], check=True, env=ENV)
        self.app = os.path.join(self.root, "app")
        subprocess.run(["git", "init", "-q", "-b", "main", self.app], check=True, env=ENV)
        commit(self.app, "a.txt", "Первый")
        git(self.app, "remote", "add", "origin", self.remote)
        git(self.app, "push", "-q", "-u", "origin", "main")

    def test_state_of_a_repo_counts_unpushed_and_uncommitted(self):
        commit(self.app, "b.txt", "Экран оплаты")
        commit(self.app, "c.txt", "Онбординг")
        with open(os.path.join(self.app, "a.txt"), "w") as f:
            f.write("правка")
        open(os.path.join(self.app, "new.txt"), "w").close()
        s = repo.state(self.app)
        self.assertEqual((s["branch"], s["head"]["subject"], s["unpushed"], s["dirty"]), ("main", "Онбординг", 2, 2))
        self.assertGreater(s["latest"], 0)

    def test_commits_on_another_branch_count_as_activity_and_unpushed(self):
        git(self.app, "checkout", "-q", "-b", "feature/x")
        commit(self.app, "b.txt", "Ветка")
        git(self.app, "checkout", "-q", "main")
        s = repo.state(self.app)
        self.assertEqual((s["branch"], s["head"]["subject"], s["unpushed"]), ("main", "Первый", 0))
        self.assertEqual(s["branches"], 2)

    def test_unpushed_branches_current_first_merged_ones_skipped(self):
        git(self.app, "checkout", "-q", "-b", "feature/pay")
        commit(self.app, "b.txt", "Оплата")
        commit(self.app, "c.txt", "Оплата 2")
        git(self.app, "push", "-q", "-u", "origin", "feature/pay")
        commit(self.app, "d.txt", "Оплата 3")
        git(self.app, "checkout", "-q", "-b", "feature/merged")
        git(self.app, "push", "-q", "-u", "origin", "feature/merged")
        commit(self.app, "e.txt", "После слияния")
        git(self.app, "push", "-q", "origin", "--delete", "feature/merged")
        git(self.app, "fetch", "-q", "--prune")
        git(self.app, "checkout", "-q", "main")
        git(self.app, "checkout", "-q", "-b", "feature/new")
        commit(self.app, "n1.txt", "Новое")
        commit(self.app, "n2.txt", "Новое 2")
        git(self.app, "checkout", "-q", "main")
        commit(self.app, "m.txt", "На main")
        self.assertEqual(repo.state(self.app)["ahead"], [{"branch": "main", "n": 1, "pushed": True},
                                                         {"branch": "feature/new", "n": 2, "pushed": False},
                                                         {"branch": "feature/pay", "n": 1, "pushed": True}])

    def test_repo_without_remote_has_no_unpushed_count(self):
        git(self.app, "remote", "remove", "origin")
        s = repo.state(self.app)
        self.assertIsNone(s["unpushed"])
        self.assertIsNone(s["web"])

    def test_web_address_from_origin(self):
        for url, want in (("git@github.com:acme/app.git", ("github", "https://github.com/acme/app")),
                          ("https://github.com/acme/app", ("github", "https://github.com/acme/app")),
                          ("ssh://git@gitlab.com/acme/mobile/app.git", ("gitlab", "https://gitlab.com/acme/mobile/app")),
                          ("https://user:token@gitlab.com/acme/app.git", ("gitlab", "https://gitlab.com/acme/app")),
                          ("/srv/git/app.git", (None, None))):
            self.assertEqual(repo.web(url), want, url)

    def test_folder_of_repos_gives_each_repo(self):
        proj = os.path.join(self.root, "proj")
        for sub in ("ios", "android"):
            subprocess.run(["git", "init", "-q", "-b", "main", os.path.join(proj, sub)], check=True, env=ENV)
        os.makedirs(os.path.join(proj, "docs"))
        self.assertEqual([os.path.basename(r) for r in repo.roots(proj)], ["android", "ios"])
        self.assertEqual(repo.roots(os.path.join(self.app)), [os.path.realpath(self.app)])
        os.makedirs(os.path.join(self.app, "Sources"))
        self.assertEqual(repo.roots(os.path.join(self.app, "Sources")), [os.path.realpath(self.app)])
        self.assertEqual(repo.roots(os.path.join(self.root, "nope")), [])


class Reviews(unittest.TestCase):
    def test_open_pull_requests_from_gh(self):
        fake = Fake({"gh": json.dumps([{"number": 7, "title": "Оплата", "url": "https://github.com/a/b/pull/7",
                                        "isDraft": True, "headRefName": "pay"}])})
        prs, err = repo.reviews("github", "/x", run=fake)
        self.assertEqual((prs, err), ([{"n": 7, "title": "Оплата", "url": "https://github.com/a/b/pull/7", "draft": True,
                                        "branch": "pay"}], None))
        self.assertEqual(fake.calls[0][:3], ["gh", "pr", "list"])

    def test_merge_requests_from_glab(self):
        fake = Fake({"glab": json.dumps([{"iid": 41, "title": "Онбординг", "web_url": "https://gitlab.com/a/b/-/merge_requests/41",
                                          "draft": False, "source_branch": "onb"}])})
        prs, err = repo.reviews("gitlab", "/x", run=fake)
        self.assertEqual(prs, [{"n": 41, "title": "Онбординг", "url": "https://gitlab.com/a/b/-/merge_requests/41",
                                "draft": False, "branch": "onb"}])

    def test_failed_login_is_an_error_not_an_empty_list(self):
        prs, err = repo.reviews("gitlab", "/x", run=Fake(fail=("glab",)))
        self.assertIsNone(prs)
        self.assertIn("glab", err)

    def test_other_hosts_are_not_asked(self):
        fake = Fake()
        self.assertEqual(repo.reviews(None, "/x", run=fake), (None, None))
        self.assertEqual(fake.calls, [])


class Cache(unittest.TestCase):
    def setUp(self):
        self.t = [1000.0]
        self.calls = []
        self.repos = repo.Repos(state=lambda r: self.calls.append(("git", r)) or {"root": r, "web": "https://github.com/a/b",
                                                                                   "kind": "github"},
                                reviews=lambda k, r: self.calls.append(("pr", r)) or ([], None), clock=lambda: self.t[0])

    def test_git_each_minute_reviews_each_ten_minutes(self):
        self.repos.refresh(["/a"])
        self.t[0] += 30
        self.repos.refresh(["/a"])
        self.t[0] += 40
        self.repos.refresh(["/a"])
        self.assertEqual(self.calls, [("git", "/a"), ("pr", "/a"), ("git", "/a")])
        self.t[0] += 600
        self.repos.refresh(["/a"])
        self.assertEqual(self.calls[-2:], [("git", "/a"), ("pr", "/a")])
        self.assertEqual(self.repos.get("/a")["prs"], [])

    def test_gone_repos_are_dropped(self):
        self.repos.refresh(["/a", "/b"])
        self.repos.refresh(["/b"])
        self.assertIsNone(self.repos.get("/a"))
        self.assertIsNotNone(self.repos.get("/b"))


class Collect(unittest.TestCase):
    def test_project_gets_repos_of_its_folder_and_linked_directions(self):
        root = tempfile.mkdtemp()
        app, android = os.path.join(root, "app"), os.path.join(root, "android")
        for p in (app, android):
            subprocess.run(["git", "init", "-q", "-b", "main", p], check=True, env=ENV)
        d = os.path.join(root, "state", "directions", "app-android")
        os.makedirs(os.path.join(d, "backlog", "tasks"))
        json.dump({"repo": android}, open(os.path.join(d, "direction.json"), "w"))
        mems = {"app": {"links": ["app-android"]}}
        got = data.collect(os.path.join(root, "state"), {"app": {"path": app}}, mems,
                           repos=lambda r: {"root": r, "branch": "main"})
        self.assertEqual([r["root"] for r in got["projects"][0]["repos"]], [os.path.realpath(app), os.path.realpath(android)])
        self.assertEqual(data.collect(os.path.join(root, "state"), {"app": {"path": app}}, mems)["projects"][0]["repos"], [])


if __name__ == "__main__":
    unittest.main()
