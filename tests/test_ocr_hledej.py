"""Testy ocr_hledej.py: hledání v OCR textech se záměnami písmen podle pravidel projektu. Bez internetu.
Zápis pravidel (pridej / odeber) přes skutečný nástroj v projektu testuje test_nastroje.py (TestOcrHledej)."""
import contextlib, inspect, io, os, re, shutil, sys, tempfile, unittest

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
        for text in ("Gansbauden", "22Gansbauden", "(Gansbauden)", "gansbauden", "GansbaudenNr"):   # velikost se nerozlišuje
            self.najde("Gansbauden", text, tv="presne")
        for text in ("Gansbaudener", "XGansbauden", "ČGansbauden", "-Gansbauden", "Gans-bauden"):
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
        self.najde("Christoph", "dristoph", p)   # velikost se nerozlišuje
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

    def test_58_nejdelsi_nalez_a_vyjimka(self):
        """Regex bere první platnou alternativu: řazení podle délky drží nejdelší nález, po výjimce hledá dál o znak."""
        def spany(slovo, text, pravidla):
            return list(oh.Vzor(slovo, pravidla, "volne").najdi(text))
        self.assertEqual(spany("Fries", "Friess", {"zameny": {"s": ["ß"]}}), [(0, 6)])
        self.assertEqual(spany("Xab", "Xabb", {"skupiny": {"ab": ["abb"]}}), [(0, 4)])
        self.assertEqual(spany("ab", "ab1ab", {"zameny": {"b": ["b1a"]}, "vyloucit": {"b1ab": ""}}), [(3, 5)])


    def test_62_velikost_pismen(self):
        """Velikost se nerozlišuje; pravidla platí pro písmeno, jak stojí ve slově; slovo verzálkami jako Fries."""
        for text in ("FRIES", "fries", "FRIES,"):
            self.najde("Fries", text)
        for tv in ("ceske", "presne"):
            self.nenajde("Fries", "FRIESEN", tv=tv)
            self.nenajde("Fries", "FRIESLAND", tv=tv)
        self.najde("Fries", "FRIESEN", tv="volne")
        self.najde("Zinecker", "ZINECKEROVÁ")
        self.nenajde("Zinecker", "ZINECKEROVÁ", tv="presne")
        ostre = {"zameny": {"s": ["ß"]}}
        self.najde("Fries", "FRIESS", ostre)
        self.nenajde("Fries", "FRIESS")
        for text in ("FRIESS", "Frieß"):
            self.najde("FRIES", text, ostre)
        self.najde("Gansbauden", "sansbauden", {"zameny": {"G": ["S"]}})
        self.najde("Gansbauden", "SANSBAUDEN", {"zameny": {"G": ["S"]}})
        self.nenajde("Gansbauden", "Sansbauden", {"zameny": {"g": ["s"]}})
        d = tempfile.mkdtemp(prefix="ocr_hledej_")
        try:
            with open(os.path.join(d, "a.txt"), "w", encoding="utf-8") as f:
                f.write("ZINECKER zinecker Zineker\n")
            self.assertEqual([k[0] for k in oh.kandidati(["Zinecker"], [d])["Zinecker"]], ["Zineker"])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_66_hranice_za_nalezem(self):
        """Za nálezem smí být velké písmeno po malém (OCR slepilo jméno s dalším slovem), ne malé a ne velké po
        velkém (slovo celé verzálkami: FRIESEN, FISCHERDAVID). Výhled je v regexu: kratší konec se zkusí znovu."""
        for slovo, text, cekam in (("Fischer", "FischerDavid", "Fischer"),
                                   ("Zinecker", "ZineckerS Fuchsbergbaude", "Zinecker"),
                                   ("Zinecker", "ZineckerAdolf", "Zinecker"), ("Zinecker", "ZineckeraAdolf", "Zineckera"),
                                   ("Zinecker", "ZineckerEDUARD", "Zinecker"),   # konec E po velkém ne → zpět na r
                                   ("Zinecker", "ZineckerŠimon", "Zinecker"), ("Bönisch", "BönischÜ", "Bönisch"),
                                   ("Fischer", "FiſcherD", "Fiſcher"), ("Fischer", "fischerDavid", "fischer")):
            with self.subTest(text=text):
                self.assertEqual(tvary(slovo, text), [cekam])
        self.assertEqual(tvary("Gansbauden", "GansbaudenNr", None, "presne"), ["Gansbauden"])
        for slovo, text, tv in (("Fischer", "Fischerei", None), ("Fischer", "FISCHERDAVID", None),
                                ("Fries", "FRIESEN", "presne"), ("Kraus", "KRAUSE", "presne"), ("Kraus", "KrauSX", None),
                                ("Zinecker", "Zineckerá", None), ("Kraus", "Krausſ", None),
                                ("Beranek", "Beranek\u0365W", None)):
            with self.subTest(text=text, tv=tv):
                self.nenajde(slovo, text, tv=tv)
        self.assertEqual(tvary("Gansbauden", "Gans-\nbaudenHof", DELENI), ["Gans-\nbauden"])   # výhled přes řádek
        self.assertEqual(tvary("Kraus", "KrausDi", None, "volne"), ["Kraus"])

