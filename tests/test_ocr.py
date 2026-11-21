"""Testy ocr.py (OCR vlastních skenů Tesseractem). Bez internetu, bez Tesseractu a Poppleru: programy nahrazuje
FalesnySpust (ocr.spust), hledání programů ocr.najdi. CLI testy běží v dočasném projektu (novy_projekt.py)."""
import contextlib, hashlib, io, json, os, re, shutil, signal, subprocess, sys, tempfile, time, unittest
from unittest import mock

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(KOREN, "skills", "dejiny-domu")
sys.path.insert(0, os.path.join(SKILL, "tools"))
import ocr  # noqa: E402
PUVODNI_NAJDI = ocr.najdi
PUVODNI_SPUST_PRIKAZ = ocr.spust_prikaz

def cti_soubor(p, mod="r"):
    with open(p, mod, **({} if "b" in mod else {"encoding": "utf-8"})) as f:
        return f.read()


class FalesnySpust:
    """Náhrada tesseract / pdftoppm / pdfinfo / vlastního příkazu („fakeocr“)."""

    def __init__(self, sysdir):
        self.sysdir = sysdir
        self.volani = []
        self.selhat = set()      # jména obrázků (bez přípony), na kterých tesseract selže
        self.prerusit = set()    # jména obrázků, na kterých přijde Ctrl-C (KeyboardInterrupt)
        self.vystupy = {}        # jméno obrázku → vlastní výstup tesseractu (např. víc stran oddělených \f)
        self.prikaz = None       # funkce(argv) -> návratový kód
        self.verze = {"tesseract": "5.5.4", "pdftoppm": "26.11.0"}

    def __call__(self, argv, **kw):
        self.volani.append(list(argv))
        ok = lambda out=b"", err=b"", rc=0: subprocess.CompletedProcess(argv, rc, out, err)
        p = os.path.basename(argv[0])
        if p == "fakeocr":
            return ok(rc=self.prikaz(argv))
        if p == "tesseract":
            if argv[1:] == ["--version"]:
                return ok(f"tesseract {self.verze['tesseract']}\n leptonica-1.87.0\n".encode())
            if argv[-1] == "--list-langs":
                d = argv[2] if argv[1] == "--tessdata-dir" else self.sysdir
                langs = sorted(f[:-12] for f in os.listdir(d) if f.endswith(".traineddata"))
                return ok(("List of available languages in \"%s/\" (%d):\n%s\n" % (d, len(langs), "\n".join(langs)))
                          .encode())
            obr = argv[-4]
            jmeno = os.path.splitext(os.path.basename(obr))[0]
            if jmeno in self.selhat:
                return ok(err=b"Error in pixReadStream", rc=1)
            if jmeno in self.prerusit:
                raise KeyboardInterrupt
            if jmeno in self.vystupy:
                return ok(self.vystupy[jmeno].encode())
            with open(obr, encoding="utf-8") as f:
                obsah = f.read().strip()
            return ok(f"Menſch {obsah} {argv[-1]}\r\n\f".encode())
        if p == "pdftoppm":
            if argv[1:] == ["-v"]:
                return ok(err=f"pdftoppm version {self.verze['pdftoppm']}\n".encode())
            cislo = argv[argv.index("-f") + 1]
            with open(argv[-2], encoding="utf-8") as f:
                pdf = f.read().strip()
            with open(argv[-1] + ".jpg", "w", encoding="utf-8") as f:
                f.write(f"strana {cislo} z {pdf}")
            return ok()
        if p == "pdfinfo":
            with open(argv[1], encoding="utf-8") as f:
                n = re.search(r"n=(\d+)", f.read()).group(1)
            return ok(f"Producer: x\nPages:          {n}\n".encode())
        raise AssertionError(f"nečekané volání {argv}")

    def tesseract_obrazky(self):
        return [os.path.splitext(os.path.basename(a[-4]))[0] for a in self.volani
                if os.path.basename(a[0]) == "tesseract" and a[-1] != "--list-langs" and a[1:] != ["--version"]]


Z = {"s": "jen_s", "ponechat": "ponechat"}   # dřívější dlouhe_s → stare_znaky


