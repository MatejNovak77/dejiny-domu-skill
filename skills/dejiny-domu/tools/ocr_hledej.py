"""Hledání jmen a míst v OCR textech (*.txt), i když je OCR zkomolilo (Gansbauden → Sansbauben, Gan&bauben).
Výchozí rovnocennosti platí i bez souboru pravidel: ſ = s, ꝛ = r, ß = ss, ä ö ü = ae oe ue = aͤ oͤ uͤ, rozložené
tvary písmen (e + U+030C = ě), měkké dělení U+00AD a česká sada pravopisu před 1849 (Wáclaw, Gilemnice). Jsou to
čtení hledaného slova – prohledávaný text se nemění. Záměny písmen z OCR jsou pravidla projektu
v data/ocr_zameny.json (bez souboru = celé slovo s rovnocennostmi a českými koncovkami). Postup: reference/ocr.md.

Použití (z kořene projektu, volby kdekoli před --; bez -- se hledá ve všech *.txt v pracovni/):
  ocr_hledej.py hledej <slovo>… [--tvary ceske|presne|volne] [--fonetika kolnska [--max 40]] [--pravidla <json>]
                [-- <soubor|složka>…]
      → slovo, nalezený tvar, soubor:řádek, řádek (tabulátory); počty na stderr; s fonetikou navíc souhrn
        podobně znějících slov (slovo, „fonetika“, tvar, počet×, první výskyt) – nejsou to nálezy
  ocr_hledej.py kandidati <slovo>… [--vzdalenost N] [--max 40] [--tvary …] [--pravidla <json>] [-- …]
      → slova blízká hledanému, která pravidla nenajdou, s počtem, ukázkou a návrhem pravidla; nic nezapíše
  ocr_hledej.py pridej|odeber zamena <znak> <čtení>…
  ocr_hledej.py pridej|odeber skupina <dvě malá písmena> <čtení>…
  ocr_hledej.py pridej|odeber vyloucit <text> [--proc "důvod"]
  ocr_hledej.py pridej|odeber volba deleni_slova|chybi_prvni_pismeno [ano|ne]
  ocr_hledej.py pridej|odeber volba tvary ceske|presne|volne
  ocr_hledej.py pridej|odeber volba fonetika kolnska
  ocr_hledej.py pridej|odeber rovnocennost <název>|vse
  ocr_hledej.py pravidla
Pravidlo, rovnocennost i volbu měň jen se souhlasem uživatele. Pravopisné varianty jmen (Zinecker / Zinnecker)
hledej jako samostatná slova.
"""
import glob, json, os, re, sys, unicodedata

for _s in (sys.stdout, sys.stderr):   # UTF-8 výstup i na Windows bez -X utf8
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I nepřidá složku skriptu sama (import zapis)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRAVIDLA = os.path.join(ROOT, "data", "ocr_zameny.json")

_LATIN = [chr(i) for i in range(0x250)]
PISMENA = "".join(c for c in _LATIN if c.isalpha())    # před slovem nesmí být písmeno (číslice smí: „22Gansbauden“)
MALA = frozenset(c for c in _LATIN if c.islower())       # za slovem nesmí pokračovat malé písmeno
DELENI = "-⸗=¬"                                          # znaky dělení slova („Gans-bauden“, „Gans⸗ bauden“)
MEZER_PO_DELENI = 250                                    # nejvíc bílých znaků po znaku dělení (i přes konec řádku)
KONCOVKY = ("a e u y i em ů ům ech ovi ové ová ovou ových ovým ovými ův ova ovo ovu ovy ovic").split()
TVARY = ("ceske", "presne", "volne")
SEKCE = ("poznamka", "zameny", "skupiny", "vyloucit", "volby")
VOLBY_BOOL = ("deleni_slova", "chybi_prvni_pismeno")
FONETIKY = ("kolnska",)
CACHE = 100_000       # položek lazy DFA (přechod množiny stavů znakem)
MEMO = 200_000        # slov v paměti kandidátů a fonetiky
SLOVO_RE = re.compile(r"[^\s.,;:!?\"'„“”‚‘’»«()\[\]{}<>/|*]+")
MEZERA_RE = re.compile(r"\s")

# Rovnocennosti: stejný znak jinak zapsaný. Platí jen na straně hledaného slova (čtení v automatu), text se nemění.
DLOUHE_S, R_ROTUNDA, NAD_E, MEKKE = "\u017f", "\ua75b", "\u0364", "\u00ad"   # ſ, ꝛ, kombinující malé e, U+00AD
OSTRE, OSTRE_VELKE = "\u00df", "\u1e9e"                                      # ß, ẞ
PREHLASKY = {"ä": "a", "ö": "o", "ü": "u", "Ä": "A", "Ö": "O", "Ü": "U"}
ZE_ZAKLADU = {v: k for k, v in PREHLASKY.items()}
STAZENI = {"ae": "ä", "Ae": "Ä", "AE": "Ä", "oe": "ö", "Oe": "Ö", "OE": "Ö", "ue": "ü", "Ue": "Ü", "UE": "Ü",
           "ss": OSTRE, "SS": OSTRE_VELKE}
