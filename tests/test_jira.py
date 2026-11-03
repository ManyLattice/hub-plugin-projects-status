import base64
import io
import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jira  # noqa: E402

TOKEN = "ATATT3xTESTtoken="
NOW = 1_800_000_000
DAY = 86400


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000+0000", time.gmtime(ts))


def raw(key, status="11", cat="indeterminate", days=1, **f):
    return {"key": key, "fields": {"summary": f"Задача {key}", "status": {"id": status, "name": {"11": "В работе", "14": "Готово"}.get(status, "?"),
            "statusCategory": {"key": cat}}, "issuetype": f.pop("issuetype", {"name": "Story", "hierarchyLevel": 0}),
            "assignee": {"accountId": "me", "displayName": "Я"}, "labels": ["dash"], "updated": iso(NOW - days * DAY),
            "statusCategoryChangedDate": iso(NOW - days * DAY), "sprint": {"id": 7, "name": "S 7", "state": "active"},
            "customfield_10016": 3, **f}}


class Fake:
    """Jira по путям: {путь: ответ или код ошибки}; site и шлюз - разные базы."""

    def __init__(self, routes, gateway_only=False):
        self.routes, self.gateway_only, self.calls = routes, gateway_only, []

    def __call__(self, req, timeout):
        u = urllib.parse.urlsplit(req.full_url)
        self.calls.append((u.netloc, u.path, dict(urllib.parse.parse_qsl(u.query)), req.headers.get("Authorization")))
        if u.path == "/_edge/tenant_info":
            return io.BytesIO(json.dumps({"cloudId": "c1"}).encode())
        path = u.path.replace("/ex/jira/c1", "")
        gw = u.path.startswith("/ex/jira/c1")
        if req.headers.get("Authorization") != "Basic " + base64.b64encode(f"me@x.com:{TOKEN}".encode()).decode() or \
                (self.gateway_only and not gw):
            raise urllib.error.HTTPError(req.full_url, 401, "no", {}, None)
        r = self.routes.get(path, 404)
        if isinstance(r, int):
            raise urllib.error.HTTPError(req.full_url, r, "x", {}, None)
        return io.BytesIO(json.dumps(r(dict(urllib.parse.parse_qsl(u.query))) if callable(r) else r).encode())


CONFIG = {"name": "B", "columnConfig": {"columns": [{"name": "К выполнению", "statuses": [{"id": "10"}]}, {"name": "В работе", "statuses": [{"id": "11"}]},
          {"name": "Пустая", "statuses": []}, {"name": "Готово", "statuses": [{"id": "14"}]}]},
          "estimation": {"field": {"fieldId": "customfield_10016", "displayName": "Story Points"}}}


def routes(issues=None, **over):
    r = {"/rest/api/2/myself": {"accountId": "me", "displayName": "Я"},
         "/rest/agile/1.0/board": {"isLast": True, "values": [{"id": 5, "name": "B", "type": "scrum", "location": {"projectKey": "ABC"}}]},
         "/rest/agile/1.0/board/5/configuration": CONFIG,
         "/rest/agile/1.0/board/5/sprint": {"values": [{"id": 7, "name": "S 7", "state": "active", "endDate": "2027-01-07T00:00:00.000Z"}]},
         "/rest/agile/1.0/board/5/issue": lambda q: {"total": len(issues or []), "issues": (issues or [])[int(q.get("startAt", 0)):][:int(q.get("maxResults", 50))]},
         "/rest/api/2/issue/ABC-1/comment": {"comments": [{"author": {"displayName": "Анна"}, "created": iso(NOW - 3600), "body": "*Готово*, см. [ссылку|https://x]"}]}}
    r.update(over)
    return r


class Store:
    def __init__(self, token=TOKEN, ok=True):
        self.token, self.ok, self.put_calls = token, ok, []

    def available(self):
        return self.ok

    def get(self, acct):
        return self.token

    def put(self, acct, token):
        self.put_calls.append(acct)


def board(fake, store=None, settings=None):
    state = tempfile.mkdtemp()
    jira.save_settings(state, settings or {"url": "https://site.atlassian.net", "email": "me@x.com", "board": 5, "project": ""})
    return jira.Board(state, opener=fake, store=store or Store(), clock=lambda: NOW)


class Clean(unittest.TestCase):
    def test_settings_are_checked_and_default_to_the_hub_jira_address(self):
        s = jira.clean({"email": "me@x.com", "board": "5", "project": "abc"}, "https://site.atlassian.net/browse")
        self.assertEqual((s["url"], s["board"], s["project"]), ("https://site.atlassian.net", 5, "ABC"))
        for bad in ({"url": "ftp://x", "email": "me@x.com"}, {"url": "http://evil.com", "email": "me@x.com"},
                    {"url": "https://s.atlassian.net", "email": "nope"}, {"url": "https://s.atlassian.net", "email": "a@b", "board": "x"},
                    {"url": "https://s.atlassian.net", "email": "a@b", "project": "a b"}):
            with self.assertRaises(ValueError):
                jira.clean(bad)

    def test_a_local_http_address_is_allowed_only_for_a_stand(self):
        self.assertEqual(jira.site_of("http://127.0.0.1:8900/x"), "http://127.0.0.1:8900")
        self.assertIsNone(jira.site_of("http://site.atlassian.net"))

    def test_nothing_of_one_company_is_built_in(self):
        src = "".join(open(os.path.join(os.path.dirname(jira.__file__), f), encoding="utf-8").read()
                      for f in ("jira.py", "main.py", "hubtasks.py", "web/jira.js", "web/jirapure.js"))
        for word in ("visualpharm", "board/93", "MS-", "10533"):
            self.assertNotIn(word, src)