VYP = {"volby": {"rovnocennosti": False}}


def s_volbou(pravidla, **volby):
    """Kopie pravidel s dalšími volbami."""
    p = dict(pravidla or {})
    p["volby"] = dict(p.get("volby", {}), **volby)
    return p


class TestRovnocennosti(Zaklad):
    """Výchozí rovnocennosti: jen na straně hledaného slova, text se nemění."""

    def test_40_dlouhe_s(self):
        self.assertEqual(tvary("Fischer", "Fiſcher"), ["Fiſcher"])   # tvar doslova
        self.najde("Fiſcher", "Fischer")
        self.nenajde("Fischer", "Fifcher")   # ſ není záměna f

    def test_41_ostre_s(self):
        for t in ("Strauss", "Strauſs", "Strausſ", "Strauſſ", "Strauß"):
            self.assertEqual(tvary("Strauß", t), [t])
        self.najde("Strauss", "Strauß")
        self.najde("STRAUSS", "STRAUẞ")
        self.najde("STRAUẞ", "STRAUSS")
        self.najde("STRAUSS", "STRAUß")
        self.nenajde("Strauß", "Straus")   # ß není s

    def test_42_prehlasky(self):
        male = ["Müller", "Mueller", "Mu\u0364ller", "Mu\u0308ller", "Mü\u0364ller"]
        velke = ["MÜLLER", "MUELLER", "MU\u0364LLER", "MU\u0308LLER"]
        for skupina in (male, velke):
            for a in skupina:
                for b in skupina:
                    with self.subTest(slovo=a, text=b):
                        self.assertEqual(tvary(a, b), [b])
        self.najde("Über", "Ueber")
        self.najde("Ueber", "Über")
        self.nenajde("Müller", "Muller")
        self.najde("Müller", "MÜLLER")   # velikost se nerozlišuje
        self.najde("MÜLLER", "Müller")
        for znak in ("\u0308", "\u1ab0", "\u20d7"):   # konec nesmí doprostřed znaku (kategorie M, ne jen U+0300–036F)
            for tv in oh.TVARY:
                with self.subTest(znak=hex(ord(znak)), tv=tv):
                    self.nenajde("Mu", "Mu" + znak, tv=tv)
                    self.nenajde("Mu", "Mu" + znak + "ller", tv=tv)

    def test_43_rozlozene(self):
        self.najde("Poděbrad", "Pode\u030cbrad")
        self.najde("Pode\u030cbrad", "Poděbrad")
        self.najde("Swẽt", "Swe\u0303t")
        self.najde("Swe\u0303t", "Swẽt")
        self.nenajde("Swẽt", "Swet")   # ne odstranění diakritiky
        self.nenajde("Poděbrad", "Podebrad")

    def test_44_r_rotunda(self):
        self.assertEqual(tvary("Krischlitz", "Kꝛischlitz"), ["Kꝛischlitz"])
        self.nenajde("Krischlitz", "Kꝛischlitz", {"volby": {"rovnocennosti": {"r_rotunda": False}}})

    def test_45_zvlastni_mezery(self):
        for mezera in ("\u00a0", "\u2003"):
            self.assertEqual(tvary("Gansbauden", "aus" + mezera + "Gansbauden" + mezera + "Nr"), ["Gansbauden"])
            self.najde("Gansbauden", "Gans-" + mezera + "bauden", DELENI)
            self.assertEqual(oh.SLOVO_RE.findall("a" + mezera + "b"), ["a", "b"])
        self.najde("Gansbauden", "Gans-" + "\u00a0" * 250 + "bauden", DELENI)
        self.nenajde("Gansbauden", "Gans-" + "\u00a0" * 251 + "bauden", DELENI)

    def test_46_vypnuti(self):
        self.najde("Fischer", "Fiſcher", VYP)   # ſ = s platí vždy: ſ je malé s i pro re.IGNORECASE
        for slovo, text in (("Strauß", "Strauss"), ("Müller", "Mueller"),
                            ("Müller", "Mu\u0308ller"), ("Poděbrad", "Pode\u030cbrad"), ("Krischlitz", "Kꝛischlitz"),
                            ("Gansbauden", "Gans\u00adbauden"), ("Václav", "Wáclaw"), ("Mu", "Mu\u0308")):
            with self.subTest(text=text):
                (self.nenajde if slovo == "Mu" else self.najde)(slovo, text)
                (self.najde if slovo == "Mu" else self.nenajde)(slovo, text, VYP)
        # najdi s false shodné s 009162b (výsledky změřené starým nástrojem na týchž vzorcích); navíc jen to, co najde
        # nerozlišování velikosti: Ganſbauden, MÜLLER, Strauſs, STRAUẞ
        pripady = [
            ("Gansbauden", "Ganſbauden Gans-bauden Gansbauben Gan&bauden Gans\u00adbauden",
             {"zameny": {"d": ["b"], "s": ["&"]}, "volby": {"deleni_slova": True}}, [(0, 10), (11, 22), (23, 33), (34, 44)]),
            ("Müller", "Müller Mueller Mu\u0308ller Mu\u0364ller Müllerova Mülleri MÜLLER", {"vyloucit": {"llerova": ""}},
             [(0, 6), (41, 48), (49, 55)]),
            ("Strauß", "Strauß Strauss Strauſs STRAUẞ", {"zameny": {"ß": ["ss"]}}, [(0, 6), (7, 14), (15, 22), (23, 29)]),
            ("Zinecker", "Zineckera Zine&er Zinecker\u0301 Ziuecker Zinec-ker",
             {"zameny": {"n": ["u"]}, "skupiny": {"ck": ["&"]},
              "volby": {"deleni_slova": True, "chybi_prvni_pismeno": True}},
             [(0, 9), (10, 17), (18, 26), (28, 36), (37, 46)]),
            ("Fries", "Fries Friesen Frieß Friese Friesland Fries\u0308", {"volby": {"tvary": "volne"}},
             [(0, 5), (6, 11), (20, 25), (27, 32), (37, 42)]),
            ("Václav", "Václav Wáclaw Va\u0301clav", {}, [(0, 6)]),
            ("Mu\u0308ller", "Müller Mu\u0308ller", {}, [(7, 14)]),   # slovo se bez rovnocenností neupravuje (NFC)
        ]
        for slovo, text, p, cekam in pripady:
            with self.subTest(slovo=slovo):
                self.assertEqual(list(oh.Vzor(slovo, s_volbou(p, rovnocennosti=False)).najdi(text)), cekam)
        bez_prehlasek = {"volby": {"rovnocennosti": {"prehlasky": False}}}
        self.nenajde("Müller", "Mueller", bez_prehlasek)
        self.najde("Fischer", "Fiſcher", bez_prehlasek)   # vypne jen jednu položku

    def test_47_pravidla_s_rovnocennostmi(self):
        for text in ("Fiſcher Fischer", "Fifcher", "Strauſs"):
            self.assertEqual(tvary("Fischer", text, {"zameny": {"s": ["ſ"]}}), tvary("Fischer", text, {}))
        for slovo in ("Jäger", "Jaeger"):
            self.najde(slovo, "Jager", {"zameny": {"ä": ["a"]}})
        A = {"zameny": {"Ä": ["A"]}}
        for slovo in ("ÄRGER", "AERGER"):
            self.najde(slovo, "ARGER", A)
        self.najde("Ärger", "Arger", A)
        self.najde("ÄRGER", "ARGER", s_volbou(A, rovnocennosti=False))
        self.nenajde("AERGER", "ARGER", s_volbou(A, rovnocennosti=False))
        self.najde("Müller", "Mneller", {"zameny": {"u": ["n"]}})
        self.najde("Zinecker", "Ziuecker", {"zameny": {"n": ["u"]}})
        self.nenajde("Zinecker", "Ziücker", {"zameny": {"n": ["u"]}})   # ü z OCR není rovnocennost
        self.najde("Waßer", "Was-\nser", DELENI)
        self.najde("Müller", "Mu-\neller", DELENI)
        au = {"skupiny": {"au": ["ml"]}}
        self.najde("Bauer", "Bmler", au)
        self.najde("Baür", "Bmler", au)
        aess = {"skupiny": {"äß": ["x"]}}
        self.najde("Häßler", "Hxler", aess)
        self.najde("Haessler", "Hxler", aess)
        self.najde("Häßler", "Hxler", s_volbou(aess, rovnocennosti=False))
        for t in ("Friess", "Frieſs", "Frieß"):
            self.najde("Fries", t, {"zameny": {"s": ["ß"]}})
        self.najde("Strasse", "Strasse", {"vyloucit": {"Straße": ""}})   # výjimka v hledaném slově neplatí
        mv = {"vyloucit": {"Müllerova": ""}}
        for t in ("Muellerova", "Mu\u0308llerova", "Mu\u0364llerova"):
            self.najde("Müller", t)
            self.nenajde("Müller", t, mv)
        self.najde("MÜLLER", "MÜLLEROVA", tv="volne")
        self.nenajde("MÜLLER", "MÜLLEROVA", mv, "volne")
        self.najde("he", "heꝛꝛ", tv="volne")
        self.nenajde("he", "heꝛꝛ", {"vyloucit": {"herr": ""}}, "volne")
        # R5: plný casefold výjimek (i víceznakový ß = SS) nezávisle na rovnocennostech
        for p in ({}, VYP):
            self.najde("Gans", "GansSTRASSE", p, "volne")
            self.nenajde("Gans", "GansSTRASSE", s_volbou(dict(p, vyloucit={"Straße": ""}), tvary="volne"))
            self.nenajde("Gans", "Gansstraße", s_volbou(dict(p, vyloucit={"STRASSE": ""}), tvary="volne"))
        chybi = {"volby": {"chybi_prvni_pismeno": True}}
        self.najde("Mullerhaus", "ullerhaus", chybi)
        self.nenajde("Müllerhaus", "üllerhaus", chybi)   # přehláska na 0–2 vypne zkratku prvního písmene
        self.nenajde("Müllerhaus", "ülllerhaus", chybi)  # (zkratka by jinak četla znaky slova proti půlkám pozic)

    def test_48_konec_slova(self):
        self.nenajde("Fries", "Frieß", tv="volne")
        self.najde("Fries", "Friesen", tv="volne")   # R5: malé písmeno za slovem ve volne smí
        self.assertEqual(tvary("Grieß", "Grieße"), ["Grieße"])
        self.nenajde("Fries", "Friesen")

    def test_49_sady_pravopisu(self):
        self.nenajde("Carl", "Karl")
        self.assertEqual(tvary("Václav", "Wáclaw"), ["Wáclaw"])
        nem = {"volby": {"rovnocennosti": {"nemcina_1901": True}}}
        for a, b in (("Carl", "Karl"), ("Thal", "Tal"), ("Joseph", "Josef"), ("Meyer", "Meier")):
            self.najde(a, b, nem)
            self.najde(b, a, nem)
        self.najde("Krkonoše", "Krkonoſſe")
        self.najde("Jilemnice", "Gilemnice")
        self.nenajde("Wáclaw", "Václav")   # jen dnešní slovo → starý zápis
        self.nenajde("Václav", "Wáclaw", {"volby": {"rovnocennosti": {"cestina_1849": False}}})

    def test_51_schema_rovnocennosti(self):
        for v, hlaska in (("ano", "musí být true, false nebo objekt"), ([], "musí být true, false nebo objekt"),
                          ({"nesmysl": True}, "neznámá položka „nesmysl“"),
                          ({"prehlasky": "ne"}, "rovnocennosti prehlasky: musí být true nebo false")):
            with self.subTest(v=v):
                chyby = oh.chyby_pravidel({"volby": {"rovnocennosti": v}})
                self.assertTrue(any(hlaska in c for c in chyby), chyby)
        for v in (True, False, {"nemcina_1901": True}):
            self.assertEqual(oh.chyby_pravidel({"volby": {"rovnocennosti": v}}), [])


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
        return [(t, os.path.basename(f), i) for t, f, i, *_ in oh.hledej(slovo, cesty or [self.d], pravidla, tv)]

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

    def test_54_mekke_deleni(self):
        """U+00AD je znak dělení i bez volby deleni_slova (je neviditelné); stejné pojistky jako u dělení."""
        shy = "\u00ad"
        self.assertTrue(tvary("Gansbauden", "Gans" + shy + "bauden"))
        self.assertTrue(tvary("Gansbauden", "Gans" + shy + " " * 250 + "bauden"))
        self.assertFalse(tvary("Gansbauden", "Gans" + shy + " " * 251 + "bauden"))
        self.assertFalse(tvary("Gansbauden", "Gans" + shy + shy + "bauden"))
        for p in ({}, DELENI):
            self.assertFalse(tvary("Gansbauden", "Gans" + shy + "-bauden", p))   # jeden znak na hranici
        f = self.soubor("a.txt", "aus Gans" + shy + "\n  bauden x\n")
        self.assertEqual(self.nalezy("Gansbauden", [f]), [("Gans" + shy + "⏎bauden", "a.txt", 1)])
        self.soubor("b.txt", "Gans" + shy + "\nbauben\n")
        k = oh.kandidati(["Gansbauden"], [os.path.join(self.d, "b.txt")])["Gansbauden"]
        self.assertEqual([w for w, *_ in k], ["Gansbauben"])
        vyp = {"volby": {"rovnocennosti": {"mekke_deleni": False}}}
        self.assertFalse(tvary("Gansbauden", "Gans" + shy + "bauden", vyp))
        self.assertEqual(self.nalezy("Gansbauden", [f], vyp), [])
        k = oh.kandidati(["Gansbauden"], [os.path.join(self.d, "b.txt")], vyp)["Gansbauden"]
        self.assertNotIn("Gansbauben", [w for w, *_ in k])

    def test_46b_text_se_nemeni(self):
        radek = "Wenzel Fi\u017fcher\u00a0Mu\u0364ller und Mu\u0308ller"
        f = self.soubor("a.txt", radek + "\n")
        for slovo in ("Fischer", "Müller"):
            for tvar, _, _, r, _ in oh.hledej(slovo, [f]):
                self.assertEqual(r.encode("utf-8"), radek.encode("utf-8"))
                self.assertIn(tvar, radek)

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                oh.main(list(argv))
            except SystemExit as e:
                err.write(str(e.code))
        return out.getvalue(), err.getvalue()

    def test_59_ukazka_okno(self):
        text = "x" * 200 + "Gansbauden" + "y" * 90
        u = oh.ukazka(text, 200, "Gansbauden")
        self.assertIn("Gansbauden", u)
        self.assertTrue(u.startswith("…"))
        self.assertEqual(oh.ukazka("Herr Gansbauden", 5, "Gansbauden"), "Herr Gansbauden")
        dlouhy = "G" + "a" * 150
        self.assertIn(dlouhy, oh.ukazka("z" * 50 + dlouhy, 50, dlouhy + "⏎bauden"))
        f = self.soubor("a.txt", "z" * 120 + " Gans-\nbauden dále\n")
        ((tvar, _, _, text, sloupec),) = oh.hledej("Gansbauden", [f], DELENI)
        self.assertEqual(tvar, "Gans-⏎bauden")
        self.assertIn("Gans-", oh.ukazka(text, sloupec, tvar))
        f = self.soubor("b.txt", "\ufeff\t" + " " * 60 + "x Gansbauden y\n")   # odsazení delší než 40 znaků před nálezem
        ((tvar, _, _, text, sloupec),) = oh.hledej("Gansbauden", [f])
        self.assertEqual(text[sloupec:sloupec + len(tvar)], "Gansbauden")
        self.assertIn("Gansbauden", oh.ukazka(text, sloupec, tvar))

    def test_60_souhrn_podle_tvaru(self):
        self.soubor("a.txt", "Gansbauden\nx Gansbauden\nGansbauden y\nGanſbauden\n")
        self.soubor("b.txt", "Gansbauden\n\nGansbauden\n")
        out, err = self.cli("hledej", "Gansbauden", "--", self.d)
        radky = out.splitlines()
        self.assertEqual(len(radky), 2)
        self.assertEqual(radky[0].split("\t")[:3], ["Gansbauden", "Gansbauden", "5×"])
        self.assertIn("a.txt:1; ", radky[0])
        self.assertIn("; +2 dalších\t", radky[0])
        self.assertEqual(radky[1].split("\t")[:3], ["Gansbauden", "Ganſbauden", "1×"])
        out2, err2 = self.cli("hledej", "Gansbauden", "--vypis", "radky", "--", self.d)
        self.assertEqual(len(out2.splitlines()), 6)
        self.assertEqual(err, err2)
        self.assertIn("# Gansbauden: 6 výskytů", err)
        self.assertIn("--vypis: souhrn | radky", str(self.cli("hledej", "X", "--vypis", "vse", "--", self.d)))

    def test_61_soubory_a_cesta(self):
        prazdna = os.path.join(self.d, "prazdna")
        os.makedirs(prazdna)
        self.assertIn("# prohledáno: 0 souborů", self.cli("hledej", "Fries", "--", prazdna)[1])
        self.soubor("a.txt", "Fries\n")
        self.assertIn("# prohledáno: 1 soubor\n", self.cli("kandidati", "Fries", "--", self.d)[1])
        _, err = self.cli("hledej", "Fries", self.d)
        self.assertIn(f"# pozor: „{self.d}“ je existující cesta", err)

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

    def test_65_kandidati_prvni_slovo_po_deleni(self):
        """První slovo řádku po rozdělení s velkým písmenem (vedlejší sloupec) se posoudí i samo, malé pokračování
        slova ne; osamělá „-“ („6,-“) se nespojí, takže se slovo nepočítá dvakrát."""
        f = self.soubor("a.txt", "in die Kirde ge-\nZineaker aus\nHedwig 6,-\nZinseker Johann\n")
        for p in ({}, DELENI):
            with self.subTest(p=p):
                k = oh.kandidati(["Zinecker"], [f], p)["Zinecker"]
                self.assertEqual([(w, n, d, pr[1]) for w, n, d, _, pr in k],
                                 [("Zineaker", 1, 1, 2), ("Zinseker", 1, 2, 4)])
        self.assertIn(("geZineaker", 1), [(w, i) for w, i, _ in oh._slova(f, True)])   # spojený tvar dál
        g = self.soubor("b.txt", "Lehrer Gott-\nfried Kunze\n")
        self.assertEqual([(w, i) for w, i, _ in oh._slova(g, True)],
                         [("Gottfried", 1), ("Lehrer", 1), ("Kunze", 2)])
        self.assertEqual(oh.kandidati(["Fries"], [g], DELENI)["Fries"], [])

    def test_24_mez_podle_delky(self):
        self.soubor("a.txt", "Frles Frlez Abcdxfy Zined&er\n")
        with self.assertRaises(ValueError) as e:
            oh.kandidati(["Bach"], [self.d])
        self.assertIn("krátké", str(e.exception))
        slova = lambda s, **kw: [w for w, *_ in oh.kandidati([s], [self.d], **kw)[s]]
        self.assertEqual(slova("Fries"), ["Frles"])
        self.assertEqual(slova("Abcdefg"), [])
        self.assertEqual(slova("Zinecker"), ["Zined&er"])
        self.assertIn("Frlez", slova("Fries", mez=2))


