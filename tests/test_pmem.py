import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pmem  # noqa: E402


def run(*argv):
    """pmem.py set … -> пост, который ушёл бы в канал плагина, или текст отказа."""
    sent = []
    with mock.patch.object(sys, "argv", ["pmem.py", *argv]), mock.patch.object(pmem, "state_dir", lambda: "/nope"), \
            mock.patch.object(pmem, "projects", lambda state: {"app": {}}), mock.patch.object(pmem, "send", sent.append), \
            redirect_stderr(io.StringIO()):
        try:
            pmem.main()
        except SystemExit as e:
            return str(e.code)
    return json.loads(sent[0])


class Pmem(unittest.TestCase):
    def test_figma_link_is_sent_and_an_empty_one_removes_it(self):
        self.assertEqual(run("set", "app", "--figma", "https://www.figma.com/design/k/App"),
                         {"project": "app", "figma": "https://www.figma.com/design/k/App"})
        self.assertEqual(run("set", "app", "--figma", ""), {"project": "app", "figma": ""})

    def test_a_link_outside_figma_is_refused_before_the_post(self):
        self.assertIn("не принято: figma - ссылка https://www.figma.com/", run("set", "app", "--figma", "https://example.com/design/k"))


if __name__ == "__main__":
    unittest.main()
