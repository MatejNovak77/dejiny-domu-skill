"""Hledání jmen a míst v OCR textech (*.txt), i když je OCR zkomolilo (Gansbauden → Sansbauben, Gan&bauben).
Záměny písmen jsou pravidla projektu v data/ocr_zameny.json (skill žádná výchozí nemá; bez souboru = celé slovo
přesně, s českými koncovkami). Postup a formát pravidel: reference/ocr.md.

Použití (z kořene projektu, volby kdekoli před --; bez -- se hledá ve všech *.txt v pracovni/):
  ocr_hledej.py hledej <slovo>… [--tvary ceske|presne|volne] [--pravidla <json>] [-- <soubor|složka>…]
      → slovo, nalezený tvar, soubor:řádek, řádek (tabulátory); počty na stderr
  ocr_hledej.py kandidati <slovo>… [--vzdalenost N] [--max 40] [--tvary …] [--pravidla <json>] [-- …]
      → slova blízká hledanému, která pravidla nenajdou, s počtem, ukázkou a návrhem pravidla; nic nezapíše
  ocr_hledej.py pridej|odeber zamena <znak> <čtení>…
  ocr_hledej.py pridej|odeber skupina <dvě malá písmena> <čtení>…
  ocr_hledej.py pridej|odeber vyloucit <text> [--proc "důvod"]
  ocr_hledej.py pridej|odeber volba deleni_slova|chybi_prvni_pismeno [ano|ne]
  ocr_hledej.py pridej|odeber volba tvary ceske|presne|volne
  ocr_hledej.py pravidla
Pravidlo přidávej jen se souhlasem uživatele. Pravopisné varianty jmen (Zinecker / Zinnecker) hledej jako
samostatná slova.
"""
import glob, json, os, re, sys

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
CACHE = 100_000       # položek lazy DFA (přechod množiny stavů znakem)
MEMO = 200_000        # slov v paměti kandidátů
SLOVO_RE = re.compile(r"[^\s.,;:!?\"'„“”‚‘’»«()\[\]{}<>/|*]+")


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
            else:
                chyby.append(f"neznámá volba „{k}“ (povolené: {', '.join(VOLBY_BOOL + ('tvary',))})")
    return chyby


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

