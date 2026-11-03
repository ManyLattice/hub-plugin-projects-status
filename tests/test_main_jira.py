import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jira  # noqa: E402
import keystore  # noqa: E402
import main  # noqa: E402
import memory  # noqa: E402

STATE = tempfile.mkdtemp()

TOKEN = "ATATT3xSECRET="
FORM = {"url": "https://site.atlassian.net", "email": "me@x.com", "board": 5, "board_name": "B", "project": ""}


class Routes(unittest.TestCase):
    def setUp(self):
        self.store = {}
        self.p = [mock.patch.object(main, "hub_jira", lambda: {}), mock.patch.object(main, "STATE", STATE),
                  mock.patch.object(main, "BOARD", jira.Board(STATE)), mock.patch.object(main, "TASKS", main.hubtasks.Index(STATE)),
                  mock.patch.object(keystore, "put", lambda a, t: self.store.__setitem__(a, t)),
                  mock.patch.object(keystore, "get", lambda a: self.store.get(a)),
                  mock.patch.object(keystore, "delete", lambda a: self.store.pop(a, None))]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()

    def test_save_puts_the_token_in_the_keychain_and_not_in_the_settings_file(self):
        code, out = main.jira_post("/jira/save", {**FORM, "token": TOKEN})
        self.assertEqual((code, out), (200, {"ok": True}))
        self.assertEqual(self.store, {"me@x.com site.atlassian.net": TOKEN})
        raw = open(jira.settings_path(STATE), encoding="utf-8").read()
        self.assertNotIn(TOKEN, raw)
        self.assertEqual(json.loads(raw)["board"], 5)

    def test_check_uses_the_stored_token_and_never_returns_it(self):
        main.jira_post("/jira/save", {**FORM, "token": TOKEN})
        seen = []
        with mock.patch.object(jira, "check", lambda s, t: seen.append(t) or {"steps": [], "token_echo": False}):
            code, out = main.jira_post("/jira/check", dict(FORM))
        self.assertEqual(seen, [TOKEN])
        self.assertNotIn(TOKEN, json.dumps(out))

    def test_save_without_any_token_is_refused(self):
        code, out = main.jira_post("/jira/save", dict(FORM, email="new@x.com"))
        self.assertFalse(out["ok"])

    def test_no_keychain_is_reported_not_written_elsewhere(self):
        def nope(*a):
            raise keystore.Unavailable(keystore.NOSTORE)
        with mock.patch.object(keystore, "put", nope), mock.patch.object(keystore, "get", nope):
            code, out = main.jira_post("/jira/save", {**FORM, "token": TOKEN})
        self.assertEqual((out["ok"], out["nostore"]), (False, True))
        for root, _, files in os.walk(STATE):
            for f in files:
                self.assertNotIn(TOKEN, open(os.path.join(root, f), encoding="utf-8", errors="replace").read())

    def test_forget_drops_the_token_and_the_board(self):
        main.jira_post("/jira/save", {**FORM, "token": TOKEN})
        main.jira_post("/jira/forget", {})
        self.assertEqual(self.store, {})
        self.assertIsNone(jira.load_settings(STATE).get("board"))

    def test_the_view_answer_has_no_token(self):
        main.jira_post("/jira/save", {**FORM, "token": TOKEN})
        self.assertNotIn(TOKEN, json.dumps(main.jira_view(), ensure_ascii=False))


class MemoryJira(unittest.TestCase):
    def test_labels_and_epics_of_a_project(self):
        upd = memory.parse(json.dumps({"project": "a", "jira": " myapp,  ABC-12 "}), {"a"})
        self.assertEqual(upd["jira"], "myapp ABC-12")
        mem = memory.empty()
        self.assertEqual(memory.apply(mem, upd, "owner", 1), ["Jira: myapp ABC-12"])
        self.assertIn("Jira (метки и эпики задач проекта): myapp ABC-12", memory.render_md("a", "", mem))
        self.assertEqual(memory.apply(mem, memory.parse(json.dumps({"project": "a", "jira": ""}), {"a"}), "owner", 2), ["Jira снято"])
        for bad in ("a b c " * 30, "bad\"quote", 5):
            with self.assertRaises(memory.Invalid):
                memory.parse(json.dumps({"project": "a", "jira": bad}), {"a"})


if __name__ == "__main__":
    unittest.main()
