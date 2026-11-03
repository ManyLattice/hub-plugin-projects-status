import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import keystore  # noqa: E402

MAC = {"platform": "darwin", "which": lambda x: "/usr/bin/security"}


class Run:
    def __init__(self, code=0, out="", err=""):
        self.calls, self.code, self.out, self.err = [], code, out, err

    def __call__(self, args, **kw):
        self.calls.append((args, kw.get("input")))
        return subprocess.CompletedProcess(args, self.code, self.out, self.err)


class Keystore(unittest.TestCase):
    def test_the_token_goes_by_stdin_and_never_into_the_arguments(self):
        run = Run()
        keystore.put("me@example.com site.atlassian.net", "ATATT3x_secret=", run=run, **MAC)
        args, stdin = run.calls[0]
        self.assertEqual(args, ["security", "-i"])
        self.assertNotIn("ATATT3x_secret=", " ".join(args))
        self.assertIn('-s hub-jira-read -a "me@example.com site.atlassian.net"', stdin)
        self.assertIn('-w "ATATT3x_secret="', stdin)

    def test_a_token_with_quotes_or_spaces_is_refused_before_security_runs(self):
        run = Run()
        for bad in ['abc" -w x', "with space token", "short"]:
            with self.assertRaises(ValueError):
                keystore.put("me@example.com h", bad, run=run, **MAC)
        self.assertEqual(run.calls, [])

    def test_without_the_macos_keychain_there_is_nowhere_to_keep_it(self):
        for kw in ({"platform": "linux", "which": lambda x: None}, {"platform": "win32", "which": lambda x: None},
                   {"platform": "darwin", "which": lambda x: None}):
            self.assertFalse(keystore.available(**kw))
            with self.assertRaises(keystore.Unavailable) as e:
                keystore.put("a b", "ATATT3x_secret=", run=Run(), **kw)
            self.assertIn("хранить токен негде", str(e.exception))
            with self.assertRaises(keystore.Unavailable):
                keystore.get("a b", run=Run(), **kw)

    def test_a_missing_item_reads_as_none(self):
        self.assertIsNone(keystore.get("a b", run=Run(code=44, err="could not be found"), **MAC))
        self.assertEqual(keystore.get("a b", run=Run(out="tok\n"), **MAC), "tok")

    def test_an_error_from_security_does_not_echo_the_token(self):
        with self.assertRaises(keystore.Unavailable) as e:
            keystore.put("a b", "ATATT3x_secret=", run=Run(code=1, err="error: ATATT3x_secret= rejected"), **MAC)
        self.assertNotIn("ATATT3x_secret=", str(e.exception))

    def test_the_account_is_email_and_jira_host(self):
        self.assertEqual(keystore.account("https://Site.atlassian.net/jira", " Me@Example.com "), "me@example.com site.atlassian.net")


if __name__ == "__main__":
    unittest.main()
