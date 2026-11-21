"""Testy ocr.py (OCR vlastních skenů Tesseractem). Bez internetu, bez Tesseractu a Poppleru: programy nahrazuje
FalesnySpust (ocr.spust), hledání programů ocr.najdi. CLI testy běží v dočasném projektu (novy_projekt.py)."""
import contextlib, hashlib, io, json, os, re, shutil, signal, subprocess, sys, tempfile, time, unittest
from unittest import mock

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(KOREN, "skills", "dejiny-domu")
DATA = os.path.join(KOREN, "tests", "data")
sys.path.insert(0, os.path.join(SKILL, "tools"))
import ocr  # noqa: E402
PUVODNI_NAJDI = ocr.najdi

TIFF1 = os.path.join(DATA, "ocr_jedna.tif")
TIFF2 = os.path.join(DATA, "ocr_vicestrankovy.tif")


def cti_soubor(p, mod="r"):
    with open(p, mod, **({} if "b" in mod else {"encoding": "utf-8"})) as f:
        return f.read()


class FalesnySpust:
    """Náhrada tesseract / pdftoppm / pdfinfo / vlastního příkazu („fakeocr“)."""

    def __init__(self, sysdir):
        self.sysdir = sysdir
        self.volani = []
        self.selhat = set()      # jména obrázků (bez přípony), na kterých tesseract selže
        self.prikaz = None       # funkce(argv) -> návratový kód

    def __call__(self, argv, **kw):
        self.volani.append(list(argv))
        ok = lambda out=b"", err=b"", rc=0: subprocess.CompletedProcess(argv, rc, out, err)
        p = os.path.basename(argv[0])
        if p == "fakeocr":
            return ok(rc=self.prikaz(argv))
        if p == "tesseract":
            if argv[1:] == ["--version"]:
                return ok(b"tesseract 5.5.4\n leptonica-1.87.0\n")
            if argv[-1] == "--list-langs":
                d = argv[2] if argv[1] == "--tessdata-dir" else self.sysdir
                langs = sorted(f[:-12] for f in os.listdir(d) if f.endswith(".traineddata"))
                return ok(("List of available languages in \"%s/\" (%d):\n%s\n" % (d, len(langs), "\n".join(langs)))
                          .encode())
            obr = argv[-4]
            jmeno = os.path.splitext(os.path.basename(obr))[0]
            if jmeno in self.selhat:
                return ok(err=b"Error in pixReadStream", rc=1)
            with open(obr, encoding="utf-8") as f:
                obsah = f.read().strip()
            return ok(f"Menſch {obsah} {argv[-1]}\r\n\f".encode())
        if p == "pdftoppm":
            if argv[1:] == ["-v"]:
                return ok(err=b"pdftoppm version 26.11.0\n")
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
        spatne = [{"prikaz": "ocr {slozka} {vystup}"}, {"prikaz": []}, {"prikaz": ["ocr", "{vystup}"]},
                  {"prikaz": ["ocr", "{slozka}"]}, {"prikaz": ["ocr", "{slozka}", "{vystup}", "{neznamy}"]},
                  {"davka": 0}, {"davka": "10"}, {"davka": True}, {"dpi": 50}, {"soubezne": 0}, {"dlouhe_s": "x"},
                  {"stare_znaky": "x"}, {"stare_znaky": "s"}, {"dlouhe_s": "s", "stare_znaky": "ponechat"},
                  {"prikaz_verze": ""}, {"prikaz_verze": 5}, {"prikaz_verze": "x" * 101}, {"tessdata": 3}, []]
        for d in spatne:
            self.assertTrue(ocr.over_nastaveni(d)[0], d)
        dobre = {"model": "german_print+ces", "stare_znaky": "ponechat", "prikaz": ["~/ocr", "{slozka}", "--out={vystup}",
                 "-l", "{model}"], "prikaz_verze": "ocr 2026-11-20", "davka": 10000, "soubezne": 64, "dpi": 72,
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
            ocr.prikaz_nastav(p, "prikaz", '["ocr", "{slozka}", "{vystup}"]')
        d = json.loads(cti_soubor(p))
        self.assertEqual(d, {"model": "ces", "x_vlastni": 1, "davka": 5, "prikaz": ["ocr", "{slozka}", "{vystup}"]})
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
        rc, out, _ = self.spust("stav")
        self.assertEqual(rc, 2)
        self.assertIn("tesseract: CHYBÍ", out)

    def test_windows_program_files(self):
        env = {"ProgramFiles": r"C:\Program Files", "LOCALAPPDATA": r"C:\Users\x\AppData\Local"}
        tess = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        najdi = PUVODNI_NAJDI   # Zaklad ocr.najdi nahrazuje
        self.assertEqual(najdi("tesseract", "win32", env, which=lambda p: None, existuje=lambda p: p == tess,
                               hledej=lambda v: []), tess)
        pop = [r"C:\Users\x\AppData\Local\Microsoft\WinGet\Packages\oschwartz10612.Poppler_Microsoft.Winget.Source_8wekyb3d8bbwe\poppler-25.07.0\Library\bin\pdftoppm.exe",
               r"C:\Users\x\AppData\Local\Microsoft\WinGet\Packages\oschwartz10612.Poppler_Microsoft.Winget.Source_8wekyb3d8bbwe\poppler-26.09.0\Library\bin\pdftoppm.exe"]
        vzory = []
        hledej = lambda v: (vzory.append(v), pop if v.startswith(env["LOCALAPPDATA"]) else [])[1]
        self.assertEqual(najdi("pdftoppm", "win32", env, which=lambda p: None, existuje=lambda p: False,
                               hledej=hledej), pop[1])
        self.assertTrue(any(r"WinGet\Packages\oschwartz10612.Poppler*" in v for v in vzory))
        links = r"C:\Users\x\AppData\Local\Microsoft\WinGet\Links\pdfinfo.exe"
        self.assertEqual(najdi("pdfinfo", "win32", env, which=lambda p: None, existuje=lambda p: p == links,
                               hledej=lambda v: []), links)
        self.assertIsNone(najdi("tesseract", "linux", env, which=lambda p: None, existuje=lambda p: True,
                                hledej=lambda v: ["x"]))
        self.assertEqual(najdi("tesseract", "win32", env, which=lambda p: "C:\\bin\\tesseract.exe"),
                         "C:\\bin\\tesseract.exe")

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
        self.assertEqual(self.manifest("kniha")["modely_sha256"]["german_print"],
                         hashlib.sha256(b"systemovy").hexdigest())
        self.assertEqual(os.listdir(prazdna), [])

    def test_model_jen_v_uzivatelske(self):
        self.assertEqual(self.spust(self.pdf(1))[0], 0)
        a = self.tess_argv()[0]
        self.assertEqual(a[a.index("--tessdata-dir") + 1], self.uziv)
        self.assertTrue(self.manifest("kniha")["model_overen"])

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

    def test_tiff_vicestrankovy_odmitne(self):
        d = os.path.join(self.tmp, "dokumenty", "tif")
        os.makedirs(d)
        shutil.copy(TIFF1, os.path.join(d, "a.tif"))
        shutil.copy(TIFF2, os.path.join(d, "b.tif"))
        rc, _, err = self.spust(d)
        self.assertEqual(rc, 1)
        self.assertIn("magick", err)
        self.assertEqual(self.fake.volani, [])
        rc, _, err = self.spust(TIFF2)
        self.assertEqual(rc, 1)
        self.assertIn("víc snímků", err)
        self.assertEqual(ocr.jeden_snimek_tiff(TIFF1), (True, ""))
        for obsah, proc in ((b"II*\x00", "useknutá hlavička"), (b"", "useknutá hlavička"),
                            (b"MM\x00+\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00\x10", "BigTIFF"),
                            (b"GIF89a\x00\x00", "není to TIFF")):
            p = os.path.join(self.tmp, "x.tif")
            with open(p, "wb") as f:
                f.write(obsah)
            self.assertEqual(ocr.jeden_snimek_tiff(p), (False, proc) if proc != "BigTIFF" else
                             (False, "BigTIFF není podporovaný"), obsah)

    def test_tiff_poskozeny(self):
        with open(TIFF1, "rb") as f:
            puvodni = f.read()
        ifd = int.from_bytes(puvodni[4:8], "little")
        pocet = int.from_bytes(puvodni[ifd:ifd + 2], "little")
        dalsi = ifd + 2 + pocet * 12
        varianty = {   # název: (bajty, čekaný důvod)
            "cyklus": (puvodni[:dalsi] + ifd.to_bytes(4, "little") + puvodni[dalsi + 4:], "víc snímků (stran)"),
            "ifd za koncem": (puvodni[:4] + (len(puvodni) + 10).to_bytes(4, "little") + puvodni[8:],
                              "první IFD je mimo soubor"),
            "počet přesahuje": (puvodni[:ifd] + (0xFFFF).to_bytes(2, "little") + puvodni[ifd + 2:], "useknutá IFD"),
            "useknutý v IFD": (puvodni[:ifd + 2 + 5 * 12], "useknutá IFD"),
        }
        for nazev, (obsah, cekany) in varianty.items():
            p = os.path.join(self.tmp, "poskozeny.tif")
            with open(p, "wb") as f:
                f.write(obsah)
            zacatek = time.time()
            ok, proc = ocr.jeden_snimek_tiff(p)
            self.assertFalse(ok, nazev)
            self.assertEqual(proc, cekany, nazev)
            self.assertLess(time.time() - zacatek, 1, nazev)

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
        m = self.manifest("kniha")
        self.assertEqual((m["zdroj"]["druh"], m["zdroj"]["stran"], m["model"], m["model_overen"], m["stare_znaky"],
                          m["cesta"], m["render"]["dpi"]),
                         ("pdf", 3, "german_print", True, "zjednodusit", {"druh": "tesseract", "verze": "5.5.4"}, 300))
        self.assertNotIn("dlouhe_s", m)
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

    def test_zmeneny_vstup_stejne_jmeno_a_stran(self):
        self.assertEqual(self.spust(self.pdf(3))[0], 0)
        self.fake.volani.clear()
        rc, _, err = self.spust(self.pdf(3, verze="v2"))
        self.assertEqual(rc, 1)
        self.assertIn("zdroj.sha256", err)
        self.assertEqual(self.fake.tesseract_obrazky(), [])

    def test_zmeneny_obrazek_hotove_strany(self):
        d = self.obrazky("a-001.jpg", "a-002.jpg")
        self.assertEqual(self.spust(d)[0], 0)
        with open(os.path.join(d, "a-001.jpg"), "w") as f:
            f.write("jiný sken")
        rc, _, err = self.spust(d)
        self.assertEqual(rc, 1)
        self.assertIn("obrazky.a-001", err)

    def test_novy_obrazek_ve_slozce(self):
        d = self.obrazky("a-001.jpg", "a-002.jpg")
        self.assertEqual(self.spust(d)[0], 0)
        self.obrazky("a-003.jpg")
        self.fake.volani.clear()
        self.assertEqual(self.spust(d)[0], 0)
        self.assertEqual(self.fake.tesseract_obrazky(), ["a-003"])
        self.assertEqual(sorted(self.manifest("skeny")["obrazky"]), ["a-001", "a-002", "a-003"])

    def test_zmenene_bajty_modelu(self):
        self.assertEqual(self.spust(self.pdf(2))[0], 0)
        self.model(self.uziv, "german_print", "jiná verze modelu")
        rc, _, err = self.spust(self.pdf(2))
        self.assertEqual(rc, 1)
        self.assertIn("modely_sha256.german_print", err)

    def test_jine_dpi(self):
        self.assertEqual(self.spust(self.pdf(2))[0], 0)
        self.nastav({"tessdata": self.uziv, "dpi": 200})
        rc, _, err = self.spust(self.pdf(2))
        self.assertEqual(rc, 1)
        self.assertIn("render.dpi", err)

    def test_jine_stare_znaky(self):
        self.assertEqual(self.spust(self.pdf(2))[0], 0)
        self.nastav({"tessdata": self.uziv, "stare_znaky": "ponechat"})
        rc, _, err = self.spust(self.pdf(2))
        self.assertEqual(rc, 1)
        self.assertIn("liší se: stare_znaky", err)

    def stary_vystup(self, dlouhe_s, verze):
        """Hotové 2 ze 3 stran a manifest ve tvaru před stare_znaky (pole dlouhe_s)."""
        self.nastav({"tessdata": self.uziv, "stare_znaky": Z[dlouhe_s]})
        self.assertEqual(self.spust(self.pdf(3, verze=verze), "--strany", "1-2")[0], 0)
        m = self.manifest("kniha")
        del m["stare_znaky"]
        m["dlouhe_s"] = dlouhe_s
        with open(self.vystup("kniha", "ocr_manifest.json"), "w", encoding="utf-8") as f:
            json.dump(m, f)

    def test_o3_stary_manifest_dodela(self):
        """O3: starý výstup dlouhe_s se dodělá stejným převodem; výslovně jiná hodnota se odmítne."""
        verze = "v1 \ua75b \u017f"
        for dlouhe_s, nastaveni, cekam in (("s", {}, "jen_s"), ("s", {"dlouhe_s": "s"}, "jen_s"),
                                           ("ponechat", {}, "ponechat")):
            with self.subTest(dlouhe_s=dlouhe_s, nastaveni=nastaveni):
                shutil.rmtree(self.vystup("kniha"), ignore_errors=True)
                self.stary_vystup(dlouhe_s, verze)
                self.nastav(dict(nastaveni, tessdata=self.uziv))
                rc, _, err = self.spust(self.pdf(3, verze=verze))
                self.assertEqual(rc, 0, err)
                if not nastaveni:
                    self.assertIn(f"staré znaky: {cekam} podle hotových stran", err)
                self.assertEqual(self.manifest("kniha")["stare_znaky"], cekam)
                self.assertNotIn("dlouhe_s", self.manifest("kniha"))
                text = self.cti("kniha", "s0003.txt")
                self.assertIn("\ua75b", text)   # ꝛ zůstane (jen_s i ponechat), žádné tiché povýšení
                self.assertEqual("\u017f" in text, cekam == "ponechat")
                self.assertEqual(self.spust(self.pdf(3, verze=verze))[0], 0)   # druhé dodělání
        shutil.rmtree(self.vystup("kniha"), ignore_errors=True)
        self.stary_vystup("s", verze)
        self.nastav({"tessdata": self.uziv, "stare_znaky": "zjednodusit"})
        pred = sorted(os.listdir(self.vystup("kniha")))
        rc, _, err = self.spust(self.pdf(3, verze=verze))
        self.assertEqual(rc, 1)
        self.assertIn("liší se: stare_znaky", err)
        self.assertEqual(sorted(os.listdir(self.vystup("kniha"))), pred)
        # nový manifest jen_s + výslovné zjednodusit při druhém dodělání
        shutil.rmtree(self.vystup("kniha"), ignore_errors=True)
        self.nastav({"tessdata": self.uziv, "stare_znaky": "jen_s"})
        self.assertEqual(self.spust(self.pdf(3, verze=verze), "--strany", "1-2")[0], 0)
        self.nastav({"tessdata": self.uziv, "stare_znaky": "zjednodusit"})
        rc, _, err = self.spust(self.pdf(3, verze=verze))
        self.assertEqual(rc, 1)
        self.assertIn("liší se: stare_znaky", err)

    def test_jiny_model(self):
        self.assertEqual(self.spust(self.pdf(2))[0], 0)
        self.model(self.uziv, "frak2021")
        pred = {f: os.path.getmtime(self.vystup("kniha", f)) for f in os.listdir(self.vystup("kniha"))}
        rc, _, err = self.spust(self.pdf(2), "--model", "frak2021")
        self.assertEqual(rc, 1)
        self.assertIn("model,", err)
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


class TestPrikaz(Zaklad):
    SABLONA = ["fakeocr", "{slozka}", "--lang", "{model}", "--out", "{vystup}"]

    def setUp(self):
        super().setUp()
        self.davky = []
        self.fake.prikaz = self.soubory

    def nastav_prikaz(self, sablona=None, **kw):
        self.nastav(dict({"tessdata": self.uziv, "prikaz": sablona or self.SABLONA}, **kw))

    def _davka(self, argv):
        slozka, vystup = argv[1], argv[argv.index("--out") + 1] if "--out" in argv else argv[2]
        obr = sorted(os.listdir(slozka))
        self.davky.append([os.path.splitext(f)[0] for f in obr])
        return slozka, vystup, obr

    def soubory(self, argv):      # tvar (a): <strana>.txt, zapsané v obráceném pořadí
        slozka, vystup, obr = self._davka(argv)
        for f in reversed(obr):
            with open(os.path.join(slozka, f), encoding="utf-8") as g, \
                    open(os.path.join(vystup, os.path.splitext(f)[0] + ".txt"), "w", encoding="utf-8") as h:
                h.write("P " + g.read() + "\n")
        return 0

    def spojeny(self, argv):      # tvar (b): jeden <slozka>.txt, každá strana končí \f
        slozka, vystup, obr = self._davka(argv)
        texty = [cti_soubor(os.path.join(slozka, f)) + "\n\f" for f in obr]
        with open(os.path.join(vystup, os.path.basename(slozka) + ".txt"), "w", encoding="utf-8") as h:
            h.write("".join(texty))
        return 0

    def test_prikaz_argv(self):
        a = ocr.prikaz_argv(["~/bin/ocr", "{slozka}", "--out={vystup}", "-l", "{model}", "~/x"], "/t/d", "/t/v", "ces")
        self.assertEqual(a, [os.path.expanduser("~/bin/ocr"), "/t/d", "--out=/t/v", "-l", "ces", "~/x"])

    def test_prikaz_tvar_a(self):
        self.nastav_prikaz()
        self.assertEqual(self.spust(self.pdf(3))[0], 0)
        for i in (1, 2, 3):
            self.assertEqual(self.cti("kniha", f"s000{i}.txt"), f"P strana {i} z %PDF n=3 v1\n")
        m = self.manifest("kniha")
        self.assertEqual((m["model"], m["model_overen"], m["modely_sha256"], m["vystup_prikazu"], m["cesta"]["druh"]),
                         ("german_print", False, None, None, "prikaz"))
        self.assertEqual(self.fake.tesseract_obrazky(), [])
        v = os.path.join(self.tmp, "v")
        for soubory, chyba in ((["a", "b"], "chybí c"), (["a", "b", "c", "x"], "cizí x"), (["a", "b", "x"], "x")):
            shutil.rmtree(v, ignore_errors=True)
            os.makedirs(v)
            for s in soubory:
                open(os.path.join(v, s + ".txt"), "w").close()
            with self.assertRaises(ocr.Chyba) as c:
                ocr.vysledky_davky(v, ["a", "b", "c"], "ocr_davka_1")
            self.assertIn(chyba, str(c.exception))

    def test_prikaz_tvar_b(self):
        v = os.path.join(self.tmp, "v")
        os.makedirs(v)

        def davka(text):
            with open(os.path.join(v, "ocr_davka_1.txt"), "w", encoding="utf-8") as f:
                f.write(text)
            return ocr.vysledky_davky(v, ["x1", "x2", "x3"], "ocr_davka_1")
        self.assertEqual(davka("\fb\f\f"), ({"x1": "", "x2": "b", "x3": ""}, True))
        self.assertEqual(davka("a\fb\fc\f\n "), ({"x1": "a", "x2": "b", "x3": "c"}, True))
        for spatne in ("a\fb", "a\fb\fc\fd\f", "a\fb\fc\fX"):
            with self.assertRaises(ocr.Chyba):
                davka(spatne)
        self.fake.prikaz = self.spojeny
        self.nastav_prikaz()
        rc, _, err = self.spust(self.pdf(3))
        self.assertEqual(rc, 0)
        self.assertIn("pořadí stran v něm nelze ověřit", err)
        self.assertEqual(self.manifest("kniha")["vystup_prikazu"], "spojeny")
        self.assertEqual(self.cti("kniha", "s0002.txt"), "strana 2 z %PDF n=3 v1\n")

    def test_prikaz_bez_model_neovereny(self):
        self.nastav_prikaz(["fakeocr", "{slozka}", "{vystup}"])
        rc, _, err = self.spust(self.pdf(1))
        self.assertEqual(rc, 0)
        self.assertIn("neověřený", err)
        m = self.manifest("kniha")
        self.assertEqual((m["model"], m["model_overen"]), ("neověřený", False))

    def test_prikaz_a_vestaveny_nemichat(self):
        self.assertEqual(self.spust(self.pdf(2))[0], 0)
        self.nastav_prikaz(prikaz_verze="ocr 1")
        rc, _, err = self.spust(self.pdf(2))
        self.assertEqual(rc, 1)
        self.assertIn("cesta", err)
        self.assertIn("model_overen", err)
        self.assertEqual(self.davky, [])
        self.assertEqual(self.spust(self.pdf(2), "--vystup", self.vystup("k2"))[0], 0)
        self.nastav({"tessdata": self.uziv})
        rc, _, err = self.spust(self.pdf(2), "--vystup", self.vystup("k2"))
        self.assertEqual(rc, 1)
        self.assertIn("cesta", err)

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
        self.nastav_prikaz(davka=2, prikaz_verze="v1")   # dodělat napříč běhy jde jen s prikaz_verze
        rc, _, err = self.spust(self.pdf(5))
        self.assertEqual(rc, 1)
        self.assertIn("cesta.verze", err)
        shutil.rmtree(self.vystup("kniha"))
        self.assertEqual(self.spust(self.pdf(5))[0], 0)
        self.assertEqual(self.davky, [["s0001", "s0002"], ["s0003", "s0004"], ["s0005"]])

    def test_prikaz_bez_verze_nedodela(self):
        self.nastav_prikaz()
        self.assertEqual(self.spust(self.pdf(3))[0], 0)
        os.remove(self.vystup("kniha", "s0002.txt"))
        self.davky.clear()
        rc, _, err = self.spust(self.pdf(3))
        self.assertEqual(rc, 1)
        self.assertIn("prikaz_verze", err)
        self.assertEqual(self.davky, [])
        self.nastav_prikaz(prikaz_verze="ocr 2026-11-20")
        self.assertEqual(self.spust(self.pdf(3), "--vystup", self.vystup("k2"))[0], 0)
        os.remove(self.vystup("k2", "s0002.txt"))
        self.davky.clear()
        self.assertEqual(self.spust(self.pdf(3), "--vystup", self.vystup("k2"))[0], 0)
        self.assertEqual(self.davky, [["s0002"]])
        self.nastav_prikaz(prikaz_verze="ocr 2026-12-01")
        os.remove(self.vystup("k2", "s0003.txt"))
        rc, _, err = self.spust(self.pdf(3), "--vystup", self.vystup("k2"))
        self.assertEqual(rc, 1)
        self.assertIn("cesta.verze", err)


FAKE_OCR = """import os, sys
slozka, vystup = sys.argv[1], sys.argv[2]
for f in sorted(os.listdir(slozka)):
    with open(os.path.join(vystup, os.path.splitext(f)[0] + ".txt"), "w", encoding="utf-8") as g:
        g.write("text " + f + "\\n")
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
        sablona = [sys.executable, "-I", self.path("pracovni", "fake_ocr.py"), "{slozka}", "{vystup}"]
        self.assertEqual(self.ocr("nastav", "prikaz", json.dumps(sablona)).returncode, 0)
        shutil.copy(TIFF1, self.path("dokumenty", "a.tif"))

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
            p = self.ocr("dokumenty/a.tif", "--vystup", cil)
            self.assertLess(time.time() - zacatek, 5)
            self.assertEqual(p.returncode, 1)
            self.assertIn("jiný běh", p.stderr)
            self.assertEqual(sorted(os.listdir(cil)), [".ocr.lock"])
            # po kill procesu A je zámek volný (systém ho uvolní)
            a.send_signal(signal.SIGKILL) if hasattr(signal, "SIGKILL") else a.kill()
            a.wait(10)
            p = self.ocr("dokumenty/a.tif", "--vystup", cil)
            self.assertEqual(p.returncode, 0, p.stderr)
            with open(os.path.join(cil, "a.txt"), encoding="utf-8") as f:
                self.assertEqual(f.read(), "text a.tif\n")
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
        p = self.ocr("dokumenty/a.tif")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("jiný běh", p.stderr)


if __name__ == "__main__":
    unittest.main()
