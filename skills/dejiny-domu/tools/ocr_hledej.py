"""Hledání jmen a míst v OCR textech (*.txt), i když je OCR zkomolilo (Gansbauden → Sansbauben, Gan&bauben).
Výchozí rovnocennosti platí i bez souboru pravidel: ſ = s, ꝛ = r, ß = ss, ä ö ü = ae oe ue = aͤ oͤ uͤ, rozložené
tvary písmen (e + U+030C = ě), měkké dělení U+00AD a česká sada pravopisu před 1849 (Wáclaw, Gilemnice). Jsou to
čtení hledaného slova – prohledávaný text se nemění. Záměny písmen z OCR jsou pravidla projektu
v data/ocr_zameny.json (bez souboru = celé slovo s rovnocennostmi, českými koncovkami a genitivem -s/-es). Postup: reference/ocr.md.

Volby hledání (dělení slov, vynechané první písmeno, tvary, rovnocennosti a sady pravopisu) jsou v nastavení
projektu: python3 -I tools/nastaveni.py ukaz ocr_hledej / nastav ocr_hledej.<klíč> <hodnota|vychozi>.

Použití (z kořene projektu, volby kdekoli před --; bez -- se hledá ve všech *.txt v pracovni/):
  ocr_hledej.py hledej <slovo>… [--tvary ceske|presne|volne] [--vypis souhrn|radky]
                [--pravidla <json>] [--volba <klíč>=<hodnota>]… [-- <soubor|složka>…]
      → souhrn podle nalezeného tvaru: slovo, tvar, počet×, první tři místa (+ kolik dalších), ukázka (tabulátory);
        --vypis radky: řádek na nález (slovo, tvar, soubor:řádek, ukázka); počty a počet souborů na stderr
      hranice (mimo --tvary volne): za nálezem nesmí být malé písmeno, velké jen po malém (FischerDavid ano,
        FISCHERDAVID ne)
      --tvary ceske (výchozí): české koncovky a německý genitiv -s/-es (Zineckers, Krauses; ne Krauss),
        genitiv jen za slovem bez záměn a skupin projektu
      --volba deleni_slova=ano: volba z nastavení jen pro tento běh (opakovatelná), nic nezapíše
  ocr_hledej.py kandidati <slovo>… [--vzdalenost N] [--max 40] [--tvary …] [--pravidla <json>] [--volba …]
                [-- …]
      → slova blízká hledanému, která pravidla nenajdou, s počtem, ukázkou a návrhem pravidla nebo volby
        (nastav ocr_hledej.… = argumenty nastaveni.py); nic nezapíše
  ocr_hledej.py pridej|odeber zamena <znak> <čtení>…
  ocr_hledej.py pridej|odeber skupina <dvě malá písmena> <čtení>…
  ocr_hledej.py pridej|odeber vyloucit <text> [--proc "důvod"]
  ocr_hledej.py pravidla
Pravidlo i volbu měň jen se souhlasem uživatele. Pravopisné varianty jmen (Zinecker / Zinnecker)
hledej jako samostatná slova.
"""
import functools, glob, json, os, re, sys, unicodedata

for _s in (sys.stdout, sys.stderr):   # UTF-8 výstup i na Windows bez -X utf8
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I nepřidá složku skriptu sama (import zapis)
import nastaveni   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRAVIDLA = os.path.join(ROOT, "data", "ocr_zameny.json")

_LATIN = [chr(i) for i in range(0x250)]
PISMENA = "".join(c for c in _LATIN if c.isalpha())    # před slovem nesmí být písmeno (číslice smí: „22Gansbauden“)
MALA = frozenset(c for c in _LATIN if c.islower())       # za slovem nesmí pokračovat malé písmeno (velké jen po malém)
VELKA = frozenset(c for c in _LATIN if c.isupper())      # velké za slovem jen po malém: slepené „FischerDavid“, ne „FRIESEN“
DELENI = "-⸗=¬"                                          # znaky dělení slova („Gans-bauden“, „Gans⸗ bauden“)
MEZER_PO_DELENI = 250                                    # nejvíc bílých znaků po znaku dělení (i přes konec řádku)
KONCOVKY = ("a e u y i em ů ům ech ovi ové ová ovou ových ovým ovými ův ova ovo ovu ovy ovic").split()
NEMECKE = ("es", "s")   # německý genitiv (Zineckers, Krauses) jen za slovem bez záměn projektu; holé s ne po
                        # s ß ſ x z (Krauss je jiný pravopis)
TVARY = ("ceske", "presne", "volne")
SEKCE = ("poznamka", "zameny", "skupiny", "vyloucit")
MEMO = 200_000        # slov v paměti kandidátů
SLOVO_RE = re.compile(r"[^\s.,;:!?\"'„“”‚‘’»«()\[\]{}<>/|*]+")
MEZERA_RE = re.compile(r"\s")

# Rovnocennosti: stejný znak jinak zapsaný. Platí jen na straně hledaného slova (čtení ve vzoru), text se nemění.
DLOUHE_S, R_ROTUNDA, NAD_E, MEKKE = "\u017f", "\ua75b", "\u0364", "\u00ad"   # ſ, ꝛ, kombinující malé e, U+00AD
OSTRE, OSTRE_VELKE = "\u00df", "\u1e9e"                                      # ß, ẞ
PREHLASKY = {"ä": "a", "ö": "o", "ü": "u", "Ä": "A", "Ö": "O", "Ü": "U"}
ZE_ZAKLADU = {v: k for k, v in PREHLASKY.items()}
STAZENI = {"ae": "ä", "Ae": "Ä", "AE": "Ä", "oe": "ö", "Oe": "Ö", "OE": "Ö", "ue": "ü", "Ue": "Ü", "UE": "Ü",
           "ss": OSTRE, "SS": OSTRE_VELKE}
ROVNOCENNOSTI = ("dlouhe_s", "r_rotunda", "ostre_s", "prehlasky", "rozlozene", "mekke_deleni")
# Sady historického pravopisu: pravidla (ne normalizace), sloučí se s pravidly projektu. Prameny: reference/ocr.md.
SADY_PRAVOPISU = {
    "cestina_1849": {   # bratrský pravopis do 1849: jen dnešní slovo → starý zápis (Václav → Wáclaw)
        "zameny": {"v": ["w"], "V": ["W"], "j": ["g"], "J": ["G"], "í": ["j"], "Í": ["J"], "š": ["ss"],
                   "Š": ["Ss", "SS"]},
        "skupiny": {"ou": ["au"]},
    },
    "nemcina_1901": {   # pravopis před 1901/1902 a varianty 19. stol., obousměrně (Thal ↔ Tal, Carl ↔ Karl)
        "zameny": {"t": ["th"], "T": ["Th", "TH"], "c": ["k", "z"], "C": ["K", "Z"], "k": ["c"], "K": ["C"],
                   "z": ["c"], "Z": ["C"], "y": ["i"], "Y": ["I"], "i": ["y"], "I": ["Y"], "f": ["ph"],
                   "F": ["Ph", "PH"]},
        "skupiny": {"th": ["t"], "ph": ["f"]},
    },
}
VSE = ROVNOCENNOSTI + tuple(SADY_PRAVOPISU)
VYCHOZI = frozenset(VSE) - {"nemcina_1901"}

