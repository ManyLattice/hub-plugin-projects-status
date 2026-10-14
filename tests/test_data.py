import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data  # noqa: E402
import main  # noqa: E402
import memory  # noqa: E402


def task(path, n, status, title, updated=""):
    with open(os.path.join(path, f"task-{n} - x.md"), "w") as f:
        f.write(f"---\nid: TASK-{n}\ntitle: '{title}'\nstatus: {status}\nupdated_date: '{updated}'\nordinal: {n}000\n---\n")


class Data(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.repo = os.path.join(self.root, "My Projects", "App")
        os.makedirs(self.repo)
        for slug, archived in (("app-redesign", False), ("app-old", True)):
            d = os.path.join(self.root, "state", "directions", *(["_archive"] if archived else []), slug)
            os.makedirs(os.path.join(d, "backlog", "tasks"))
            os.makedirs(os.path.join(d, "backlog", "decisions"))
            json.dump({"repo": self.repo}, open(os.path.join(d, "direction.json"), "w"))
        t = os.path.join(self.root, "state", "directions", "app-redesign", "backlog", "tasks")
        task(t, 1, "Done", "Срез 1"); task(t, 2, "In Progress", "Срез 2: иконка"); task(t, 3, "To Do", "Срез 3")
        with open(os.path.join(t, "..", "decisions", "decision-1 - a.md"), "w") as f:
            f.write("---\nid: decision-1\ntitle: Макеты - в Figma\ndate: '2026-10-09 18:31'\n---\n")

    def test_a_project_gets_its_live_direction_by_the_repo_path(self):
        got = data.collect(os.path.join(self.root, "state"),
                           {"app": {"path": self.repo, "about": "x"}, "idea": {"path": os.path.join(self.root, "nope")}}, {})
        app, idea = got["projects"]
        self.assertEqual((app["direction"], app["board"]["archived"]), ("app-redesign", False))
        self.assertEqual(app["board"]["counts"], {"Done": 1, "In Progress": 1, "To Do": 1})
        self.assertEqual(app["board"]["doing"], ["Срез 2: иконка"])
        self.assertEqual(app["board"]["decisions"][0]["title"], "Макеты - в Figma")
        self.assertEqual((idea["direction"], idea["exists"]), (None, False))

    def test_done_tasks_come_newest_first_with_the_date_they_closed(self):
        t = os.path.join(self.root, "state", "directions", "app-redesign", "backlog", "tasks")
        task(t, 4, "Done", "Срез 4: оплата", "2026-10-11 09:30")
        task(t, 5, "Done", "Срез 5: виджет", "2026-10-12 14:05")
        b = data.board(os.path.join(self.root, "state", "directions", "app-redesign"))
        self.assertEqual([(d["title"], d["date"]) for d in b["done"]],
                         [("Срез 5: виджет", "2026-10-12 14:05"), ("Срез 4: оплата", "2026-10-11 09:30"), ("Срез 1", "")])
        # номер - чтобы «Что изменилось» не показало закрытие задачи дважды: из истории карточки и с доски
        self.assertEqual([d["id"] for d in b["done"]], ["TASK-5", "TASK-4", "TASK-1"])

    def test_a_long_yaml_title_is_read_whole(self):
        self.assertEqual(data.field("title: >-\n  Разбор: почему бот\n  выходит из канала\nstatus: To Do\n", "title"),
                         "Разбор: почему бот выходит из канала")

    def test_posts_fold_once_and_bad_ones_are_kept_with_the_reason(self):
        st = {"last": 0, "projects": {}, "refused": []}
        posts = [{"id": "p5", "by": "app-redesign", "ts": 1, "text": '{"project": "app", "stage": "Разработка"}'},
                 {"id": "p7", "by": "owner", "ts": 2, "text": "просто текст"}]
        self.assertEqual(main.fold(st, posts, {"app": {}}), {"app"})
        self.assertEqual(main.fold(st, posts, {"app": {}}), set())                 # уже свёрнуто
        self.assertEqual(st["projects"]["app"]["stage"], "Разработка")
        self.assertEqual([(r["id"], r["why"]) for r in st["refused"]], [("p7", "не JSON")])


if __name__ == "__main__":
    unittest.main()
