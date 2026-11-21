"""OCR vlastních skenů Tesseractem: z PDF, obrázku nebo složky obrázků text po stranách do pracovni/ocr/<dokument>/.
Postup, volba modelu, staré znaky (ſ, ꝛ, aͤ) a vlastní příkaz: reference/ocr.md.

Použití (z kořene projektu):
  ocr.py <vstup>… [--model M] [--vystup SLOŽKA] [--strany A-B]
      vstup = PDF (potřebuje Poppler: pdftoppm, pdfinfo), obrázek (.jpg .jpeg .png .tif .tiff) nebo složka obrázků
      (pořadí stran = abecední pořadí jmen). Text: <strana>.txt (PDF s0001.txt…, obrázek a-001.jpg → a-001.txt).
      Opakované spuštění dodělá jen chybějící strany; ocr_manifest.json hlídá, že se nemíchají různé vstupy,
      modely ani cesty OCR (jinak exit 1 s výpisem rozdílných polí).
  ocr.py stav [--model M]          co chybí (Tesseract, Poppler, model) a návod pro tento systém; bez sítě
  ocr.py modely                    známé modely a kde jsou nainstalované
  ocr.py nastaveni                 platné nastavení (data/ocr.json a výchozí hodnoty)
  ocr.py nastav <klíč> <hodnota|vychozi>
      klíče: model, stare_znaky (zjednodusit|ponechat|jen_s), prikaz (JSON seznam), davka,
      soubezne, dpi, tessdata; zastaralé dlouhe_s (s|ponechat) se zapíše jako stare_znaky
  ocr.py stahni <model>…           stáhne známý model (jen po souhlasu uživatele; jen přes slusne.py)
Exit: 0 vše hotovo, 1 selhání nebo nesoulad, 2 něco není nainstalované.
Samotné OCR nic nestahuje.
"""
import concurrent.futures, contextlib, glob, hashlib, itertools, json, ntpath, os, re, shutil, struct, subprocess, sys, tempfile

for _s in (sys.stdout, sys.stderr):   # UTF-8 výstup i na Windows bez -X utf8 (cp1250 neumí třeba „→“)
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I nepřidá složku skriptu sama
try:   # stahuje se jen přes slusne.py (limit, robots.txt, podmínky); bez něj stahování odmítne (fail-closed)
    import slusne
    slusne.instaluj()
except ImportError:
    slusne = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRIPONY = (".jpg", ".jpeg", ".png", ".tif", ".tiff")
MODEL_RE = re.compile(r"^[A-Za-z0-9_]+(\+[A-Za-z0-9_]+)*$")
ZASTUPCE_RE = re.compile(r"\{([^{}]*)\}")
ZASTUPCI = ("slozka", "vystup", "model")
MANIFEST = "ocr_manifest.json"
ZAMEK = ".ocr.lock"
MIN_MODEL = 100_000   # menší stažený soubor není model (chybová stránka)
PRO_UZIVATELE = "příkaz pro uživatele (spustí ho sám, v Claude Code `! sudo apt install …`; Claude sudo nespouští)"
PO_SOUHLASU = "(po souhlasu smí Claude spustit)"

UBMA = "https://ub-backup.bib.uni-mannheim.de/~stweil/tesstrain"
BEST = "https://github.com/tesseract-ocr/tessdata_best/raw/e12c65a915945e4c28e237a9b52bc4a8f39a0cec"   # připnutý commit
ZNAME = {   # model: (url, sha256, MB, popis)
    "german_print": (f"{UBMA}/german_print/tessdata_best/german_print_0.877_1254744_7309067.traineddata",
                     "15facd4c76266dd8518452665f5a5ffdfe17423c922d7afffc739855faa50d94", 3.5,
                     "německý tisk 18.–20. stol., fraktura i stará antikva (UB Mannheim) – výchozí"),
    "frak2021": (f"{UBMA}/frak2021/tessdata_fast/frak2021_0.905.traineddata",
                 "e0c3bc0762c45a243214b8954375cef2c908c632dd1285085076c2e61cf18665", 5.1,
                 "německá fraktura 16.–20. stol. (UB Mannheim 2021)"),
    "deu_latf": (f"{BEST}/deu_latf.traineddata",
                 "429b8c33d37e1a4823a2bb082a644ff13e252f735b7945e08a518d22ddcc459e", 12.9,
                 "německá fraktura (Google, dřív frk) – výrazně horší než german_print"),
    "deu": (f"{BEST}/deu.traineddata", "8407331d6aa0229dc927685c01a7938fc5a641d1a9524f74838cdac599f0d06e", 8.6,
            "němčina, antikva"),
    "ces": (f"{BEST}/ces.traineddata", "d821773116d3c4e0360ea750066436c60ae45af02c39da3a840a543d761b3f41", 10.9,
            "čeština, antikva (čeština ve fraktuře: german_print+ces)"),
    "lat": (f"{BEST}/lat.traineddata", "60054dd32ac03ebd9b4f87d0665bd491a7ffe0d3ee99ceb91aefaf348b65e94f", 9.7,
            "latina"),
    "eng": (f"{BEST}/eng.traineddata", "8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba", 15.4,
            "angličtina"),
    "pol": (f"{BEST}/pol.traineddata", "e80cc4cefbdface06e9223f43f089556b9dcf104020fbc0a200f6863c57d4405", 12.0,
            "polština"),
}
POLE = ("model", "stare_znaky", "dlouhe_s", "prikaz", "davka", "soubezne", "dpi", "tessdata")
# stare_znaky: zjednodusit = ſ → s, ꝛ → r, aͤ oͤ uͤ → ä ö ü (výchozí); ponechat = věrný přepis; jen_s = jen ſ → s
# (dřívější dlouhe_s: s; staré výstupy se dodělávají stejně). Zastaralé dlouhe_s se převádí: s → jen_s.
STARE_ZNAKY = ("zjednodusit", "ponechat", "jen_s")
Z_DLOUHE_S = {"s": "jen_s", "ponechat": "ponechat"}
ROZSAHY = {"davka": (1, 10000), "soubezne": (1, 64), "dpi": (72, 1200)}


class Chyba(Exception):
    """Ukončení s hláškou a kódem (1 selhání/nesoulad, 2 nenainstalované)."""

    def __init__(self, zprava, kod=1):
        super().__init__(zprava)
        self.kod = kod


