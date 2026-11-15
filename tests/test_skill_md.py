"""Hlavička SKILL.md musí být platný YAML (jinak skill nenajde `npx skills` ani katalogy)."""
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "dejiny-domu" / "SKILL.md"


class TestSkillMd(unittest.TestCase):
    def test_hlavicka_je_platny_yaml(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("chybí PyYAML")
        hlavicka = SKILL.read_text(encoding="utf-8").split("---")[1]
        data = yaml.safe_load(hlavicka)
        self.assertEqual(data["name"], "dejiny-domu")
        self.assertTrue(data["description"])


if __name__ == "__main__":
    unittest.main()
