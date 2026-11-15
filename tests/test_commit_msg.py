"""Hook commit-msg (tests/commit_msg.py)."""
import unittest

from commit_msg import chyba


class TestCommitMsg(unittest.TestCase):
    def test_platne(self):
        for p in ("fix(skill): oprava", "feat: nové", "release: 0.14.0", "docs(readme)!: změna", "Merge branch x"):
            self.assertIsNone(chyba(p), p)

    def test_neplatne(self):
        for p in ("oprava", "fix(neco): x", "Fix(skill): x", "fix(skill):bez mezery"):
            self.assertIsNotNone(chyba(p), p)

    def test_dlouhy_predmet(self):
        self.assertIn("přes 80 znaků", chyba("fix(skill): " + "x" * 80))


if __name__ == "__main__":
    unittest.main()