class Parse(unittest.TestCase):
    def test_an_issue_keeps_only_the_fields_the_view_needs(self):
        i = jira.issue(raw("ABC-1", issuetype={"name": "Ошибка", "hierarchyLevel": 0}), "customfield_10016")
        self.assertEqual((i["key"], i["type"], i["sp"], i["status"]["id"], i["status"]["cat"]), ("ABC-1", "bug", 3, "11", "indeterminate"))
        self.assertEqual(i["sprint"], {"id": 7, "name": "S 7", "state": "active"})
        self.assertEqual(jira.issue(raw("ABC-2", issuetype={"name": "Epic", "hierarchyLevel": 1}))["type"], "epic")

    def test_comment_markup_becomes_one_plain_line(self):
        self.assertEqual(jira.plain("h2. Итог\n*Готово*, см. [ссылку|https://x] [~accountid:abc]"), "Итог Готово, см. ссылку @")
        adf = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Привет"}, {"type": "mention", "attrs": {"text": "@Анна"}}]}]}
        self.assertEqual(jira.plain(adf), "Привет@Анна")


class Connect(unittest.TestCase):
    def test_a_classic_token_goes_to_the_site_and_a_scoped_one_through_the_gateway(self):
        fake = Fake(routes())
        c = jira.Client("https://site.atlassian.net", "me@x.com", TOKEN, fake)
        c.connect()
        self.assertEqual(c.base, "https://site.atlassian.net")
        fake = Fake(routes(), gateway_only=True)
        c = jira.Client("https://site.atlassian.net", "me@x.com", TOKEN, fake)
        c.connect()
        self.assertEqual(c.base, f"{jira.GATEWAY}/ex/jira/c1")
        c.config(5)
        self.assertEqual(fake.calls[-1][1], "/ex/jira/c1/rest/agile/1.0/board/5/configuration")

    def test_only_get_requests_are_made(self):
        seen = []

        def opener(req, timeout):
            seen.append(req.get_method())
            return Fake(routes([raw("ABC-1")]))(req, timeout)
        b = board(opener)
        b.cycle()
        self.assertEqual(set(seen), {"GET"})

    def test_check_names_the_missing_rights(self):
        fake = Fake(routes(**{"/rest/agile/1.0/board/5/configuration": 403}))
        r = jira.check({"url": "https://site.atlassian.net", "email": "me@x.com", "board": 5, "project": ""}, TOKEN, fake)
        st = {s["what"]: s for s in r["steps"]}
        self.assertTrue(st["myself"]["ok"])
        self.assertTrue(st["boards"]["ok"])
        self.assertFalse(st["config"]["ok"])
        self.assertIn("read:board-scope.admin:jira-software", st["config"]["need"])
        self.assertTrue(st["sprints"]["ok"])
        self.assertEqual(r["me"]["name"], "Я")
        self.assertNotIn(TOKEN, json.dumps(r, ensure_ascii=False))

    def test_a_classic_token_is_flagged_as_having_write_rights(self):
        r = jira.check({"url": "https://site.atlassian.net", "email": "me@x.com", "board": 5}, TOKEN, Fake(routes()))
        self.assertIn("все права", r["warn"])
        r = jira.check({"url": "https://site.atlassian.net", "email": "me@x.com", "board": 5}, TOKEN, Fake(routes(), gateway_only=True))
        self.assertNotIn("warn", r)

    def test_a_done_issue_counts_from_its_last_move_not_only_from_the_category_change(self):
        moved = raw("ABC-5", status="14", cat="done", days=30)
        moved["fields"]["updated"] = iso(NOW - DAY)
        b = board(Fake(routes([moved])))
        b.cycle()
        self.assertEqual([i["key"] for i in b.snapshot()["issues"]], ["ABC-5"])

    def test_check_with_a_wrong_token_stops_at_who_you_are(self):
        r = jira.check({"url": "https://site.atlassian.net", "email": "me@x.com", "board": 5}, "ATATT3xWRONG=", Fake(routes()))
        self.assertEqual([(s["what"], s["ok"]) for s in r["steps"]], [("myself", False)])
        self.assertIn("токен не подходит", r["steps"][0]["why"])


