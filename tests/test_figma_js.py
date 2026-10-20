import json
import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import memory  # noqa: E402

NODE = shutil.which("node")
RUN = """
import { figmaAbout, figmaHref, figmaMeta } from %s;
const out = JSON.parse(process.argv[1]).map((u) => { const f = figmaMeta(u); return [figmaHref(u), f && figmaAbout(f), f && f.name]; });
console.log(JSON.stringify(out));
"""


def meta(*urls):
    src = RUN % json.dumps("file://" + os.path.join(ROOT, "web", "figma.js"))
    r = subprocess.run([NODE, "--input-type=module", "-e", src, json.dumps(urls)], capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


@unittest.skipUnless(NODE, "нужен node")
class FigmaJs(unittest.TestCase):
    def test_the_kind_and_the_name_come_from_the_address(self):
        got = meta("https://www.figma.com/design/Dm0LuMeN42/Lumen-App?node-id=12-80",
                   "https://figma.com/file/Pk7NoTes/Pocket-Notes",
                   "https://www.figma.com/board/RiDgE9/Ridge-Flow",
                   "https://www.figma.com/proto/Xy/On-boarding--v2",
                   "https://www.figma.com/slides/Ab/Pitch",
                   "https://www.figma.com/deck/Ab/Pitch",
                   "https://www.figma.com/make/Ab/Toy",
                   "https://www.figma.com/design/OnlyKey",
                   "https://www.figma.com/files/team/123/Team-Page",
                   "https://www.figma.com/constructor/Ab/Name")
        self.assertEqual([x[1] for x in got], [
            "макет «Lumen App»", "макет «Pocket Notes»", "доска FigJam «Ridge Flow»", "прототип «On boarding v2»",
            "слайды «Pitch»", "слайды «Pitch»", "Make «Toy»", "макет", "файл", "файл"])

    def test_the_name_is_decoded_and_a_broken_escape_keeps_it_as_is(self):
        got = meta("https://www.figma.com/design/K/%D0%9B%D1%83%D0%BC%D0%B5%D0%BD-%D0%BC%D0%B0%D0%BA%D0%B5%D1%82",
                   "https://www.figma.com/design/K/100%-done",
                   "https://www.figma.com/design/K/%E0%A4%A")
        self.assertEqual([x[2] for x in got], ["Лумен макет", "100% done", "%E0%A4%A"])

    def test_only_https_figma_links_open_as_memory_accepts_them(self):
        urls = ["https://www.figma.com/design/K/N", "https://figma.com/board/K", "  https://figma.com/file/K/N  ",
                "http://www.figma.com/design/K/N", "https://evil.com/design/K/N", "https://figma.com.evil.com/design/K",
                "https://user:pw@www.figma.com/design/K", "https://www.figma.com/", "javascript:alert(1)", "not a link"]
        got = meta(*urls)
        self.assertEqual([bool(x[0]) for x in got], [memory.figma_ok(u.strip()) for u in urls])
        self.assertEqual([bool(x[0]) for x in got], [True, True, True] + [False] * 7)
        self.assertEqual([x[1] for x in got[3:]], [None] * 7)


if __name__ == "__main__":
    unittest.main()