def spust(argv, **kw):
    """Jediné místo, kde nástroj spouští programy (testy ho nahrazují)."""
    return subprocess.run(argv, **kw)


def spust_prikaz(argv):
    """Vlastní příkaz uživatele. Po Ctrl-C počká, až příkaz sám skončí (terminál mu přerušení poslal taky; další
    Ctrl-C ho ukončí hned), a teprve pak přerušení pustí dál – jinak by osiřelý proces četl smazanou dávku."""
    proc = subprocess.Popen(argv, cwd=ROOT)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        print("Přerušeno – čekám, až vlastní příkaz skončí (další Ctrl-C ho ukončí hned).", file=sys.stderr, flush=True)
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.kill()
            proc.wait()
        raise


def vychozi_soubezne():
    return max(1, min(4, (os.cpu_count() or 2) // 2))


# --- hledání programů a návody --------------------------------------------------------------------------------

def najdi(program, platform=None, env=None, which=shutil.which, existuje=os.path.isfile, hledej=glob.glob):
    """Cesta k programu: PATH, na Windows i obvyklé složky instalátorů (bez restartu po instalaci)."""
    platform = sys.platform if platform is None else platform
    env = os.environ if env is None else env
    p = which(program)
    if p:
        return p
    if platform != "win32":
        return None
    exe = program + ".exe"
    j = ntpath.join
    kandidati, vzory = [], []
    for pf in (env.get("ProgramFiles"), env.get("ProgramFiles(x86)"), r"C:\Program Files"):
        if pf:
            kandidati.append(j(pf, "Tesseract-OCR", exe))
            vzory.append(j(pf, "WinGet", "Packages", "oschwartz10612.Poppler*", "*", "Library", "bin", exe))
    la = env.get("LOCALAPPDATA")
    if la:
        kandidati += [j(la, "Programs", "Tesseract-OCR", exe), j(la, "Microsoft", "WinGet", "Links", exe)]
        vzory.append(j(la, "Microsoft", "WinGet", "Packages", "oschwartz10612.Poppler*", "*", "Library", "bin", exe))
    for k in kandidati:
        if existuje(k):
            return k
    for v in vzory:
        nalez = sorted(hledej(v))
        if nalez:
            return nalez[-1]   # nejnovější verze (poppler-26.09.0 > poppler-25.07.0)
    return None


def navod(co, platform=None):
    """Návod na instalaci Tesseractu nebo Poppleru pro daný systém. brew/winget smí Claude spustit po souhlasu,
    sudo nikdy (hook hlidac.py ho zamítne) – na Linuxu je to příkaz pro uživatele."""
    platform = sys.platform if platform is None else platform
    if platform == "darwin":
        return {"tesseract": f"macOS {PO_SOUHLASU}: brew install tesseract   (Homebrew: https://brew.sh)",
                "poppler": f"macOS {PO_SOUHLASU}: brew install poppler"}[co]
    if platform == "win32":
        return {"tesseract": f"Windows {PO_SOUHLASU}: winget install --id UB-Mannheim.TesseractOCR -e   (dá 5.4.0; novější instalátor "
                             "na https://github.com/UB-Mannheim/tesseract/wiki). PATH se nenastaví, ocr.py ho najde "
                             "v Program Files i bez restartu.",
                "poppler": f"Windows {PO_SOUHLASU}: winget install --id oschwartz10612.Poppler -e   (přenosný balíček; ocr.py ho "
                           "najde ve WinGet\\Packages i bez restartu)"}[co]
    return {"tesseract": f"Linux, {PRO_UZIVATELE}: sudo apt install tesseract-ocr   (Fedora: sudo dnf install tesseract)",
            "poppler": f"Linux, {PRO_UZIVATELE}: sudo apt install poppler-utils   (Fedora: sudo dnf install poppler-utils)"}[co]


def puvod(model):
    """Odkud model je a pod jakou licencí (odvozeno z adresy v ZNAME)."""
    if "uni-mannheim" in ZNAME[model][0]:
        return "server UB Mannheim (ne GitHub), licence neuvedená"
    return "tessdata_best na GitHubu, Apache-2.0"


def _vystup(r):
    return ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")


def verze_tesseractu(tess):
    r = spust([tess, "--version"], capture_output=True)
    m = re.search(r"tesseract\s+v?(\d+(?:\.\d+)*)", _vystup(r))
    return m.group(1) if m else None


def verze_poppleru(pdftoppm):
    r = spust([pdftoppm, "-v"], capture_output=True)
    m = re.search(r"version\s+(\S+)", _vystup(r))
    return m.group(1) if m else "?"


def rozbor_jazyku(text):
    """Výstup `tesseract --list-langs` → (složka|None, [modely]). Tesseract 4 složku neuvádí."""
    radky = [r.strip() for r in text.replace("\r\n", "\n").split("\n") if r.strip()]
    for i, r in enumerate(radky):
        if r.startswith("List of available languages"):
            m = re.search(r'"(.+)"', r)
            jazyky = [x for x in radky[i + 1:] if re.match(r"^[A-Za-z0-9_]+$", x)]
            return (m.group(1) if m else None), jazyky
    return None, []


def jazyky(tess, tessdata=None):
    argv = [tess] + (["--tessdata-dir", tessdata] if tessdata else []) + ["--list-langs"]
    return rozbor_jazyku(_vystup(spust(argv, capture_output=True)))


def systemova_slozka(slozka, env=None):
    """Složka systémových modelů; Tesseract 4 ji v --list-langs nevypíše, pak obvyklá místa."""
    if slozka:
        return slozka.rstrip("/\\") or slozka
    env = os.environ if env is None else env
    kandidati = []
    if env.get("TESSDATA_PREFIX"):   # rodič složky tessdata, nebo (starší zvyk) přímo ona
        kandidati += [os.path.join(env["TESSDATA_PREFIX"], "tessdata"), env["TESSDATA_PREFIX"]]
    kandidati += ["/usr/share/tesseract-ocr/5/tessdata", "/usr/share/tesseract-ocr/4.00/tessdata",
                  "/usr/share/tessdata", "/usr/local/share/tessdata", "/opt/homebrew/share/tessdata"]
    for k in kandidati:
        if glob.glob(os.path.join(k, "*.traineddata")):
            return k
    return None


# --- modely ---------------------------------------------------------------------------------------------------

def rozloz_model(model):
    if not isinstance(model, str) or not MODEL_RE.match(model):
        raise Chyba(f"Neplatný název modelu {json.dumps(model, ensure_ascii=False)}: jen písmena, číslice a _, "
                    "víc modelů spoj +, např. german_print+ces.")
    return model.split("+")


def uzivatelska_slozka(nastaveni=None, platform=None, env=None):
    """Kam se modely stahují a odkud se berou ty, které systém nemá."""
    platform = sys.platform if platform is None else platform
    env = os.environ if env is None else env
    t = (nastaveni or {}).get("tessdata")
    if t:
        t = os.path.expanduser(t)
        return t if os.path.isabs(t) else os.path.normpath(os.path.join(ROOT, t))
    if platform == "win32":
        return ntpath.join(env.get("LOCALAPPDATA") or os.path.expanduser("~"), "tessdata")
    if env.get("XDG_DATA_HOME"):
        return os.path.join(env["XDG_DATA_HOME"], "tessdata")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "tessdata")


def kde_modely(casti, system, uziv):
    """system = (složka|None, [modely ze --list-langs]); uziv = uživatelská složka.
    Vrací (tessdata_dir|None, {část: cesta}, [chybí], [zkopírovat ze systému]).
    1) všechny části v systému → bez --tessdata-dir; 2) jinak --tessdata-dir uživatelská (části jen v systému se
    zkopírují); 3) co není nikde, chybí."""
    sdir, sjazyky = system
    v_systemu = {c for c in casti if c in sjazyky}
    if len(v_systemu) == len(set(casti)):
        return None, {c: os.path.join(sdir, c + ".traineddata") if sdir else None for c in casti}, [], []
    cesty, chybi, kopie = {}, [], []
    for c in casti:
        u = os.path.join(uziv, c + ".traineddata")
        if os.path.isfile(u):
            cesty[c] = u
        elif c in v_systemu and sdir and os.path.isfile(os.path.join(sdir, c + ".traineddata")):
            cesty[c] = u
            kopie.append(c)
        else:
            chybi.append(c)
    return uziv, cesty, chybi, kopie


def rada_modelu(model, uziv):
    if model in ZNAME:
        return (f"stáhni: python3 -I tools/ocr.py stahni {model} ({str(ZNAME[model][2]).replace('.', ',')} MB, "
                f"{puvod(model)}; jen po souhlasu)")
    return f"skill tento model nezná; soubor {model}.traineddata dej ručně do {uziv}"


def priprav_modely(tess, model, nastaveni, kopirovat=True):
    """Najde (a pro běh zkopíruje) části modelu. Vrací tessdata_dir|None. Chybí → Chyba(kód 2)."""
    casti = rozloz_model(model)
    sdir, sjaz = jazyky(tess)
    sdir = systemova_slozka(sdir)
    uziv = uzivatelska_slozka(nastaveni)
    tdir, cesty, chybi, kopie = kde_modely(casti, (sdir, sjaz), uziv)
    if chybi:
        raise Chyba("Chybí model: " + "; ".join(f"{c} – {rada_modelu(c, uziv)}" for c in chybi), 2)
    if kopirovat:
        for c in kopie:
            os.makedirs(uziv, exist_ok=True)
            cil = os.path.join(uziv, c + ".traineddata")
            shutil.copyfile(os.path.join(sdir, c + ".traineddata"), cil + ".part")
            os.replace(cil + ".part", cil)
            print(f"{c}: zkopírován ze systémové složky do {uziv}")
    for c, p in cesty.items():
        if p is None or not os.path.isfile(p):
            raise Chyba(f"Model {c}: Tesseract ho hlásí, ale soubor se nenašel (složka modelů neznámá) – "
                        f"dej {c}.traineddata do {uziv}.", 2)
    return tdir


# --- nastavení ------------------------------------------------------------------------------------------------

def cesta_nastaveni():
    return os.path.join(ROOT, "data", "ocr.json")


def nacti_nastaveni(cesta=None):
    """data/ocr.json (utf-8-sig) → dict; chybí → {}. Chybný JSON nebo typ → Chyba (bez tracebacku)."""
    cesta = cesta or cesta_nastaveni()
    if not os.path.exists(cesta):
        return {}
    try:
        with open(cesta, encoding="utf-8-sig") as f:
            d = json.load(f)
    except json.JSONDecodeError as e:
        raise Chyba(f"{cesta}: chybný JSON na řádku {e.lineno}, sloupec {e.colno} ({e.msg}). Oprav soubor, "
                    "nebo ho smaž (platí výchozí hodnoty).")
    except (OSError, UnicodeDecodeError) as e:
        raise Chyba(f"{cesta}: nejde přečíst ({e}).")
    chyby, varovani = over_nastaveni(d)
    for v in varovani:
        print(f"Varování: {cesta}: {v}", file=sys.stderr)
    if chyby:
        raise Chyba(f"{cesta}: " + "; ".join(chyby))
    return d


def over_nastaveni(d):
    """→ (chyby, varování). Všechna pole jsou volitelná; neznámá pole jen varují."""
    if not isinstance(d, dict):
        return ["kořen musí být objekt { … }"], []
    chyby, varovani = [], []
    for k in d:
        if k not in POLE:
            varovani.append(f"neznámé pole {k} (nástroj ho nepoužívá)")
    if "model" in d:
        try:
            rozloz_model(d["model"])
        except Chyba as e:
            chyby.append(f"model: {e}")
    if "stare_znaky" in d and d["stare_znaky"] not in STARE_ZNAKY:
        chyby.append(f"stare_znaky: musí být {' | '.join(STARE_ZNAKY)}")
    if "dlouhe_s" in d:
        if d["dlouhe_s"] not in Z_DLOUHE_S:
            chyby.append('dlouhe_s: musí být "s" nebo "ponechat"')
        else:
            varovani.append("dlouhe_s je zastaralé, použij stare_znaky (ocr.py nastav stare_znaky "
                            f"{Z_DLOUHE_S[d['dlouhe_s']]})")
            if "stare_znaky" in d and d["stare_znaky"] != Z_DLOUHE_S[d["dlouhe_s"]]:
                chyby.append(f"dlouhe_s {d['dlouhe_s']} a stare_znaky {d['stare_znaky']} si odporují – nech jen "
                             "stare_znaky")
    if "prikaz" in d:
        p = d["prikaz"]
        if not isinstance(p, list) or not p or not all(isinstance(x, str) and x for x in p):
            chyby.append('prikaz: musí být neprázdný seznam neprázdných textů, např. ["ocr", "{slozka}", "--lang", '
                         '"{model}", "--out", "{vystup}"]')
        else:
            nalezene = [z for x in p for z in ZASTUPCE_RE.findall(x)]
            for z in nalezene:
                if z not in ZASTUPCI:
                    chyby.append(f"prikaz: neznámé {{{z}}} (povolené jsou {{slozka}}, {{vystup}}, {{model}})")
            for z in ZASTUPCI:   # {model} povinný: manifest pak nese model, který program skutečně použil
                if z not in nalezene:
                    chyby.append(f"prikaz: chybí {{{z}}}")
    for k, (lo, hi) in ROZSAHY.items():
        if k in d:
            v = d[k]
            if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
                chyby.append(f"{k}: celé číslo {lo}–{hi}")
    if "tessdata" in d and (not isinstance(d["tessdata"], str) or not d["tessdata"].strip()):
        chyby.append("tessdata: cesta ke složce s modely (text)")
    return chyby, varovani


def uloz_nastaveni(d, cesta=None):
    cesta = cesta or cesta_nastaveni()
    os.makedirs(os.path.dirname(cesta), exist_ok=True)
    with open(cesta + ".part", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(d, ensure_ascii=False, indent=1) + "\n")
    os.replace(cesta + ".part", cesta)


def platne(nast, model=None):
    """Výsledné hodnoty: --model, pak soubor, pak výchozí."""
    return {"model": model or nast.get("model") or "german_print", "stare_znaky": stare_znaky(nast) or "zjednodusit",
            "prikaz": nast.get("prikaz"),
            "davka": nast.get("davka", 100), "soubezne": nast.get("soubezne", vychozi_soubezne()),
            "dpi": nast.get("dpi", 300), "tessdata": nast.get("tessdata")}


def stare_znaky(d):
    """Výslovně nastavené staré znaky v nastavení nebo manifestu (stare_znaky, jinak převedené dlouhe_s), jinak None."""
    v, s = d.get("stare_znaky"), d.get("dlouhe_s")
    if isinstance(v, str) and v:
        return v
    return Z_DLOUHE_S.get(s) if isinstance(s, str) else None


def varuj_model(model):
    if "deu_latf" in model.split("+"):
        print("Varování: deu_latf čte frakturu výrazně hůř než german_print (celé strany CER 11,2 % proti 7,0 %); "
              "použij german_print, pokud nemáš důvod jinak.", file=sys.stderr)


# --- stahování ------------------------------------------------------------------------------------------------

def _otevri(url):
    import urllib.request
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": slusne.UA}), timeout=120)


def stahni(model, cil, otevri=None):
    """Stáhne známý model do cil/<model>.traineddata přes .part; nesedí-li sha256 (nebo je soubor malý), nic
    nenainstaluje. Bez slusne.py skončí dřív, než otevře spojení."""
    if model not in ZNAME:
        raise Chyba(f"Model {model} skill nezná (známé: {', '.join(ZNAME)}). Soubor {model}.traineddata dej ručně "
                    f"do {cil}.", 2)
    url, sha, _, _ = ZNAME[model]
    if slusne is None or not getattr(slusne, "_instalovano", False):
        raise Chyba(f"Stahování je vypnuté (chybí tools/slusne.py, nástroj bez něj nestahuje). Stáhni ručně {url} "
                    f"a ulož jako {os.path.join(cil, model + '.traineddata')} (sha256 {sha}).", 2)
    otevri = otevri or _otevri
    os.makedirs(cil, exist_ok=True)
    konec = os.path.join(cil, model + ".traineddata")
    part = konec + ".part"
    h, velikost = hashlib.sha256(), 0
    try:
        with otevri(url) as r, open(part, "wb") as f:
            for kus in iter(lambda: r.read(1 << 16), b""):
                h.update(kus)
                f.write(kus)
                velikost += len(kus)
    except BaseException as e:
        with contextlib.suppress(OSError):
            os.remove(part)
        if isinstance(e, (SystemExit, KeyboardInterrupt)):
            raise
        raise Chyba(f"Stažení {model} selhalo ({e}). Ručně: {url} → {konec}.")
    if velikost < MIN_MODEL or h.hexdigest() != sha:
        os.remove(part)
        raise Chyba(f"Stažený {model} nesedí (velikost {velikost} B, sha256 {h.hexdigest()}, čekáno {sha}); "
                    f"nic se nenainstalovalo. Soubor se na serveru možná změnil – ověř {url}.")
    os.replace(part, konec)
    print(f"{model}: staženo do {konec} ({velikost} B, sha256 sedí)")
    return konec


# --- vstupy ---------------------------------------------------------------------------------------------------

def jeden_snimek_tiff(cesta):
    """Klasický TIFF s jediným snímkem? Čte jen hlavičku a první IFD (meze proti velikosti souboru); další IFD
    nenásleduje, takže se nedá zacyklit. → (bool, důvod)."""
    try:
        velikost = os.path.getsize(cesta)
        with open(cesta, "rb") as f:
            h = f.read(8)
            if len(h) < 8:
                return False, "useknutá hlavička"
            if h[:2] == b"II":
                o = "<"
            elif h[:2] == b"MM":
                o = ">"
            else:
                return False, "není to TIFF"
            magie = struct.unpack(o + "H", h[2:4])[0]
            if magie == 43:
                return False, "BigTIFF není podporovaný"
            if magie != 42:
                return False, "není to TIFF"
            ifd = struct.unpack(o + "I", h[4:8])[0]
            if ifd < 8 or ifd + 2 > velikost:
                return False, "první IFD je mimo soubor"
            f.seek(ifd)
            pocet = struct.unpack(o + "H", f.read(2))[0]
            konec = ifd + 2 + pocet * 12
            if konec + 4 > velikost:
                return False, "useknutá IFD"
            f.seek(konec)
            dalsi = struct.unpack(o + "I", f.read(4))[0]
    except (OSError, struct.error) as e:
        return False, f"nejde přečíst ({e})"
    if dalsi != 0:
        return False, "víc snímků (stran)"
    return True, ""


def _rada_tiff(cesta):
    jmeno = os.path.splitext(os.path.basename(cesta))[0]
    return (f"Rozděl ho na snímky: magick \"{cesta}\" pracovni/{jmeno}/s-%03d.tif – a jako vstup dej složku "
            f"pracovni/{jmeno}/.")


def over_tiff(cesta):
    if cesta.lower().endswith((".tif", ".tiff")):
        ok, proc = jeden_snimek_tiff(cesta)
        if not ok:
            raise Chyba(f"{cesta}: TIFF odmítnut – {proc}. {_rada_tiff(cesta)}")


def pocet_stran_pdf(pdfinfo, pdf):
    r = spust([pdfinfo, pdf], capture_output=True)
    m = re.search(r"^Pages:\s+(\d+)", _vystup(r), re.M)
    if r.returncode != 0 or not m:
        raise Chyba(f"{pdf}: pdfinfo nezjistil počet stran ({_vystup(r).strip()[:300]}).")
    return int(m.group(1))


def strany(vstup):
    """→ (druh, [{"jmeno", "obrazek"|"cislo"}], poppler). Kolize jmen a vícestránkový TIFF jsou chyba před OCR."""
    if os.path.isdir(vstup):
        obr = sorted(f for f in os.listdir(vstup) if f.lower().endswith(PRIPONY) and not f.startswith("."))
        if not obr:
            raise Chyba(f"{vstup}: ve složce nejsou obrázky ({' '.join(PRIPONY)}).")
        kmeny = {}
        for f in obr:
            k = os.path.splitext(f)[0]
            if k.lower() in kmeny:
                raise Chyba(f"{vstup}: {kmeny[k.lower()]} a {f} by daly stejný soubor {k}.txt – přejmenuj jeden.")
            kmeny[k.lower()] = f
        out = []
        for f in obr:
            p = os.path.join(vstup, f)
            over_tiff(p)
            out.append({"jmeno": os.path.splitext(f)[0], "obrazek": p})
        return "slozka", out, None
    if not os.path.isfile(vstup):
        raise Chyba(f"{vstup}: soubor ani složka neexistuje.")
    if vstup.lower().endswith(".pdf"):
        pdftoppm, pdfinfo = najdi("pdftoppm"), najdi("pdfinfo")
        if not pdftoppm or not pdfinfo:
            raise Chyba(f"{vstup}: PDF potřebuje Poppler (pdftoppm, pdfinfo). {navod('poppler')}", 2)
        n = pocet_stran_pdf(pdfinfo, vstup)
        sirka = max(4, len(str(n)))
        return "pdf", [{"jmeno": "s%0*d" % (sirka, i), "cislo": i} for i in range(1, n + 1)], pdftoppm
    if vstup.lower().endswith(PRIPONY):
        over_tiff(vstup)
        return "obrazek", [{"jmeno": os.path.splitext(os.path.basename(vstup))[0], "obrazek": vstup}], None
    raise Chyba(f"{vstup}: nepodporovaný vstup (PDF, {' '.join(PRIPONY)} nebo složka obrázků).")


def rozsah_stran(text, n):
    m = re.match(r"^(\d+)(?:-(\d+))?$", text or "")
    if not m:
        raise Chyba(f"--strany {text}: zadej A-B, např. 1-40.")
    a, b = int(m.group(1)), int(m.group(2) or m.group(1))
    if not 1 <= a <= b <= n:
        raise Chyba(f"--strany {text}: vstup má strany 1–{n}.")
    return a, b


# --- manifest -------------------------------------------------------------------------------------------------

POROVNAVANE = ("verze", "zdroj", "model", "stare_znaky", "dpi")   # programy se jen zaznamenají


def manifest(druh, vstup, seznam, model, znaky, dpi, programy):
    zdroj = {"druh": druh, "jmeno": os.path.basename(os.path.normpath(vstup))}
    if druh == "pdf":
        zdroj["stran"] = len(seznam)
    return {"verze": 2, "zdroj": zdroj, "model": model, "stare_znaky": znaky, "dpi": dpi if druh == "pdf" else None,
            "programy": programy}


def porovnej_manifest(stary, novy):
    """→ rozdíly jako 'klíč: staré → nové' (prázdné = lze dodělat). Verze programů dodělání neblokují."""
    j = lambda v: json.dumps(v, ensure_ascii=False)
    return [f"{k}: {j(stary.get(k))} → {j(novy.get(k))}" for k in POROVNAVANE if stary.get(k) != novy.get(k)]


def zapis_json(cesta, d):
    with open(cesta + ".part", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(d, ensure_ascii=False, indent=1) + "\n")
    os.replace(cesta + ".part", cesta)


@contextlib.contextmanager
def zamek_slozky(slozka):
    """Výhradní zápis do výstupní složky; nečeká. Systém zámek uvolní i po pádu nebo kill procesu
    (vzor zapis.py:zamek, zkopírovaný kvůli samostatnosti nástroje)."""
    os.makedirs(slozka, exist_ok=True)
    with open(os.path.join(slozka, ZAMEK), "a+b") as f:
        if os.name == "nt":
            import msvcrt
            zamkni = lambda: msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            odemkni = lambda: msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            zamkni = lambda: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            odemkni = lambda: fcntl.flock(f, fcntl.LOCK_UN)
        f.seek(0)   # msvcrt zamyká bajty od aktuální pozice
        try:
            zamkni()
        except OSError:
            raise Chyba(f"{slozka}: do složky už zapisuje jiný běh OCR – počkej, až skončí, nebo zvol --vystup.")
        try:
            yield
        finally:
            f.seek(0)
            odemkni()


# --- převod ---------------------------------------------------------------------------------------------------

_NAD_E = "\u0364"   # kombinující malé e nad písmenem (aͤ = ä)
_PREHLASKY = {"a": "ä", "o": "ö", "u": "ü", "A": "Ä", "O": "Ö", "U": "Ü"}
_NAD_E_RE = re.compile(f"([aouAOU{''.join(_PREHLASKY.values())}]){_NAD_E}")


def uprav_text(text, znaky):
    """Konce řádků a stránek; staré znaky podle volby (zjednodusit: ſ → s, ꝛ → r, aͤ → ä, üͤ → ü; jen_s: ſ → s)."""
    text = text.replace("\r\n", "\n").replace("\f", "")
    if znaky in ("zjednodusit", "jen_s"):
        text = text.replace("\u017f", "s")
    if znaky == "zjednodusit":
        text = text.replace("\ua75b", "r")
        text = _NAD_E_RE.sub(lambda m: _PREHLASKY.get(m.group(1), m.group(1)), text)
    return text


def zapis_stranu(slozka, jmeno, text):
    cil = os.path.join(slozka, jmeno + ".txt")
    with open(cil + ".part", "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(cil + ".part", cil)


def vykresli(pdftoppm, pdf, cislo, dpi, cil_bez_pripony):
    r = spust([pdftoppm, "-f", str(cislo), "-l", str(cislo), "-r", str(dpi), "-gray", "-jpeg", "-jpegopt",
               "quality=92", "-singlefile", pdf, cil_bez_pripony], capture_output=True)
    obr = cil_bez_pripony + ".jpg"
    if r.returncode != 0 or not os.path.isfile(obr):
        raise Chyba(f"pdftoppm strana {cislo}: {_vystup(r).strip()[:300]}")
    return obr


def tesseract_strana(tess, obrazek, model, tessdata=None):
    argv = [tess] + (["--tessdata-dir", tessdata] if tessdata else []) + [obrazek, "stdout", "-l", model]
    r = spust(argv, capture_output=True, env=dict(os.environ, OMP_THREAD_LIMIT="1"))
    if r.returncode != 0:
        raise Chyba(f"tesseract: {(r.stderr or b'').decode('utf-8', 'replace').strip()[:300]}")
    return (r.stdout or b"").decode("utf-8", "replace")


def prikaz_argv(sablona, slozka, vystup, model):
    hodnoty = {"slozka": slozka, "vystup": vystup, "model": model}
    argv = [ZASTUPCE_RE.sub(lambda m: hodnoty[m.group(1)], x) for x in sablona]
    argv[0] = os.path.expanduser(argv[0])
    return argv


def vysledky_davky(vystup, jmena):
    """Výstup vlastního příkazu → {strana: text}: ve {vystup} právě jeden .txt, za každou stranou \\f
    (tak píše např. `ocr --no-pdf`); za posledním \\f jen bílé znaky."""
    soubory = [f for f in os.listdir(vystup) if f.endswith(".txt")]
    if len(soubory) != 1:
        raise Chyba(f"vlastní příkaz: čekán jeden soubor .txt se všemi stranami, je jich {len(soubory)}.")
    with open(os.path.join(vystup, soubory[0]), encoding="utf-8", errors="replace", newline="") as f:
        kusy = f.read().split("\f")
    if len(kusy) != len(jmena) + 1 or kusy[-1].strip():
        raise Chyba(f"vlastní příkaz: {len(kusy) - 1} konců stran (\\f), čekáno {len(jmena)} – jiný počet stran "
                    "(vícestránkový TIFF?), nebo text za posledním \\f.")
    return dict(zip(jmena, kusy))


# --- příkazy --------------------------------------------------------------------------------------------------

def _tesseract():
    tess = najdi("tesseract")
    if not tess:
        raise Chyba(f"Chybí Tesseract. {navod('tesseract')}", 2)
    v = verze_tesseractu(tess)
    if not v or int(v.split(".")[0]) < 4:
        raise Chyba(f"Tesseract {v or '?'} je starý (potřeba ≥ 4). {navod('tesseract')}", 2)
    return tess, v


def zpracuj(vstup, nast, model_arg=None, vystup=None, rozsah=None, znovu=False):
    """OCR jednoho vstupu. → počet chyb stran (0 = vše hotovo)."""
    p = platne(nast, model_arg)
    druh, seznam, pdftoppm = strany(vstup)
    if rozsah:
        a, b = rozsah_stran(rozsah, len(seznam))
        vyber = seznam[a - 1:b]
    else:
        vyber = seznam
    dokument = os.path.splitext(os.path.basename(os.path.normpath(vstup)))[0] if druh != "slozka" \
        else os.path.basename(os.path.normpath(vstup))
    vystup = vystup or os.path.join(ROOT, "pracovni", "ocr", dokument)
    sablona = p["prikaz"]
    # kontroly (Tesseract, modely) před zámkem: bez nich nevznikne prázdná výstupní složka
    model = p["model"]
    rozloz_model(model)
    if sablona:
        programy, tess, tdir = {"prikaz": sablona}, None, None
    else:
        varuj_model(model)
        tess, verze = _tesseract()
        tdir = priprav_modely(tess, model, nast)
        programy = {"tesseract": verze}
    if druh == "pdf":
        programy["pdftoppm"] = verze_poppleru(pdftoppm)
    with zamek_slozky(vystup):
        mpath = os.path.join(vystup, MANIFEST)
        txt = {f[:-4] for f in os.listdir(vystup) if f.endswith(".txt")}
        if znovu and (os.path.exists(mpath) or not txt):   # jen naše složka; maže jen strany zdroje, ne cizí soubory
            for s in seznam:
                for f in (s["jmeno"] + ".txt", s["jmeno"] + ".txt.part", MANIFEST):
                    with contextlib.suppress(FileNotFoundError):
                        os.remove(os.path.join(vystup, f))
            txt = set()
        stary = None
        if os.path.exists(mpath):
            try:
                with open(mpath, encoding="utf-8") as f:
                    stary = json.load(f)
                if not isinstance(stary, dict):
                    raise ValueError("není objekt")
            except (OSError, ValueError) as e:
                if txt:
                    raise Chyba(f"{mpath}: nečitelný manifest ({e}) a ve složce jsou strany – nelze zaručit původ. "
                                "Spusť s --znovu, nebo zvol --vystup.")
                stary = None
        if txt and stary is None:
            raise Chyba(f"{vystup}: jsou tu strany bez {MANIFEST} – nelze zaručit původ. Smaž složku, nebo zvol --vystup.")
        sz = stary.get("stare_znaky") if stary and txt else None
        if stare_znaky(nast) is None and sz in STARE_ZNAKY and sz != p["stare_znaky"]:
            # nenastavené výslovně: dodělat stejně jako hotové strany (žádné tiché povýšení starého výstupu)
            p["stare_znaky"] = sz
            print(f"staré znaky: {sz} podle hotových stran", file=sys.stderr)
        novy = manifest(druh, vstup, seznam, model, p["stare_znaky"], p["dpi"], programy)
        if stary is not None and txt:
            rozdil = porovnej_manifest(stary, novy)
            if rozdil:
                raise Chyba(f"{vystup}: hotové strany vznikly jinak – {'; '.join(rozdil)}. Spusť s --znovu (smaže "
                            "hotové strany a udělá dokument celý znovu), nebo zvol --vystup s novou složkou.")
        zapis_json(mpath, novy)

        hotove = [s for s in vyber if s["jmeno"] in txt]
        todo = [s for s in vyber if s["jmeno"] not in txt]
        print(f"{dokument}: hotovo {len(hotove)}, zbývá {len(todo)} → {vystup}", flush=True)
        if not todo:
            return 0
        try:
            if sablona:
                return _davky_prikazu(todo, druh, vstup, pdftoppm, p, sablona, model, vystup)
            return _tesseract_strany(todo, druh, vstup, pdftoppm, p, tess, model, tdir, vystup)
        except KeyboardInterrupt:
            h = len({f[:-4] for f in os.listdir(vystup) if f.endswith(".txt")} & {s["jmeno"] for s in vyber})
            raise Chyba(f"Přerušeno: {dokument} hotovo {h} z {len(vyber)} stran ({vystup}). "
                        "Další spuštění dodělá zbytek.", 130)


def _tesseract_strany(todo, druh, vstup, pdftoppm, p, tess, model, tdir, vystup):
    def jedna(s):
        with tempfile.TemporaryDirectory(prefix="ocr_") as t:
            obr = s["obrazek"] if druh != "pdf" else vykresli(pdftoppm, vstup, s["cislo"], p["dpi"],
                                                               os.path.join(t, s["jmeno"]))
            text = tesseract_strana(tess, obr, model, tdir)
        zapis_stranu(vystup, s["jmeno"], uprav_text(text, p["stare_znaky"]))

    # v poolu nejvýš `soubezne` stran, nic nečeká ve frontě: po Ctrl-C se čeká jen na právě běžící strany
    chyby, n, fronta, bezi = 0, 0, iter(todo), {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=p["soubezne"]) as ex:
        while True:
            for s in itertools.islice(fronta, p["soubezne"] - len(bezi)):
                bezi[ex.submit(jedna, s)] = s
            if not bezi:
                break
            hotove, _ = concurrent.futures.wait(bezi, return_when=concurrent.futures.FIRST_COMPLETED)
            for b in hotove:
                s = bezi.pop(b)
                n += 1
                try:
                    b.result()
                except Exception as e:   # jedna vadná strana nezastaví ostatní
                    chyby += 1
                    print(f"  {s['jmeno']}: CHYBA {e}", file=sys.stderr, flush=True)
                    continue
                print(f"  {s['jmeno']} ({n}/{len(todo)})", flush=True)
    return chyby


def _davky_prikazu(todo, druh, vstup, pdftoppm, p, sablona, model, vystup):
    for i in range(0, len(todo), p["davka"]):
        davka = todo[i:i + p["davka"]]
        slozka = tempfile.mkdtemp(prefix="ocr_davka_")
        vyst = tempfile.mkdtemp(prefix="ocr_vystup_")
        try:
            # pořadová jména: program řadící abecedně i „přirozeně“ (1, 2, 10) vidí strany ve stejném pořadí jako my
            sirka = max(4, len(str(len(davka))))
            for k, s in enumerate(davka, 1):
                cil = os.path.join(slozka, "p%0*d" % (sirka, k))
                if druh == "pdf":
                    vykresli(pdftoppm, vstup, s["cislo"], p["dpi"], cil)
                else:
                    shutil.copyfile(s["obrazek"], cil + os.path.splitext(s["obrazek"])[1])
            argv = prikaz_argv(sablona, slozka, vyst, model)
            print(f"  vlastní příkaz: dávka {i // p['davka'] + 1}, strany {davka[0]['jmeno']}–{davka[-1]['jmeno']}",
                  flush=True)
            rc = spust_prikaz(argv)
            if rc != 0:
                raise Chyba(f"vlastní příkaz skončil kódem {rc}; dávka zahozena, hotové dávky zůstaly.")
            texty = vysledky_davky(vyst, [s["jmeno"] for s in davka])
            for s in davka:
                zapis_stranu(vystup, s["jmeno"], uprav_text(texty[s["jmeno"]], p["stare_znaky"]))
        except Chyba as e:
            print(f"CHYBA dávky {davka[0]['jmeno']}–{davka[-1]['jmeno']}: {e}", file=sys.stderr)
            return 1
        finally:
            shutil.rmtree(slozka, ignore_errors=True)
            shutil.rmtree(vyst, ignore_errors=True)
    return 0


def prikaz_stav(nast, model_arg=None):
    p = platne(nast, model_arg)
    chybi = False
    print(f"stahovani: {'slusne.py' if slusne is not None and getattr(slusne, '_instalovano', False) else 'vypnuto (chybí slusne.py)'}")
    tess = najdi("tesseract")
    if tess:
        v = verze_tesseractu(tess)
        if v and int(v.split(".")[0]) >= 4:
            print(f"tesseract: {tess} ({v})")
        else:
            print(f"tesseract: {tess} ({v or '?'}) – STARÝ, potřeba ≥ 4. {navod('tesseract')}")
            tess, chybi = None, True
    else:
        print(f"tesseract: CHYBÍ. {navod('tesseract')}")
        chybi = True
    pop = {x: najdi(x) for x in ("pdftoppm", "pdfinfo")}
    for x, cesta in pop.items():
        print(f"{x}: {cesta}" if cesta else f"{x}: CHYBÍ (jen pro PDF). {navod('poppler')}")
    if not all(pop.values()):
        chybi = True
    if not tess and not all(pop.values()) and sys.platform.startswith("linux"):
        print(f"Linux, obojí najednou, {PRO_UZIVATELE}: sudo apt install tesseract-ocr poppler-utils")
    model = p["model"]
    casti = rozloz_model(model)
    uziv = uzivatelska_slozka(nast)
    print(f"model: {model}")
    varuj_model(model)
    print(f"uživatelská složka modelů: {uziv}")
    if tess:
        sdir, sjaz = jazyky(tess)
        sdir = systemova_slozka(sdir)
        print(f"systémová složka modelů: {sdir or '?'} ({' '.join(sjaz) or 'žádné'})")
        tdir, cesty, chyb, kopie = kde_modely(casti, (sdir, sjaz), uziv)
        for c in casti:
            if c in chyb:
                print(f"  {c}: CHYBÍ – {rada_modelu(c, uziv)}")
            elif c in kopie:
                print(f"  {c}: jen v systémové složce, před během se zkopíruje do uživatelské")
            else:
                print(f"  {c}: {cesty[c]}")
        if chyb:
            chybi = True
        else:
            print(f"složka modelů pro běh: {tdir or sdir} ({'--tessdata-dir' if tdir else 'systémová'})")
    if p["prikaz"]:
        print(f"vlastní příkaz: {json.dumps(p['prikaz'], ensure_ascii=False)}")
    print(f"staré znaky: {p['stare_znaky']} " + ("(nastaveno v data/ocr.json)" if stare_znaky(nast) else
                                                  "(výchozí, nenastaveno – u fraktury se zeptej uživatele)"))
    return 2 if chybi else 0


def prikaz_modely(nast):
    uziv = uzivatelska_slozka(nast)
    tess = najdi("tesseract")
    sdir, sjaz = (None, [])
    if tess:
        sdir, sjaz = jazyky(tess)
        sdir = systemova_slozka(sdir)
    print(f"systémová složka: {sdir or '?'}\nuživatelská složka: {uziv}")
    jine = set(sjaz) | {os.path.basename(f)[:-12] for f in glob.glob(os.path.join(uziv, "*.traineddata"))}
    for m, (_, _, mb, popis) in ZNAME.items():
        kde = [k for k, ano in (("systém", m in sjaz), ("uživatel", os.path.isfile(os.path.join(uziv, m + ".traineddata"))))
               if ano]
        print(f"{m:14} {mb:5.1f} MB  {'+'.join(kde) or '–':16} {popis}; {puvod(m)}")
    for m in sorted(jine - set(ZNAME)):
        print(f"{m:14}           nainstalovaný (skill ho nezná)")
    return 0


def prikaz_nastav(nast_cesta, klic, hodnota):
    if klic not in POLE:
        raise Chyba(f"Neznámý klíč {klic} (známé: {', '.join(POLE)}).")
    d = {}
    if os.path.exists(nast_cesta):
        try:
            with open(nast_cesta, encoding="utf-8-sig") as f:
                d = json.load(f)
        except (OSError, ValueError) as e:
            raise Chyba(f"{nast_cesta}: nejde přečíst ({e}); oprav nebo smaž soubor.")
        if not isinstance(d, dict):
            raise Chyba(f"{nast_cesta}: kořen musí být objekt.")
    if klic == "dlouhe_s":   # zastaralé pole: zapíše se převedené jako stare_znaky
        if hodnota != "vychozi" and hodnota not in Z_DLOUHE_S:
            raise Chyba('dlouhe_s: musí být "s" nebo "ponechat" – nic se nezapsalo.')
        klic, hodnota = "stare_znaky", Z_DLOUHE_S.get(hodnota, hodnota)
    if klic == "stare_znaky":
        d.pop("dlouhe_s", None)
    if hodnota == "vychozi":
        d.pop(klic, None)
    elif klic == "prikaz":
        try:
            d[klic] = json.loads(hodnota)
        except ValueError:
            raise Chyba('prikaz: hodnota je JSON seznam, např. \'["/cesta/ocr", "{slozka}", "--out", "{vystup}"]\'')
    elif klic in ROZSAHY:
        try:
            d[klic] = int(hodnota)
        except ValueError:
            raise Chyba(f"{klic}: celé číslo")
    else:
        d[klic] = hodnota
    chyby, _ = over_nastaveni(d)
    if chyby:
        raise Chyba("; ".join(chyby) + " – nic se nezapsalo.")
    uloz_nastaveni(d, nast_cesta)
    print(f"Zapsáno do data/ocr.json: {klic} = {json.dumps(d.get(klic, 'výchozí'), ensure_ascii=False)}")
    return 0


NAPOVEDA = __doc__


def _volby(argv, povolene, prepinace=()):
    poz, volby, i = [], {}, 0
    while i < len(argv):
        a = argv[i]
        if a in prepinace:
            volby[a[2:]] = True
            i += 1
        elif a.startswith("--"):
            if a not in povolene or i + 1 >= len(argv):
                raise Chyba(f"Neznámá volba nebo chybí hodnota: {a}\n{NAPOVEDA}")
            volby[a[2:]] = argv[i + 1]
            i += 2
        else:
            poz.append(a)
            i += 1
    return poz, volby


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(NAPOVEDA)
        return 0
    try:
        prikaz = argv[0]
        if prikaz == "nastav":
            if len(argv) != 3:
                raise Chyba("Použití: ocr.py nastav <klíč> <hodnota|vychozi>")
            return prikaz_nastav(cesta_nastaveni(), argv[1], argv[2])
        nast = nacti_nastaveni()
        if prikaz == "stav":
            _, volby = _volby(argv[1:], ("--model",))
            return prikaz_stav(nast, volby.get("model"))
        if prikaz == "modely":
            return prikaz_modely(nast)
        if prikaz == "nastaveni":
            print(json.dumps({"soubor": cesta_nastaveni() if os.path.exists(cesta_nastaveni()) else None,
                              "platne": platne(nast)}, ensure_ascii=False, indent=1))
            return 0
        if prikaz == "stahni":
            if len(argv) < 2:
                raise Chyba("Použití: ocr.py stahni <model>…")
            cil = uzivatelska_slozka(nast)
            for m in argv[1:]:
                for c in rozloz_model(m):
                    stahni(c, cil)
            return 0
        vstupy, volby = _volby(argv, ("--model", "--vystup", "--strany"), ("--znovu",))
        if volby.get("vystup") and len(vstupy) != 1:
            raise Chyba("--vystup jde jen s jedním vstupem.")
        if volby.get("model"):
            rozloz_model(volby["model"])
        chyby, nehotove = 0, []
        for v in vstupy:   # vadný vstup nezastaví ostatní; nenainstalované (2) a Ctrl-C (130) ano
            try:
                chyby += zpracuj(v, nast, volby.get("model"), volby.get("vystup"), volby.get("strany"),
                                 volby.get("znovu", False))
            except Chyba as e:
                if e.kod != 1:
                    raise
                print(f"CHYBA: {e}", file=sys.stderr)   # hlášky vstup nebo jeho složku jmenují samy
                nehotove.append(v)
        if chyby:
            print(f"Nehotové strany: {chyby}. Spusť znovu – dodělá jen chybějící.", file=sys.stderr)
        if nehotove:
            print(f"Nehotové vstupy: {', '.join(nehotove)}.", file=sys.stderr)
        return 1 if chyby or nehotove else 0
    except Chyba as e:
        print(e if e.kod == 130 else f"CHYBA: {e}", file=sys.stderr)
        return e.kod
    except KeyboardInterrupt:
        print("Přerušeno.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