class Vzor:
    """Slovo a jeho zkomoleniny podle pravidel jako NFA; simulace množinami stavů (bez backtrackingu).

    Doba hledání v řádku délky m je nejvýš O(m · maxlen) kroků; přechody množin stavů jsou v omezené cache."""

    def __init__(self, slovo, pravidla=None, tvary=None):
        if not slovo:
            raise ValueError("prázdné hledané slovo")
        p = pravidla or {}
        zameny, skupiny, volby = p.get("zameny", {}), p.get("skupiny", {}), p.get("volby", {})
        self.slovo = slovo
        self.tvary = tvary or volby.get("tvary", "ceske")
        if self.tvary not in TVARY:
            raise ValueError(f"tvary: {self.tvary} (povolené: {', '.join(TVARY)})")
        deleni = volby.get("deleni_slova", False)
        n = len(slovo)
        self._prechody = []   # stav → {znak: [stav, …]}
        self._mezera = {}     # stav → stav po bílém znaku
        self._eps = {}        # stav → [stav, …]

        def stav():
            self._prechody.append({})
            return len(self._prechody) - 1

        def retez(z, text, do):   # z --text--> do
            for c in text[:-1]:
                s = stav()
                self._prechody[z].setdefault(c, []).append(s)
                z = s
            self._prechody[z].setdefault(text[-1], []).append(do)

        J = [stav() for _ in range(n + 1)]     # vstup do hranice písmen i (sem vede přechod přes písmeno)
        jadro = list(J)                        # odsud se čte písmeno i; po dělení se vrací sem (jen 1 znak dělení)
        if deleni:
            for i in range(1, n):
                jadro[i] = stav()
                self._eps.setdefault(J[i], []).append(jadro[i])
                D = [stav() for _ in range(MEZER_PO_DELENI + 1)]   # D[k] = po znaku dělení a k bílých znacích
                for c in DELENI:
                    self._prechody[J[i]].setdefault(c, []).append(D[0])
                for k in range(MEZER_PO_DELENI):
                    self._mezera[D[k]] = D[k + 1]
                for d in D:
                    self._eps.setdefault(d, []).append(jadro[i])
        maxlen = 0
        for i, c in enumerate(slovo):
            cteni = [c] + [r for r in zameny.get(c, []) if r != c]
            nejdelsi = 0
            for r in dict.fromkeys(cteni):
                retez(jadro[i], r, J[i + 1])
                nejdelsi = max(nejdelsi, len(r))
            d = slovo[i:i + 2]
            if len(d) == 2 and d.isalpha() and d.lower() in skupiny:   # skupina se přidává k záměnám po písmenech
                for r in dict.fromkeys(skupiny[d.lower()]):
                    if d[0].isupper():
                        r = r[0].upper() + r[1:]   # „Ch“ → „D“
                    if r != d:
                        retez(jadro[i], r, J[i + 2])
                        nejdelsi = max(nejdelsi, len(r))
            maxlen += nejdelsi
        if (volby.get("chybi_prvni_pismeno") and n > 6
                and not any(slovo[i:i + 2].isalpha() and slovo[i:i + 2].lower() in skupiny for i in range(3))):
            retez(J[0], slovo[1:3].lower(), J[3])   # OCR vynechalo první písmeno, další dvě musí sedět přesně
        self._prijmout = {J[n]}
        if self.tvary == "ceske":
            acc = stav()
            for k in KONCOVKY:
                retez(J[n], k, acc)
            self._prijmout.add(acc)
        self.maxlen = maxlen + (n - 1) * (1 + MEZER_PO_DELENI) + 5

        self._uzaver = []
        for s in range(len(self._prechody)):
            u, zasobnik = {s}, [s]
            while zasobnik:
                for t in self._eps.get(zasobnik.pop(), ()):
                    if t not in u:
                        u.add(t)
                        zasobnik.append(t)
            self._uzaver.append(frozenset(u))
        self._start = self._uzaver[J[0]]
        prvni = sorted({c for s in self._start for c in self._prechody[s]})
        self._pred = re.compile(f"(?<![{re.escape(PISMENA)}\\-])(?=[{''.join(map(re.escape, prvni))}])")
        self._cache, self._prijima = {}, {}
        hledane = slovo.casefold()
        self._vyloucit = [t.casefold() for t in p.get("vyloucit", {}) if t.casefold() not in hledane]

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

    def _konec(self, text, p):
        """Nejdelší platný konec shody začínající na p, nebo None."""
        S, j, konec = self._start, p, None
        stop, volne, delka = min(len(text), p + self.maxlen), self.tvary == "volne", len(text)
        while True:
            pr = self._prijima.get(S)
            if pr is None:
                pr = self._prijima[S] = not S.isdisjoint(self._prijmout)
            if pr and (volne or j == delka or text[j] not in MALA):
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
        token = None   # (začátek, konec, pozice znaků v casefold, nejzazší výskyt výjimky) – jednou na token
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
                if token[2][p - token[0]] <= token[3]:   # úsek text[p:] do mezery obsahuje vyloučený text
                    pos = p + 1
                    continue
            yield p, e
            pos = e

    def _token(self, text, p):
        """Úsek od p do první mezery: pozice každého znaku v casefold textu a nejzazší začátek výjimky v něm."""
        m = re.compile(r"\s").search(text, p)
        konec = m.start() if m else len(text)
        pozice, kusy, n = [], [], 0
        for c in text[p:konec]:
            pozice.append(n)
            f = c.casefold()
            kusy.append(f)
            n += len(f)
        cf = "".join(kusy)
        return p, konec, pozice, max(cf.rfind(t) for t in self._vyloucit)


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