# Volby hledání v nastavení projektu (data/nastaveni.json, tools/nastaveni.py). Literál: nastaveni.py ho čte přes ast.
# Výchozí hodnoty = VYCHOZI a dřívější výchozí chování (hlídá test).
NASTAVENI_SEKCE = {"ocr_hledej": {
    "deleni_slova": {"vychozi": "ne", "hodnoty": ["ano", "ne"],
                     "popis": "slovo rozdělené znakem dělení na konci řádku (Gans-⏎bauden)"},
    "chybi_prvni_pismeno": {"vychozi": "ne", "hodnoty": ["ano", "ne"],
                            "popis": "OCR vynechalo první písmeno (u slov delších než 6 písmen)"},
    "tvary": {"vychozi": "ceske", "hodnoty": ["ceske", "presne", "volne"],
              "popis": "ceske = české koncovky a genitiv -s/-es, presne = jen celé slovo, volne = slovo kdekoli; "
                       "--tvary přebije"},
    "dlouhe_s": {"vychozi": "ano", "hodnoty": ["ano", "ne"], "popis": "ſ = s"},
    "r_rotunda": {"vychozi": "ano", "hodnoty": ["ano", "ne"], "popis": "ꝛ = r"},
    "ostre_s": {"vychozi": "ano", "hodnoty": ["ano", "ne"], "popis": "ß = ss (i ſs, sſ, ſſ; ẞ = SS)"},
    "prehlasky": {"vychozi": "ano", "hodnoty": ["ano", "ne"], "popis": "ä ö ü = ae oe ue = aͤ oͤ uͤ (i velká)"},
    "rozlozene": {"vychozi": "ano", "hodnoty": ["ano", "ne"],
                  "popis": "rozložené tvary písmen (e + U+030C = ě, a + U+0308 = ä)"},
    "mekke_deleni": {"vychozi": "ano", "hodnoty": ["ano", "ne"], "popis": "měkké dělení U+00AD jako znak dělení slova"},
    "cestina_1849": {"vychozi": "ano", "hodnoty": ["ano", "ne"],
                     "popis": "čeština před 1849: v→w, j→g, í→j, ou→au, š→ss (jen dnešní slovo → starý zápis)"},
    "nemcina_1901": {"vychozi": "ne", "hodnoty": ["ano", "ne"],
                     "popis": "němčina před 1901: th↔t, c↔k, c↔z, y↔i, ph↔f (obousměrně)"},
}}


# --- pravidla -------------------------------------------------------------------------------------------------

def _cteni(hodnota, kde, chyby):
    if not isinstance(hodnota, list):
        chyby.append(f"{kde}: hodnota musí být seznam čtení, např. [\"f\", \"ſ\"]")
        return
    for r in hodnota:
        if not isinstance(r, str) or not r:
            chyby.append(f"{kde}: čtení musí být neprázdný text (je {json.dumps(r, ensure_ascii=False)})")
        elif any(c.isspace() for c in r):
            chyby.append(f"{kde}: čtení „{r}“ obsahuje mezeru nebo jiný bílý znak")


def chyby_pravidel(p):
    """Všechny chyby schématu pravidel najednou (prázdný seznam = v pořádku)."""
    if not isinstance(p, dict):
        return ["kořen musí být objekt { … }, ne " + type(p).__name__]
    chyby = [hlaska_prenosu(p["volby"])] if "volby" in p else []
    for k in p:
        if k not in SEKCE and k != "volby":
            chyby.append(f"neznámá sekce „{k}“ (povolené: {', '.join(SEKCE)})")
    if "poznamka" in p and not isinstance(p["poznamka"], str):
        chyby.append("poznamka: musí být text")
    for sekce in ("zameny", "skupiny", "vyloucit"):
        if sekce in p and not isinstance(p[sekce], dict):
            chyby.append(f"{sekce}: musí být objekt {{ … }}")
    if isinstance(p.get("zameny"), dict):
        for k, v in p["zameny"].items():
            if len(k) != 1 or k.isspace():
                chyby.append(f"zameny: klíč „{k}“ musí být jeden znak (ne mezera); dvojice písmen patří do skupiny")
            _cteni(v, f"zameny „{k}“", chyby)
    if isinstance(p.get("skupiny"), dict):
        for k, v in p["skupiny"].items():
            if len(k) != 2 or not all(c.isalpha() and c.islower() for c in k):
                chyby.append(f"skupiny: klíč „{k}“ musí být dvě malá písmena (např. „ck“)")
            _cteni(v, f"skupiny „{k}“", chyby)
    if isinstance(p.get("vyloucit"), dict):
        for k, v in p["vyloucit"].items():
            if not k or any(c.isspace() for c in k):
                chyby.append(f"vyloucit: text „{k}“ musí být neprázdný a bez mezer")
            if not isinstance(v, str):
                chyby.append(f"vyloucit „{k}“: důvod musí být text")
    return chyby


def prikazy_prenosu(volby):
    """Dřívější sekce „volby“ souboru pravidel jako [(klíč, hodnota)] pro nastaveni.py; None = nejde přečíst."""
    if not isinstance(volby, dict):
        return None
    an = lambda b: "ano" if b else "ne"
    out = []
    for k, v in volby.items():
        if k in ("deleni_slova", "chybi_prvni_pismeno") and isinstance(v, bool):
            out.append((k, an(v)))
        elif k == "tvary" and v in TVARY:
            out.append((k, v))
        elif k == "rovnocennosti" and v is True:
            pass
        elif k == "rovnocennosti" and v is False:
            out += [(n, "ne") for n in VSE]
        elif k == "rovnocennosti" and isinstance(v, dict) and all(n in VSE and isinstance(b, bool)
                                                                   for n, b in v.items()):
            out += [(n, an(b)) for n, b in v.items()]
        else:
            return None
    return out


