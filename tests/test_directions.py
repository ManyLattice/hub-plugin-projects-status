import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data  # noqa: E402
import main  # noqa: E402
import memory  # noqa: E402
import tasks  # noqa: E402


def post(n, by, **kw):
    return {"id": f"p{n}", "by": by, "ts": n, "text": json.dumps(kw, ensure_ascii=False)}


class Directions(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp()
        self.ios, self.android = os.path.join(self.state, "App"), os.path.join(self.state, "App Android")
        for slug, repo in (("app-ios", self.ios), ("app-widget", self.ios), ("app-android", self.android)):
            d = os.path.join(self.state, "directions", slug)
            os.makedirs(os.path.join(d, "backlog", "tasks"))
            json.dump({"repo": repo}, open(os.path.join(d, "direction.json"), "w"))
            os.makedirs(repo, exist_ok=True)
        self.cfg = {"app": {"path": self.ios}}
        self.st = {"last": 0, "projects": {}, "refused": []}

    def fold(self, *posts):
        return main.fold(self.st, list(posts), data.known(self.state, self.cfg), data.task_homes(self.state, self.cfg, None, self.st["projects"]))

    def collect(self):
        return {p["name"]: p for p in data.collect(self.state, self.cfg, self.st["projects"])["projects"]}

    def test_a_project_shows_every_direction_of_its_repo_and_the_linked_ones(self):
        self.assertEqual(sorted(self.collect()), ["app", "app-android"])        # чужое репо - пока отдельный проект
        self.fold(post(1, "owner", project="app", link="app-android"))
        got = self.collect()
        self.assertEqual(sorted(got), ["app"])
        self.assertEqual(sorted((d["slug"], d["linked"]) for d in got["app"]["directions"]),
                         [("app-android", True), ("app-ios", False), ("app-widget", False)])
        self.assertEqual(self.st["projects"]["app"]["history"][-1]["what"], "направление app-android привязано")
        self.fold(post(2, "owner", project="app", unlink="app-android"))
        self.assertEqual(sorted(self.collect()), ["app", "app-android"])

    def test_a_direction_belongs_to_the_deepest_project_folder(self):
        widget = os.path.join(self.ios, "Widget")
        d = os.path.join(self.state, "directions", "app-widget")
        json.dump({"repo": widget}, open(os.path.join(d, "direction.json"), "w"))
        os.makedirs(widget)
        self.cfg["widget"] = {"path": widget}
        got = self.collect()
        self.assertEqual([x["slug"] for x in got["widget"]["directions"]], ["app-widget"])
        self.assertEqual([x["slug"] for x in got["app"]["directions"]], ["app-ios"])

    def test_tasks_of_several_directions_keep_their_own_backlog(self):
        self.fold(post(1, "owner", task="create", project="app", title="Виджет", direction="app-widget"),
                  post(2, "owner", task="create", project="app", title="Экран", direction="app-ios"),
                  post(3, "owner", task="create", project="app", title="Подписка"),
                  post(4, "owner", task="status", project="app", id="TASK-1", status="Done", direction="app-widget"))
        app = self.collect()["app"]
        self.assertEqual(sorted((t["title"], t["home"], t["status"]) for t in app["tasks"]),
                         [("Виджет", "app-widget", "Done"), ("Подписка", None, "To Do"), ("Экран", "app-ios", "To Do")])
        self.assertEqual(app["tasks_home"], None)                               # направлений два - по умолчанию свой бэклог
        self.assertEqual(app["board"]["counts"], {"Done": 1, "In Progress": 0, "To Do": 1})
        self.fold(post(5, "owner", task="create", project="app", title="x", direction="app-android"))
        self.assertEqual(self.st["refused"][-1]["why"], "у проекта app нет направления app-android")


if __name__ == "__main__":
    unittest.main()
