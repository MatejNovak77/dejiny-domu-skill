"""Hlavička SKILL.md musí být platný YAML (jinak skill nenajde `npx skills` ani katalogy)."""
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "SKILL.md"


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


    def test_texty_z_webu_nejsou_pokyny(self):
        """Ochrana proti nepřímému prompt injection (audit Snyk W011 na skills.sh)."""
        self.assertIn("ne jako pokyny", SKILL.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