ROVNOCENNOSTI = {
    "dlouhe_s": "ſ = s",
    "r_rotunda": "ꝛ = r",
    "ostre_s": "ß = ss (i ſs, sſ, ſſ; ẞ = SS)",
    "prehlasky": "ä ö ü = ae oe ue = aͤ oͤ uͤ (i velká)",
    "rozlozene": "rozložené tvary písmen (e + U+030C = ě, a + U+0308 = ä)",
    "mekke_deleni": "měkké dělení U+00AD jako znak dělení slova",
}
# Sady historického pravopisu: pravidla (ne normalizace), sloučí se s pravidly projektu. Prameny: reference/ocr.md.
SADY_PRAVOPISU = {
    "cestina_1849": {   # bratrský pravopis do 1849: jen dnešní slovo → starý zápis (Václav → Wáclaw)
        "popis": "čeština před 1849: v→w, j→g, í→j, ou→au, š→ss (jen dnešní slovo → starý zápis)",
        "zameny": {"v": ["w"], "V": ["W"], "j": ["g"], "J": ["G"], "í": ["j"], "Í": ["J"], "š": ["ss"],
                   "Š": ["Ss", "SS"]},
        "skupiny": {"ou": ["au"]},
    },
    "nemcina_1901": {   # pravopis před 1901/1902 a varianty 19. stol., obousměrně (Thal ↔ Tal, Carl ↔ Karl)
        "popis": "němčina před 1901: th↔t, c↔k, c↔z, y↔i, ph↔f (obousměrně)",
        "zameny": {"t": ["th"], "T": ["Th", "TH"], "c": ["k", "z"], "C": ["K", "Z"], "k": ["c"], "K": ["C"],
                   "z": ["c"], "Z": ["C"], "y": ["i"], "Y": ["I"], "i": ["y"], "I": ["Y"], "f": ["ph"],
                   "F": ["Ph", "PH"]},
        "skupiny": {"th": ["t"], "ph": ["f"]},
    },
}
VSE = tuple(ROVNOCENNOSTI) + tuple(SADY_PRAVOPISU)
VYCHOZI = frozenset(VSE) - {"nemcina_1901"}


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
    chyby = []
    for k in p:
        if k not in SEKCE:
            chyby.append(f"neznámá sekce „{k}“ (povolené: {', '.join(SEKCE)})")
    if "poznamka" in p and not isinstance(p["poznamka"], str):
        chyby.append("poznamka: musí být text")
    for sekce in ("zameny", "skupiny", "vyloucit", "volby"):
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
    if isinstance(p.get("volby"), dict):
        for k, v in p["volby"].items():
            if k in VOLBY_BOOL:
                if not isinstance(v, bool):
                    chyby.append(f"volby {k}: musí být true nebo false (je {json.dumps(v, ensure_ascii=False)})")
            elif k == "tvary":
                if not (isinstance(v, str) and v in TVARY):
                    chyby.append(f"volby tvary: musí být {' | '.join(TVARY)} (je {json.dumps(v, ensure_ascii=False)})")
            elif k == "fonetika":
                if not (isinstance(v, str) and v in FONETIKY):
                    chyby.append(f"volby fonetika: musí být {' | '.join(FONETIKY)} "
                                 f"(je {json.dumps(v, ensure_ascii=False)})")
            elif k == "rovnocennosti":
                if isinstance(v, dict):
                    for n, b in v.items():
                        if n not in VSE:
                            chyby.append(f"volby rovnocennosti: neznámá položka „{n}“ (povolené: {', '.join(VSE)})")
                        elif not isinstance(b, bool):
                            chyby.append(f"volby rovnocennosti {n}: musí být true nebo false "
                                         f"(je {json.dumps(b, ensure_ascii=False)})")
                elif not isinstance(v, bool):
                    chyby.append("volby rovnocennosti: musí být true, false nebo objekt {\"název\": true|false} "
                                 f"(je {json.dumps(v, ensure_ascii=False)})")
            else:
                chyby.append(f"neznámá volba „{k}“ (povolené: "
                             f"{', '.join(VOLBY_BOOL + ('tvary', 'fonetika', 'rovnocennosti'))})")
    return chyby


