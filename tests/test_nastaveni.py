"""Testy tools/nastaveni.py – nastavení skillu v projektu (data/nastaveni.json).

Spuštění z kořene repa:  python3 -m unittest discover tests
Bez sítě; každý test si založí projekt ze šablony v dočasné složce (Projekt z test_nastroje).
"""
import hashlib, json, os, subprocess, sys, unittest

from test_nastroje import SKILL, Projekt

PRESNE = '{\n "verze": 1,\n "pomocnici": {\n  "rukopisy": "opus"\n }\n}\n'

ZKUSEBNI = '''"""Falešný nástroj s vlastní sekcí nastavení."""
# NASTAVENI_SEKCE = {"komentar": {"x": {"vychozi": 1, "cele": [1, 2], "popis": "jen v komentáři"}}}
TEXT = "NASTAVENI_SEKCE = {'retezec': {}}"


def vnorena():
    NASTAVENI_SEKCE = {"vnorena": {"x": {"vychozi": 1, "cele": [1, 2], "popis": "jen ve funkci"}}}
    return NASTAVENI_SEKCE


NASTAVENI_SEKCE = {
    "zkouska": {
        "vlakna": {"vychozi": 4, "cele": [1, 64], "popis": "počet vláken"},
        "prikaz": {"vychozi": None, "text": True, "popis": "libovolný text"},
    },
}
'''


