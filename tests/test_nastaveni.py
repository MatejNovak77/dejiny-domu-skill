"""Testy tools/nastaveni.py – nastavení skillu v projektu (data/nastaveni.json).

Spuštění z kořene repa:  python3 -m unittest discover tests
Bez sítě; každý test si založí projekt ze šablony v dočasné složce (Projekt z test_nastroje). Sekci si deklaruje
falešný nástroj tools/zkusebni.py (ZKUSEBNI) – skill sám žádnou sekci mít nemusí.
"""
import hashlib, json, os, subprocess, sys, unittest

from test_nastroje import SKILL, Projekt

PRESNE = '{\n "verze": 1,\n "zkouska": {\n  "rezim": "presny"\n }\n}\n'

ZKUSEBNI = '''"""Falešný nástroj s vlastní sekcí nastavení."""
# NASTAVENI_SEKCE = {"komentar": {"x": {"vychozi": 1, "cele": [1, 2], "popis": "jen v komentáři"}}}
TEXT = "NASTAVENI_SEKCE = {'retezec': {}}"


def vnorena():
    NASTAVENI_SEKCE = {"vnorena": {"x": {"vychozi": 1, "cele": [1, 2], "popis": "jen ve funkci"}}}
    return NASTAVENI_SEKCE


NASTAVENI_SEKCE = {
    "zkouska": {
        "rezim": {"vychozi": "rychly", "hodnoty": ["rychly", "presny"], "popis": "způsob práce"},
        "vlakna": {"vychozi": 4, "cele": [1, 64], "popis": "počet vláken"},
        "prikaz": {"vychozi": None, "text": True, "popis": "libovolný text"},
    },
}
'''

DRUHY = '''NASTAVENI_SEKCE = {
    "rozsirene": {
        "slozka": {"vychozi": None, "text": True, "nepovinne": True, "popis": "nástroj si poradí sám"},
        "argv": {"vychozi": None, "seznam": True, "nepovinne": True, "popis": "program a jeho argumenty"},
        "otazka": {"vychozi": None, "hodnoty": ["a", "b"], "popis": "na tohle se zeptej"},
    },
}
'''