def hlaska_prenosu(volby):
    """Chyba pro soubor pravidel s dřívější sekcí „volby“: přesné příkazy, jak je přenést do nastavení."""
    out = ["volby hledání jsou teď v nastavení projektu (data/nastaveni.json). Se souhlasem uživatele je přenes "
           "a sekci „volby“ z tohoto souboru smaž:"]
    prikazy = prikazy_prenosu(volby)
    if prikazy is None:
        out.append(f"  sekce „volby“ = {json.dumps(volby, ensure_ascii=False)} – přenes ji ručně podle "
                   "python3 -I tools/nastaveni.py ukaz ocr_hledej")
    elif not prikazy:
        out.append("  (nic k přenesení – sekce „volby“ odpovídá výchozím hodnotám)")
    else:
        out += [f"  python3 -I tools/nastaveni.py nastav ocr_hledej.{k} {v}" for k, v in prikazy]
        out.append("  Jen pro jeden běh bez zápisu: " + " ".join(f"--volba {k}={v}" for k, v in prikazy))
    return "\n".join(out)


def volby_hledani(prepis=()):
    """Volby hledání z nastavení projektu, přepsané --volba klíč=hodnota (jen pro tento běh), ve vnitřním tvaru
    pravidla["volby"] pro Vzor/hledej/kandidati. Chyba nastavení nebo --volba ukončí program před hledáním."""
    try:
        s = nastaveni.sekce("ocr_hledej")
    except nastaveni.Chyba as e:
        sys.exit(f"CHYBA: {e}")
    sch = NASTAVENI_SEKCE["ocr_hledej"]
    for x in prepis:
        k, _, v = x.partition("=")
        if k not in sch:
            sys.exit(f"--volba {x}: neznámá volba „{k}“ (známé: {', '.join(sch)})")
        if v.lower() not in sch[k]["hodnoty"]:
            sys.exit(f"--volba {x}: hodnota je {' | '.join(sch[k]['hodnoty'])}")
        s[k] = v.lower()
    return {"deleni_slova": s["deleni_slova"] == "ano", "chybi_prvni_pismeno": s["chybi_prvni_pismeno"] == "ano",
            "tvary": s["tvary"], "rovnocennosti": {n: s[n] == "ano" for n in VSE}}


def zapnute(pravidla):
    """Zapnuté rovnocennosti a sady pravopisu podle vnitřní volby rovnocennosti (chybí = výchozí)."""
    v = (pravidla or {}).get("volby", {}).get("rovnocennosti", True)
    if v is True:
        return VYCHOZI
    if v is False:
        return frozenset()
    return frozenset(k for k in VSE if v.get(k, k in VYCHOZI))


def uprav_slovo(s, zap):
    """Hledané slovo, klíč nebo čtení pravidla bez kontextu na kanonický tvar (text se tak neupravuje nikdy):
    NFC, ſ → s, ꝛ → r, aͤ → ä, üͤ → ü, stažení dvojic ae → ä, Ue → Ü, ss → ß, SS → ẞ (zleva)."""
    if not zap:
        return s
    s = unicodedata.normalize("NFC", s)
    if "dlouhe_s" in zap:
        s = s.replace(DLOUHE_S, "s")
    if "r_rotunda" in zap:
        s = s.replace(R_ROTUNDA, "r")
    dvojice = []
    if "prehlasky" in zap:
        s = re.sub(f"([{''.join(PREHLASKY)}]){NAD_E}", r"\1", s)
        s = re.sub(f"([aouAOU]){NAD_E}", lambda m: ZE_ZAKLADU[m.group(1)], s)
        dvojice += [k for k in STAZENI if k.lower() != "ss"]
    if "ostre_s" in zap:
        dvojice += ["ss", "SS"]
    if dvojice:
        s = re.sub("|".join(dvojice), lambda m: STAZENI[m.group(0)], s)
    return s


def slovo_pravidel(slovo):
    """Slovo celé verzálkami bere pravidla jako slovo s velkým prvním písmenem (FRIES jako Fries)."""
    return slovo[0] + slovo[1:].lower() if slovo.isupper() and len(slovo) > 1 else slovo


def _precti(cesta):
    """Pravidla ze souboru (chybějící = None); chybný soubor ukončí program srozumitelnou hláškou."""
    if not os.path.exists(cesta):
        return None
    try:
        with open(cesta, encoding="utf-8-sig") as f:
            text = f.read()
    except UnicodeDecodeError:
        sys.exit(f"CHYBA: {cesta}: není v UTF-8 – ulož ho v UTF-8, nebo ho smaž")
    if not text.strip():
        return {}
    try:
        p = json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"CHYBA: {cesta}: řádek {e.lineno}, sloupec {e.colno}: {e.msg} – oprav ho "
                 "(git diff ukáže poslední změnu), nebo ho smaž")
    chyby = chyby_pravidel(p)
    if chyby:
        sys.exit("\n".join(f"CHYBA: {cesta}: {c}" for c in chyby))
    return p


def nacti_pravidla(cesta=PRAVIDLA):
    """Pravidla projektu; chybějící soubor = {} (bez záměn)."""
    p = _precti(cesta)
    return {} if p is None else p


# --- vzor (regex) -----------------------------------------------------------------------------------------------

def _sloucena(p, zap):
    """Záměny a skupiny projektu sloučené se zapnutými sadami pravopisu (kopie, vstup se nemění)."""
    zameny = {k: list(v) for k, v in p.get("zameny", {}).items()}
    skupiny = {k: list(v) for k, v in p.get("skupiny", {}).items()}
    for nazev, sada in SADY_PRAVOPISU.items():
        if nazev in zap:
            for sekce, cil in (("zameny", zameny), ("skupiny", skupiny)):
                for k, v in sada[sekce].items():
                    cil.setdefault(k, []).extend(r for r in v if r not in cil.get(k, ()))
    return zameny, skupiny


def _uprav_pravidla(zameny, skupiny, zap):
    """Klíče a čtení po úpravě slova; čtení shodné s klíčem odpadne (pokryje ho rovnocennost). Klíč skupiny se
    rozepíše na základní písmena (äß → aess), aby seděl na pozice slova."""
    z = {}
    for k, v in zameny.items():
        k = uprav_slovo(k, zap)
        cil = z.setdefault(k, [])
        cil.extend(r for r in (uprav_slovo(r, zap) for r in v) if r != k and r not in cil)
    s = {}
    for k, v in skupiny.items():
        k = "".join(_zaklad(c, zap) for c in uprav_slovo(k, zap)).lower()
        cil = s.setdefault(k, [])
        cil.extend(r for r in (uprav_slovo(r, zap) for r in v) if r not in cil)
    return z, s