class Zaklad(unittest.TestCase):
    """Dočasný kořen projektu (ocr.ROOT), systémová a uživatelská složka modelů, falešné programy."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ocr_test_")
        self.sysdir = os.path.join(self.tmp, "sys")
        self.uziv = os.path.join(self.tmp, "uziv")
        for d in (self.sysdir, self.uziv, os.path.join(self.tmp, "data"), os.path.join(self.tmp, "dokumenty")):
            os.makedirs(d)
        self.model(self.uziv, "german_print")
        self.nastav({"tessdata": self.uziv})
        self.fake = FalesnySpust(self.sysdir)
        self.programy = {"tesseract": "/x/tesseract", "pdftoppm": "/x/pdftoppm", "pdfinfo": "/x/pdfinfo"}
        for p in (mock.patch.object(ocr, "ROOT", self.tmp), mock.patch.object(ocr, "spust", self.fake),
                  mock.patch.object(ocr, "spust_prikaz", lambda argv: self.fake(argv).returncode),
                  mock.patch.object(ocr, "najdi", lambda program: self.programy.get(program))):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def model(self, slozka, jmeno, obsah=None):
        with open(os.path.join(slozka, jmeno + ".traineddata"), "w") as f:
            f.write(obsah or f"model {jmeno}")

    def nastav(self, d):
        with open(os.path.join(self.tmp, "data", "ocr.json"), "w", encoding="utf-8") as f:
            json.dump(d, f)

    def pdf(self, n=3, jmeno="kniha.pdf", verze="v1"):
        p = os.path.join(self.tmp, "dokumenty", jmeno)
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"%PDF n={n} {verze}\n")
        return p

    def obrazky(self, *jmena, slozka="skeny"):
        d = os.path.join(self.tmp, "dokumenty", slozka)
        os.makedirs(d, exist_ok=True)
        for j in jmena:
            with open(os.path.join(d, j), "w", encoding="utf-8") as f:
                f.write(f"obrazek {j}")
        return d

    def spust(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = ocr.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def vystup(self, *p):
        return os.path.join(self.tmp, "pracovni", "ocr", *p)

    def cti(self, *p):
        with open(self.vystup(*p), encoding="utf-8", newline="") as f:
            return f.read()

    def manifest(self, dok):
        return json.loads(self.cti(dok, "ocr_manifest.json"))


class TestModel(Zaklad):
    def test_model_priorita(self):
        self.assertEqual(ocr.platne({})["model"], "german_print")
        self.assertEqual(ocr.platne({"model": "ces"})["model"], "ces")
        self.assertEqual(ocr.platne({"model": "ces"}, "deu")["model"], "deu")
        self.nastav({"tessdata": self.uziv, "model": "ces"})
        self.model(self.uziv, "ces")
        self.model(self.uziv, "deu")
        p = self.pdf(1)
        self.assertEqual(self.spust(p)[0], 0)
        self.assertEqual(self.manifest("kniha")["model"], "ces")
        self.assertEqual(self.spust(p, "--model", "deu", "--vystup", self.vystup("k2"))[0], 0)
        self.assertEqual(self.manifest("k2")["model"], "deu")

    def test_model_neplatny(self):
        for m in ("", "../x", "a b", "a++b", "german_print+", 5):
            with self.assertRaises(ocr.Chyba):
                ocr.rozloz_model(m)
            self.assertTrue(ocr.over_nastaveni({"model": m})[0], m)
        self.assertEqual(ocr.rozloz_model("german_print+ces"), ["german_print", "ces"])
        rc, _, err = self.spust(self.pdf(1), "--model", "../x")
        self.assertEqual(rc, 1)
        self.assertIn("Neplatný název modelu", err)

    def test_deu_latf_varuje(self):
        self.model(self.uziv, "deu_latf")
        rc, _, err = self.spust(self.pdf(1), "--model", "deu_latf")
        self.assertEqual(rc, 0)
        self.assertIn("german_print", err)
        self.assertIn("deu_latf", err)


class TestNastaveni(Zaklad):
    def test_nastaveni_chybi(self):
        self.assertEqual(ocr.nacti_nastaveni(os.path.join(self.tmp, "neni.json")), {})

    def test_nastaveni_bom(self):
        p = os.path.join(self.tmp, "bom.json")
        with open(p, "wb") as f:
            f.write(b"\xef\xbb\xbf" + json.dumps({"model": "ces"}).encode())
        self.assertEqual(ocr.nacti_nastaveni(p), {"model": "ces"})

    def test_nastaveni_typy(self):
        spatne = [{"prikaz": "ocr {slozka} {vystup}"}, {"prikaz": []}, {"prikaz": ["ocr", "{vystup}", "{model}"]},
                  {"prikaz": ["ocr", "{slozka}", "{model}"]}, {"prikaz": ["ocr", "{slozka}", "{vystup}"]},
                  {"prikaz": ["ocr", "{slozka}", "{vystup}", "{model}", "{neznamy}"]},
                  {"davka": 0}, {"davka": "10"}, {"davka": True}, {"dpi": 50}, {"soubezne": 0}, {"dlouhe_s": "x"},
                  {"stare_znaky": "x"}, {"stare_znaky": "s"}, {"dlouhe_s": "s", "stare_znaky": "ponechat"},
                  {"tessdata": 3}, []]
        for d in spatne:
            self.assertTrue(ocr.over_nastaveni(d)[0], d)
        dobre = {"model": "german_print+ces", "stare_znaky": "ponechat", "prikaz": ["~/ocr", "{slozka}", "--out={vystup}",
                 "-l", "{model}"], "davka": 10000, "soubezne": 64, "dpi": 72,
                 "tessdata": "~/td"}
        self.assertEqual(ocr.over_nastaveni(dobre), ([], []))

    def test_o2_dlouhe_s_zastarale(self):
        for d, cekam in (({"dlouhe_s": "s"}, "jen_s"), ({"dlouhe_s": "ponechat"}, "ponechat"), ({}, "zjednodusit"),
                         ({"stare_znaky": "jen_s"}, "jen_s")):
            chyby, varovani = ocr.over_nastaveni(d)
            self.assertEqual(chyby, [], d)
            self.assertEqual(any("dlouhe_s je zastaralé" in v for v in varovani), "dlouhe_s" in d)
            self.assertEqual(ocr.platne(d)["stare_znaky"], cekam)
        chyby, _ = ocr.over_nastaveni({"dlouhe_s": "s", "stare_znaky": "ponechat"})
        self.assertTrue(any("odporují" in c for c in chyby))
        self.assertEqual(ocr.over_nastaveni({"dlouhe_s": "s", "stare_znaky": "jen_s"})[0], [])
        p = os.path.join(self.tmp, "data", "ocr.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write('{"model": "ces", "dlouhe_s": "ponechat"}')
        with contextlib.redirect_stdout(io.StringIO()):
            ocr.prikaz_nastav(p, "dlouhe_s", "s")
        self.assertEqual(json.loads(cti_soubor(p)), {"model": "ces", "stare_znaky": "jen_s"})
        with open(p, "w", encoding="utf-8") as f:
            f.write('{"dlouhe_s": "ponechat"}')
        with contextlib.redirect_stdout(io.StringIO()):
            ocr.prikaz_nastav(p, "stare_znaky", "zjednodusit")
        self.assertEqual(json.loads(cti_soubor(p)), {"stare_znaky": "zjednodusit"})

    def test_nastaveni_nezname_pole_varuje(self):
        chyby, varovani = ocr.over_nastaveni({"model": "ces", "barva": "modra"})
        self.assertEqual(chyby, [])
        self.assertTrue(any("barva" in v for v in varovani))

    def test_nastav_zachova_ostatni(self):
        p = os.path.join(self.tmp, "data", "ocr.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write('{"model": "ces", "x_vlastni": 1, "dpi": 200}')
        with contextlib.redirect_stdout(io.StringIO()):
            ocr.prikaz_nastav(p, "davka", "5")
            self.assertEqual(json.loads(cti_soubor(p)), {"model": "ces", "x_vlastni": 1, "dpi": 200,
                                                                     "davka": 5})
            ocr.prikaz_nastav(p, "dpi", "vychozi")
            ocr.prikaz_nastav(p, "prikaz", '["ocr", "{slozka}", "{vystup}", "{model}"]')
        d = json.loads(cti_soubor(p))
        self.assertEqual(d, {"model": "ces", "x_vlastni": 1, "davka": 5,
                             "prikaz": ["ocr", "{slozka}", "{vystup}", "{model}"]})
        pred = cti_soubor(p, "rb")
        self.assertTrue(pred.endswith(b"\n") and b"\r" not in pred)
        for k, v in (("davka", "0"), ("dpi", "abc"), ("dlouhe_s", "x"), ("stare_znaky", "s"), ("prikaz", '["ocr"]'),
                     ("neznamy", "1")):
            with self.assertRaises(ocr.Chyba):
                ocr.prikaz_nastav(p, k, v)
        self.assertEqual(cti_soubor(p, "rb"), pred)


class TestDetekce(Zaklad):
    def test_navod_os(self):
        self.assertIn("brew install tesseract", ocr.navod("tesseract", "darwin"))
        self.assertIn("brew install poppler", ocr.navod("poppler", "darwin"))
        self.assertIn("UB-Mannheim.TesseractOCR", ocr.navod("tesseract", "win32"))
        self.assertIn("oschwartz10612.Poppler", ocr.navod("poppler", "win32"))
        self.assertIn("sudo apt install tesseract-ocr", ocr.navod("tesseract", "linux"))
        self.assertIn("poppler-utils", ocr.navod("poppler", "linux"))
        for co in ("tesseract", "poppler"):   # Linux: sudo jen jako příkaz pro uživatele, brew/winget po souhlasu
            self.assertIn("spustí ho sám", ocr.navod(co, "linux"))
            self.assertIn("! sudo", ocr.navod(co, "linux"))
            for plat in ("darwin", "win32"):
                self.assertIn("po souhlasu smí Claude spustit", ocr.navod(co, plat))
                self.assertNotIn("sudo", ocr.navod(co, plat))

    def test_rada_modelu_puvod(self):
        gp = ocr.rada_modelu("german_print", "/u")
        self.assertIn("3,5 MB", gp)
        self.assertIn("UB Mannheim (ne GitHub)", gp)
        self.assertIn("licence neuvedená", gp)
        for m in ("deu", "ces", "lat"):
            self.assertIn("tessdata_best na GitHubu, Apache-2.0", ocr.rada_modelu(m, "/u"))
        self.assertIn("licence neuvedená", ocr.rada_modelu("frak2021", "/u"))
        rc, out, _ = self.spust("modely")
        self.assertEqual(rc, 0)
        radky = {r.split()[0]: r for r in out.splitlines() if r.split() and r.split()[0] in ocr.ZNAME}
        self.assertIn("server UB Mannheim", radky["german_print"])
        self.assertIn("Apache-2.0", radky["ces"])

    def test_reference_velikosti_modelu(self):
        with open(os.path.join(SKILL, "reference", "ocr.md"), encoding="utf-8") as f:
            radky = f.read().splitlines()
        for m, (url, _, mb, _) in ocr.ZNAME.items():
            radek = [r for r in radky if r.startswith(f"| `{m}`")]
            self.assertEqual(len(radek), 1, m)
            self.assertIn(f"| {mb:.1f} MB |".replace(".", ","), radek[0])
            self.assertIn("neuvedená" if "uni-mannheim" in url else "Apache-2.0", radek[0])

    def test_stav_stare_znaky_nastaveno(self):
        rc, out, _ = self.spust("stav")
        self.assertIn("staré znaky: zjednodusit (výchozí, nenastaveno – u fraktury se zeptej uživatele)", out)
        self.nastav({"tessdata": self.uziv, "stare_znaky": "ponechat"})
        rc, out, _ = self.spust("stav")
        self.assertIn("staré znaky: ponechat (nastaveno v data/ocr.json)", out)
        self.nastav({"tessdata": self.uziv, "dlouhe_s": "s"})   # zastaralé pole se počítá jako nastavené
        rc, out, _ = self.spust("stav")
        self.assertIn("staré znaky: jen_s (nastaveno v data/ocr.json)", out)

    def test_chybi_tesseract_exit2(self):
        del self.programy["tesseract"]
        rc, _, err = self.spust(self.obrazky("a.jpg"))
        self.assertEqual(rc, 2)
        self.assertIn(ocr.navod("tesseract"), err)
        self.assertFalse(os.path.exists(self.vystup("skeny")))   # kontrola před zámkem: žádná prázdná složka
        rc, out, _ = self.spust("stav")
        self.assertEqual(rc, 2)
        self.assertIn("tesseract: CHYBÍ", out)

    def test_windows_program_files(self):
        najdi = PUVODNI_NAJDI   # Zaklad ocr.najdi nahrazuje
        nikde = lambda p: None
        self.assertEqual(najdi("tesseract", "win32", {"ProgramFiles": r"D:\Prg"}, which=nikde,
                               existuje=lambda p: p == r"D:\Prg\Tesseract-OCR\tesseract.exe"),
                         r"D:\Prg\Tesseract-OCR\tesseract.exe")
        self.assertEqual(najdi("tesseract", "win32", {}, which=nikde,
                               existuje=lambda p: p == r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
                         r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        winget = lambda p: "WinGet" in p   # složky WinGet se už nehádají (Poppler patří do PATH)
        self.assertIsNone(najdi("pdftoppm", "win32", {"LOCALAPPDATA": r"C:\Users\x\AppData\Local"}, which=nikde,
                                existuje=winget))
        self.assertEqual(najdi("pdftoppm", "win32", {}, which=lambda p: r"C:\bin\pdftoppm.exe", existuje=winget),
                         r"C:\bin\pdftoppm.exe")
        self.assertIsNone(najdi("tesseract", "linux", {}, which=nikde, existuje=lambda p: True))

    def test_list_langs_parse(self):
        self.assertEqual(ocr.rozbor_jazyku('List of available languages in "/opt/homebrew/share/tessdata/" (2):\n'
                                           'deu\neng\n'), ("/opt/homebrew/share/tessdata/", ["deu", "eng"]))
        self.assertEqual(ocr.rozbor_jazyku('List of available languages in "C:\\Program Files\\Tesseract-OCR/tessdata/"'
                                           ' (1):\r\neng\r\n'), ("C:\\Program Files\\Tesseract-OCR/tessdata/", ["eng"]))
        self.assertEqual(ocr.rozbor_jazyku('List of available languages in "/usr/share/x/" (0):\n'),
                         ("/usr/share/x/", []))
        self.assertEqual(ocr.rozbor_jazyku("List of available languages (2):\nces\nosd\n"), (None, ["ces", "osd"]))
        self.assertEqual(ocr.rozbor_jazyku("Error opening data file\nnesmysl ! x\n"), (None, []))




class TestSlozkyModelu(Zaklad):
    def tess_argv(self):
        return [a for a in self.fake.volani if os.path.basename(a[0]) == "tesseract" and "stdout" in a]

    def test_model_v_systemu(self):
        self.model(self.sysdir, "german_print", "systemovy")
        prazdna = os.path.join(self.tmp, "prazdna")
        os.makedirs(prazdna)
        self.nastav({"tessdata": prazdna})
        self.assertEqual(self.spust(self.pdf(1))[0], 0)
        self.assertNotIn("--tessdata-dir", self.tess_argv()[0])
        self.assertEqual(os.listdir(prazdna), [])

    def test_model_jen_v_uzivatelske(self):
        self.assertEqual(self.spust(self.pdf(1))[0], 0)
        a = self.tess_argv()[0]
        self.assertEqual(a[a.index("--tessdata-dir") + 1], self.uziv)
        self.assertEqual(self.manifest("kniha")["model"], "german_print")

    def test_model_rozdeleny_zkopiruje(self):
        self.model(self.sysdir, "ces", "cesky")
        rc, out, _ = self.spust("stav", "--model", "german_print+ces")
        self.assertEqual(rc, 0)
        self.assertIn("zkopíruje", out)
        self.assertFalse(os.path.exists(os.path.join(self.uziv, "ces.traineddata")))   # stav nic nemění
        self.assertEqual(self.spust(self.pdf(1), "--model", "german_print+ces")[0], 0)
        with open(os.path.join(self.uziv, "ces.traineddata")) as f:
            self.assertEqual(f.read(), "cesky")
        self.assertIn("--tessdata-dir", self.tess_argv()[0])
        os.remove(os.path.join(self.uziv, "ces.traineddata"))
        os.remove(os.path.join(self.sysdir, "ces.traineddata"))
        rc, _, err = self.spust(self.pdf(1), "--model", "german_print+ces", "--vystup", self.vystup("k2"))
        self.assertEqual(rc, 2)
        self.assertIn("ocr.py stahni ces", err)

    def test_neznamy_model_navod(self):
        rc, _, err = self.spust(self.pdf(1), "--model", "xyz")
        self.assertEqual(rc, 2)
        self.assertIn("skill tento model nezná", err)
        self.assertFalse(os.path.exists(self.vystup("kniha")))
        self.assertIn(self.uziv, err)
        rc, out, _ = self.spust("stav", "--model", "xyz")
        self.assertEqual(rc, 2)
        self.assertIn("xyz: CHYBÍ", out)


class FalesnaOdpoved(io.BytesIO):
    pass


class TestStahovani(Zaklad):
    DATA = b"m" * 200_000

    def test_stahni_hash(self):
        cil = os.path.join(self.tmp, "td")
        dobry = hashlib.sha256(self.DATA).hexdigest()
        with mock.patch.dict(ocr.ZNAME, {"test_m": ("https://example.org/m", "0" * 64, 0.2, "x")}):
            with self.assertRaises(ocr.Chyba):
                ocr.stahni("test_m", cil, otevri=lambda url: FalesnaOdpoved(self.DATA))
            self.assertEqual(os.listdir(cil), [])
        male = b"m" * 1000
        with mock.patch.dict(ocr.ZNAME, {"test_m": ("https://example.org/m", hashlib.sha256(male).hexdigest(), 0, "x")}):
            with self.assertRaises(ocr.Chyba):
                ocr.stahni("test_m", cil, otevri=lambda url: FalesnaOdpoved(male))
            self.assertEqual(os.listdir(cil), [])

        def prerusene(url):
            class R(io.BytesIO):
                def read(self, n=-1):
                    raise OSError("spojení přerušeno")
            return R()
        with mock.patch.dict(ocr.ZNAME, {"test_m": ("https://example.org/m", dobry, 0.2, "x")}):
            with self.assertRaises(ocr.Chyba):
                ocr.stahni("test_m", cil, otevri=prerusene)
            self.assertEqual(os.listdir(cil), [])
            with contextlib.redirect_stdout(io.StringIO()):
                ocr.stahni("test_m", cil, otevri=lambda url: FalesnaOdpoved(self.DATA))
        self.assertEqual(os.listdir(cil), ["test_m.traineddata"])

    def test_stahni_bez_slusne_odmitne(self):
        def otevri(url):
            raise AssertionError("bez slusne.py se nesmí otevřít spojení")
        with mock.patch.object(ocr, "slusne", None):
            with self.assertRaises(ocr.Chyba) as c:
                ocr.stahni("german_print", os.path.join(self.tmp, "td"), otevri=otevri)
        self.assertEqual(c.exception.kod, 2)
        self.assertIn(ocr.ZNAME["german_print"][0], str(c.exception))
        with self.assertRaises(ocr.Chyba) as c:
            ocr.stahni("neznamy", os.path.join(self.tmp, "td"), otevri=otevri)
        self.assertEqual(c.exception.kod, 2)


class TestVstupy(Zaklad):
    def test_obrazek_bez_poppleru(self):
        del self.programy["pdftoppm"], self.programy["pdfinfo"]
        d = self.obrazky("a-001.jpg")
        self.assertEqual(self.spust(os.path.join(d, "a-001.jpg"))[0], 0)
        self.assertIn("obrazek a-001.jpg", self.cti("a-001", "a-001.txt"))

    def test_pdf_bez_poppleru_exit2(self):
        del self.programy["pdftoppm"]
        rc, _, err = self.spust(self.pdf(1))
        self.assertEqual(rc, 2)
        self.assertIn(ocr.navod("poppler"), err)
        self.assertFalse(os.path.exists(self.vystup("kniha")))

    def test_slozka_obrazku_podle_jmena(self):
        d = self.obrazky("b.png", "a-002.jpg", "a-001.JPG", "poznamka.txt")
        self.assertEqual(self.spust(d)[0], 0)
        self.assertEqual(sorted(f for f in os.listdir(self.vystup("skeny")) if f.endswith(".txt")),
                         ["a-001.txt", "a-002.txt", "b.txt"])
        self.assertIn("obrazek a-002.jpg", self.cti("skeny", "a-002.txt"))
        self.assertEqual(self.fake.tesseract_obrazky().count("a-001"), 1)
        d2 = self.obrazky("a.jpg", "a.png", slozka="kolize")
        self.fake.volani.clear()
        rc, _, err = self.spust(d2)
        self.assertEqual(rc, 1)
        self.assertIn("stejný soubor a.txt", err)
        self.assertEqual(self.fake.volani, [])

    def test_tiff_vice_stran(self):
        """Vícestránkový TIFF pozná \\f ve výstupu Tesseractu (i s prázdným prvním snímkem); koncové \\f
        (Tesseract 4, prázdná poslední strana) projde jako jedna strana."""
        d = self.obrazky("a.tif", "b.tif", "c.tif", "d.tif", "e.tif", slozka="tif")
        self.fake.vystupy = {"b": "a\fb\n", "c": "a\n\f", "d": "\f", "e": "\fb\n"}
        rc, _, err = self.spust(d)
        self.assertEqual(rc, 1)
        for j in ("b", "e"):
            self.assertIn(f"{j}: CHYBA víc stran v jednom souboru", err)
        self.assertIn("magick", err)
        self.assertEqual(sorted(f for f in os.listdir(self.vystup("tif")) if f.endswith(".txt")),
                         ["a.txt", "c.txt", "d.txt"])

    def test_vic_vstupu_pokracuje(self):
        neni = os.path.join(self.tmp, "dokumenty", "neexistuje.pdf")
        rc, _, err = self.spust(neni, self.obrazky("a.jpg"))
        self.assertEqual(rc, 1)
        self.assertTrue(os.path.exists(self.vystup("skeny", "a.txt")))
        self.assertIn("Nehotové vstupy: " + neni, err)

    def test_vic_vstupu_nenainstalovano(self):
        del self.programy["tesseract"]
        rc, _, err = self.spust(self.obrazky("a.jpg"), self.obrazky("b.jpg", slozka="druha"))
        self.assertEqual(rc, 2)
        self.assertEqual(err.count("Chybí Tesseract"), 1)
        self.assertFalse(os.path.exists(self.vystup("skeny")) or os.path.exists(self.vystup("druha")))
        self.assertEqual(self.fake.tesseract_obrazky(), [])

    def test_strany_rozsah(self):
        for r in ("3-2", "0-1", "6-7", "x", "1-"):
            with self.assertRaises(ocr.Chyba):
                ocr.rozsah_stran(r, 5)
        self.assertEqual(ocr.rozsah_stran("2-4", 5), (2, 4))
        self.assertEqual(ocr.rozsah_stran("5", 5), (5, 5))
        self.assertEqual(self.spust(self.pdf(5), "--strany", "2-3")[0], 0)
        self.assertEqual(sorted(f for f in os.listdir(self.vystup("kniha")) if f.endswith(".txt")),
                         ["s0002.txt", "s0003.txt"])
        self.assertEqual(self.spust(self.pdf(5), "--strany", "6-7")[0], 1)


class TestDodelavani(Zaklad):
    def txt(self, dok):
        return sorted(f for f in os.listdir(self.vystup(dok)) if f.endswith(".txt"))

    def test_dodela_jen_chybejici(self):
        p = self.pdf(3)
        self.assertEqual(self.spust(p)[0], 0)
        self.assertEqual(self.txt("kniha"), ["s0001.txt", "s0002.txt", "s0003.txt"])
        self.assertEqual(self.manifest("kniha"), {
            "verze": 2, "zdroj": {"druh": "pdf", "jmeno": "kniha.pdf", "stran": 3}, "model": "german_print",
            "stare_znaky": "zjednodusit", "dpi": 300, "programy": {"tesseract": "5.5.4", "pdftoppm": "26.11.0"}})
        os.remove(self.vystup("kniha", "s0002.txt"))
        open(self.vystup("kniha", "s0002.txt.part"), "w").close()
        open(self.vystup("kniha", "s0003.txt"), "w").close()
        self.fake.volani.clear()
        rc, out, _ = self.spust(p)
        self.assertEqual(rc, 0)
        self.assertIn("hotovo 2, zbývá 1", out)
        self.assertEqual(self.fake.tesseract_obrazky(), ["s0002"])
        self.assertEqual(self.cti("kniha", "s0003.txt"), "")
        self.assertFalse(os.path.exists(self.vystup("kniha", "s0002.txt.part")))

    def test_novy_obrazek_ve_slozce(self):
        d = self.obrazky("a-001.jpg", "a-002.jpg")
        self.assertEqual(self.spust(d)[0], 0)
        self.obrazky("a-003.jpg")
        self.fake.volani.clear()
        self.assertEqual(self.spust(d)[0], 0)
        self.assertEqual(self.fake.tesseract_obrazky(), ["a-003"])
        m = self.manifest("skeny")
        self.assertEqual((m["zdroj"], m["dpi"]), ({"druh": "slozka", "jmeno": "skeny"}, None))

    def test_zmenene_bajty_modelu(self):
        self.assertEqual(self.spust(self.pdf(2))[0], 0)
        self.model(self.uziv, "german_print", "jiná verze modelu")   # vědomě nehlídané (jen název modelu)
        os.remove(self.vystup("kniha", "s0002.txt"))
        self.fake.volani.clear()
        self.assertEqual(self.spust(self.pdf(2))[0], 0)
        self.assertEqual(self.fake.tesseract_obrazky(), ["s0002"])

    def test_jine_verze_programu_dodela(self):
        self.fake.verze = {"tesseract": "5.5.3", "pdftoppm": "26.02.0"}
        self.assertEqual(self.spust(self.pdf(3), "--strany", "1-2")[0], 0)
        self.fake.verze = {"tesseract": "5.5.4", "pdftoppm": "26.03.0"}
        self.fake.volani.clear()
        self.assertEqual(self.spust(self.pdf(3))[0], 0)
        self.assertEqual(self.fake.tesseract_obrazky(), ["s0003"])
        self.assertEqual(self.manifest("kniha")["programy"], {"tesseract": "5.5.4", "pdftoppm": "26.03.0"})

    def test_jiny_zdroj(self):
        self.assertEqual(self.spust(self.pdf(3))[0], 0)
        for argv in ((self.pdf(4),), (self.pdf(3, jmeno="jina.pdf"), "--vystup", self.vystup("kniha")),
                     (os.path.join(self.obrazky("kniha.jpg"), "kniha.jpg"), "--vystup", self.vystup("kniha"))):
            rc, _, err = self.spust(*argv)
            self.assertEqual(rc, 1, argv)
            self.assertIn("zdroj: {", err)

    def test_stary_manifest(self):
        os.makedirs(self.vystup("kniha"))
        open(self.vystup("kniha", "s0001.txt"), "w").close()
        with open(self.vystup("kniha", "ocr_manifest.json"), "w") as f:
            json.dump({"verze": 1, "zdroj": {"druh": "pdf", "jmeno": "kniha.pdf", "stran": 2}, "model": "german_print",
                       "stare_znaky": "zjednodusit"}, f)
        rc, _, err = self.spust(self.pdf(2))
        self.assertEqual(rc, 1)
        self.assertIn("verze: 1 → 2", err)
        self.assertIn("--znovu", err)

    def test_znovu(self):
        self.assertEqual(self.spust(self.pdf(3))[0], 0)
        for f in ("poznamka.txt", "poznamka.md"):   # vlastní soubory uživatele ve složce stran
            open(self.vystup("kniha", f), "w").close()
        self.model(self.uziv, "frak2021")
        self.assertEqual(self.spust(self.pdf(3), "--model", "frak2021")[0], 1)
        self.fake.volani.clear()
        rc, _, err = self.spust(self.pdf(3), "--model", "frak2021", "--znovu")
        self.assertEqual(rc, 0, err)
        self.assertEqual(sorted(self.fake.tesseract_obrazky()), ["s0001", "s0002", "s0003"])
        self.assertEqual(self.manifest("kniha")["model"], "frak2021")
        self.assertTrue(os.path.exists(self.vystup("kniha", "poznamka.txt")))
        self.assertTrue(os.path.exists(self.vystup("kniha", "poznamka.md")))
        cizi = self.vystup("cizi")   # .txt bez manifestu: složka nemusí být naše → nic nesmazat
        os.makedirs(cizi)
        open(os.path.join(cizi, "s0001.txt"), "w").close()
        rc, _, err = self.spust(self.pdf(3), "--vystup", cizi, "--znovu")
        self.assertEqual(rc, 1)
        self.assertIn("bez ocr_manifest.json", err)
        self.assertTrue(os.path.exists(os.path.join(cizi, "s0001.txt")))

    def test_jine_dpi(self):
        self.assertEqual(self.spust(self.pdf(2))[0], 0)
        self.nastav({"tessdata": self.uziv, "dpi": 200})
        rc, _, err = self.spust(self.pdf(2))
        self.assertEqual(rc, 1)
        self.assertIn("dpi: 300 → 200", err)

    def test_jine_stare_znaky(self):
        self.assertEqual(self.spust(self.pdf(2))[0], 0)
        self.nastav({"tessdata": self.uziv, "stare_znaky": "ponechat"})
        rc, _, err = self.spust(self.pdf(2))
        self.assertEqual(rc, 1)
        self.assertIn('stare_znaky: "zjednodusit" → "ponechat"', err)

    def test_stare_znaky_z_manifestu(self):
        """Nenastavené staré znaky se dodělají podle hotových stran; s výchozí hodnotou bez hlášky."""
        verze = "v1 \u017f"
        self.nastav({"tessdata": self.uziv, "stare_znaky": "ponechat"})
        self.assertEqual(self.spust(self.pdf(3, verze=verze), "--strany", "1-2")[0], 0)
        self.nastav({"tessdata": self.uziv})
        rc, _, err = self.spust(self.pdf(3, verze=verze))
        self.assertEqual(rc, 0, err)
        self.assertIn("staré znaky: ponechat podle hotových stran", err)
        self.assertIn("\u017f", self.cti("kniha", "s0003.txt"))
        self.assertEqual(self.spust(self.pdf(3), "--strany", "1-2", "--vystup", self.vystup("k2"))[0], 0)
        rc, _, err = self.spust(self.pdf(3), "--vystup", self.vystup("k2"))
        self.assertEqual(rc, 0)
        self.assertNotIn("podle hotových stran", err)

    def test_jiny_model(self):
        self.assertEqual(self.spust(self.pdf(2))[0], 0)
        self.model(self.uziv, "frak2021")
        pred = {f: os.path.getmtime(self.vystup("kniha", f)) for f in os.listdir(self.vystup("kniha"))}
        rc, _, err = self.spust(self.pdf(2), "--model", "frak2021")
        self.assertEqual(rc, 1)
        self.assertIn('model: "german_print" → "frak2021"', err)
        self.assertIn("--znovu", err)
        self.assertEqual(pred, {f: os.path.getmtime(self.vystup("kniha", f)) for f in os.listdir(self.vystup("kniha"))})

    def test_strany_bez_manifestu(self):
        os.makedirs(self.vystup("kniha"))
        open(self.vystup("kniha", "s0001.txt"), "w").close()
        rc, _, err = self.spust(self.pdf(2))
        self.assertEqual(rc, 1)
        self.assertIn("bez ocr_manifest.json", err)
        self.assertEqual(self.fake.tesseract_obrazky(), [])

    def test_rozbity_manifest(self):
        os.makedirs(self.vystup("kniha"))
        open(self.vystup("kniha", "s0001.txt"), "w").close()
        with open(self.vystup("kniha", "ocr_manifest.json"), "w") as f:
            f.write("{")
        rc, _, err = self.spust(self.pdf(2))
        self.assertEqual(rc, 1)
        self.assertIn("nečitelný manifest", err)

    def test_preruseny_manifest(self):
        os.makedirs(self.vystup("kniha"))
        with open(self.vystup("kniha", "ocr_manifest.json.part"), "w") as f:
            f.write("{")
        self.assertEqual(self.spust(self.pdf(2))[0], 0)
        os.makedirs(self.vystup("k2"))
        with open(self.vystup("k2", "ocr_manifest.json"), "w") as f:
            json.dump({"verze": 1, "model": "jiny"}, f)
        self.assertEqual(self.spust(self.pdf(2), "--vystup", self.vystup("k2"))[0], 0)
        self.assertEqual(self.manifest("k2")["model"], "german_print")


class TestText(Zaklad):
    def test_o1_stare_znaky(self):
        text = "Fi\u017fch \ua75bc. Mu\u0364ller U\u0364ber Mü\u0364ller"
        self.assertEqual(ocr.uprav_text(text, "zjednodusit"), "Fisch rc. Müller Über Müller")
        self.assertEqual(ocr.uprav_text(text, "jen_s"), "Fisch \ua75bc. Mu\u0364ller U\u0364ber Mü\u0364ller")
        self.assertEqual(ocr.uprav_text(text, "ponechat"), text)
        self.assertEqual(ocr.uprav_text("Menſch\n\f", "ponechat"), "Menſch\n")
        self.assertEqual(ocr.uprav_text("a\r\nb\f", "zjednodusit"), "a\nb")
        self.assertEqual(self.spust(self.pdf(1))[0], 0)
        self.assertEqual(self.cti("kniha", "s0001.txt"), "Mensch strana 1 z %PDF n=1 v1 german_print\n")

    def test_chyba_strany_pokracuje(self):
        self.fake.selhat = {"s0002"}
        rc, _, err = self.spust(self.pdf(3))
        self.assertEqual(rc, 1)
        self.assertIn("s0002: CHYBA", err)
        self.assertTrue(os.path.exists(self.vystup("kniha", "s0001.txt")))
        self.assertTrue(os.path.exists(self.vystup("kniha", "s0003.txt")))
        self.assertFalse(os.path.exists(self.vystup("kniha", "s0002.txt")))
        self.fake.selhat = set()
        self.fake.volani.clear()
        self.assertEqual(self.spust(self.pdf(3))[0], 0)
        self.assertEqual(self.fake.tesseract_obrazky(), ["s0002"])


class TestPreruseni(Zaklad):
    def test_preruseni_tesseract(self):
        """Ctrl-C: nic nečeká ve frontě (zavolají se jen strany do přerušení), hláška bez CHYBA, exit 130."""
        self.nastav({"tessdata": self.uziv, "soubezne": 1})
        self.fake.prerusit = {"s0003"}
        rc, _, err = self.spust(self.pdf(10))
        self.assertEqual(rc, 130)
        self.assertEqual(self.fake.tesseract_obrazky(), ["s0001", "s0002", "s0003"])
        self.assertIn("hotovo 2 z 10", err)
        self.assertNotIn("CHYBA", err)
        self.assertEqual([f for f in os.listdir(self.vystup("kniha")) if f.endswith(".part")], [])
        self.fake.prerusit = set()
        self.fake.volani.clear()
        self.assertEqual(self.spust(self.pdf(10))[0], 0)
        self.assertEqual(self.fake.tesseract_obrazky(), ["s%04d" % i for i in range(3, 11)])

    def test_spust_prikaz_ceka(self):
        for wait, kill in (([KeyboardInterrupt, 0], 0), ([KeyboardInterrupt, KeyboardInterrupt, 0], 1)):
            proc = mock.Mock()
            proc.wait.side_effect = wait
            with mock.patch.object(subprocess, "Popen", return_value=proc), \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                with self.assertRaises(KeyboardInterrupt):
                    PUVODNI_SPUST_PRIKAZ(["x"])
            self.assertEqual(proc.wait.call_count, len(wait))
            self.assertEqual(proc.kill.call_count, kill)
            self.assertIn("čekám", err.getvalue())


class TestPrikaz(Zaklad):
    SABLONA = ["fakeocr", "{slozka}", "--lang", "{model}", "--out", "{vystup}"]

    def setUp(self):
        super().setUp()
        self.davky, self.jmena_v_davce = [], []
        self.fake.prikaz = self.soubory

    def nastav_prikaz(self, sablona=None, **kw):
        self.nastav(dict({"tessdata": self.uziv, "prikaz": sablona or self.SABLONA}, **kw))

    def soubory(self, argv):
        """Jako `ocr --no-pdf`: jeden <slozka>.txt, za každou stranou \\f. Řadí „přirozeně“ (1, 2, 10), aby test
        poznal, kdyby nástroj dal do dávky jména, která tak řadí jinak než on. self.davky = strany podle obsahu."""
        slozka, vystup = argv[1], argv[argv.index("--out") + 1]
        obr = sorted(os.listdir(slozka), key=lambda f: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", f)])
        self.jmena_v_davce.append(obr)
        texty = [cti_soubor(os.path.join(slozka, f)) for f in obr]
        self.davky.append([("s%04d" % int(x.split()[1])) if x.startswith("strana ") else os.path.splitext(x.split()[1])[0]
                           for x in texty])
        with open(os.path.join(vystup, os.path.basename(slozka) + ".txt"), "w", encoding="utf-8") as h:
            h.write("".join("P " + x + "\n\f" for x in texty))
        return 0

    def test_prikaz_argv(self):
        a = ocr.prikaz_argv(["~/bin/ocr", "{slozka}", "--out={vystup}", "-l", "{model}", "~/x"], "/t/d", "/t/v", "ces")
        self.assertEqual(a, [os.path.expanduser("~/bin/ocr"), "/t/d", "--out=/t/v", "-l", "ces", "~/x"])

    def test_prikaz_vystup(self):
        v = os.path.join(self.tmp, "v")
        os.makedirs(v)

        def davka(text, jmena=("x1", "x2", "x3"), soubory=("ocr_davka_1.txt",)):
            for f in os.listdir(v):
                os.remove(os.path.join(v, f))
            for f in soubory:
                with open(os.path.join(v, f), "w", encoding="utf-8", newline="") as g:
                    g.write(text)
            return ocr.vysledky_davky(v, list(jmena))
        self.assertEqual(davka("\fb\f\f"), {"x1": "", "x2": "b", "x3": ""})
        self.assertEqual(davka("a\fb\fc\f\n "), {"x1": "a", "x2": "b", "x3": "c"})
        self.assertEqual(davka("a\f", ["x1"]), {"x1": "a"})
        for spatne, soubory in (("a\fb", None), ("a\fb\fc\fd\f", None), ("a\fb\fc\fX", None),
                                ("a\fb\fc\f", ()), ("a\fb\fc\f", ("a.txt", "b.txt"))):
            with self.assertRaises(ocr.Chyba, msg=repr(spatne)) as c:
                davka(spatne, soubory=soubory or (() if soubory == () else ("ocr_davka_1.txt",)))
            if spatne == "a\fb\fc\fd\f":
                self.assertIn("vícestránkový TIFF", str(c.exception))
        self.nastav_prikaz()
        self.assertEqual(self.spust(self.pdf(3))[0], 0)
        for i in (1, 2, 3):
            self.assertEqual(self.cti("kniha", f"s000{i}.txt"), f"P strana {i} z %PDF n=3 v1\n")
        m = self.manifest("kniha")
        self.assertEqual((m["model"], m["programy"]), ("german_print", {"prikaz": self.SABLONA, "pdftoppm": "26.11.0"}))
        self.assertEqual(self.fake.tesseract_obrazky(), [])
        # 1, 10, 2 (naše abecední pořadí) – v dávce pořadová jména, takže „přirozeně“ řadící program nic neprohodí
        self.jmena_v_davce.clear()
        self.assertEqual(self.spust(self.obrazky("1.jpg", "2.jpg", "10.jpg", slozka="cisla"))[0], 0)
        self.assertEqual(self.jmena_v_davce, [["p0001.jpg", "p0002.jpg", "p0003.jpg"]])
        for j in ("1", "2", "10"):
            self.assertEqual(self.cti("cisla", j + ".txt"), f"P obrazek {j}.jpg\n")

    def test_preruseni_prikaz(self):
        self.nastav_prikaz(davka=2)
        davky = []

        def prikaz(argv):
            davky.append(1)
            if len(davky) == 2:
                raise KeyboardInterrupt
            return self.soubory(argv)
        self.fake.prikaz = prikaz
        tmp = os.path.join(self.tmp, "tmp")
        os.makedirs(tmp)
        with mock.patch.object(tempfile, "tempdir", tmp):
            rc, _, err = self.spust(self.pdf(5))
        self.assertEqual(rc, 130)
        self.assertIn("hotovo 2 z 5", err)
        self.assertEqual(sorted(f for f in os.listdir(self.vystup("kniha")) if f.endswith(".txt")),
                         ["s0001.txt", "s0002.txt"])
        self.assertEqual(os.listdir(tmp), [])

    def test_prikaz_rc_nenula(self):
        self.fake.prikaz = lambda argv: 3
        self.nastav_prikaz()
        rc, _, err = self.spust(self.pdf(2))
        self.assertEqual(rc, 1)
        self.assertIn("kódem 3", err)
        self.assertEqual([f for f in os.listdir(self.vystup("kniha")) if f.endswith(".txt")], [])

    def test_prikaz_davky(self):
        self.nastav_prikaz(davka=2)
        volani = []

        def druha_selze(argv):
            volani.append(1)
            return 1 if len(volani) == 2 else self.soubory(argv)
        self.fake.prikaz = druha_selze
        rc, _, _ = self.spust(self.pdf(5))
        self.assertEqual(rc, 1)
        self.assertEqual(sorted(f for f in os.listdir(self.vystup("kniha")) if f.endswith(".txt")),
                         ["s0001.txt", "s0002.txt"])
        self.fake.prikaz = self.soubory
        self.davky.clear()
        self.assertEqual(self.spust(self.pdf(5))[0], 0)
        self.assertEqual(self.davky, [["s0003", "s0004"], ["s0005"]])

    def test_prikaz_dodela(self):
        """Dodělání bez prikaz_verze, stejně jako vestavěná cesta; i ve složce hotové vestavěným Tesseractem."""
        self.nastav_prikaz()
        self.assertEqual(self.spust(self.pdf(3))[0], 0)
        os.remove(self.vystup("kniha", "s0002.txt"))
        self.davky.clear()
        self.assertEqual(self.spust(self.pdf(3))[0], 0)
        self.assertEqual(self.davky, [["s0002"]])
        self.nastav({"tessdata": self.uziv})
        self.assertEqual(self.spust(self.pdf(3), "--strany", "1-2", "--vystup", self.vystup("k2"))[0], 0)
        self.nastav_prikaz()
        self.davky.clear()
        self.assertEqual(self.spust(self.pdf(3), "--vystup", self.vystup("k2"))[0], 0)
        self.assertEqual(self.davky, [["s0003"]])
        os.remove(self.vystup("k2", "s0003.txt"))
        rc, _, err = self.spust(self.pdf(3), "--vystup", self.vystup("k2"), "--model", "frak2021")
        self.assertEqual(rc, 1)
        self.assertIn('model: "german_print" → "frak2021"', err)


FAKE_OCR = """import os, sys
slozka, vystup = sys.argv[1], sys.argv[2]
with open(os.path.join(vystup, os.path.basename(slozka) + ".txt"), "w", encoding="utf-8") as g:
    for f in sorted(os.listdir(slozka)):
        g.write("text " + f + "\\n\\f")