def zapnute(pravidla):
    """Zapnuté rovnocennosti a sady pravopisu podle volby rovnocennosti (chybí = výchozí)."""
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


# --- automat (NFA) ----------------------------------------------------------------------------------------------

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
    rozepíše na základní písmena (äß → aess), aby seděl na pozice automatu."""
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
    """Přímá čtení celého znaku (seznamy množin): sám, rozložený tvar (NFD), ä + ͤ, ß ↔ ẞ."""
    out = [[{c}]]
    if "rozlozene" in zap:
        d = unicodedata.normalize("NFD", c)
        if d != c:
            out.append([{x} for x in d])
    if c in PREHLASKY and "prehlasky" in zap:
        out.append([{c}, {NAD_E}])
    if "ostre_s" in zap and c in (OSTRE, OSTRE_VELKE):
        out.append([{OSTRE_VELKE if c == OSTRE else OSTRE}])
    return out


def _stav(pr):
    pr.append({})
    return len(pr) - 1


def _hrana(pr, z, znaky, do):
    for c in sorted(znaky):
        pr[z].setdefault(c, []).append(do)


def _retez(pr, z, stitky, do):   # z --stitky--> do, štítek = množina znaků jedné pozice
    for L in stitky[:-1]:
        s = _stav(pr)
        _hrana(pr, z, L, s)
        z = s
    _hrana(pr, z, stitky[-1], do)


def _cteni_hrany(pr, z, text, do, zap):
    """Čtení pravidla jako řetěz; každý znak i se svými rovnocennostmi (podautomat lineární v délce čtení).
    Vrátí horní mez délky v znacích textu."""
    delka = 0
    for j, c in enumerate(text):
        cil = do if j == len(text) - 1 else _stav(pr)
        nejd = 1
        h = _pulky(c, zap)
        if h:
            _retez(pr, z, h, cil)
            nejd = 2
        for st in _prime(c, zap):
            _retez(pr, z, st, cil)
            nejd = max(nejd, len(st))
        _hrana(pr, z, _alt(c, zap) - {c}, cil)
        delka += nejd
        z = cil
    return delka


def _pozice(slovo, zap):
    """Pozice automatu (množiny znaků), index první pozice každého znaku slova a základní písmena pozic."""
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


def _hrany(pr, slovo, P, zac, zaklad, jadro, J, zameny, skupiny, zap):
    """Hrany písmen, přímých čtení, záměn a skupin; vrátí nejdelší čtení (ve znacích textu) na každé pozici."""
    nejd = [1] * len(P)
    for i, L in enumerate(P):
        _hrana(pr, jadro[i], L, J[i + 1])
        for c in sorted(L):   # záměny na pozici (i půlky přehlásky: u → n najde Mneller)
            for r in zameny.get(c, ()):
                nejd[i] = max(nejd[i], _cteni_hrany(pr, jadro[i], r, J[i + 1], zap))
    for j, c in enumerate(slovo):
        i = zac[j]
        h = _pulky(c, zap)
        konec = i + (2 if h else 1)
        for st in _prime(c, zap):
            if h or st != [{c}]:
                _retez(pr, jadro[i], st, J[konec])
                nejd[i] = max(nejd[i], len(st))
        if h:   # záměny celého znaku (ü → u) na přímou hranu
            for r in zameny.get(c, ()):
                nejd[i] = max(nejd[i], _cteni_hrany(pr, jadro[i], r, J[konec], zap))
    for k, v in skupiny.items():
        if not k.isalpha():
            continue
        for i in range(len(P) - len(k) + 1):
            if zaklad[i:i + len(k)] == k:
                velke = any(x.isupper() for x in P[i]) and not any(x.islower() for x in P[i])
                for r in dict.fromkeys(v):
                    if velke:
                        r = r[0].upper() + r[1:]   # „Ch“ → „D“
                    nejd[i] = max(nejd[i], _cteni_hrany(pr, jadro[i], r, J[i + len(k)], zap))
    return nejd


def _uzavery(pr, eps):
    out = []
    for s in range(len(pr)):
        u, zasobnik = {s}, [s]
        while zasobnik:
            for t in eps.get(zasobnik.pop(), ()):
                if t not in u:
                    u.add(t)
                    zasobnik.append(t)
        out.append(frozenset(u))
    return out


class Vyjimky:
    """Texty vyloucit jako jeden obrácený automat nad casefold znaků textu (plný Unicode casefold i víceznakový,
    ß = SS, nezávisle na rovnocennostech) se zapnutými rovnocennostmi a sadami, bez záměn projektu. Běží zprava
    doleva bez kotvy, takže první přijetí je nejzazší začátek výjimky; text se nekopíruje."""

    def __init__(self, texty, zap):
        zap = frozenset(zap) - {"ostre_s"}   # ß i ẞ jsou po casefold ss, stažení ss → ß by je minulo
        zameny, skupiny = _sloucena({}, zap)
        zameny = {k: [r.casefold() for r in v] for k, v in zameny.items() if k == k.casefold()}
        skupiny = {k: [r.casefold() for r in v] for k, v in skupiny.items()}
        zameny, skupiny = _uprav_pravidla(zameny, skupiny, zap)
        pr = []
        zacatek, konec = _stav(pr), _stav(pr)
        for t in texty:
            x = uprav_slovo(t.casefold(), zap)
            P, zac, zaklad = _pozice(x, zap)
            J = [zacatek] + [_stav(pr) for _ in range(len(P) - 1)] + [konec]
            _hrany(pr, x, P, zac, zaklad, J, J, zameny, skupiny, zap)
        self._pr = [{} for _ in pr]   # obrácené hrany
        for s, d in enumerate(pr):
            for ch, cile in d.items():
                for t in cile:
                    self._pr[t].setdefault(ch, []).append(s)
        self._zac, self._prijmout, self._cache = frozenset({konec}), zacatek, {}

    def nejzazsi(self, text, a, b):
        """Index nejzazšího znaku text[a:b], ve kterém začíná některá výjimka (i uprostřed jeho casefold), nebo -1."""
        S = self._zac
        for q in range(b - 1, a - 1, -1):
            for ch in reversed(text[q].casefold()):
                klic = (S, ch)
                T = self._cache.get(klic)
                if T is None:
                    T = frozenset(t for s in S for t in self._pr[s].get(ch, ()))
                    if len(self._cache) >= CACHE:
                        self._cache.clear()
                    self._cache[klic] = T
                if self._prijmout in T:
                    return q
                S = T | self._zac
        return -1


class Vzor:
    """Slovo, jeho rovnocenné zápisy a zkomoleniny podle pravidel jako NFA; simulace množinami stavů (bez
    backtrackingu). Text se nemění: rovnocennosti jsou pozice s více znaky a přímá čtení ve slově.

    Doba hledání v řádku délky m je nejvýš O(m · maxlen) kroků; přechody množin stavů jsou v omezené cache."""

    def __init__(self, slovo, pravidla=None, tvary=None):
        if not slovo:
            raise ValueError("prázdné hledané slovo")
        p = pravidla or {}
        volby = p.get("volby", {})
        zap = self.zapnute = zapnute(p)
        zameny, skupiny = _uprav_pravidla(*_sloucena(p, zap), zap)
        puvodni, slovo = slovo, uprav_slovo(slovo, zap)
        self.slovo = slovo
        self.tvary = tvary or volby.get("tvary", "ceske")
        if self.tvary not in TVARY:
            raise ValueError(f"tvary: {self.tvary} (povolené: {', '.join(TVARY)})")
        self.znaky_deleni = (DELENI if volby.get("deleni_slova", False) else "") + \
            (MEKKE if "mekke_deleni" in zap else "")
        self._konec_znaku = bool(zap)   # za nálezem nesmí být kombinující znak (Mu nenajde začátek Mu + U+0308)
        P, zac, zaklad = _pozice(slovo, zap)
        n = len(P)
        pr = self._prechody = []   # stav → {znak: [stav, …]}
        self._mezera = {}          # stav → stav po bílém znaku
        self._eps = {}             # stav → [stav, …]
        J = [_stav(pr) for _ in range(n + 1)]   # vstup do hranice pozic i (sem vede přechod přes pozici)
        jadro = list(J)                          # odsud se čte pozice i; po dělení se vrací sem (jen 1 znak dělení)
        if self.znaky_deleni:
            for i in range(1, n):
                jadro[i] = _stav(pr)
                self._eps.setdefault(J[i], []).append(jadro[i])
                D = [_stav(pr) for _ in range(MEZER_PO_DELENI + 1)]   # D[k] = po znaku dělení a k bílých znacích
                for c in self.znaky_deleni:
                    pr[J[i]].setdefault(c, []).append(D[0])
                for k in range(MEZER_PO_DELENI):
                    self._mezera[D[k]] = D[k + 1]
                for d in D:
                    self._eps.setdefault(d, []).append(jadro[i])
        nejd = _hrany(pr, slovo, P, zac, zaklad, jadro, J, zameny, skupiny, zap)
        if (volby.get("chybi_prvni_pismeno") and len(slovo) > 6 and not any(_pulky(c, zap) for c in slovo[:3])
                and not any(zaklad[i:i + len(k)] == k for i in range(3) for k in skupiny)):
            _retez(pr, J[0], [{c} for c in slovo[1:3].lower()], J[3])   # OCR vynechalo první písmeno
        self._prijmout = {J[n]}
        if self.tvary == "ceske":
            acc = _stav(pr)
            for k in KONCOVKY:
                _retez(pr, J[n], [{c} for c in k], acc)
            self._prijmout.add(acc)
        self.maxlen = sum(nejd) + (n - 1) * (1 + MEZER_PO_DELENI) + 5
        self._uzaver = _uzavery(pr, self._eps)
        self._start = self._uzaver[J[0]]
        prvni = sorted({c for s in self._start for c in pr[s]})
        self._pred = re.compile(f"(?<![{re.escape(PISMENA)}\\-])(?=[{''.join(map(re.escape, prvni))}])")
        self._cache, self._prijima = {}, {}
        # výjimka, kterou automat výjimek najde v hledaném slově, neplatí (Strasse s výjimkou Straße)
        vyl = [t for t in p.get("vyloucit", {}) if Vyjimky([t], zap).nejzazsi(puvodni, 0, len(puvodni)) < 0]
        self._vyloucit = Vyjimky(vyl, zap) if vyl else None

    def _krok(self, S, ch):
        klic = (S, ch)
        r = self._cache.get(klic)
        if r is None:
            out = set()
            mezera = ch.isspace()
            for s in S:
                for t in self._prechody[s].get(ch, ()):
                    out |= self._uzaver[t]
                if mezera and s in self._mezera:
                    out |= self._uzaver[self._mezera[s]]
            r = frozenset(out)
            if len(self._cache) >= CACHE:
                self._cache.clear()
            self._cache[klic] = r
        return r

    def _platny_konec(self, text, j):
        """Za nálezem nesmí být kombinující znak (kategorie M, všechny režimy) a mimo volne ani malé písmeno."""
        if j == len(text):
            return True
        c = text[j]
        if self.tvary != "volne" and c in MALA:
            return False
        return not (self._konec_znaku and unicodedata.category(c)[0] == "M")

    def _konec(self, text, p):
        """Nejdelší platný konec shody začínající na p, nebo None."""
        S, j, konec = self._start, p, None
        stop = min(len(text), p + self.maxlen)
        while True:
            pr = self._prijima.get(S)
            if pr is None:
                pr = self._prijima[S] = not S.isdisjoint(self._prijmout)
            if pr and self._platny_konec(text, j):
                konec = j
            if j >= stop:
                return konec
            S = self._krok(S, text[j])
            j += 1
            if not S:
                return konec

    def najdi(self, text, limit=None):
        """Nálezy (začátek, konec) v textu; s limit jen ty, které začínají před ním."""
        limit = len(text) if limit is None else limit
        token = None   # (začátek, konec, nejzazší začátek výjimky) – jednou na token
        pos = 0
        while pos < limit:
            m = self._pred.search(text, pos, limit)
            if not m:
                return
            p = m.start()
            e = self._konec(text, p)
            if e is None:
                pos = p + 1
                continue
            if self._vyloucit:
                if token is None or not (token[0] <= p < token[1]):
                    token = self._token(text, p)
                if p <= token[2]:   # úsek text[p:] do mezery obsahuje vyloučený text
                    pos = p + 1
                    continue
            yield p, e
            pos = e

    def _token(self, text, p):
        """Úsek od p do první mezery a index znaku, kde v něm začíná nejzazší výjimka (-1 = žádná)."""
        m = MEZERA_RE.search(text, p)
        konec = m.start() if m else len(text)
        return p, konec, self._vyloucit.nejzazsi(text, p, konec)


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
    """[(nalezený tvar, soubor, číslo řádku, řádek), …]; dělení přes konec řádku se hlásí na prvním řádku (tvar s ⏎)."""
    vzor = Vzor(slovo, pravidla, tvary)
    znaky = vzor.znaky_deleni
    nalezy = []
    for f in soubory(cesty):
        for i, radek, dalsi in _dvojice(f):
            if znaky and dalsi is not None and _deleny(radek, znaky):
                text, limit = radek + "\n" + dalsi, len(radek)
            else:
                text, limit = radek, None
            for p, e in vzor.najdi(text, limit):
                nalezy.append((re.sub(r"\n\s*", "⏎", text[p:e]), f, i, radek.strip()))
    return nalezy


# --- fonetika ---------------------------------------------------------------------------------------------------

_KOLN_PREVOD = {"ä": "a", "ö": "o", "ü": "u", OSTRE: "s", DLOUHE_S: "s", OSTRE_VELKE: "s"}


def kolnsky_kod(slovo):
    """Kölner Phonetik (Postel 1969, podle de.wikipedia „Kölner Phonetik“): písmena → číslice podle sousedů,
    sloučit sousední shodné, odstranit 0 mimo začátek. Ä Ö Ü jako samohlásky, ß ſ jako S; jiné znaky se vynechají."""
    w = unicodedata.normalize("NFC", slovo).lower()
    w = "".join(_KOLN_PREVOD.get(c, c) for c in w).upper()
    w = "".join(c for c in w if "A" <= c <= "Z")
    kody = []
    for i, c in enumerate(w):
        pred = w[i - 1] if i else ""
        dal = w[i + 1] if i + 1 < len(w) else ""
        if c in "AEIJOUY":
            k = "0"
        elif c == "H":
            k = ""
        elif c == "B":
            k = "1"
        elif c == "P":
            k = "3" if dal == "H" else "1"
        elif c in "DT":
            k = "8" if dal and dal in "CSZ" else "2"
        elif c in "FVW":
            k = "3"
        elif c in "GKQ":
            k = "4"
        elif c == "C":
            if i == 0:
                k = "4" if dal and dal in "AHKLOQRUX" else "8"
            else:
                k = "4" if dal and dal in "AHKOQUX" and pred not in ("S", "Z") else "8"
        elif c == "X":
            k = "8" if pred and pred in "CKQ" else "48"
        elif c == "L":
            k = "5"
        elif c in "MN":
            k = "6"
        elif c == "R":
            k = "7"
        else:   # S Z
            k = "8"
        kody.append(k)
    out = []
    for d in "".join(kody):   # H nemá kód, takže sousední shodné kódy kolem něj se sloučí
        if not out or out[-1] != d:
            out.append(d)
    return "".join(out[:1]) + "".join(out[1:]).replace("0", "")


def fonetika(slova, cesty, pravidla=None, tvary=None):
    """{slovo: {tvar: [počet, (soubor, řádek, text)]}}: slova s velkým prvním písmenem, která mají stejný kölnský kód
    jako hledané slovo a automat je nenajde. Jeden průchod soubory pro všechna slova; nejsou to nálezy."""
    vzory = [Vzor(s, pravidla, tvary) for s in slova]
    kody = {}
    for x, s in enumerate(slova):
        kody.setdefault(kolnsky_kod(s), []).append(x)
    out, memo = [dict() for _ in slova], {}
    for f in soubory(cesty):
        for i, radek in enumerate(radky(f), 1):
            for w in SLOVO_RE.findall(radek):
                if not w[0].isupper():
                    continue
                shody = memo.get(w)
                if shody is None:
                    shody = tuple(x for x in kody.get(kolnsky_kod(w), ()) if next(vzory[x].najdi(w), None) is None)
                    if len(memo) >= MEMO:
                        memo.clear()
                    memo[w] = shody
                for x in shody:
                    z = out[x].get(w)
                    if z is None:
                        out[x][w] = [1, (f, i, radek.strip())]
                    else:
                        z[0] += 1
    return dict(zip(slova, out))


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
    """Pravidla, se kterými by hledání slova cil našlo tvar (texty jako argumenty `pridej`); existující vynechá."""
    p = pravidla or {}
    zameny, skupiny, volby = p.get("zameny", {}), p.get("skupiny", {}), p.get("volby", {})
    n, m = len(cil), len(tvar)
    D = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        for j in range(m + 1):
            D[i][j] = i + j if not i or not j else min(D[i - 1][j - 1] + (cil[i - 1] != tvar[j - 1]),
                                                       D[i - 1][j] + 1, D[i][j - 1] + 1)
    ops, i, j = [], n, m   # (T, R) po znacích; zpětně: diagonála > vypuštění > vložení
    while i or j:
        if i and j and D[i][j] == D[i - 1][j - 1] + (cil[i - 1] != tvar[j - 1]):
            ops.append((cil[i - 1], tvar[j - 1])); i -= 1; j -= 1
        elif i and D[i][j] == D[i - 1][j] + 1:
            ops.append((cil[i - 1], "")); i -= 1
        else:
            ops.append(("", tvar[j - 1])); j -= 1
    ops.reverse()
    bloky, k = [], 0   # (začátek, konec) úseků neshod v ops
    while k < len(ops):
        if ops[k][0] == ops[k][1]:
            k += 1
            continue
        z = k
        while k < len(ops) and ops[k][0] != ops[k][1]:
            k += 1
        bloky.append((z, k))
    out = []
    for z, k in bloky:
        T = "".join(t for t, _ in ops[z:k])
        R = "".join(r for _, r in ops[z:k])
        if T and T.casefold() == R.casefold() and len(T) > 1:
            out.append("velikost")
        elif not T and any(c in DELENI for c in R):
            if not volby.get("deleni_slova"):
                out.append("volba deleni_slova")
        elif k == len(ops) and (not T or not R):
            out.append("koncovka")
        elif z == 0 and len(T) == 1 and not R:
            if not volby.get("chybi_prvni_pismeno"):
                out.append("volba chybi_prvni_pismeno")
        elif z == 0 and not T:
            out.append("predpona")
        else:
            if not T:          # vložení patří k předchozímu znaku
                T, R = ops[z - 1][0], ops[z - 1][1] + R
            elif not R:        # vypuštění k následujícímu
                T, R = T + ops[k][0], ops[k][1]
            if any(c.isspace() for c in R) or not R:
                out.append("bez_navrhu")
            elif len(T) == 1:
                if R not in zameny.get(T, []):
                    out.append(f"zamena {T} {R}")
            elif len(T) == 2 and T.isalpha():
                klic = T.lower()
                if T[0].isupper():
                    R = R[0].lower() + R[1:]
                if klic.islower() and R not in skupiny.get(klic, []):
                    out.append(f"skupina {klic} {R}")
                elif not klic.islower():
                    out.append("bez_navrhu")
            else:
                out.append("bez_navrhu")
    return list(dict.fromkeys(out))


def _slova(soubor, spojit, mekke=False):
    """(slovo, číslo řádku, řádek) po souborech; slovo rozdělené na konci řádku se spojí s prvním slovem dalšího
    (s volbou deleni_slova bez znaku dělení, jinak se znakem – návrh pak řekne „volba deleni_slova“; měkké dělení
    U+00AD se s mekke vynechá vždy)."""
    preskocit = False
    znaky = DELENI + (MEKKE if mekke else "")
    for i, radek, dalsi in _dvojice(soubor):
        slova = list(SLOVO_RE.finditer(radek))
        if preskocit and slova:
            slova = slova[1:]
        preskocit = False
        if slova and dalsi is not None and _deleny(radek, znaky) and slova[-1].end() == len(radek.rstrip()):
            prvni = SLOVO_RE.match(dalsi, len(dalsi) - len(dalsi.lstrip()))
            if prvni:
                posledni = slova.pop().group(0)
                zkratit = spojit or posledni[-1] == MEKKE
                yield (posledni[:-1] if zkratit else posledni) + prvni.group(0), i, radek
                preskocit = True
        for s in slova:
            yield s.group(0), i, radek


def kandidati(slova, cesty, pravidla=None, vzdalenost=None, tvary=None):
    """{slovo: [(tvar, počet, vzdálenost, návrhy, (soubor, řádek, text))]}: slova blízká hledanému, která pravidla
    nenajdou. Jeden průchod soubory; počty se drží jen u kandidátů."""
    p = pravidla or {}
    meze = [mez_vzdalenosti(s) if vzdalenost is None else vzdalenost for s in slova]
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
                    d = _vzd(wcf, s, k)
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


_vzd = vzdalenost


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


def _zapis_rovnocennosti(p, nove):
    """Kanonický zápis: shoda s výchozími = klíč pryč, vše vypnuté = false, jinak jen odchylky od výchozích."""
    volby = p.setdefault("volby", {})
    if nove == VYCHOZI:
        volby.pop("rovnocennosti", None)
    elif not nove:
        volby["rovnocennosti"] = False
    else:
        volby["rovnocennosti"] = {k: k in nove for k in VSE if (k in nove) != (k in VYCHOZI)}
    if not volby:
        del p["volby"]


def _popis_zapnutych(zap):
    return ", ".join(k for k in VSE if k in zap) or "žádné"


def _zmena(akce, druh, args, proc):
    """Funkce změny pravidel pro příkaz pridej/odeber (chybné argumenty ukončí program)."""
    pridat = akce == "pridej"
    if druh == "rovnocennost":
        if len(args) != 1:
            sys.exit(f"{akce} rovnocennost <název>|vse (názvy: {', '.join(VSE)})")
        nazev = args[0]
        if nazev != "vse" and nazev not in VSE:
            sys.exit(f"neznámá rovnocennost „{nazev}“ (povolené: {', '.join(VSE)}, vse) – nic jsem nezměnil")

        def z(p):
            pred = zapnute(p)
            if nazev == "vse":
                nove = VYCHOZI if pridat else frozenset()
            else:
                nove = pred | {nazev} if pridat else pred - {nazev}
            if nove == pred:
                return False, f"rovnocennost {nazev}: už tak je, nic jsem nezměnil (zapnuté: {_popis_zapnutych(pred)})"
            _zapis_rovnocennosti(p, nove)
            return True, f"{'zapnuto' if pridat else 'vypnuto'}: {nazev}; zapnuté rovnocennosti: {_popis_zapnutych(nove)}"
        return z
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
                zap = zapnute(p)
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
    if druh == "volba":
        if not args or len(args) > 2:
            sys.exit(f"{akce} volba deleni_slova|chybi_prvni_pismeno [ano|ne] | {akce} volba tvary ceske|presne|volne"
                     f" | {akce} volba fonetika kolnska")
        nazev = args[0]
        if not pridat:
            def z(p):
                s = p.get("volby", {})
                if nazev not in s:
                    return False, f"volba {nazev}: není nastavená, nic jsem nezměnil"
                del s[nazev]
                if not s:
                    del p["volby"]
                return True, f"odebráno: volba {nazev}"
            return z
        if nazev in ("tvary", "fonetika"):
            hodnota = args[1] if len(args) == 2 else None
        elif len(args) == 1 or args[1] in ("ano", "ne"):
            hodnota = len(args) == 1 or args[1] == "ano"
        else:
            sys.exit(f"volba {nazev}: hodnota je ano nebo ne (je „{args[1]}“) – nic jsem nezměnil")

        def z(p):
            s = p.setdefault("volby", {})
            if nazev in s and s[nazev] == hodnota:
                return False, f"volba {nazev}: už tam je, nic jsem nezměnil"
            s[nazev] = hodnota
            return True, f"přidáno: volba {nazev} = {json.dumps(hodnota, ensure_ascii=False)}"
        return z
    sys.exit(f"{akce}: neznámý druh pravidla „{druh}“ (zamena, skupina, vyloucit, volba, rovnocennost)")


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
    cesta = volby.get("pravidla", PRAVIDLA)
    p = _precti(cesta)
    if p is None:
        if "pravidla" in volby:
            sys.exit(f"Nenalezeno: {cesta}")
        print(f"# pravidla: žádná – hledám celé slovo; rovnocennosti: {_popis_zapnutych(VYCHOZI)}", file=sys.stderr)
        return {}
    print(f"# pravidla: {_cesta(cesta)}; rovnocennosti: {_popis_zapnutych(zapnute(p))}", file=sys.stderr)
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
        povolene = ["--tvary", "--pravidla", "--max"] + (["--vzdalenost"] if prikaz == "kandidati" else ["--fonetika"])
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
        p = _pravidla_cli(volby)
        cesty = _cesty_cli(cesty)
        if prikaz == "hledej":
            fon = volby.get("fonetika", p.get("volby", {}).get("fonetika"))
            if fon is not None and fon not in FONETIKY:
                sys.exit(f"--fonetika: {' | '.join(FONETIKY)}")
            if fon:
                kratke = [f"{s} ({kolnsky_kod(s) or 'prázdný'})" for s in slova if len(kolnsky_kod(s)) < 3]
                if kratke:
                    sys.exit(f"fonetika: krátký kód u {', '.join(kratke)} – méně než 3 číslice by našly stovky "
                             "nesouvisejících slov; hledej bez --fonetika")
            podobne = fonetika(slova, cesty, p, tvary) if fon else {}
            for s in slova:
                nalezy = hledej(s, cesty, p, tvary)
                for tvar, f, i, radek in nalezy:
                    print(f"{s}\t{tvar}\t{_cesta(f)}:{i}\t{radek[:110]}")
                print(f"# {s}: {len(nalezy)} výskytů", file=sys.stderr)
                if fon:
                    tvary_f = podobne[s]
                    rad = sorted(tvary_f.items(), key=lambda x: (-x[1][0], x[0]))
                    for w, (n, (f, i, _)) in rad[:nejvic]:
                        print(f"{s}\tfonetika\t{w}\t{n}×\t{_cesta(f)}:{i}")
                    print(f"# {s}: fonetika {fon} (kód {kolnsky_kod(s)}): {len(rad)} podobně znějících tvarů, "
                          f"{sum(n for n, _ in tvary_f.values())} výskytů – nejsou to nálezy, ověř je ve skenu",
                          file=sys.stderr)
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
            print("Pravidla zatím nejsou (data/ocr_zameny.json chybí) – hledá se celé slovo s českými koncovkami.")
        else:
            print(json.dumps(p, ensure_ascii=False, indent=1))
        zap = zapnute(p)
        print(f"Zapnuté rovnocennosti: {_popis_zapnutych(zap)}")
        for k in VSE:
            popis = ROVNOCENNOSTI.get(k) or SADY_PRAVOPISU[k]["popis"]
            print(f"  {'+' if k in zap else '-'} {k}: {popis}")
        return
    sys.exit(f"Neznámý příkaz „{prikaz}“\n\n{__doc__}")


if __name__ == "__main__":
    main(sys.argv[1:])