class TestNastaveni(Projekt):
    def nast(self, *args):
        return self.nastroj("nastaveni.py", *args)

    def soubor(self):
        return self.path("data", "nastaveni.json")

    def uloz(self, text):
        with open(self.soubor(), "w", encoding="utf-8", newline="") as f:
            f.write(text)

    def bajty(self):
        with open(self.soubor(), "rb") as f:
            return f.read()

    def test_bez_souboru_vychozi_a_zeptej_se(self):
        p = self.nast("ukaz")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("→ ZEPTEJ_SE pomocnici.rukopisy", p.stdout)
        self.assertIn("pomocnici.ostatni = sonnet", p.stdout)
        self.assertFalse(os.path.exists(self.soubor()))

    def test_nastav_zapise_presny_text(self):
        p = self.nast("nastav", "pomocnici.rukopisy", "opus")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.bajty(), PRESNE.encode())
        p = self.nast("ukaz", "pomocnici")
        self.assertIn("pomocnici.rukopisy = opus", p.stdout)
        self.assertNotIn("ZEPTEJ_SE", p.stdout)

    def test_nastav_velka_pismena_normalizuje(self):
        p = self.nast("nastav", "pomocnici.rukopisy", "Opus")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.bajty(), PRESNE.encode())

    def test_neplatna_hodnota_nic_nezmeni(self):
        p = self.nast("nastav", "pomocnici.rukopisy", "")
        self.assertEqual(p.returncode, 1)
        self.assertIn("neprázdný text", p.stderr)
        self.assertFalse(os.path.exists(self.soubor()))
        self.nast("nastav", "pomocnici.rukopisy", "opus")
        p = self.nast("nastav", "pomocnici.ostatni", "   ")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.bajty(), PRESNE.encode())

    def test_libovolny_model_hostitele(self):
        self.assertEqual(self.nast("nastav", "pomocnici.rukopisy", "fable").returncode, 0)
        self.assertEqual(self.nast("nastav", "pomocnici.ostatni", " Haiku ").returncode, 0)
        self.assertEqual(json.loads(self.bajty())["pomocnici"], {"rukopisy": "fable", "ostatni": "haiku"})
        p = self.nast("ukaz", "pomocnici")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("pomocnici.rukopisy = fable", p.stdout)
        self.assertIn("alias sonnet, opus, haiku nebo fable", p.stdout)
        self.uloz('{"pomocnici": {"rukopisy": ""}}')
        p = self.nast("ukaz", "pomocnici")
        self.assertEqual(p.returncode, 1)
        self.assertIn("CHYBA", p.stderr)

    def test_neznamy_klic_a_sekce_odmitne(self):
        for klic in ("pomocnici.rukopis", "ocrr.model", "pomocnici"):
            p = self.nast("nastav", klic, "opus")
            self.assertEqual(p.returncode, 1, klic)
            self.assertIn("nezn", p.stderr, klic)
        self.assertFalse(os.path.exists(self.soubor()))

    def test_vychozi_smaze_klic_a_prazdnou_sekci(self):
        p = self.nast("nastav", "pomocnici.rukopisy", "vychozi")   # bez souboru: nic nezakládá
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(os.path.exists(self.soubor()))
        self.nast("nastav", "pomocnici.rukopisy", "opus")
        self.nast("nastav", "pomocnici.ostatni", "opus")
        self.nast("nastav", "pomocnici.ostatni", "vychozi")
        self.assertEqual(self.bajty(), PRESNE.encode())
        p = self.nast("nastav", "pomocnici.rukopisy", "vychozi")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(self.bajty()), {"verze": 1})
        self.assertIn("→ ZEPTEJ_SE pomocnici.rukopisy", self.nast("ukaz").stdout)

    def test_nezname_klice_varuji_a_zapis_je_zachova(self):
        self.uloz('{"verze": 1, "budouci": {"a": 1}, "pomocnici": {"novy": "x"}}')
        p = self.nast("ukaz")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("budouci", p.stderr)
        self.assertIn("pomocnici.novy", p.stderr)
        p = self.nast("nastav", "pomocnici.rukopisy", "sonnet")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(self.bajty()),
                         {"verze": 1, "budouci": {"a": 1}, "pomocnici": {"novy": "x", "rukopisy": "sonnet"}})

    def test_rozbity_json_ukaz_chyba_nastav_neprepise(self):
        self.uloz('{"verze": 1, "pomocnici": {"rukopisy": "opus",}')
        puvodni = self.bajty()
        p = self.nast("ukaz")
        self.assertEqual(p.returncode, 1)
        self.assertIn("nejde přečíst", p.stderr)
        p = self.nast("nastav", "pomocnici.rukopisy", "sonnet")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.bajty(), puvodni)

    def test_spatne_typy(self):
        for text in ('[]', '{"pomocnici": "opus"}', '{"verze": "1"}', '{"verze": true}', '{"verze": 0}'):
            self.uloz(text)
            p = self.nast("ukaz")
            self.assertEqual(p.returncode, 1, text)
            self.assertIn("CHYBA" if "pomocnici" in text else "nastaveni.json", p.stderr, text)
            p = self.nast("nastav", "pomocnici.rukopisy", "opus")
            self.assertEqual(p.returncode, 1, text)
            self.assertEqual(self.bajty(), text.encode(), text)
        self.uloz('{"pomocnici": {"rukopisy": 5, "ostatni": "opus"}}')
        p = self.nast("ukaz")
        self.assertEqual(p.returncode, 1)
        self.assertIn("pomocnici.rukopisy", p.stderr)
        self.assertIn("vychozi", p.stderr)   # rada, jak to opravit
        self.assertIn("pomocnici.ostatni = opus", p.stdout)   # platné volby se vypíšou i tak
        p = self.nast("nastav", "pomocnici.rukopisy", "vychozi")   # opravit jde nástrojem
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(self.bajty()), {"verze": 1, "pomocnici": {"ostatni": "opus"}})

    def test_novejsi_verze_varuje_a_cte(self):
        self.uloz('{"verze": 2, "pomocnici": {"rukopisy": "opus"}}')
        p = self.nast("ukaz")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("verzi 2", p.stderr)
        self.assertIn("pomocnici.rukopisy = opus", p.stdout)
        self.nast("nastav", "pomocnici.ostatni", "opus")
        self.assertEqual(json.loads(self.bajty())["verze"], 2)

    def test_bom_precte(self):
        with open(self.soubor(), "wb") as f:
            f.write(b"\xef\xbb\xbf" + b'{"verze": 1, "pomocnici": {"rukopisy": "sonnet"}}')
        p = self.nast("ukaz")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("pomocnici.rukopisy = sonnet", p.stdout)
        p = self.nast("nastav", "pomocnici.ostatni", "opus")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(self.bajty().startswith(b"\xef\xbb\xbf"))

    def volej(self, kod):
        """Python v projektu: import nastaveni z projektové kopie tools/."""
        return subprocess.run([sys.executable, "-I", "-X", "utf8", "-c",
                               "import sys; sys.path.insert(0, 'tools'); import nastaveni\n" + kod],
                              cwd=self.root, capture_output=True, text=True, encoding="utf-8")

    def test_chyba_v_jine_sekci_neblokuje(self):
        self.uloz('{"verze": 1, "pomocnici": {"rukopisy": "opus"}, "zkouska": "rozbite"}')
        with open(self.path("tools", "zkusebni.py"), "w", encoding="utf-8") as f:
            f.write(ZKUSEBNI)
        p = self.volej("print(nastaveni.sekce('pomocnici'))")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("'rukopisy': 'opus'", p.stdout)
        p = self.volej("nastaveni.sekce('zkouska')")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("zkouska", p.stderr)
        p = self.nast("ukaz")
        self.assertEqual(p.returncode, 1)
        self.assertIn("pomocnici.rukopisy = opus", p.stdout)

    def test_sekce_z_jineho_nastroje(self):
        with open(self.path("tools", "zkusebni.py"), "w", encoding="utf-8") as f:
            f.write(ZKUSEBNI)
        p = self.nast("ukaz", "zkouska")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("zkouska.vlakna = 4", p.stdout)
        self.assertIn("→ ZEPTEJ_SE zkouska.prikaz", p.stdout)
        for spatne in ("0", "65", "abc"):
            self.assertEqual(self.nast("nastav", "zkouska.vlakna", spatne).returncode, 1, spatne)
        for dobre in ("1", "64"):
            self.assertEqual(self.nast("nastav", "zkouska.vlakna", dobre).returncode, 0, dobre)
            self.assertEqual(json.loads(self.bajty())["zkouska"]["vlakna"], int(dobre))
        self.assertEqual(self.nast("nastav", "zkouska.prikaz", "tesseract --psm 6").returncode, 0)
        self.assertEqual(json.loads(self.bajty())["zkouska"]["prikaz"], "tesseract --psm 6")
        p = self.volej("print(sorted(nastaveni.schema()))")
        self.assertEqual(p.stdout.strip(), "['pomocnici', 'zkouska']")   # komentář, řetězec ani funkce se nepočítají

    def test_vadna_nebo_dvojita_deklarace(self):
        vadna = self.path("tools", "vadny.py")
        for text, hlaska in (('NASTAVENI_SEKCE = dict(x={})\n', "literál"),
                             ('NASTAVENI_SEKCE = {"x": {"k": {"vychozi": 1, "popis": "bez druhu"}}}\n', "právě jedno"),
                             ('NASTAVENI_SEKCE = {"pomocnici": {"k": {"vychozi": "a", "hodnoty": ["a"], '
                              '"popis": "p"}}}\n', "dvakrát")):
            with open(vadna, "w", encoding="utf-8") as f:
                f.write(text)
            p = self.nast("ukaz")
            self.assertEqual(p.returncode, 1, text)
            self.assertIn("vadny.py", p.stderr, text)
            self.assertIn(hlaska, p.stderr, text)

    def test_soubeh_dvou_zapisu(self):
        for _ in range(5):
            if os.path.exists(self.soubor()):
                os.remove(self.soubor())
            procesy = [subprocess.Popen([sys.executable, "-I", self.path("tools", "nastaveni.py"), "nastav", k, "opus"],
                                        cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                       for k in ("pomocnici.rukopisy", "pomocnici.ostatni")]
            for p in procesy:
                out, err = p.communicate()
                self.assertEqual(p.returncode, 0, err)
            self.assertEqual(json.loads(self.bajty())["pomocnici"], {"rukopisy": "opus", "ostatni": "opus"})

    def test_aktualizace_nezmeni_soubor(self):
        self.assertTrue(os.path.exists(self.path("tools", "nastaveni.py")))
        self.nast("nastav", "pomocnici.rukopisy", "opus")
        pred = hashlib.sha256(self.bajty()).hexdigest()
        p = subprocess.run([sys.executable, "-I", os.path.join(SKILL, "tools", "novy_projekt.py"), self.root],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(hashlib.sha256(self.bajty()).hexdigest(), pred)

    def test_odmitne_bezet_ze_slozky_skillu(self):
        p = subprocess.run([sys.executable, "-I", os.path.join(SKILL, "tools", "nastaveni.py"), "nastav",
                            "pomocnici.rukopisy", "opus"], capture_output=True, text=True, encoding="utf-8")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("není složka projektu", p.stdout + p.stderr)
        self.assertFalse(os.path.exists(os.path.join(SKILL, "data")))


if __name__ == "__main__":
    unittest.main()