def _deleny(radek):
    r = radek.rstrip()
    return bool(r) and r[-1] in DELENI


def hledej(slovo, cesty, pravidla=None, tvary=None):
    """[(nalezený tvar, soubor, číslo řádku, řádek), …]; dělení přes konec řádku se hlásí na prvním řádku (tvar s ⏎)."""
    vzor = Vzor(slovo, pravidla, tvary)
    deleni = (pravidla or {}).get("volby", {}).get("deleni_slova", False)
    nalezy = []
    for f in soubory(cesty):
        for i, radek, dalsi in _dvojice(f):
            if deleni and dalsi is not None and _deleny(radek):
                text, limit = radek + "\n" + dalsi, len(radek)
            else:
                text, limit = radek, None
            for p, e in vzor.najdi(text, limit):
                nalezy.append((re.sub(r"\n\s*", "⏎", text[p:e]), f, i, radek.strip()))
    return nalezy


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


def _slova(soubor, spojit):
    """(slovo, číslo řádku, řádek) po souborech; slovo rozdělené na konci řádku se spojí s prvním slovem dalšího
    (s volbou deleni_slova bez znaku dělení, jinak se znakem – návrh pak řekne „volba deleni_slova“)."""
    preskocit = False
    for i, radek, dalsi in _dvojice(soubor):
        slova = list(SLOVO_RE.finditer(radek))
        if preskocit and slova:
            slova = slova[1:]
        preskocit = False
        if slova and dalsi is not None and _deleny(radek) and slova[-1].end() == len(radek.rstrip()):
            prvni = SLOVO_RE.match(dalsi, len(dalsi) - len(dalsi.lstrip()))
            if prvni:
                posledni = slova.pop().group(0)
                yield (posledni[:-1] if spojit else posledni) + prvni.group(0), i, radek
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
    memo, nalez = {}, [dict() for _ in slova]
    for f in soubory(cesty):
        for w, i, radek in _slova(f, spojit):
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


def _zmena(akce, druh, args, proc):
    """Funkce změny pravidel pro příkaz pridej/odeber (chybné argumenty ukončí program)."""
    pridat = akce == "pridej"
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
                return True, f"přidáno: {druh} {klic} → {' '.join(nove)}"
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
            sys.exit(f"{akce} volba deleni_slova|chybi_prvni_pismeno [ano|ne] | {akce} volba tvary ceske|presne|volne")
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
        if nazev == "tvary":
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
    sys.exit(f"{akce}: neznámý druh pravidla „{druh}“ (zamena, skupina, vyloucit, volba)")


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
        print("# pravidla: žádná – hledám celé slovo", file=sys.stderr)
        return {}
    print(f"# pravidla: {_cesta(cesta)}", file=sys.stderr)
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
        povolene = ["--tvary", "--pravidla"] + (["--vzdalenost", "--max"] if prikaz == "kandidati" else [])
        slova, volby, cesty = _volby(argv, povolene)
        if not slova:
            sys.exit(__doc__)
        tvary = volby.get("tvary")
        if tvary is not None and tvary not in TVARY:
            sys.exit(f"--tvary: {' | '.join(TVARY)}")
        p = _pravidla_cli(volby)
        cesty = _cesty_cli(cesty)
        if prikaz == "hledej":
            for s in slova:
                nalezy = hledej(s, cesty, p, tvary)
                for tvar, f, i, radek in nalezy:
                    print(f"{s}\t{tvar}\t{_cesta(f)}:{i}\t{radek[:110]}")
                print(f"# {s}: {len(nalezy)} výskytů", file=sys.stderr)
            return
        try:
            k = None if "vzdalenost" not in volby else int(volby["vzdalenost"])
            nejvic = int(volby.get("max", 40))
        except ValueError:
            sys.exit("--vzdalenost a --max jsou celá čísla")
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
        return
    sys.exit(f"Neznámý příkaz „{prikaz}“\n\n{__doc__}")


if __name__ == "__main__":
    main(sys.argv[1:])
