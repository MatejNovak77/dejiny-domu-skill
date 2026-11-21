"""Testy ocr_hledej.py: hledání v OCR textech se záměnami písmen podle pravidel projektu. Bez internetu.
Zápis pravidel (pridej / odeber) přes skutečný nástroj v projektu testuje test_nastroje.py (TestOcrHledej)."""
import contextlib, io, os, shutil, sys, tempfile, time, unittest

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(KOREN, "skills", "dejiny-domu")
sys.path.insert(0, os.path.join(SKILL, "tools"))
import ocr_hledej as oh  # noqa: E402

DELENI = {"volby": {"deleni_slova": True}}


def tvary(slovo, text, pravidla=None, tvary=None):
    """Nalezené tvary slova v textu."""
    return [text[p:e] for p, e in oh.Vzor(slovo, pravidla, tvary).najdi(text)]


class Zaklad(unittest.TestCase):
    def najde(self, slovo, text, pravidla=None, tv=None):
        self.assertTrue(tvary(slovo, text, pravidla, tv), f"{slovo} v „{text}“ nenalezeno")

    def nenajde(self, slovo, text, pravidla=None, tv=None):
        self.assertFalse(tvary(slovo, text, pravidla, tv), f"{slovo} v „{text}“ nalezeno")


class TestVzor(Zaklad):
    def test_01_presne_bez_pravidel(self):
        for text in ("Gansbauden", "22Gansbauden", "(Gansbauden)", "GansbaudenNr"):
            self.najde("Gansbauden", text, tv="presne")
        for text in ("Gansbaudener", "XGansbauden", "ČGansbauden", "-Gansbauden", "Gans-bauden", "gansbauden"):
            self.nenajde("Gansbauden", text, tv="presne")

    def test_02_bez_escapovani(self):
        self.nenajde("a.b", "axb")
        self.najde("a.b", "a.b")

    def test_03_tvary(self):
        for t in ("Zineckera", "Zineckerové", "Zineckerů", "Zineckerovy", "Zineckerem", "Zineckerová"):
            self.assertEqual(tvary("Zinecker", t), [t])
        for t in ("Zineckerin", "Zineckers"):
            self.nenajde("Zinecker", t)
        for t in ("Friesland", "Friesen", "Friesl"):
            self.nenajde("Fries", t)
        self.assertEqual(tvary("Fries", "Friese"), ["Friese"])   # známý zbytek českých koncovek
        self.nenajde("Zinecker", "Zineckera", tv="presne")
        self.najde("Fries", "Friesen", tv="volne")
        for tv in oh.TVARY:
            self.nenajde("Zinecker", "XZinecker", tv=tv)

    def test_04_zamena(self):
        p = {"zameny": {"d": ["b"], "s": ["ſ", "&"]}}
        for t in ("Gansbauben", "Gan&bauden", "Ganſbauden"):
            self.najde("Gansbauden", t, p)
        self.nenajde("Gansbauden", "Gansbaucen", p)

    def test_05_velikost(self):
        self.nenajde("Gansbauden", "Sansbauden", {"zameny": {"g": ["s"]}})
        self.najde("Gansbauden", "Sansbauden", {"zameny": {"G": ["S"]}})
        self.najde("Erbe", "Erbe", {"zameny": {"e": ["c"]}})   # znak se najde vždy i sám sebou

    def test_06_vic_znaku(self):
        self.assertEqual(tvary("Hammer", "Harnrner", {"zameny": {"m": ["rn"]}}), ["Harnrner"])

    def test_07_skupina_se_pridava(self):
        p = {"zameny": {"c": ["e"]}, "skupiny": {"ck": ["&"]}}
        for t in ("Zine&er", "Zineeker", "Zinecker"):
            self.najde("Zinecker", t, p)

    def test_08_skupina_velke_pismeno(self):
        p = {"skupiny": {"ch": ["d"]}}
        self.najde("Christoph", "Christoph", p)
        self.najde("Christoph", "Dristoph", p)
        self.nenajde("Christoph", "dristoph", p)
        self.najde("Bach", "Bad", p)

    def test_09_deleni_v_radku(self):
        for t in ("Gans-bauden", "Gans⸗ bauden", "Gans¬bauden", "Gans= bauden"):
            self.najde("Gansbauden", t, DELENI)
        self.nenajde("Gansbauden", "Gans -bauden", DELENI)

    def test_10_chybi_prvni_pismeno(self):
        p = {"zameny": {"n": ["u"], "a": ["e"], "d": ["t"]}, "volby": {"chybi_prvni_pismeno": True}}
        self.najde("Gansbauden", "ansbauden", p)
        self.nenajde("Gansbauden", "ausbeuten", p)
        self.najde("Abcdefg", "bcdefg", p)
        self.nenajde("Abcdef", "bcdef", p)
        self.nenajde("Pausbacke", "ausbacke", {"skupiny": {"au": ["ml"]}, "volby": {"chybi_prvni_pismeno": True}})
        self.nenajde("Gansbauden", "ansbauden", {"zameny": p["zameny"]})

    def test_11_vylouceni(self):
        p = {"zameny": {"b": ["h"], "u": ["l"]}}
        pv = dict(p, vyloucit={"hald": "Gänshalde"})
        self.najde("Gansbauden", "Ganshalden", p)
        self.nenajde("Gansbauden", "Ganshalden", pv)
        self.assertEqual(tvary("Gansbauden", "Gänshalde, Gansbauden", pv), ["Gansbauden"])
        self.najde("Haldenbaude", "Haldenbaude", pv)
        self.nenajde("Gansbauden", "GansbaudenHALDE", dict(pv, volby={"tvary": "volne"}))

    def test_12_prekryv_skupin(self):
        self.najde("abc", "ay", {"skupiny": {"bc": ["y"]}})
        p = {"skupiny": {"bc": ["y"], "ab": ["x"]}}
        self.najde("abc", "ay", p)
        self.najde("abc", "xc", p)
        p = {"skupiny": {"ab": ["x"], "bc": ["y"], "cd": ["z"]}}
        for t in ("xz", "ayd", "abcd"):
            self.najde("abcd", t, p)

    def test_13_deleni_uvnitr_skupiny(self):
        p = {"skupiny": {"ck": ["&"]}, "volby": {"deleni_slova": True}}
        self.najde("Zinecker", "Zinec-ker", p)
        self.najde("Zinecker", "Zinec⸗ ker", p)

    def test_37_vyloucit_jednou_na_token(self):
        """R3: kontrola výjimky nejvýš jednou na token – mnoho začátků v dlouhém tokenu bez mezer je lineární."""
        text = "a1" * 100_000
        vzor = oh.Vzor("a1a", {"vyloucit": {"zzz": "nikde"}}, "presne")
        t = time.monotonic()
        n = sum(1 for _ in vzor.najdi(text))
        self.assertEqual(n, 50_000)
        self.assertLess(time.monotonic() - t, 2.0)
        volani = []
        puvodni = vzor._token
        vzor._token = lambda *a: volani.append(1) or puvodni(*a)
        self.assertEqual(sum(1 for _ in vzor.najdi(text + " " + text)), 2 * 50_000)
        self.assertEqual(len(volani), 2)   # jednou na každý token

    def test_38_mez_mezer_po_deleni(self):
        """R3: po znaku dělení nejvýš 250 bílých znaků, i přes konec řádku."""
        self.najde("Gansbauden", "Gans-" + " " * 250 + "bauden", DELENI)
        self.nenajde("Gansbauden", "Gans-" + " " * 251 + "bauden", DELENI)
        self.najde("Gansbauden", "Gans-" + " " * 100 + "\n" + " " * 149 + "bauden", DELENI)
        self.nenajde("Gansbauden", "Gans-" + " " * 100 + "\n" + " " * 150 + "bauden", DELENI)

    def test_39_jeden_znak_deleni(self):
        """R3: nejvýš jeden znak dělení na hranici písmen, i přes konec řádku."""
        for t in ("Gans--bauden", "Gans- -bauden", "Gans-⸗bauden", "Gans-\n-bauden", "Gans-\n  ¬ bauden"):
            self.nenajde("Gansbauden", t, DELENI)
        self.najde("Gansbauden", "Gans-\n  bauden", DELENI)

    def test_36_doba_behu(self):
        def rychle(slovo, text, pravidla, tv=None, nalezu=0):
            t = time.monotonic()
            self.assertEqual(len(tvary(slovo, text, pravidla, tv)), nalezu)
            self.assertLess(time.monotonic() - t, 0.5, slovo[:20])
        ss = {"zameny": {"s": ["ss"]}}
        rychle("s" * 28, "s" * 56 + "x", ss, "presne")
        rychle("s" * 28, "s" * 56 + "x", ss, "ceske")
        bloky = {"skupiny": {"ab": ["x", "xx", "a"]}, "zameny": {"a": ["x"], "b": ["x", "xx"]},
                 "volby": {"deleni_slova": True}}
        rychle("ab" * 14, "x" * 40 + "q", bloky)
        t = time.monotonic()
        tvary("Gansbauden", ("Gans-" + " " * 300 + "ss") * 300 + "a" * 100_000, dict(DELENI, zameny={"s": ["ss"]}))
        self.assertLess(time.monotonic() - t, 0.5, "dlouhý odpad")
        rychle("s" * 28, "s " * 500_000, ss)


