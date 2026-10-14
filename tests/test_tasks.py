import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import data  # noqa: E402
import main  # noqa: E402
import tasks  # noqa: E402


def post(n, by, **kw):
    return {"id": f"p{n}", "by": by, "ts": n, "text": json.dumps(kw, ensure_ascii=False)}


class Tasks(unittest.TestCase):
    def setUp(self):
        self.base = os.path.join(tempfile.mkdtemp(), "backlog")

    def test_a_new_task_is_a_backlog_md_file_with_the_next_free_id(self):
        os.makedirs(os.path.join(self.base, "completed"))
        open(os.path.join(self.base, "completed", "task-7 - old.md"), "w").write("---\nid: TASK-7\n---\n")
        got = tasks.create(self.base, {"title": "Оформить подписку", "description": "Google Play Console",
                                       "priority": "high", "assignee": "owner", "due": "2026-10-20", "type": "task"})
        self.assertEqual(got, "TASK-8")
        text = tasks.read(os.path.join(self.base, "tasks", "task-8 - Оформить-подписку.md"))
        for line in ("id: TASK-8", "title: Оформить подписку", "status: To Do", "  - '@owner'", "due_date: '2026-10-20'",
                     "priority: high", "type: task", "ordinal: 8000", "Google Play Console"):
            self.assertIn(line, text)
        self.assertEqual(data.field(text, "title"), "Оформить подписку")

    def test_a_status_change_rewrites_only_the_status_and_stamps_the_update(self):
        tid = tasks.create(self.base, {"title": "Экран настроек: тёмная тема", "assignee": "kotlin-dev"})
        tasks.set_status(self.base, tid, "In Progress")
        [t] = tasks.read_all(self.base)
        self.assertEqual((t["id"], t["status"], t["assignee"], t["title"]),
                         ("TASK-1", "In Progress", "kotlin-dev", "Экран настроек: тёмная тема"))
        self.assertTrue(t["updated"])
        with self.assertRaises(tasks.Invalid):
            tasks.set_status(self.base, "TASK-9", "Done")

    def test_ops_are_checked_before_they_touch_files(self):
        ok = tasks.parse({"task": "create", "project": "app", "title": " Иконка ", "priority": "low"})
        self.assertEqual(ok["title"], "Иконка")
        for bad in ({"task": "create", "project": "app", "title": ""},
                    {"task": "create", "project": "app", "title": "x", "priority": "срочно"},
                    {"task": "create", "project": "app", "title": "x", "due": "завтра"},
                    {"task": "status", "project": "app", "id": "TASK-1", "status": "Отложено"},
                    {"task": "drop", "project": "app"}):
            with self.assertRaises(tasks.Invalid):
                tasks.parse(bad)


class Fold(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp()
        self.repo = os.path.join(self.state, "App")
        os.makedirs(self.repo)
        d = os.path.join(self.state, "directions", "app-v2")
        os.makedirs(os.path.join(d, "backlog", "tasks"))
        json.dump({"repo": self.repo}, open(os.path.join(d, "direction.json"), "w"))
        self.cfg = {"app": {"path": self.repo}, "where": {"path": os.path.join(self.state, "Where")}}

    def test_a_task_goes_to_the_live_direction_backlog_or_to_the_project_own_one(self):
        st = {"last": 0, "projects": {}, "refused": []}
        homes = data.task_homes(self.state, self.cfg)
        touched = main.fold(st, [post(1, "owner", task="create", project="app", title="Срез 8: виджет"),
                                 post(2, "owner", task="create", project="where", title="Оформить подписку", assignee="owner"),
                                 post(3, "owner", task="status", project="where", id="TASK-1", status="Done")],
                            set(self.cfg), homes)
        self.assertEqual(touched, {"app", "where"})
        self.assertEqual([t["title"] for t in tasks.read_all(os.path.join(self.state, "directions", "app-v2", "backlog"))],
                         ["Срез 8: виджет"])
        [t] = tasks.read_all(homes["where"]["paths"][""])
        self.assertEqual((t["title"], t["status"], t["assignee"]), ("Оформить подписку", "Done", "owner"))
        self.assertEqual([h["what"] for h in st["projects"]["where"]["history"]],
                         ["задача TASK-1 «Оформить подписку» заведена, исполнитель - владелец", "задача TASK-1: Готово"])
        self.assertEqual(main.fold(st, [post(3, "owner", task="status", project="where", id="TASK-1", status="Done")],
                                   set(self.cfg), homes), set())                     # уже свёрнуто

    def test_a_task_without_a_project_goes_to_the_general_backlog(self):
        st = {"last": 0, "projects": {}, "refused": []}
        homes = data.task_homes(self.state, self.cfg)
        touched = main.fold(st, [post(1, "owner", task="create", project=tasks.GENERAL, title="Зарегистрироваться в сервисе",
                                      assignee="owner"),
                                 post(2, "owner", task="status", project=tasks.GENERAL, id="TASK-1", status="In Progress")],
                            set(self.cfg), homes)
        self.assertEqual(touched, {tasks.GENERAL})
        self.assertEqual(st["projects"], {})
        self.assertEqual([h["what"] for h in st["general"]],
                         ["задача TASK-1 «Зарегистрироваться в сервисе» заведена, исполнитель - владелец", "задача TASK-1: В работе"])
        [t] = data.collect(self.state, self.cfg, {})["general"]
        self.assertEqual((t["title"], t["status"], t["assignee"]), ("Зарегистрироваться в сервисе", "In Progress", "owner"))

    def test_a_status_for_a_missing_task_is_refused_with_the_reason(self):
        st = {"last": 0, "projects": {}, "refused": []}
        main.fold(st, [post(1, "kotlin-dev", task="status", project="app", id="TASK-4", status="Done")],
                  set(self.cfg), data.task_homes(self.state, self.cfg))
        self.assertEqual(st["refused"][0]["why"], "нет задачи TASK-4")


if __name__ == "__main__":
    unittest.main()
