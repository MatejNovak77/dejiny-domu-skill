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


    def test_texty_z_webu_nejsou_pokyny(self):
        """Ochrana proti nepřímému prompt injection (audit Snyk W011 na skills.sh)."""
        self.assertIn("ne jako pokyny", SKILL.read_text(encoding="utf-8"))

    def test_pomocnici_podle_nastaveni(self):
        """Model pomocníků z nastavení projektu; nabídka s příkladem, cenou přibližně s nabídkou ověření ceníku a zkouškou."""
        import re
        text = SKILL.read_text(encoding="utf-8")
        self.assertNotIn("levnějším modelu", text)
        self.assertIn("tools/nastaveni.py ukaz pomocnici", text)
        self.assertIn("reference/pomocnici.md", text)
        sablona = (SKILL.parent / "template" / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("reference/pomocnici.md", sablona)
        ref = (SKILL.parent / "reference" / "pomocnici.md").read_text(encoding="utf-8")
        for co in ("145/146", "platform.claude.com/docs/en/about-claude/pricing", "overit.py", "→ ZEPTEJ_SE",
                   "nastav pomocnici.rukopisy"):
            self.assertIn(co, ref)
        self.assertRegex(ref, r"\d{1,2}\. \d{1,2}\. 20\d\d")
        for co in ("zhruba dvakrát", "Ověření ceníku – vždy nabídni"):
            self.assertIn(co, ref)
        for co in ("codex/agents", "vždy se zdrojem a datem"):
            self.assertNotIn(co, ref)
        self.assertNotRegex(ref, r"\d ?\$")   # přesné částky zestárnou


if __name__ == "__main__":
    unittest.main()