class TestNastaveni(Projekt):
    def setUp(self):
        super().setUp()
        with open(self.path("tools", "zkusebni.py"), "w", encoding="utf-8") as f:
            f.write(ZKUSEBNI)

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

    def volej(self, kod):
        """Python v projektu: import nastaveni z projektové kopie tools/."""
        return subprocess.run([sys.executable, "-I", "-X", "utf8", "-c",
                               "import sys; sys.path.insert(0, 'tools'); import nastaveni\n" + kod],
                              cwd=self.root, capture_output=True, text=True, encoding="utf-8")

    def test_bez_sekci(self):
        for f in os.listdir(self.path("tools")):   # i nástroje skillu, které sekci mají
            if f.endswith(".py") and f != "nastaveni.py":
                with open(self.path("tools", f), encoding="utf-8") as h:
                    sekce = "\nNASTAVENI_SEKCE = " in h.read()
                if sekce:
                    os.remove(self.path("tools", f))
        p = self.nast("ukaz")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("Žádný nástroj", p.stdout)
        p = self.nast("nastav", "x.y", "z")
        self.assertEqual(p.returncode, 1)
        self.assertIn("neznámá sekce", p.stderr)
        self.assertIn("žádné", p.stderr)
        self.assertFalse(os.path.exists(self.soubor()))

    def test_bez_souboru_vychozi_a_zeptej_se(self):
        p = self.nast("ukaz")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("→ ZEPTEJ_SE zkouska.prikaz", p.stdout)
        self.assertIn("zkouska.rezim = rychly   (výchozí; rychly, presny – způsob práce)", p.stdout)
        self.assertIn("zkouska.vlakna = 4", p.stdout)
        self.assertFalse(os.path.exists(self.soubor()))

    def test_nastav_zapise_presny_text(self):
        p = self.nast("nastav", "zkouska.rezim", "presny")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.bajty(), PRESNE.encode())
        p = self.nast("ukaz", "zkouska")
        self.assertIn("zkouska.rezim = presny   (nastaveno;", p.stdout)

    def test_hodnoty_velka_pismena_normalizuje(self):
        p = self.nast("nastav", "zkouska.rezim", "Presny")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.bajty(), PRESNE.encode())

    def test_neplatna_hodnota_nic_nezmeni(self):
        for klic, hodnota in (("zkouska.rezim", "pomaly"), ("zkouska.prikaz", ""), ("zkouska.prikaz", "   ")):
            p = self.nast("nastav", klic, hodnota)
            self.assertEqual(p.returncode, 1, hodnota)
            self.assertIn("nic jsem nezměnil", p.stderr)
            self.assertFalse(os.path.exists(self.soubor()))
        self.nast("nastav", "zkouska.rezim", "presny")
        self.assertEqual(self.nast("nastav", "zkouska.rezim", "x").returncode, 1)
        self.assertEqual(self.bajty(), PRESNE.encode())

    def test_text_a_cele(self):
        for spatne in ("0", "65", "abc"):
            self.assertEqual(self.nast("nastav", "zkouska.vlakna", spatne).returncode, 1, spatne)
        for dobre in ("1", "64"):
            self.assertEqual(self.nast("nastav", "zkouska.vlakna", dobre).returncode, 0, dobre)
            self.assertEqual(json.loads(self.bajty())["zkouska"]["vlakna"], int(dobre))
        self.assertEqual(self.nast("nastav", "zkouska.prikaz", " tesseract --psm 6 ").returncode, 0)
        self.assertEqual(json.loads(self.bajty())["zkouska"]["prikaz"], "tesseract --psm 6")
        p = self.volej("print(nastaveni.sekce('zkouska'))")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), "{'rezim': 'rychly', 'vlakna': 64, 'prikaz': 'tesseract --psm 6'}")

    def test_neznamy_klic_a_sekce_odmitne(self):
        for klic in ("zkouska.rezm", "zkuska.rezim", "zkouska"):
            p = self.nast("nastav", klic, "presny")
            self.assertEqual(p.returncode, 1, klic)
            self.assertIn("nezn", p.stderr, klic)
        self.assertFalse(os.path.exists(self.soubor()))

    def test_neznamy_klic_v_souboru_chyba(self):
        """Překlep v klíči známé sekce: nástroj nesmí potichu běžet s výchozí hodnotou."""
        self.uloz('{"verze": 1, "zkouska": {"rezm": "presny", "vlakna": 8}}')
        p = self.volej("print(nastaveni.sekce('zkouska'))")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("zkouska.rezm", p.stderr)
        self.assertIn("rezim", p.stderr)   # známé klíče v hlášce
        p = self.nast("ukaz", "zkouska")
        self.assertEqual(p.returncode, 1)
        self.assertIn("CHYBA: neznámá volba „zkouska.rezm“", p.stderr)
        self.assertIn("zkouska.vlakna = 8", p.stdout)   # platné volby se vypíšou i tak

    def test_vychozi_smaze_klic_a_prazdnou_sekci(self):
        p = self.nast("nastav", "zkouska.rezim", "vychozi")   # bez souboru: nic nezakládá
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(os.path.exists(self.soubor()))
        self.nast("nastav", "zkouska.rezim", "presny")
        self.nast("nastav", "zkouska.vlakna", "8")
        self.nast("nastav", "zkouska.vlakna", "vychozi")
        self.assertEqual(self.bajty(), PRESNE.encode())
        p = self.nast("nastav", "zkouska.rezim", "vychozi")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(self.bajty()), {"verze": 1})
        self.assertIn("zkouska.rezim = rychly   (výchozí;", self.nast("ukaz").stdout)

    def test_nezname_sekce_varuji_a_zapis_je_zachova(self):
        self.uloz('{"verze": 1, "budouci": {"a": 1}, "zkouska": {"vlakna": 2}}')
        p = self.nast("ukaz")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("budouci", p.stderr)
        p = self.nast("nastav", "zkouska.rezim", "presny")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(self.bajty()),
                         {"verze": 1, "budouci": {"a": 1}, "zkouska": {"vlakna": 2, "rezim": "presny"}})

    def test_rozbity_json_ukaz_chyba_nastav_neprepise(self):
        self.uloz('{"verze": 1, "zkouska": {"rezim": "presny",}')
        puvodni = self.bajty()
        p = self.nast("ukaz")
        self.assertEqual(p.returncode, 1)
        self.assertIn("nejde přečíst", p.stderr)
        p = self.nast("nastav", "zkouska.rezim", "rychly")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.bajty(), puvodni)

    def test_spatne_typy(self):
        for text in ('[]', '{"zkouska": "presny"}', '{"verze": "1"}', '{"verze": true}', '{"verze": 0}'):
            self.uloz(text)
            p = self.nast("ukaz")
            self.assertEqual(p.returncode, 1, text)
            self.assertIn("CHYBA" if "zkouska" in text else "nastaveni.json", p.stderr, text)
            p = self.nast("nastav", "zkouska.rezim", "presny")
            self.assertEqual(p.returncode, 1, text)
            self.assertEqual(self.bajty(), text.encode(), text)
        self.uloz('{"zkouska": {"vlakna": "5", "rezim": "presny"}}')
        p = self.nast("ukaz")
        self.assertEqual(p.returncode, 1)
        self.assertIn("zkouska.vlakna", p.stderr)
        self.assertIn("vychozi", p.stderr)   # rada, jak to opravit
        self.assertIn("zkouska.rezim = presny", p.stdout)   # platné volby se vypíšou i tak
        p = self.nast("nastav", "zkouska.vlakna", "vychozi")   # opravit jde nástrojem
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(self.bajty()), {"verze": 1, "zkouska": {"rezim": "presny"}})

    def test_novejsi_verze_varuje_a_cte(self):
        self.uloz('{"verze": 2, "zkouska": {"rezim": "presny"}}')
        p = self.nast("ukaz")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("verzi 2", p.stderr)
        self.assertIn("zkouska.rezim = presny", p.stdout)
        self.nast("nastav", "zkouska.vlakna", "2")
        self.assertEqual(json.loads(self.bajty())["verze"], 2)

    def test_bom_precte(self):
        with open(self.soubor(), "wb") as f:
            f.write(b"\xef\xbb\xbf" + b'{"verze": 1, "zkouska": {"rezim": "presny"}}')
        p = self.nast("ukaz")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("zkouska.rezim = presny", p.stdout)
        p = self.nast("nastav", "zkouska.vlakna", "2")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(self.bajty().startswith(b"\xef\xbb\xbf"))

    def test_chyba_v_jine_sekci_neblokuje(self):
        with open(self.path("tools", "druhy.py"), "w", encoding="utf-8") as f:
            f.write('NASTAVENI_SEKCE = {"druha": {"x": {"vychozi": "a", "hodnoty": ["a", "b"], "popis": "p"}}}\n')
        self.uloz('{"verze": 1, "zkouska": {"rezim": "presny"}, "druha": "rozbite"}')
        p = self.volej("print(nastaveni.sekce('zkouska'))")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("'rezim': 'presny'", p.stdout)
        p = self.volej("nastaveni.sekce('druha')")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("druha", p.stderr)
        p = self.nast("ukaz")
        self.assertEqual(p.returncode, 1)
        self.assertIn("zkouska.rezim = presny", p.stdout)

    def test_schema_jen_literal_na_nejvyssi_urovni(self):
        p = self.volej("print(sorted(nastaveni.schema()))")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("'zkouska'", p.stdout)
        for x in ("komentar", "retezec", "vnorena"):   # komentář, řetězec ani funkce se nepočítají
            self.assertNotIn(x, p.stdout)
        p = self.volej("nastaveni.sekce('nic')")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("zkouska", p.stderr)

    def test_vadna_nebo_dvojita_deklarace(self):
        vadna = self.path("tools", "vadny.py")
        for text, hlaska in (('NASTAVENI_SEKCE = dict(x={})\n', "literál"),
                             ('NASTAVENI_SEKCE = {"x": {"k": {"vychozi": 1, "popis": "bez druhu"}}}\n', "právě jedno"),
                             ('NASTAVENI_SEKCE = {"x": {"k": {"vychozi": "A", "hodnoty": ["A"], "popis": "p"}}}\n',
                              "malými"),
                             ('NASTAVENI_SEKCE = {"x": {"k": {"vychozi": "c", "hodnoty": ["a"], "popis": "p"}}}\n',
                              "není povolená"),
                             ('NASTAVENI_SEKCE = {"zkouska": {"k": {"vychozi": "a", "hodnoty": ["a"], '
                              '"popis": "p"}}}\n', "dvakrát")):
            with open(vadna, "w", encoding="utf-8") as f:
                f.write(text)
            p = self.nast("ukaz")
            self.assertEqual(p.returncode, 1, text)
            self.assertIn("vadny.py", p.stderr, text)
            self.assertIn(hlaska, p.stderr, text)

    def test_nepovinna_bez_dotazu(self):
        with open(self.path("tools", "druhy.py"), "w", encoding="utf-8") as f:
            f.write(DRUHY)
        p = self.nast("ukaz", "rozsirene")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("rozsirene.slozka nenastaveno   (neprázdný text – nástroj si poradí sám)", p.stdout)
        self.assertNotIn("ZEPTEJ_SE rozsirene.slozka", p.stdout)
        self.assertIn("→ ZEPTEJ_SE rozsirene.otazka", p.stdout)   # dotaz se nevypnul všem
        p = self.volej("print(nastaveni.sekce('rozsirene'))")
        self.assertEqual(p.stdout.strip(), "{'slozka': None, 'argv': None, 'otazka': None}", p.stderr)
        self.assertEqual(self.nast("nastav", "rozsirene.slozka", "/x").returncode, 0)
        self.assertIn("rozsirene.slozka = /x   (nastaveno;", self.nast("ukaz", "rozsirene").stdout)
        self.assertEqual(self.nast("nastav", "rozsirene.slozka", "vychozi").returncode, 0)
        self.assertIn("rozsirene.slozka nenastaveno", self.nast("ukaz", "rozsirene").stdout)
        vadna = self.path("tools", "vadny.py")
        for text in ('NASTAVENI_SEKCE = {"x": {"k": {"vychozi": "a", "text": True, "nepovinne": True, '
                     '"popis": "p"}}}\n',
                     'NASTAVENI_SEKCE = {"x": {"k": {"vychozi": None, "text": True, "nepovinne": False, '
                     '"popis": "p"}}}\n'):
            with open(vadna, "w", encoding="utf-8") as f:
                f.write(text)
            p = self.nast("ukaz")
            self.assertEqual(p.returncode, 1, text)
            self.assertIn("nepovinne", p.stderr, text)

    def test_seznam(self):
        with open(self.path("tools", "druhy.py"), "w", encoding="utf-8") as f:
            f.write(DRUHY)
        p = self.nast("nastav", "rozsirene.argv", '["ocr", "{x}"]')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(self.bajty()), {"verze": 1, "rozsirene": {"argv": ["ocr", "{x}"]}})
        self.assertIn('rozsirene.argv = ["ocr", "{x}"]   (nastaveno;', self.nast("ukaz", "rozsirene").stdout)
        p = self.volej("print(nastaveni.sekce('rozsirene')['argv'])")
        self.assertEqual(p.stdout.strip(), "['ocr', '{x}']", p.stderr)
        puvodni = self.bajty()
        for spatne in ('ocr {x}', '[]', '[""]', '["a", 3]', '"a"', '{"a": 1}'):
            p = self.nast("nastav", "rozsirene.argv", spatne)
            self.assertEqual(p.returncode, 1, spatne)
            self.assertIn("nic jsem nezměnil", p.stderr, spatne)
            self.assertEqual(self.bajty(), puvodni, spatne)
        self.assertEqual(self.nast("nastav", "rozsirene.argv", '["a"]').returncode, 0)   # hranice: jeden prvek
        self.uloz('{"verze": 1, "rozsirene": {"argv": "ocr"}}')
        p = self.volej("nastaveni.sekce('rozsirene')")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("rozsirene.argv", p.stderr)
        with open(self.path("tools", "vadny.py"), "w", encoding="utf-8") as f:
            f.write('NASTAVENI_SEKCE = {"x": {"k": {"vychozi": None, "seznam": 1, "popis": "p"}}}\n')
        p = self.nast("ukaz")
        self.assertEqual(p.returncode, 1)
        self.assertIn("„seznam“ musí být True", p.stderr)

    def test_soubeh_dvou_zapisu(self):
        for _ in range(5):
            if os.path.exists(self.soubor()):
                os.remove(self.soubor())
            procesy = [subprocess.Popen([sys.executable, "-I", self.path("tools", "nastaveni.py"), "nastav", k, v],
                                        cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                       for k, v in (("zkouska.rezim", "presny"), ("zkouska.vlakna", "8"))]
            for p in procesy:
                out, err = p.communicate()
                self.assertEqual(p.returncode, 0, err)
            self.assertEqual(json.loads(self.bajty())["zkouska"], {"rezim": "presny", "vlakna": 8})

    def test_aktualizace_nezmeni_soubor(self):
        self.assertTrue(os.path.exists(self.path("tools", "nastaveni.py")))
        self.nast("nastav", "zkouska.rezim", "presny")
        pred = hashlib.sha256(self.bajty()).hexdigest()
        p = subprocess.run([sys.executable, "-I", os.path.join(SKILL, "tools", "novy_projekt.py"), self.root],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(hashlib.sha256(self.bajty()).hexdigest(), pred)

    def test_odmitne_bezet_ze_slozky_skillu(self):
        # skill sám žádnou sekci nemá: nastav skončí dřív (neznámá sekce), data/ ve skillu nesmí vzniknout ani tak
        p = subprocess.run([sys.executable, "-I", os.path.join(SKILL, "tools", "nastaveni.py"), "nastav",
                            "zkouska.rezim", "presny"], capture_output=True, text=True, encoding="utf-8")
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(SKILL, "data")))


if __name__ == "__main__":
    unittest.main()