class TestSoubory(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="ocr_hledej_")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def soubor(self, jmeno, text, kodovani="utf-8"):
        cesta = os.path.join(self.d, jmeno)
        os.makedirs(os.path.dirname(cesta), exist_ok=True)
        with open(cesta, "w", encoding=kodovani, newline="") as f:
            f.write(text)
        return cesta

    def nalezy(self, slovo, cesty=None, pravidla=None, tv=None):
        return [(t, os.path.basename(f), i) for t, f, i, _ in oh.hledej(slovo, cesty or [self.d], pravidla, tv)]

    def test_14_deleni_pres_radek(self):
        for text in ("Gans-\nbauden\n", "Gans-\n   bauden\n"):
            f = self.soubor("a.txt", text)
            self.assertEqual(self.nalezy("Gansbauden", [f], DELENI), [("Gans-⏎bauden", "a.txt", 1)])
            self.assertEqual(self.nalezy("Gansbauden", [f]), [])
        f = self.soubor("a.txt", "Gansbauden-\nGansbauden\n")
        self.assertEqual(self.nalezy("Gansbauden", [f], DELENI), [("Gansbauden", "a.txt", 1), ("Gansbauden", "a.txt", 2)])
        f = self.soubor("a.txt", "x\nGans-")
        self.assertEqual(self.nalezy("Gansbauden", [f], DELENI), [])

    def test_15_soubory(self):
        self.soubor(os.path.join("Šumava ěš", "ocr", "s1.txt"), "Erste Zeile\nWenzel aus Gansbauden Nr. 7\n")
        self.soubor(os.path.join("Šumava ěš", "ocr", "pod", "s2.txt"), "Gansbauden\n")
        self.soubor("bom.txt", "﻿Gansbauden\n")
        crlf = self.soubor("crlf.txt", "Gansbauden x\r\ndruhý\r\n")
        self.soubor("cp.txt", "Žluťoučký kůň\nGansbauden\n", "cp1250")
        md = self.soubor("jine.md", "Gansbauden\n")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            n = self.nalezy("Gansbauden")
        self.assertEqual(sorted(n), sorted([("Gansbauden", "s1.txt", 2), ("Gansbauden", "s2.txt", 1),
                                            ("Gansbauden", "bom.txt", 1), ("Gansbauden", "crlf.txt", 1),
                                            ("Gansbauden", "cp.txt", 2)]))
        self.assertIn("cp.txt", err.getvalue())
        self.assertIn("není celý v UTF-8", err.getvalue())
        self.assertEqual(oh.hledej("Gansbauden", [crlf])[0][3], "Gansbauden x")
        self.assertEqual(list(oh.radky(crlf)), ["Gansbauden x", "druhý"])
        self.assertEqual(self.nalezy("Gansbauden", [md]), [("Gansbauden", "jine.md", 1)])

    def test_16_chybejici_pravidla(self):
        self.assertEqual(oh.nacti_pravidla(os.path.join(self.d, "nic.json")), {})

    def test_17_neplatny_json(self):
        f = self.soubor("p.json", '{"zameny": {"s": ["f",]}}')
        with self.assertRaises(SystemExit) as e:
            oh.nacti_pravidla(f)
        self.assertIn("řádek", str(e.exception.code))
        self.assertNotIn("Traceback", str(e.exception.code))
        self.assertNotIn("JSONDecodeError", str(e.exception.code))

    def test_18_schema(self):
        pripady = [
            ([], "kořen musí být objekt"),
            ({"zamneny": {}}, "neznámá sekce „zamneny“"),
            ({"zameny": {"s": "f"}}, "hodnota musí být seznam"),
            ({"zameny": {"ab": ["x"]}}, "musí být jeden znak"),
            ({"zameny": {"s": [""]}}, "neprázdný text"),
            ({"zameny": {"s": ["a b"]}}, "bílý znak"),
            ({"skupiny": {"c": ["x"]}}, "dvě malá písmena"),
            ({"skupiny": {"Ck": ["x"]}}, "dvě malá písmena"),
            ({"volby": {"deleni": True}}, "neznámá volba „deleni“"),
            ({"volby": {"deleni_slova": "ano"}}, "true nebo false"),
            ({"volby": {"tvary": "nesmysl"}}, "tvary: musí být"),
            ({"volby": {"tvary": True}}, "tvary: musí být"),
            ({"vyloucit": ["hald"]}, "vyloucit: musí být objekt"),
        ]
        for p, hlaska in pripady:
            with self.subTest(p=p):
                chyby = oh.chyby_pravidel(p)
                self.assertTrue(any(hlaska in c for c in chyby), chyby)
        self.assertEqual(oh.chyby_pravidel({"zameny": {"s": ["ſ"]}, "volby": {"tvary": "presne"}}), [])

    def test_19_bom_v_pravidlech(self):
        f = self.soubor("p.json", '﻿{"zameny": {"s": ["f"]}}')
        self.assertEqual(oh.nacti_pravidla(f), {"zameny": {"s": ["f"]}})

    def test_22_kandidati(self):
        self.soubor("a.txt", "Herr Zine&er aus\nZinecker und Zine&er\n")
        k = oh.kandidati(["Zinecker"], [self.d])["Zinecker"]
        self.assertEqual([(w, n, d) for w, n, d, _, _ in k], [("Zine&er", 2, 2)])
        self.assertEqual(k[0][3], ["skupina ck &"])
        self.assertEqual((os.path.basename(k[0][4][0]),) + k[0][4][1:], ("a.txt", 1, "Herr Zine&er aus"))
        self.assertEqual(oh.kandidati(["Zinecker"], [self.d], {"skupiny": {"ck": ["&"]}})["Zinecker"], [])
        self.assertEqual(oh.kandidati(["Zinecker"], [self.d], {"vyloucit": {"E&E": "x"}})["Zinecker"], [])

    def test_23_kandidati_pres_radek(self):
        self.soubor("a.txt", "Gans-\nbauben x\n")
        k = oh.kandidati(["Gansbauden"], [self.d], DELENI)["Gansbauden"]
        self.assertEqual([w for w, *_ in k], ["Gansbauben"])
        self.assertEqual(k[0][3], ["zamena d b"])
        self.assertEqual(k[0][4][1], 1)

    def test_24_mez_podle_delky(self):
        self.soubor("a.txt", "Frles Frlez Abcdxfy Zined&er\n")
        with self.assertRaises(ValueError) as e:
            oh.kandidati(["Bach"], [self.d])
        self.assertIn("krátké", str(e.exception))
        slova = lambda s, **kw: [w for w, *_ in oh.kandidati([s], [self.d], **kw)[s]]
        self.assertEqual(slova("Fries"), ["Frles"])
        self.assertEqual(slova("Abcdefg"), [])
        self.assertEqual(slova("Zinecker"), ["Zined&er"])
        self.assertIn("Frlez", slova("Fries", vzdalenost=2))


