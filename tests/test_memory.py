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

    def test_kind_and_store_figures_are_kept_with_the_history(self):
        m = memory.empty()
        self.assertIsNone(m["kind"])                                                     # без отметки - приложение
        memory.apply(m, upd(project="where", kind="legal"), "hub-dev", 1)
        memory.apply(m, upd(project="where", store="1,2 тыс. загрузок за 30 дн · $40"), "aso", 2)
        self.assertEqual((m["kind"], m["store"], m["store_at"]), ("legal", "1,2 тыс. загрузок за 30 дн · $40", 2))
        self.assertEqual([h["what"] for h in m["history"]], ["тип: legal", "магазин: 1,2 тыс. загрузок за 30 дн · $40"])
        with self.assertRaises(memory.Invalid) as e:
            upd(project="where", kind="game")
        self.assertIn("тип - один из", str(e.exception))
        self.assertIn("Тип: legal", memory.render_md("where", "", m))

    def test_a_figma_link_is_set_replaced_and_removed_with_the_history(self):
        m = memory.empty()
        url = "https://www.figma.com/design/AbC123/Where?node-id=1-2"
        memory.apply(m, upd(project="where", figma=f"  {url} "), "design", 1)
        self.assertEqual(memory.apply(m, upd(project="where", figma=url), "owner", 2), [])    # та же - не правка
        self.assertIn(f"Figma: {url}", memory.render_md("where", "", m))
        memory.apply(m, upd(project="where", figma="https://figma.com/board/Xy9/Flow"), "owner", 3)
        memory.apply(m, upd(project="where", figma=""), "owner", 4)
        self.assertEqual(m["figma"], "")
        self.assertEqual([h["what"] for h in m["history"]],
                         [f"Figma: {url}", "Figma: https://figma.com/board/Xy9/Flow", "Figma снято"])
        self.assertNotIn("\nFigma:", memory.render_md("where", "", m))

    def test_a_memory_without_the_figma_field_takes_a_link(self):
        m = memory.empty()
        del m["figma"]                                                                   # память до 0.9.0
        self.assertEqual(memory.apply(m, upd(project="where", figma=""), "owner", 1), [])
        memory.apply(m, upd(project="where", figma="https://www.figma.com/proto/Q1/Demo"), "owner", 2)
        self.assertEqual(m["figma"], "https://www.figma.com/proto/Q1/Demo")

    def test_only_https_figma_links_are_taken(self):
        for good in ("https://www.figma.com/file/k/Name", "https://figma.com/slides/k", "https://WWW.Figma.com/design/k/x#y"):
            self.assertTrue(upd(project="where", figma=good)["figma"])
        for bad in ("http://www.figma.com/design/k", "https://figma.com", "https://www.figma.com/", "https://evil.com/figma.com/x",
                    "https://figma.com.evil.com/design/k", "https://user@figma.com/design/k", "https://figma.com:8443/design/k",
                    "javascript:alert(1)", "www.figma.com/design/k", "https://www.figma.com/design/k x", 42, None):
            with self.assertRaises(memory.Invalid, msg=bad) as e:
                upd(project="where", figma=bad)
            self.assertIn("figma - ссылка https://www.figma.com/", str(e.exception))

    def test_the_file_for_sessions_has_the_stage_goal_and_next(self):
        m = memory.empty()
        memory.apply(m, upd(project="abrief", stage="Разработка", goal="Выпуск в App Store", add=["Иконка"]), "owner", 1)
        md = memory.render_md("abrief", "пересказы", m)
        self.assertIn("Этап: Разработка", md)
        self.assertIn("- [ ] Иконка", md)
        self.assertIn("владелец", md)


if __name__ == "__main__":
    unittest.main()
