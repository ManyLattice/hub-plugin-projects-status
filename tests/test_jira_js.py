import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")
NOW = 1_800_000_000


def js(body, data):
    src = f"import * as J from {json.dumps('file://' + os.path.join(ROOT, 'web', 'jirapure.js'))};\n" \
          f"const D = JSON.parse(process.argv[1]);\nconsole.log(JSON.stringify((() => {{ {body} }})()));"
    r = subprocess.run([NODE, "--input-type=module", "-e", src, json.dumps(data)], capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


def task(id_, doer, by="владелец", role="lead", at=NOW - 3600, closed=False, last="шаг"):
    return {"id": id_, "doer": doer, "by": by, "role": role, "at": at, "closed": closed, "title": f"задача {id_}",
            "last": {"ts": at, "who": doer, "text": last}, "log": []}


def ses(name, state="idle", **kw):
    return {"name": name, "state": state, "kind": "work", "pending": [], **kw}


ASK = {"request_id": "r1", "tool": "AskUserQuestion", "since": NOW - 60, "input": {"questions": [{"question": "Делаем так?", "header": "Схема"}]}}


@unittest.skipUnless(NODE, "нужен node")
class HubLine(unittest.TestCase):
    def line(self, tasks, sessions, delegations=(), hints=None):
        return js("return J.hubLine(D.t, {sessions: D.s, delegations: D.d}, D.h);",
                  {"t": tasks, "s": sessions, "d": list(delegations), "h": hints or {}})

    def test_the_owner_card_of_the_lead_session_comes_first(self):
        got = self.line([task("d1", "dash")], [ses("dash", "dialog", pending=[ASK], waiting={"text": "x", "ts": NOW})])
        self.assertEqual((got["state"], got["session"], got["text"]), ("you", "dash", "Делаем так?"))

    def test_a_busy_executor_beats_the_card_of_its_raiser(self):
        got = self.line([task("d1", "dash-ext", by="dash", last="Код: тесты зелёные")],
                        [ses("dash", "dialog", pending=[ASK]), ses("dash-ext", "busy", raised_by="dash")])
        self.assertEqual((got["state"], got["session"], got["under"], got["text"]), ("work", "dash-ext", "dash", "Код: тесты зелёные"))

    def test_an_asleep_executor_hands_over_to_its_raiser(self):
        got = self.line([task("d1", "dash-ext", by="dash", closed=True)],
                        [ses("dash", waiting={"text": "ответа ревью", "ts": NOW}), ses("dash-ext", "asleep", raised_by="dash")])
        self.assertEqual((got["state"], got["session"]), ("wait", "dash"))

    def test_a_closed_task_with_idle_sessions_is_handed_in(self):
        got = self.line([task("d1", "app", closed=True, last="Готово")], [ses("app")])
        self.assertEqual((got["state"], got["session"], got["text"]), ("done", "app", "Готово"))

    def test_the_open_task_wins_over_a_fresher_closed_one(self):
        got = self.line([task("d1", "a", at=NOW - 10, closed=True), task("d2", "b", at=NOW - 999)], [ses("a"), ses("b")],
                        [{"id": "d2", "state": "working"}])
        self.assertEqual((got["task"]["id"], got["open"], [t["id"] for t in got["others"]]), ("d2", True, ["d1"]))

    def test_no_lead_says_where_the_key_still_shows_up(self):
        got = self.line([task("d9", "x", role="mention")], [], hints={"memory": [], "backlog": []})
        self.assertEqual((got["state"], got["hint"]), ("none", "упоминается в d9"))
        got = self.line([], [], hints={"memory": ["dash"], "backlog": []})
        self.assertEqual(got["hint"], "есть в памяти проекта dash")

    def test_the_hub_session_is_never_the_lead(self):
        got = self.line([task("d1", "gone", by="hub-core")], [dict(ses("hub-core", "dialog", pending=[ASK]), kind="hub")])
        self.assertEqual(got["state"], "done")


@unittest.skipUnless(NODE, "нужен node")
class Board(unittest.TestCase):
    def test_project_by_label_then_epic_then_hub_direction(self):
        projects = [{"name": "dash", "memory": {"jira": "ads ABC-7"}, "directions": [{"slug": "dash-dir"}]},
                    {"name": "pom", "memory": {}, "direction": "pom"}]
        got = js("""const ix = J.projectIndex(D.p);
          return D.i.map((it) => J.projectLink(it, ix, it.line, {sessions: D.s}));""",
                 {"p": projects, "s": [{"name": "w", "backlog": "dash-dir"}],
                  "i": [{"labels": ["POM"]}, {"labels": ["ads"]}, {"labels": [], "epic": {"key": "ABC-7"}},
                        {"labels": [], "line": {"session": "w", "task": {"doer": "w", "by": ""}}}, {"labels": ["other"]}]})
        self.assertEqual(got, [{"name": "pom", "by": "по метке pom"}, {"name": "dash", "by": "по метке ads"},
                               {"name": "dash", "by": "по эпику ABC-7"}, {"name": "dash", "by": "через направление dash-dir"}, None])

    def test_columns_follow_status_ids_and_strays_go_before_the_last(self):
        got = js("""return J.columns(D.c, D.i).map((c) => [c.name, c.items.map((x) => x.key), c.last]);""",
                 {"c": [{"name": "A", "statuses": ["1"]}, {"name": "B", "statuses": ["2", "3"]}, {"name": "Done", "statuses": ["9"]}],
                  "i": [{"key": "K-1", "status": {"id": "3"}}, {"key": "K-2", "status": {"id": "9"}}, {"key": "K-3", "status": {"id": "7"}}]})
        self.assertEqual(got, [["A", [], False], ["B", ["K-1"], False], ["Вне колонок доски", ["K-3"], False], ["Done", ["K-2"], True]])

    def test_sprint_options_and_filter(self):
        got = js("""const o = J.sprintOptions(D.s);
          return [o.map((x) => x[0]), D.i.map((it) => ["active", "s:8", "none", "all"].map((p) => J.inSprint(it, p)))];""",
                 {"s": [{"id": 7, "name": "S7", "state": "active", "end": "2026-11-07T00:00"}, {"id": 8, "name": "S8", "state": "future"}],
                  "i": [{"sprint": {"id": 7, "state": "active"}}, {"sprint": {"id": 8, "state": "future"}}, {"sprint": None}]})
        self.assertEqual(got[0], ["active", "s:8", "none", "all"])
        self.assertEqual(got[1], [[True, False, False, True], [False, True, False, True], [False, False, True, True]])
        self.assertEqual(js("return J.sprintOptions(null);", {}), [])

    def test_stale_only_in_progress_and_only_after_a_week(self):
        got = js("""return [J.staleDays(D.a, D.t, D.now), J.staleDays(D.a, [], D.now), J.staleDays(D.b, D.t, D.now)];""",
                 {"now": NOW, "a": {"status": {"cat": "indeterminate"}, "updated": NOW - 3 * 86400},
                  "b": {"status": {"cat": "new"}, "updated": 0}, "t": [{"at": NOW - 15 * 86400}]})
        self.assertEqual(got, [15, 0, 0])

    def test_branches_and_reviews_with_the_key(self):
        got = js("return J.codeOf('ABC-1136', D.p);", {"p": [{"repos": [{"kind": "gitlab", "names": ["task/abc1136-house", "task/abc11360-x", "main"],
                                                                       "prs": [{"n": 57, "branch": "task/abc1136-house", "title": "x", "url": "u"}]}]}]})
        self.assertEqual(got["branches"], ["task/abc1136-house"])
        self.assertEqual([x["n"] for x in got["prs"]], [57])

    def test_a_big_column_groups_by_the_hub_line(self):
        got = js("""const st = ["none", "work", "you", "done", "wait", "work"];
          return J.compactGroups(st.map((s, i) => ({key: i, s})), (it) => ({state: it.s})).map((g) => [g.state, g.items.length, g.folded]);""", {})
        self.assertEqual(got, [["you", 1, False], ["wait", 1, False], ["work", 2, False], ["done", 1, True], ["none", 1, True]])


if __name__ == "__main__":
    unittest.main()