def _alt(c, zap):
    """Znaky, které platí za jednu pozici slova (s = ſ, r = ꝛ)."""
    if c == "s" and "dlouhe_s" in zap:
        return {c, DLOUHE_S}
    if c == "r" and "r_rotunda" in zap:
        return {c, R_ROTUNDA}
    return {c}


def _pulky(c, zap):
    """Přehláska nebo ß rozepsané na dvě pozice (ä = {a}{e, ͤ}, ß = {s ſ S}{s ſ S}), jinak None."""
    if c in PREHLASKY and "prehlasky" in zap:
        b = PREHLASKY[c]
        return [_alt(b, zap), {"e", NAD_E} | ({"E"} if b.isupper() else set())]
    if c in (OSTRE, OSTRE_VELKE) and "ostre_s" in zap:
        s = {"s", "S"} | ({DLOUHE_S} if "dlouhe_s" in zap else set())
        return [s, set(s)]
    return None


def _zaklad(c, zap):
    """Základní písmena znaku pro párování skupin (ä → ae, ß → ss)."""
    if _pulky(c, zap):
        return "ss" if c in (OSTRE, OSTRE_VELKE) else PREHLASKY[c] + "e"
    return c


def _prime(c, zap):
    """Přímá čtení celého znaku: sám, rozložený tvar (NFD), ä + ͤ, ß ↔ ẞ."""
    out, d = [c], unicodedata.normalize("NFD", c)
    if "rozlozene" in zap and d != c:
        out.append(d)
    if c in PREHLASKY and "prehlasky" in zap:
        out.append(c + NAD_E)
    if "ostre_s" in zap and c in (OSTRE, OSTRE_VELKE):
        out.append(OSTRE_VELKE if c == OSTRE else OSTRE)
    return out


def _pozice(slovo, zap):
    """Pozice slova (množiny znaků), index první pozice každého znaku slova a základní písmena pozic."""
    P, zac, zaklad = [], [], []
    for c in slovo:
        zac.append(len(P))
        h = _pulky(c, zap)
        if h:
            P.extend(h)
            zaklad.extend(_zaklad(c, zap).lower())
        else:
            P.append(_alt(c, zap))
            m = c.lower()
            zaklad.append(m if len(m) == 1 else c)
    return P, zac, "".join(zaklad)


def _tr(znaky):
    return "[" + "".join(map(re.escape, sorted(znaky))) + "]"


def _nebo(alts):
    """Alternativy (délka, regex): delší dřív, aby vyhrál nejdelší nález."""
    a = list(dict.fromkeys(r for _, r in sorted(alts, key=lambda x: -x[0])))
    return a[0] if len(a) == 1 else "(?:" + "|".join(a) + ")"


def _cteni_re(text, zap):
    """Čtení pravidla jako (nejvyšší délka v textu, regex); každý znak i se svými rovnocennostmi."""
    out = []
    for c in text:
        h = _pulky(c, zap)
        alts = [(2, _tr(h[0]) + _tr(h[1]))] if h else []
        alts += [(len(x), re.escape(x)) for x in _prime(c, zap)] + [(1, _tr(_alt(c, zap)))]
        out.append((max(n for n, _ in alts), _nebo(alts)))
    return sum(n for n, _ in out), "".join(r for _, r in out)


def _slovo_re(slovo, zameny, skupiny, zap, deleni):
    """Regex slova bez okrajů: písmena, záměny, přímá čtení celého znaku a skupiny jako hrany mezi pozicemi;
    R[i] = zbytek slova od pozice i (s volitelným znakem dělení a ≤ 250 bílými znaky před ní); zac = index první
    pozice každého znaku slova."""
    P, zac, zaklad = _pozice(slovo, zap)
    n, hrany = len(P), [{} for _ in P]   # hrany[i][cíl] = [(délka, regex)]
    for i, L in enumerate(P):
        hrany[i][i + 1] = [(1, _tr(L))] + [_cteni_re(r, zap) for c in sorted(L) for r in zameny.get(c, ())]
    for j, c in enumerate(slovo):
        i, h = zac[j], _pulky(c, zap)
        cil = hrany[i].setdefault(i + (2 if h else 1), [])
        cil += [(len(x), re.escape(x)) for x in _prime(c, zap) if h or x != c]
        cil += [_cteni_re(r, zap) for r in zameny.get(c, ())] if h else []
    for k, v in skupiny.items():
        for i in range(n - len(k) + 1):
            if k.isalpha() and zaklad[i:i + len(k)] == k:
                velke = any(x.isupper() for x in P[i]) and not any(x.islower() for x in P[i])
                hrany[i].setdefault(i + len(k), []).extend(
                    _cteni_re(r[0].upper() + r[1:] if velke else r, zap) for r in dict.fromkeys(v))   # „Ch“ → „D“
    H = f"(?:{_tr(deleni)}\\s{{0,{MEZER_PO_DELENI}}})?" if deleni else ""
    R = [(0, "")] * (n + 1)   # (nejvyšší délka bez dělení, regex)
    for i in range(n - 1, -1, -1):
        alts = [(max(d for d, _ in a) + R[c][0], _nebo(a) + R[c][1]) for c, a in hrany[i].items()]
        R[i] = (max(d for d, _ in alts), (H if i else "") + _nebo(alts))
    return [r for _, r in R], zac


@functools.cache
def _znaky_m():
    """Třída všech kombinujících znaků (kategorie M*)."""
    return "".join(re.escape(chr(i)) for i in range(0x110000) if unicodedata.category(chr(i))[0] == "M")


def _vyjimky_re(texty, zap):
    """Texty vyloucit jako jeden regex nad casefold textu (plný Unicode casefold, ß = SS, nezávisle na
    rovnocennostech) se zapnutými rovnocennostmi a sadami, bez záměn projektu."""
    zap = frozenset(zap) - {"ostre_s"}   # ß i ẞ jsou po casefold ss, stažení ss → ß by je minulo
    zameny, skupiny = _sloucena({}, zap)
    zameny = {k: [r.casefold() for r in v] for k, v in zameny.items() if k == k.casefold()}
    skupiny = {k: [r.casefold() for r in v] for k, v in skupiny.items()}
    zameny, skupiny = _uprav_pravidla(zameny, skupiny, zap)
    return re.compile("|".join(_slovo_re(uprav_slovo(t.casefold(), zap), zameny, skupiny, zap, "")[0][0]
                               for t in texty))