class TestNavrh(unittest.TestCase):
    def test_20_navrh(self):
        pripady = [
            ("Gansbauden", "Sansbauben", ["zamena G S", "zamena d b"]),
            ("Gansbauden", "ansbauden", ["volba chybi_prvni_pismeno"]),
            ("Zinecker", "Zine&er", ["skupina ck &"]),
            ("Zinecker", "Zineker", ["skupina ck k"]),
            ("Zinecker", "Bineder", ["zamena Z B", "skupina ck d"]),
            ("Gansbauden", "Gans-bauden", ["volba deleni_slova"]),
            ("Gansbauden", "GanSbmlden", ["skupina au ml"]),   # velikost se nerozlišuje
            ("Zinecker", "Zineckers", []),       # koncovka: --tvary volne nebo samostatné slovo
            ("Zinecker", "ZINECKER", []),
            ("Zinecker", "InZinecker", []),      # předpona: samostatné slovo
        ]
        for cil, tvar, cekam in pripady:
            with self.subTest(tvar=tvar):
                self.assertEqual(oh.navrh(cil, tvar), cekam)

    def test_21_existujici_vynecha(self):
        self.assertEqual(oh.navrh("Gansbauden", "Gdnsbaudeh", {"zameny": {"a": ["d"]}}), ["zamena n h"])

    def test_64_navrh_pro_verzalky(self):
        """Návrh pro slovo verzálkami má klíč, který hledání použije (FRIES bere pravidla jako Fries)."""
        self.assertEqual(oh.navrh("GANSBAUDEN", "GANSSBAUDEN"), ["zamena n NS"])
        self.assertEqual(oh.navrh("FRIES", "FRIEF"), ["zamena s F"])
        self.assertTrue(list(oh.Vzor("FRIES", {"zameny": {"s": ["F"]}}).najdi("FRIEF")))