"""
DRZ_ZAMEK = """import os, sys, time
sys.path.insert(0, sys.argv[1])
import ocr
with ocr.zamek_slozky(sys.argv[2]):
    open(sys.argv[3], "w").close()
    while not os.path.exists(sys.argv[4]):
        time.sleep(0.05)
"""


class TestCli(unittest.TestCase):
    """Skutečný nástroj v dočasném projektu (python3 -I tools/ocr.py)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ocr_cli_")
        self.root = os.path.join(self.tmp, "proj")
        p = subprocess.run([sys.executable, "-I", os.path.join(SKILL, "tools", "novy_projekt.py"), self.root,
                            "--bez-webu"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self, *p):
        return os.path.join(self.root, *p)

    def ocr(self, *args, timeout=60):
        return subprocess.run([sys.executable, "-I", "-X", "utf8", self.path("tools", "ocr.py"), *args], cwd=self.root,
                              capture_output=True, text=True, encoding="utf-8", timeout=timeout)

    def test_nastaveni_poskozene(self):
        with open(self.path("data", "ocr.json"), "w", encoding="utf-8") as f:
            f.write('{\n "model": ,\n}\n')
        p = self.ocr("stav")
        self.assertEqual(p.returncode, 1)
        self.assertIn("ocr.json", p.stderr)
        self.assertIn("řádku 2", p.stderr)
        self.assertNotIn("Traceback", p.stderr + p.stdout)
        with open(self.path("data", "ocr.json"), "w", encoding="utf-8") as f:
            f.write('{"davka": "10"}')
        p = self.ocr("stav")
        self.assertEqual(p.returncode, 1)
        self.assertIn("davka", p.stderr)
        self.assertNotIn("Traceback", p.stderr + p.stdout)

    def test_nastaveni_prezije_aktualizaci(self):
        self.assertEqual(self.ocr("nastav", "stare_znaky", "ponechat").returncode, 0)
        self.assertEqual(self.ocr("nastav", "model", "german_print+ces").returncode, 0)
        with open(self.path("data", "ocr.json"), "rb") as f:
            pred = f.read()
        for _ in range(2):
            subprocess.run([sys.executable, "-I", os.path.join(SKILL, "tools", "novy_projekt.py"), self.root,
                            "--bez-webu"], capture_output=True, check=True)
        with open(self.path("data", "ocr.json"), "rb") as f:
            self.assertEqual(f.read(), pred)
        self.assertEqual(json.loads(pred), {"stare_znaky": "ponechat", "model": "german_print+ces"})

    def test_cli_I_pouziva_slusne(self):
        p = self.ocr("stav")
        self.assertIn("stahovani: slusne.py", p.stdout)
        self.assertNotIn("Traceback", p.stderr)

    def test_cli_bez_slusne(self):
        os.remove(self.path("tools", "slusne.py"))
        td = os.path.join(self.tmp, "td")
        self.assertEqual(self.ocr("nastav", "tessdata", td).returncode, 0)
        p = self.ocr("stav")
        self.assertIn("stahovani: vypnuto", p.stdout)
        p = self.ocr("stahni", "german_print")
        self.assertEqual(p.returncode, 2)
        self.assertIn(ocr.ZNAME["german_print"][0], p.stderr)
        self.assertFalse(os.path.exists(td) and any(f.endswith(".part") for f in os.listdir(td)))
        self.assertNotIn("Traceback", p.stderr)

    def _prikaz(self):
        with open(self.path("pracovni", "fake_ocr.py"), "w", encoding="utf-8") as f:
            f.write(FAKE_OCR)
        sablona = [sys.executable, "-I", self.path("pracovni", "fake_ocr.py"), "{slozka}", "{vystup}", "{model}"]
        self.assertEqual(self.ocr("nastav", "prikaz", json.dumps(sablona)).returncode, 0)
        with open(self.path("dokumenty", "a.jpg"), "w") as f:
            f.write("sken")

    def test_zamek_druhy_beh_odmitne(self):
        self._prikaz()
        cil = self.path("pracovni", "ocr", "a")
        pripraven, konec = os.path.join(self.tmp, "pripraven"), os.path.join(self.tmp, "konec")
        with open(os.path.join(self.tmp, "drz.py"), "w", encoding="utf-8") as f:
            f.write(DRZ_ZAMEK)
        a = subprocess.Popen([sys.executable, "-I", os.path.join(self.tmp, "drz.py"), self.path("tools"), cil,
                              pripraven, konec])
        try:
            for _ in range(200):
                if os.path.exists(pripraven):
                    break
                time.sleep(0.05)
            zacatek = time.time()
            p = self.ocr("dokumenty/a.jpg", "--vystup", cil)
            self.assertLess(time.time() - zacatek, 5)
            self.assertEqual(p.returncode, 1)
            self.assertIn("jiný běh", p.stderr)
            self.assertEqual(sorted(os.listdir(cil)), [".ocr.lock"])
            # po kill procesu A je zámek volný (systém ho uvolní)
            a.send_signal(signal.SIGKILL) if hasattr(signal, "SIGKILL") else a.kill()
            a.wait(10)
            p = self.ocr("dokumenty/a.jpg", "--vystup", cil)
            self.assertEqual(p.returncode, 0, p.stderr)
            with open(os.path.join(cil, "a.txt"), encoding="utf-8") as f:
                self.assertEqual(f.read(), "text p0001.jpg\n")
        finally:
            open(konec, "w").close()
            if a.poll() is None:
                a.kill()
            a.wait(10)

    def test_zamek_po_skonceni_volny(self):
        self._prikaz()
        cil = self.path("pracovni", "ocr", "a")
        pripraven, konec = os.path.join(self.tmp, "pripraven"), os.path.join(self.tmp, "konec")
        with open(os.path.join(self.tmp, "drz.py"), "w", encoding="utf-8") as f:
            f.write(DRZ_ZAMEK)
        a = subprocess.Popen([sys.executable, "-I", os.path.join(self.tmp, "drz.py"), self.path("tools"), cil,
                              pripraven, konec])
        for _ in range(200):
            if os.path.exists(pripraven):
                break
            time.sleep(0.05)
        open(konec, "w").close()   # A skončí normálně
        a.wait(10)
        p = self.ocr("dokumenty/a.jpg")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("jiný běh", p.stderr)


if __name__ == "__main__":
    unittest.main()