class Vzor:
    """Slovo, jeho rovnocenné zápisy a zkomoleniny podle pravidel jako jeden regex. Text se nemění: rovnocennosti
    jsou alternativy ve vzoru. Velikost písmen se nerozlišuje; pravidla platí pro písmeno, jak stojí ve slově
    (slovo_pravidel). Za slovem nesmí být malé písmeno, velké jen po malém (výhled bez IGNORECASE, `(?-i:…)`).
    Doba běhu není omezená pro umělé vstupy (místní nástroj, vlastní pravidla a texty)."""

    def __init__(self, slovo, pravidla=None, tvary=None):
        if not slovo:
            raise ValueError("prázdné hledané slovo")
        p = pravidla or {}
        volby = p.get("volby", {})
        zap = self.zapnute = zapnute(p)
        zameny, skupiny = _uprav_pravidla(*_sloucena(p, zap), zap)
        puvodni, slovo = slovo, uprav_slovo(slovo_pravidel(slovo), zap)
        self.slovo = slovo
        self.tvary = tvary or volby.get("tvary", "ceske")
        if self.tvary not in TVARY:
            raise ValueError(f"tvary: {self.tvary} (povolené: {', '.join(TVARY)})")
        self.znaky_deleni = (DELENI if volby.get("deleni_slova", False) else "") + \
            (MEKKE if "mekke_deleni" in zap else "")
        R, zac = _slovo_re(slovo, zameny, skupiny, zap, self.znaky_deleni)
        jadro = R[0]
        if volby.get("chybi_prvni_pismeno") and len(slovo) > 6:
            # OCR vynechalo první písmeno: další dvě písmena jen s rovnocennostmi (ö = oe, ß = ss), bez záměn
            # projektu (jinak Bönisch najde „Erich“), zbytek od pozice čtvrtého znaku (přehláska = dvě pozice)
            jadro = f"(?:{jadro}|{_cteni_re(slovo[1:3].lower(), zap)[1]}{R[zac[3]]})"
        konec = _nebo((len(k), re.escape(k)) for k in KONCOVKY) + "?" if self.tvary == "ceske" else ""
        jadro += konec
        if self.tvary == "ceske":
            # genitiv jen za slovem čteným s rovnocennostmi, ne přes záměny projektu (Kraus + záměny ≠ „Kreuzes“)
            nem = [(len(k), re.escape(k)) for k in NEMECKE if k != "s" or slovo[-1].lower() not in "sßſxz"]
            Rc, zc = _slovo_re(slovo, *_uprav_pravidla(*_sloucena({}, zap), zap), zap, self.znaky_deleni)
            cele = Rc[0]
            if volby.get("chybi_prvni_pismeno") and len(slovo) > 6:   # i bez prvního písmene (UCHBERGERS)
                cele = f"(?:{cele}|{_cteni_re(slovo[1:3].lower(), zap)[1]}{Rc[zc[3]]})"
            jadro = f"(?:{cele}{_nebo(nem)}|{jadro})"
        m = _tr(MALA)
        za = ((f"(?-i:(?!{m}|(?<!{m}){_tr(VELKA)}))" if self.tvary != "volne" else "")
              + (f"(?![{_znaky_m()}])" if zap else ""))
        self._re = re.compile(f"(?<![{re.escape(PISMENA)}\\-]){jadro}{za}", re.IGNORECASE)
        # výjimka, kterou vzor výjimek najde v hledaném slově, neplatí (Strasse s výjimkou Straße)
        vyl = [t for t in p.get("vyloucit", {}) if not _vyjimky_re([t], zap).search(puvodni.casefold())]
        self._vyloucit = _vyjimky_re(vyl, zap) if vyl else None

    def najdi(self, text, limit=None):
        """Nálezy (začátek, konec) v textu; s limit jen ty, které začínají před ním. Nález se zahodí, když úsek od
        jeho začátku do mezery obsahuje výjimku."""
        limit = len(text) if limit is None else limit
        pos = 0
        while pos < limit:
            m = self._re.search(text, pos)
            if not m or m.start() >= limit:
                return
            p, e = m.span()
            if self._vyloucit:
                w = MEZERA_RE.search(text, p)
                if self._vyloucit.search(text[p:w.start() if w else len(text)].casefold()):
                    pos = p + 1
                    continue
            yield p, e
            pos = e


# --- soubory ----------------------------------------------------------------------------------------------------

def soubory(cesty):
    """Zadané soubory a všechny *.txt ve složkách (i podsložkách), seřazené."""
    out = []
    for c in cesty:
        out += sorted(glob.glob(os.path.join(glob.escape(c), "**", "*.txt"), recursive=True)) if os.path.isdir(c) else [c]
    return out


def radky(soubor):
    """Řádky souboru bez konce řádku, po jednom (soubor se nenačítá celý). Poškozené UTF-8 ohlásí jednou na stderr."""
    poskozenych = 0
    with open(soubor, encoding="utf-8-sig", errors="replace") as f:
        for radek in f:
            poskozenych += radek.count("�")
            yield radek[:-1] if radek.endswith("\n") else radek
    if poskozenych:
        print(f"# {soubor}: není celý v UTF-8 ({poskozenych} poškozených znaků)", file=sys.stderr)


def _dvojice(soubor):
    """(číslo řádku, řádek, další řádek nebo None)."""
    pred, i = None, 0
    for radek in radky(soubor):
        if pred is not None:
            yield i, pred, radek
        pred, i = radek, i + 1
    if pred is not None:
        yield i, pred, None


def _deleny(radek, znaky=DELENI):
    r = radek.rstrip()
    return bool(r) and r[-1] in znaky


def hledej(slovo, cesty, pravidla=None, tvary=None):
    """[(nalezený tvar, soubor, číslo řádku, řádek bez okrajových mezer, sloupec nálezu v něm), …]; dělení přes konec
    řádku se hlásí na prvním řádku (tvar s ⏎)."""
    vzor = Vzor(slovo, pravidla, tvary)
    znaky = vzor.znaky_deleni
    nalezy = []
    for f in soubory(cesty):
        for i, radek, dalsi in _dvojice(f):
            if znaky and dalsi is not None and _deleny(radek, znaky):
                text, limit = radek + "\n" + dalsi, len(radek)
            else:
                text, limit = radek, None
            odsazeni = len(radek) - len(radek.lstrip())
            for p, e in vzor.najdi(text, limit):
                nalezy.append((re.sub(r"\n\s*", "⏎", text[p:e]), f, i, radek.strip(), p - odsazeni))
    return nalezy


def ukazka(text, sloupec, tvar):
    """Výřez řádku kolem nálezu: od 40 znaků před ním, aspoň 110 znaků a vždy celá část tvaru před ⏎."""
    od = max(0, sloupec - 40)
    do = max(od + 110, sloupec + len(tvar.split("⏎")[0]))
    return ("…" if od else "") + text[od:do] + ("…" if do < len(text) else "")