class Poll(unittest.TestCase):
    def test_board_columns_issues_and_comments(self):
        old_done = raw("ABC-3", status="14", cat="done", days=30)
        fake = Fake(routes([raw("ABC-1"), raw("ABC-2", status="14", cat="done", days=2), old_done,
                            raw("ABC-9", issuetype={"name": "Epic", "hierarchyLevel": 1})]))
        b = board(fake)
        b.cycle()
        d = b.snapshot()
        self.assertEqual(d["state"], "ok")
        self.assertEqual([c["name"] for c in d["columns"]], ["К выполнению", "В работе", "Готово"])
        self.assertEqual([i["key"] for i in d["issues"]], ["ABC-1", "ABC-2"])
        self.assertEqual(d["issues"][0]["comments"][0]["text"], "Готово, см. ссылку")
        self.assertEqual(d["issues"][0]["url"], "https://site.atlassian.net/browse/ABC-1")
        jql = next(q for _, p, q, _ in fake.calls if p.endswith("/board/5/issue"))["jql"]
        self.assertEqual(jql, "status not in (14) OR updated >= -14d")
        self.assertEqual(b.keys(), ["ABC"])
        self.assertNotIn(TOKEN, json.dumps(d, ensure_ascii=False))

    def test_comments_are_fetched_again_only_for_changed_issues(self):
        issues = [raw("ABC-1")]
        fake = Fake(routes(issues))
        b = board(fake)
        b.cycle()
        b.cycle()
        self.assertEqual(sum(p.endswith("/comment") for _, p, _, _ in fake.calls), 1)
        issues[0] = raw("ABC-1", days=0)
        b.cycle()
        self.assertEqual(sum(p.endswith("/comment") for _, p, _, _ in fake.calls), 2)

    def test_the_column_date_is_remembered_across_polls(self):
        issues = [raw("ABC-1", days=5)]
        b = board(Fake(routes(issues)))
        b.cycle()
        self.assertEqual(b.snapshot()["issues"][0]["since"], NOW - 5 * DAY)
        issues[0] = raw("ABC-1", status="10", cat="new", days=1)
        b.cycle()
        self.assertEqual(b.snapshot()["issues"][0]["since"], NOW - DAY)
        again = jira.Board(b.state, opener=Fake(routes(issues)), store=Store(), clock=lambda: NOW)
        again.cycle()
        self.assertEqual(again.snapshot()["issues"][0]["since"], NOW - DAY)

    def test_without_a_token_or_a_board_the_view_is_off(self):
        b = board(Fake(routes()), store=Store(token=None))
        b.cycle()
        self.assertEqual((b.snapshot()["state"], b.snapshot()["why"]), ("off", "нет токена"))
        b = board(Fake(routes()), settings={"url": "https://site.atlassian.net", "email": "me@x.com", "board": None})
        b.cycle()
        self.assertEqual(b.snapshot()["why"], "не выбрана доска")

    def test_the_first_poll_replaces_connecting(self):
        b = board(Fake(routes([raw("ABC-1")])))
        b.reconnect()
        self.assertEqual(b.snapshot()["state"], "connecting")
        b.cycle()
        self.assertEqual(b.snapshot()["state"], "ok")
        b = board(Fake(routes()), store=Store(token=None))
        b.reconnect()
        b.cycle()
        self.assertEqual(b.snapshot()["state"], "off")

    def test_a_fresh_process_with_saved_settings_starts_connecting(self):
        self.assertEqual(board(Fake(routes())).snapshot()["state"], "connecting")
        self.assertEqual(jira.Board(tempfile.mkdtemp()).snapshot()["state"], "off")
        no_board = board(Fake(routes()), settings={"url": "https://site.atlassian.net", "email": "me@x.com", "board": None})
        self.assertEqual(no_board.snapshot()["state"], "off")

    def test_no_keychain_is_said_plainly(self):
        b = board(Fake(routes()), store=Store(ok=False))
        b.cycle()
        self.assertEqual(b.snapshot()["state"], "nostore")
        self.assertIn("хранить токен негде", b.snapshot()["why"])

    def test_an_expired_token_keeps_the_last_board_with_the_reason(self):
        issues = [raw("ABC-1")]
        fake = Fake(routes(issues))
        b = board(fake)
        b.cycle()
        fake.routes["/rest/agile/1.0/board/5/issue"] = 401
        b.cycle()
        d = b.snapshot()
        self.assertEqual((d["state"], d["status"]), ("error", 401))
        self.assertIn("токен не подходит", d["why"])
        self.assertEqual(len(d["issues"]), 1)

    def test_a_kanban_board_has_no_sprints(self):
        b = board(Fake(routes([raw("ABC-1")], **{"/rest/agile/1.0/board/5/sprint": 400})))
        b.cycle()
        self.assertEqual(b.snapshot()["state"], "ok")
        self.assertIsNone(b.snapshot()["sprints"])

    def test_the_project_setting_narrows_the_jql(self):
        fake = Fake(routes([raw("ABC-1")]))
        b = board(fake, settings={"url": "https://site.atlassian.net", "email": "me@x.com", "board": 5, "project": "ABC"})
        b.cycle()
        jql = next(q for _, p, q, _ in fake.calls if p.endswith("/board/5/issue"))["jql"]
        self.assertTrue(jql.startswith("project = ABC AND ("))


if __name__ == "__main__":
    unittest.main()
