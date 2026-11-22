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

    def test_pomocnici_rukopisy_opus(self):
        """Pravidlo: pomocníci u rukopisů na Opusu, s odkazem na referenci (bez přesného znění)."""
        text = SKILL.read_text(encoding="utf-8")
        zacatek = text.index("### Pomocníci")
        sekce = text[zacatek:text.index("\n#", zacatek + 1)]   # rejstřík nahoře pravidlo nenahradí
        for co in ("opus", "sonnet"):
            self.assertIn(co, sekce.lower())
        self.assertIn("reference/pomocnici.md", sekce)
        self.assertTrue((SKILL.parent / "reference" / "pomocnici.md").is_file())


if __name__ == "__main__":
    unittest.main()