def souhrn(nalezy, mist=3):
    """Řádek na nalezený tvar, od nejčastějšího: tvar, počet×, prvních pár míst, ukázka prvního (tabulátory)."""
    podle = {}
    for n in nalezy:
        podle.setdefault(n[0], []).append(n)
    out = []
    for tvar, ns in sorted(podle.items(), key=lambda x: (-len(x[1]), x[0])):
        mista = "; ".join(f"{_cesta(f)}:{i}" for _, f, i, _, _ in ns[:mist])
        if len(ns) > mist:
            mista += f"; +{len(ns) - mist} dalších"
        out.append(f"{tvar}\t{len(ns)}×\t{mista}\t{ukazka(*ns[0][3:], tvar)}")
    return out


# --- kandidáti --------------------------------------------------------------------------------------------------

def vzdalenost(a, b, k):
    """Levenshteinova vzdálenost a, b; větší než k vrátí k + 1 (výpočet skončí předčasně)."""
    if abs(len(a) - len(b)) > k:
        return k + 1
    pred = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        akt = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            akt[j] = min(pred[j] + 1, akt[j - 1] + 1, pred[j - 1] + (ca != cb))
        if min(akt) > k:
            return k + 1
        pred = akt
    return min(pred[-1], k + 1)


def mez_vzdalenosti(slovo):
    """Výchozí největší vzdálenost kandidáta podle délky slova; krátké slovo (≤ 4) ji musí mít zadanou."""
    n = len(slovo)
    if n >= 8:
        return 2
    if n >= 5:
        return 1
    raise ValueError(f"„{slovo}“ je krátké slovo – kandidátů by bylo moc; zadej --vzdalenost N (0–3)")


def navrh(cil, tvar, pravidla=None):
    """Pravidla, se kterými by hledání slova cil našlo tvar (texty jako argumenty `pridej`, volba jako argumenty
    `nastaveni.py`); existující vynechá. Jen záměna, skupina a volba; jiný rozdíl (koncovka, předpona, mezera, víc znaků) návrh nemá. Velikost písmen
    se nerozlišuje stejně jako při hledání."""
    p, cil = pravidla or {}, slovo_pravidel(cil)
    zameny, skupiny, volby = p.get("zameny", {}), p.get("skupiny", {}), p.get("volby", {})
    cil_cf, tvar_cf = [c.casefold() for c in cil], [c.casefold() for c in tvar]
    n, m = len(cil), len(tvar)
    D = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        for j in range(m + 1):
            D[i][j] = i + j if not i or not j else min(D[i - 1][j - 1] + (cil_cf[i - 1] != tvar_cf[j - 1]),
                                                       D[i - 1][j] + 1, D[i][j - 1] + 1)
    ops, i, j = [], n, m   # (T, R) po znacích; zpětně: diagonála > vypuštění > vložení
    while i or j:
        if i and j and D[i][j] == D[i - 1][j - 1] + (cil_cf[i - 1] != tvar_cf[j - 1]):
            ops.append((cil[i - 1], tvar[j - 1])); i -= 1; j -= 1
        elif i and D[i][j] == D[i - 1][j] + 1:
            ops.append((cil[i - 1], "")); i -= 1
        else:
            ops.append(("", tvar[j - 1])); j -= 1
    ops.reverse()
    stejne = lambda o: o[0].casefold() == o[1].casefold()
    bloky, k = [], 0   # (začátek, konec) úseků neshod v ops
    while k < len(ops):
        if stejne(ops[k]):
            k += 1
            continue
        z = k
        while k < len(ops) and not stejne(ops[k]):
            k += 1
        bloky.append((z, k))
    out = []
    for z, k in bloky:
        T = "".join(t for t, _ in ops[z:k])
        R = "".join(r for _, r in ops[z:k])
        if not T and any(c in DELENI for c in R):
            if not volby.get("deleni_slova"):
                out.append("nastav ocr_hledej.deleni_slova ano")
        elif k == len(ops) and (not T or not R):
            pass               # koncovka: --tvary volne nebo samostatné slovo
        elif z == 0 and len(T) == 1 and not R:
            if not volby.get("chybi_prvni_pismeno"):
                out.append("nastav ocr_hledej.chybi_prvni_pismeno ano")
        elif z == 0 and not T:
            pass               # předpona: samostatné slovo
        else:
            if not T:          # vložení patří k předchozímu znaku
                T, R = ops[z - 1][0], ops[z - 1][1] + R
            elif not R:        # vypuštění k následujícímu
                T, R = T + ops[k][0], ops[k][1]
            if any(c.isspace() for c in R) or not R:
                pass
            elif len(T) == 1:
                if R not in zameny.get(T, []):
                    out.append(f"zamena {T} {R}")
            elif len(T) == 2 and T.isalpha():
                klic = T.lower()
                if T[0].isupper():
                    R = R[0].lower() + R[1:]
                if klic.islower() and R not in skupiny.get(klic, []):
                    out.append(f"skupina {klic} {R}")
    return list(dict.fromkeys(out))


def _slova(soubor, spojit, mekke=False):
    """(slovo, číslo řádku, řádek) po souborech; slovo rozdělené na konci řádku se spojí s prvním slovem dalšího
    (s volbou deleni_slova bez znaku dělení, jinak se znakem – návrh pak řekne „volba deleni_slova“; měkké dělení
    U+00AD se s mekke vynechá vždy). První slovo dalšího řádku s velkým písmenem se vrátí i samo: znak dělení může
    patřit vedlejšímu sloupci (pokračování slova „Gott-/fried“ je malé). Osamělý znak dělení („6,-“) se nespojuje."""
    preskocit = False
    znaky = DELENI + (MEKKE if mekke else "")
    for i, radek, dalsi in _dvojice(soubor):
        slova = list(SLOVO_RE.finditer(radek))
        if preskocit and slova:
            slova = slova[1:]
        preskocit = False
        if (slova and dalsi is not None and _deleny(radek, znaky) and slova[-1].end() == len(radek.rstrip())
                and len(slova[-1].group(0)) > 1):
            prvni = SLOVO_RE.match(dalsi, len(dalsi) - len(dalsi.lstrip()))
            if prvni:
                posledni = slova.pop().group(0)
                zkratit = spojit or posledni[-1] == MEKKE
                yield (posledni[:-1] if zkratit else posledni) + prvni.group(0), i, radek
                preskocit = not prvni.group(0)[0].isupper()
        for s in slova:
            yield s.group(0), i, radek


