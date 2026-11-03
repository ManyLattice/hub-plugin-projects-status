import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hubtasks  # noqa: E402

REC = """# d{n} — {title}

Поставил: {by} · делает: {doer}

## Задача
{body}

## Ход
- 02.11 10:00 · ядро: задача поставлена: {by} → {doer}
{log}
"""


def write(d, n, title, by="владелец", doer="dash", body="", log=""):
    with open(os.path.join(d, f"d{n}.md"), "w", encoding="utf-8") as f:
        f.write(REC.format(n=n, title=title, by=by, doer=doer, body=body or title, log=log))


class HubTasks(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp()
        self.dir = os.path.join(self.state, "tasks")
        os.makedirs(self.dir)
        self.ix = hubtasks.Index(self.state)

    def test_key_in_the_title_or_task_leads_and_in_the_log_only_mentions(self):
        write(self.dir, 1, "ABC-10: доход по источникам")
        write(self.dir, 2, "Разбор", body="Сделать по ABC-11")
        write(self.dir, 3, "Сводка", log="- 02.11 11:00 · dash: упомянул ABC-10 и XYZ-5")
        got = self.ix.by_key(["ABC"])
        self.assertEqual([(t["id"], t["role"]) for t in got["ABC-10"]], [("d1", "lead"), ("d3", "mention")])
        self.assertEqual(got["ABC-11"][0]["role"], "lead")
        self.assertNotIn("XYZ-5", got)

    def test_keys_listed_in_the_task_text_are_examples_not_its_work(self):
        write(self.dir, 1, "Доска Jira в плагине", body="Как в ABC-1, ABC-2 и ABC-3")
        write(self.dir, 2, "ABC-4: отчёт", body="ABC-4, по образцу ABC-5")
        got = self.ix.by_key(["ABC"])
        self.assertEqual([t["role"] for t in got["ABC-1"]], ["mention"])
        self.assertEqual([t["role"] for t in got["ABC-4"]], ["lead"])
        self.assertEqual([t["role"] for t in got["ABC-5"]], ["mention"])

    def test_a_task_listing_many_keys_leads_none_of_them(self):
        write(self.dir, 1, "ABC-1 ABC-2 ABC-3 ABC-4 ABC-5: доска по ключам")
        got = self.ix.by_key(["ABC"])
        self.assertEqual({t["role"] for k in got for t in got[k]}, {"mention"})

    def test_closed_handed_and_woken_tasks(self):
        write(self.dir, 1, "ABC-1", log="- 02.11 11:00 · dash: итог: Готово, коммит abc\n- 02.11 11:01 · ядро: dash сдал и уснул (разбудить)")
        write(self.dir, 2, "ABC-2", log="- 02.11 11:00 · ядро: задача закрыта (hub-core)\n- 02.11 12:00 · ядро: dash разбужен: Владелец сказал «да»")
        write(self.dir, 3, "ABC-3", log="- 02.11 11:00 · dash: Код: тесты зелёные")
        got = self.ix.by_key(["ABC"])
        t1, t2, t3 = got["ABC-1"][0], got["ABC-2"][0], got["ABC-3"][0]
        self.assertTrue(t1["closed"])
        self.assertTrue(t1["handed"])
        self.assertEqual(t1["last"]["text"], "Готово, коммит abc")
        self.assertFalse(t2["closed"])
        self.assertFalse(t3["closed"])
        self.assertFalse(t3["handed"])
        self.assertEqual(t3["log"][-1]["text"], "Код: тесты зелёные")

    def test_a_date_later_than_the_file_belongs_to_the_previous_year(self):
        ref = time.mktime((2026, 1, 3, 12, 0, 0, 0, 0, -1))
        self.assertEqual(time.localtime(hubtasks.when("30", "12", "10", "00", ref)).tm_year, 2025)
        self.assertEqual(time.localtime(hubtasks.when("02", "01", "10", "00", ref)).tm_year, 2026)

    def test_a_changed_file_is_read_again_and_a_removed_one_drops(self):
        write(self.dir, 1, "ABC-1")
        self.assertIn("ABC-1", self.ix.by_key(["ABC"]))
        write(self.dir, 1, "ABC-2")
        os.utime(os.path.join(self.dir, "d1.md"), (time.time() + 5, time.time() + 5))
        self.assertEqual(list(self.ix.by_key(["ABC"])), ["ABC-2"])
        os.remove(os.path.join(self.dir, "d1.md"))
        self.assertEqual(self.ix.by_key(["ABC"]), {})

    def test_no_project_keys_no_index(self):
        write(self.dir, 1, "ABC-1")
        self.assertEqual(self.ix.by_key([]), {})
        self.assertEqual(self.ix.by_key(["bad key"]), {})


if __name__ == "__main__":
    unittest.main()