class TestNavrh(unittest.TestCase):
    def test_20_navrh(self):
        pripady = [
            ("Gansbauden", "Sansbauben", ["zamena G S", "zamena d b"]),
            ("Gansbauden", "ansbauden", ["volba chybi_prvni_pismeno"]),
            ("Zinecker", "Zine&er", ["skupina ck &"]),
            ("Zinecker", "Zineker", ["skupina ck k"]),
            ("Zinecker", "Bineder", ["zamena Z B", "skupina ck d"]),
            ("Gansbauden", "Gans-bauden", ["volba deleni_slova"]),
            ("Gansbauden", "GanSbmlden", ["zamena s S", "skupina au ml"]),
            ("Zinecker", "Zineckers", ["koncovka"]),
            ("Zinecker", "ZINECKER", ["velikost"]),
            ("Zinecker", "InZinecker", ["predpona"]),
        ]
        for cil, tvar, cekam in pripady:
            with self.subTest(tvar=tvar):
                self.assertEqual(oh.navrh(cil, tvar), cekam)

    def test_21_existujici_vynecha(self):
        self.assertEqual(oh.navrh("Gansbauden", "Gdnsbaudeh", {"zameny": {"a": ["d"]}}), ["zamena n h"])


class TestDokumentace(unittest.TestCase):
    def test_25_skill_md(self):
        with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("ocr_hledej.py kandidati", text)
        self.assertIn("data/ocr_zameny.json", text)
        self.assertTrue(os.path.exists(os.path.join(SKILL, "reference", "ocr.md")))


if __name__ == "__main__":
    unittest.main()