def kandidati(slova, cesty, pravidla=None, mez=None, tvary=None):
    """{slovo: [(tvar, počet, vzdálenost, návrhy, (soubor, řádek, text))]}: slova blízká hledanému, která pravidla
    nenajdou. Jeden průchod soubory; počty se drží jen u kandidátů."""
    p = pravidla or {}
    meze = [mez_vzdalenosti(s) if mez is None else mez for s in slova]
    vzory = [Vzor(s, p, tvary) for s in slova]
    cf = [s.casefold() for s in slova]
    vyloucit = [t.casefold() for t in p.get("vyloucit", {})]
    nejkratsi = min(len(s) - k for s, k in zip(slova, meze))
    nejdelsi = max(len(s) + k for s, k in zip(slova, meze))
    spojit = p.get("volby", {}).get("deleni_slova", False)
    mekke = "mekke_deleni" in zapnute(p)
    memo, nalez = {}, [dict() for _ in slova]
    for f in soubory(cesty):
        for w, i, radek in _slova(f, spojit, mekke):
            if not nejkratsi <= len(w) <= nejdelsi:
                continue
            vysl = memo.get(w)
            if vysl is None:
                wcf, vysl = w.casefold(), []
                for x, (s, k) in enumerate(zip(cf, meze)):
                    d = vzdalenost(wcf, s, k)
                    if (d <= k and next(vzory[x].najdi(w), None) is None
                            and not any(t in wcf for t in vyloucit)):
                        vysl.append((x, d))
                vysl = tuple(vysl)
                if len(memo) >= MEMO:
                    memo.clear()
                memo[w] = vysl
            for x, d in vysl:
                z = nalez[x].get(w)
                if z is None:
                    nalez[x][w] = [1, d, (f, i, radek.strip())]
                else:
                    z[0] += 1
    out = {}
    for x, s in enumerate(slova):
        rad = [(w, n, d, navrh(s, w, p), pr) for w, (n, d, pr) in nalez[x].items()]
        rad.sort(key=lambda r: (r[2], -r[1], r[0]))
        out[s] = rad
    return out


# --- zápis pravidel ---------------------------------------------------------------------------------------------

def zmen_pravidla(zmena, cesta=PRAVIDLA):
    """Čtení, kontrola, změna a zápis pod jedním zámkem (zapis.zamek není reentrantní, proto ne zapis.zapis()).
    zmena(p) změní slovník na místě a vrátí (změněno, zpráva)."""
    import zapis   # až tady: mimo projekt zapis.py při importu skončí, hledání ale jde i bez projektu
    with zapis.zamek("ocr_zameny"):
        p = _precti(cesta)
        p = {} if p is None else p
        zmeneno, zprava = zmena(p)
        chyby = chyby_pravidel(p)
        if chyby:
            sys.exit("\n".join(f"CHYBA: {c} – nic jsem nezměnil" for c in chyby))
        if zmeneno:
            zapis.zapis_atomicky(cesta, json.dumps(p, ensure_ascii=False, indent=1) + "\n")
    return zprava


def _pokryto(druh, klic, cteni, zap):
    """Název zapnuté rovnocennosti nebo sady, která čtení klíče už pokryje, jinak None."""
    if druh == "zamena":
        for nazev in SADY_PRAVOPISU:
            if nazev in zap and cteni in SADY_PRAVOPISU[nazev]["zameny"].get(klic, ()):
                return nazev
    if "rozlozene" in zap and klic != cteni and \
            unicodedata.normalize("NFC", klic) == unicodedata.normalize("NFC", cteni):
        return "rozlozene"
    for nazev in ROVNOCENNOSTI:
        if nazev in zap and nazev != "rozlozene" and uprav_slovo(klic, {nazev}) == uprav_slovo(cteni, {nazev}):
            return nazev
    return None


def _popis_zapnutych(zap):
    return ", ".join(k for k in VSE if k in zap) or "žádné"


def _zmena(akce, druh, args, proc):
    """Funkce změny pravidel pro příkaz pridej/odeber (chybné argumenty ukončí program)."""
    pridat = akce == "pridej"
    if druh in ("volba", "rovnocennost"):
        k = args[0] if args and args[0] in NASTAVENI_SEKCE["ocr_hledej"] else "<klíč>"
        v = args[1] if len(args) == 2 else "ano" if pridat else "vychozi" if druh == "volba" else "ne"
        sys.exit(f"{akce} {druh}: volby hledání jsou teď v nastavení projektu – se souhlasem uživatele "
                 f"python3 -I tools/nastaveni.py nastav ocr_hledej.{k} {v} (všechny volby: nastaveni.py ukaz "
                 "ocr_hledej) – nic jsem nezměnil")
    if druh in ("zamena", "skupina"):
        if len(args) < 2:
            sys.exit(f"{akce} {druh} <{'znak' if druh == 'zamena' else 'dvojice'}> <čtení>…")
        sekce, klic, cteni = "zameny" if druh == "zamena" else "skupiny", args[0], args[1:]

        def z(p):
            s = p.setdefault(sekce, {})
            if pridat:
                nove = [r for r in dict.fromkeys(cteni) if r not in s.get(klic, [])]
                if not nove:
                    return False, f"{druh} {klic}: {' '.join(cteni)} už tam je, nic jsem nezměnil"
                s.setdefault(klic, []).extend(nove)
                zap = zapnute({"volby": volby_hledani()})
                pokryte = [f"{r} (už pokryto výchozí rovnocenností {n}, uloženo pro případ vypnutí)"
                           for r in nove for n in [_pokryto(druh, klic, r, zap)] if n]
                return True, f"přidáno: {druh} {klic} → {' '.join(nove)}" + "".join(f"\n  {x}" for x in pokryte)
            pryc = [r for r in cteni if r in s.get(klic, [])]
            if not pryc:
                if not s:
                    del p[sekce]
                return False, f"{druh} {klic}: {' '.join(cteni)} tam není, nic jsem nezměnil"
            s[klic] = [r for r in s[klic] if r not in pryc]
            if not s[klic]:
                del s[klic]
            if not s:
                del p[sekce]
            return True, f"odebráno: {druh} {klic} → {' '.join(pryc)}"
        return z
    if druh == "vyloucit":
        if len(args) != 1:
            sys.exit(f"{akce} vyloucit <text> [--proc \"důvod\"]")
        text = args[0]

        def z(p):
            s = p.setdefault("vyloucit", {})
            if pridat:
                if text in s and (proc is None or s[text] == proc):
                    return False, f"vyloucit {text}: už tam je, nic jsem nezměnil"
                s[text] = proc if proc is not None else s.get(text, "")
                return True, f"přidáno: vyloucit {text}"
            if text not in s:
                if not s:
                    del p["vyloucit"]
                return False, f"vyloucit {text}: tam není, nic jsem nezměnil"
            del s[text]
            if not s:
                del p["vyloucit"]
            return True, f"odebráno: vyloucit {text}"
        return z
    sys.exit(f"{akce}: neznámý druh pravidla „{druh}“ (zamena, skupina, vyloucit)")


