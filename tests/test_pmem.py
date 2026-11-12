import io
import json
import os
import sys
import tempfile
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


class HubCode(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = os.path.realpath(tmp.name)

    def code(self, name):
        path = os.path.join(self.root, name)
        os.makedirs(os.path.join(path, "core"))
        open(os.path.join(path, "core", "daemon.py"), "w").close()
        return path

    def wrapper(self):
        path = os.path.join(self.root, "bin", "hub")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
        return path

    def find(self, env=None, hub=None):
        return pmem.find_hub_code(env=env or {}, which=lambda _: hub, home=os.path.join(self.root, "home"))

    def test_hub_code_env_comes_first(self):
        code = self.code("own")
        self.code("state/code")
        self.assertEqual(self.find({"HUB_CODE": code, "HUB_STATE_DIR": os.path.join(self.root, "state")}), code)

    def test_a_package_wrapper_in_path_leads_to_the_state_code(self):
        state = os.path.join(self.root, "state")
        code = self.code("state/code")
        self.assertEqual(self.find({"HUB_STATE_DIR": state}, hub=self.wrapper()), code)

    def test_hub_from_a_code_checkout_is_used_when_state_has_no_code(self):
        code = self.code("checkout")
        os.makedirs(os.path.join(code, "bin"))
        exe = os.path.join(code, "bin", "hub")
        open(exe, "w").close()
        self.assertEqual(self.find({"HUB_STATE_DIR": os.path.join(self.root, "empty")}, hub=exe), code)

    def test_work_hub_code_in_home_is_the_last_resort(self):
        code = self.code("home/.hub-core/code")
        self.assertEqual(self.find(hub=self.wrapper()), code)

    def test_a_place_without_core_daemon_is_skipped(self):
        os.makedirs(os.path.join(self.root, "bare", "core"))
        self.assertIsNone(self.find({"HUB_CODE": os.path.join(self.root, "bare")}))

    def test_nothing_found_exits_with_a_hint(self):
        with mock.patch.object(pmem, "find_hub_code", lambda: None):
            with self.assertRaises(SystemExit) as e:
                pmem.hub_code()
        self.assertIn("HUB_CODE", str(e.exception.code))


if __name__ == "__main__":
    unittest.main()