class TestDokumentace(unittest.TestCase):
    def test_25_skill_md(self):
        with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("ocr_hledej.py kandidati", text)
        self.assertIn("data/ocr_zameny.json", text)
        self.assertTrue(os.path.exists(os.path.join(SKILL, "reference", "ocr.md")))
        with open(os.path.join(SKILL, "reference", "ocr.md"), encoding="utf-8") as f:
            ocr = f.read()
        self.assertNotIn("zamena s \u017f", ocr)   # dlouhé s je výchozí rovnocennost, ne pravidlo
        self.assertIn("rovnocennost", ocr)
        self.assertIn("jen po souhlasu", ocr)
        self.assertIn("pridej", ocr[max(0, ocr.index("jen po souhlasu") - 200):ocr.index("jen po souhlasu")])

    def test_63_stitky_navrhu_v_ocr_md(self):
        """Každý štítek, který navrh umí vytisknout, je vysvětlený v oddílu „Návrhy kandidátů“ reference."""
        stitky = set(re.findall(r'out\.append\(f?"([a-z_]+(?: [a-z_]+)?)', inspect.getsource(oh.navrh)))
        self.assertEqual(stitky, {"zamena", "skupina", "volba deleni_slova", "volba chybi_prvni_pismeno"})
        with open(os.path.join(SKILL, "reference", "ocr.md"), encoding="utf-8") as f:
            ocr = f.read()
        oddil = ocr[ocr.index("## Návrhy kandidátů"):]
        oddil = oddil[:oddil.index("\n## ", 1)]
        for s in stitky:
            self.assertIn(f"`{s}", oddil)


if __name__ == "__main__":
    unittest.main()