# --- příkazová řádka --------------------------------------------------------------------------------------------

def _volby(argv, povolene):
    """Odstraní volby (--x hodnota) před --; vrátí (zbytek, volby, cesty nebo None)."""
    cesty = None
    if "--" in argv:
        argv, cesty = argv[:argv.index("--")], argv[argv.index("--") + 1:]
    zbytek, volby, i = [], {}, 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            if a not in povolene:
                sys.exit(f"Neznámá volba {a} (povolené: {', '.join(povolene) or 'žádné'})")
            if i + 1 >= len(argv):
                sys.exit(f"Volba {a} potřebuje hodnotu")
            if a == "--volba":   # opakovatelná
                volby.setdefault("volba", []).append(argv[i + 1])
            else:
                volby[a[2:]] = argv[i + 1]
            i += 2
        else:
            zbytek.append(a)
            i += 1
    return zbytek, volby, cesty


def _cesta(f):
    try:   # absolutní cesta (výchozí pracovni/) přes realpath: /var → /private/var na macOS
        return os.path.relpath(os.path.realpath(f), os.path.realpath(os.getcwd())) if os.path.isabs(f) else os.path.relpath(f)
    except ValueError:   # Windows: jiný disk
        return f


def _pravidla_cli(volby):
    """Pravidla ze souboru + volby hledání z nastavení (a --volba) ve vnitřním tvaru p["volby"]."""
    cesta = volby.get("pravidla", PRAVIDLA)
    p = _precti(cesta)
    if p is None and "pravidla" in volby:
        sys.exit(f"Nenalezeno: {cesta}")
    p = dict(p or {}, volby=volby_hledani(volby.get("volba", [])))
    kde = f"pravidla: {_cesta(cesta)}" if len(p) > 1 else "pravidla: žádná – hledám celé slovo"
    print(f"# {kde}; rovnocennosti: {_popis_zapnutych(zapnute(p))}", file=sys.stderr)
    return p


def _cesty_cli(cesty):
    cesty = cesty if cesty else [os.path.join(ROOT, "pracovni")]
    chybi = [c for c in cesty if not os.path.exists(c)]
    if chybi:
        sys.exit(f"Nenalezeno: {', '.join(chybi)}")
    return cesty


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        sys.exit(__doc__)
    prikaz, argv = argv[0], argv[1:]
    if prikaz in ("hledej", "kandidati"):
        povolene = ["--tvary", "--pravidla", "--volba"] + (["--vzdalenost", "--max"] if prikaz == "kandidati"
                                                            else ["--vypis"])
        slova, volby, cesty = _volby(argv, povolene)
        if not slova:
            sys.exit(__doc__)
        tvary = volby.get("tvary")
        if tvary is not None and tvary not in TVARY:
            sys.exit(f"--tvary: {' | '.join(TVARY)}")
        try:
            k = None if "vzdalenost" not in volby else int(volby["vzdalenost"])
            nejvic = int(volby.get("max", 40))
        except ValueError:
            sys.exit("--vzdalenost a --max jsou celá čísla")
        vypis = volby.get("vypis", "souhrn")
        if vypis not in ("souhrn", "radky"):
            sys.exit("--vypis: souhrn | radky")
        for s in slova:
            if os.path.exists(s):
                print(f"# pozor: „{s}“ je existující cesta – hledám ji jako slovo; soubory a složky patří za --",
                      file=sys.stderr)
        p = _pravidla_cli(volby)
        cesty = _cesty_cli(cesty)
        n = len(soubory(cesty))
        print(f"# prohledáno: {n} soubor{'' if n == 1 else 'y' if 2 <= n <= 4 else 'ů'}", file=sys.stderr)
        if prikaz == "hledej":
            for s in slova:
                nalezy = hledej(s, cesty, p, tvary)
                if vypis == "radky":
                    for tvar, f, i, text, sloupec in nalezy:
                        print(f"{s}\t{tvar}\t{_cesta(f)}:{i}\t{ukazka(text, sloupec, tvar)}")
                else:
                    for radek in souhrn(nalezy):
                        print(f"{s}\t{radek}")
                print(f"# {s}: {len(nalezy)} výskytů", file=sys.stderr)
            return
        if k is not None and not 0 <= k <= 3:
            sys.exit("--vzdalenost: 0 až 3")
        try:
            vysledek = kandidati(slova, cesty, p, k, tvary)
        except ValueError as e:
            sys.exit(str(e))
        for s in slova:
            rad = vysledek[s]
            for w, n, d, navrhy, (f, i, _) in rad[:nejvic]:
                print(f"{s}\t{w}\t{n}×\t{d}\t{'; '.join(navrhy)}\t{_cesta(f)}:{i}")
            mez = k if k is not None else mez_vzdalenosti(s)
            print(f"# {s}: {len(rad)} kandidátů (vzdálenost ≤ {mez}), nic jsem nezapsal – pravidlo přidej až "
                  "po souhlasu", file=sys.stderr)
        return
    if prikaz in ("pridej", "odeber"):
        args, volby, _ = _volby(argv, ["--proc"])
        if not args:
            sys.exit(__doc__)
        print(zmen_pravidla(_zmena(prikaz, args[0], args[1:], volby.get("proc"))))
        return
    if prikaz == "pravidla":
        p = _precti(PRAVIDLA)
        if p is None:
            print("Pravidla zatím nejsou (data/ocr_zameny.json chybí) – hledá se celé slovo s českými koncovkami a genitivem -s/-es.")
        else:
            print(json.dumps(p, ensure_ascii=False, indent=1))
        zap = zapnute({"volby": volby_hledani()})
        print(f"Zapnuté rovnocennosti (nastaveni.py ukaz ocr_hledej): {_popis_zapnutych(zap)}")
        for k in VSE:
            print(f"  {'+' if k in zap else '-'} {k}: {NASTAVENI_SEKCE['ocr_hledej'][k]['popis']}")
        return
    sys.exit(f"Neznámý příkaz „{prikaz}“\n\n{__doc__}")


if __name__ == "__main__":
    main(sys.argv[1:])
