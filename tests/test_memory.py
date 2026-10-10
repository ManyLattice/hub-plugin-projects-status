import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory  # noqa: E402

PROJECTS = {"abrief", "where"}


def upd(**kw):
    return memory.parse(json.dumps(kw, ensure_ascii=False), PROJECTS)


class Memory(unittest.TestCase):
    def test_a_stage_change_goes_to_the_history_with_its_author(self):
        m = memory.empty()
        self.assertEqual(memory.apply(m, upd(project="abrief", stage="Разработка", note="перенос C в код"), "abrief-redesign", 10),
                         ["этап - → Разработка", "пояснение этапа: перенос C в код"])
        memory.apply(m, upd(project="abrief", stage="Разработка"), "owner", 11)          # то же - не правка
        self.assertEqual([(h["by"], h["ts"]) for h in m["history"]], [("abrief-redesign", 10)])
        self.assertEqual((m["updated"], m["by"]), (10, "abrief-redesign"))

    def test_next_items_are_added_and_ticked_by_their_start(self):
        m = memory.empty()
        memory.apply(m, upd(project="abrief", add=["Новая иконка - выбор из 4 стилей", "Хвосты"]), "owner", 1)
        memory.apply(m, upd(project="abrief", done=["новая иконка"]), "abrief-redesign", 2)
        self.assertEqual([(x["text"][:5], x["done"]) for x in m["next"]], [("Новая", True), ("Хвост", False)])
        memory.apply(m, upd(project="abrief", add=["хвосты"]), "owner", 3)               # уже есть - не дубль
        self.assertEqual(len(m["next"]), 2)

    def test_bad_posts_are_refused_with_a_reason(self):
        for text, why in (("привет", "не JSON"), ('{"project": "x", "stage": "Разработка"}', "нет проекта"),
                          ('{"project": "abrief", "stage": "Done"}', "этап"), ('{"project": "abrief"}', "нечего менять"),
                          ('{"project": "abrief", "color": 1}', "неизвестные поля")):
            with self.assertRaises(memory.Invalid) as e:
                memory.parse(text, PROJECTS)
            self.assertIn(why, str(e.exception))

    def test_the_file_for_sessions_has_the_stage_goal_and_next(self):
        m = memory.empty()
        memory.apply(m, upd(project="abrief", stage="Разработка", goal="Выпуск в App Store", add=["Иконка"]), "owner", 1)
        md = memory.render_md("abrief", "пересказы", m)
        self.assertIn("Этап: Разработка", md)
        self.assertIn("- [ ] Иконка", md)
        self.assertIn("владелец", md)


if __name__ == "__main__":
    unittest.main()
