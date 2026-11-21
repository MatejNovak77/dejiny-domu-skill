"""Nastavení skillu v projektu: data/nastaveni.json (volby po sekcích). Chybí soubor nebo klíč = výchozí hodnota;
aktualizace skillu soubor nepřepíše (není v šabloně).

Použití (z kořene projektu):
  nastaveni.py ukaz [sekce]                     všechny volby (nebo jedné sekce) s výchozími hodnotami a povolenými
                                                hodnotami; řádek „→ ZEPTEJ_SE <klíč>“ = volba nenastavená, zeptej
                                                se uživatele, než ji použiješ
  nastaveni.py nastav <sekce.klíč> <hodnota>    uloží volbu (jen se souhlasem uživatele); „vychozi“ volbu smaže
Příklad: nastaveni.py nastav pomocnici.rukopisy opus

Sekce si deklaruje každý nástroj sám literálem na nejvyšší úrovni souboru:
  NASTAVENI_SEKCE = {"<sekce>": {"<klíč>": {"vychozi": …, "hodnoty": [...] | "cele": [min, max] | "text": True,
                                            "popis": "…"}}}
„text“ = neprázdný text bez mezer na okrajích; s „"mala": True“ se ukládá malými písmeny.
„vychozi“: None = nenastaveno, zeptej se uživatele. nastaveni.py je najde v tools/*.py bez importu (ast).
Z Pythonu: import nastaveni; nastaveni.sekce("pomocnici") → {klíč: hodnota}; výjimka nastaveni.Chyba.
Neznámé sekce a klíče (z novější verze skillu) jen varují a zápis je zachová.
"""
import ast, json, os, sys
for _s in (sys.stdout, sys.stderr):   # UTF-8 výstup i na Windows bez -X utf8 (cp1250 neumí třeba „→“)
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

TOOLS = os.path.dirname(os.path.abspath(__file__))
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)   # -I nepřidá složku skriptu sama (import zapis v nastav())
ROOT = os.path.dirname(TOOLS)
SOUBOR = os.path.join(ROOT, "data", "nastaveni.json")
VERZE = 1   # verze formátu souboru, kterou tenhle nástroj zná
VYCHOZI = "vychozi"

NASTAVENI_SEKCE = {
    "pomocnici": {   # pomocníky (subagenty) pouští Claude podle SKILL.md, žádný nástroj; viz reference/pomocnici.md
        "rukopisy": {"vychozi": None, "text": True, "mala": True,
                     "popis": "model pomocníků, kteří čtou snímky ručně psaného textu (matriky, gruntovní "
                              "a pozemkové knihy, sčítací operáty, kurent); název modelu, jak ho zná hostitel "
                              "(v Claude Code alias sonnet, opus, haiku nebo fable)"},
        "ostatni": {"vychozi": "sonnet", "text": True, "mala": True,
                    "popis": "model pomocníků pro ostatní práci (tištěné zdroje, OCR texty, procházení portálů); "
                             "název modelu jako u rukopisů"},
    },
}


class Chyba(Exception):
    """Neplatné nastavení nebo deklarace sekce; text je hláška pro uživatele."""


def varuj(zprava):
    print(f"nastaveni.py: POZOR: {zprava}", file=sys.stderr)


def _deklarace(soubor, sekce):
    """Zkontroluje literál NASTAVENI_SEKCE jednoho nástroje (chyba = chyba v nástroji, ne u uživatele)."""
    kde = f"tools/{soubor}: NASTAVENI_SEKCE"
    if not isinstance(sekce, dict):
        raise Chyba(f"{kde} musí být slovník sekcí")
    for nazev, klice in sekce.items():
        if not isinstance(nazev, str) or not nazev or "." in nazev or not isinstance(klice, dict) or not klice:
            raise Chyba(f"{kde}: sekce {nazev!r} musí mít jméno bez tečky a neprázdný slovník klíčů")
        for klic, popis in klice.items():
            k = f"{kde}: {nazev}.{klic}"
            if not isinstance(klic, str) or not klic or "." in klic or not isinstance(popis, dict):
                raise Chyba(f"{k} – klíč musí být jméno bez tečky s popisem ve slovníku")
            druhy = [d for d in ("hodnoty", "cele", "text") if d in popis]
            if len(druhy) != 1 or "vychozi" not in popis or not isinstance(popis.get("popis"), str):
                raise Chyba(f"{k} – potřebuje „vychozi“, „popis“ a právě jedno z „hodnoty“, „cele“, „text“")
            h = popis[druhy[0]]
            if druhy[0] == "hodnoty" and not (isinstance(h, list) and h
                                              and all(isinstance(x, str) and x == x.lower() for x in h)):
                raise Chyba(f"{k} – „hodnoty“ musí být neprázdný seznam textů malými písmeny")
            if druhy[0] == "cele" and not (isinstance(h, list) and len(h) == 2
                                           and all(type(x) is int for x in h) and h[0] <= h[1]):
                raise Chyba(f"{k} – „cele“ musí být [min, max] (celá čísla)")
            if druhy[0] == "text" and h is not True:
                raise Chyba(f"{k} – „text“ musí být True")
            if popis["vychozi"] is not None and not _platna(popis, popis["vychozi"]):
                raise Chyba(f"{k} – výchozí hodnota {popis['vychozi']!r} není povolená")


def schema():
    """Sekce všech nástrojů v tools/: {sekce: {klíč: popis}}. Nástroje se neimportují (žádné vedlejší účinky)."""
    out, odkud = {}, {}
    for soubor in sorted(os.listdir(TOOLS)):
        if not soubor.endswith(".py"):
            continue
        with open(os.path.join(TOOLS, soubor), encoding="utf-8-sig") as f:
            text = f.read()
        if "NASTAVENI_SEKCE" not in text:
            continue
        try:
            strom = ast.parse(text, soubor)
        except SyntaxError as e:
            raise Chyba(f"tools/{soubor} nejde přečíst ({e})")
        for uzel in strom.body:
            if not (isinstance(uzel, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "NASTAVENI_SEKCE" for t in uzel.targets)):
                continue
            try:
                sekce = ast.literal_eval(uzel.value)
            except ValueError:
                raise Chyba(f"tools/{soubor}: NASTAVENI_SEKCE musí být literál (jen slovníky, seznamy, texty, "
                            "čísla, True/False/None), ne výraz")
            _deklarace(soubor, sekce)
            for nazev, klice in sekce.items():
                if nazev in out:
                    raise Chyba(f"sekce „{nazev}“ je deklarovaná dvakrát: tools/{odkud[nazev]} a tools/{soubor}")
                out[nazev], odkud[nazev] = klice, soubor
    return out


def _platna(popis, v):
    if "hodnoty" in popis:
        return isinstance(v, str) and v in popis["hodnoty"]
    if "cele" in popis:
        return type(v) is int and popis["cele"][0] <= v <= popis["cele"][1]
    return isinstance(v, str) and v.strip() != ""


def _povoleno(popis):
    if "hodnoty" in popis:
        return ", ".join(popis["hodnoty"])
    if "cele" in popis:
        return f"celé číslo {popis['cele'][0]}–{popis['cele'][1]}"
    return "neprázdný text" + (" (ukládá se malými písmeny)" if popis.get("mala") else "")


def _nacti():
    """Obsah data/nastaveni.json ({} když chybí). Rozbitý soubor = Chyba (nic se nehádá ani nepřepíše)."""
    if not os.path.exists(SOUBOR):
        return {}
    try:
        with open(SOUBOR, encoding="utf-8-sig") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        raise Chyba(f"data/nastaveni.json nejde přečíst ({e}) – oprav ho (git diff ukáže poslední změnu); "
                    "nic jsem nezměnil.")
    if not isinstance(d, dict):
        raise Chyba("data/nastaveni.json musí být objekt JSON ({…}) – oprav ho (git diff ukáže poslední změnu).")
    verze = d.get("verze", 1)
    if type(verze) is not int or verze < 1:
        raise Chyba(f"data/nastaveni.json: „verze“ musí být celé číslo od 1, je {verze!r} – oprav ji.")
    if verze > VERZE:
        varuj(f"data/nastaveni.json má verzi {verze}, novější než tento skill ({VERZE}); čtu známé volby, "
              "aktualizuj skill (tools/verze.py).")
    return d


def _sekce_ze_souboru(d, nazev):
    s = d.get(nazev, {})
    if not isinstance(s, dict):
        raise Chyba(f"data/nastaveni.json: sekce „{nazev}“ musí být objekt ({{…}}), je {s!r} – oprav ji "
                    "(git diff ukáže poslední změnu).")
    return s


def _hodnoty_sekce(d, nazev, klice):
    """[(klíč, hodnota nebo None, nastaveno?, chyba nebo None)] jedné sekce; neznámé klíče jen varují."""
    s = _sekce_ze_souboru(d, nazev)
    for k in s:
        if k not in klice:
            varuj(f"neznámá volba „{nazev}.{k}“ v data/nastaveni.json (novější skill?) – nechávám ji být.")
    out = []
    for k, popis in klice.items():
        if k not in s:
            out.append((k, popis["vychozi"], False, None))
        elif _platna(popis, s[k]):
            out.append((k, s[k], True, None))
        else:
            out.append((k, None, True, f"{nazev}.{k}: neplatná hodnota {s[k]!r} v data/nastaveni.json (povoleno: "
                                       f"{_povoleno(popis)}) – oprav: python3 -I tools/nastaveni.py nastav "
                                       f"{nazev}.{k} <hodnota>, nebo nastav {nazev}.{k} {VYCHOZI}"))
    return out


def sekce(nazev):
    """{klíč: hodnota} jedné sekce, chybějící klíče s výchozí hodnotou (None = zeptej se uživatele).
    Kontroluje jen tuhle sekci: vadná jiná sekce ji nezastaví. Bez data/ (mimo projekt) vrátí výchozí."""
    sch = schema()
    if nazev not in sch:
        raise Chyba(f"neznámá sekce „{nazev}“ (známé: {', '.join(sch) or 'žádné'})")
    out = {}
    for k, v, _, chyba in _hodnoty_sekce(_nacti(), nazev, sch[nazev]):
        if chyba:
            raise Chyba(chyba)
        out[k] = v
    return out


def _prevod(klic, popis, text):
    if "hodnoty" in popis:
        if text.lower() in popis["hodnoty"]:
            return text.lower()
    elif "cele" in popis:
        try:
            v = int(text.strip())
        except ValueError:
            v = None
        if v is not None and _platna(popis, v):
            return v
    elif text.strip():
        return text.strip().lower() if popis.get("mala") else text.strip()
    raise Chyba(f"{klic}: neplatná hodnota „{text}“ (povoleno: {_povoleno(popis)}, nebo {VYCHOZI}) – "
                "nic jsem nezměnil.")


def nastav(klic, hodnota):
    """Uloží volbu „sekce.klíč“ (text jako z příkazové řádky); hodnota „vychozi“ volbu smaže. Vrátí uloženou
    hodnotu (None = smazáno). Zapisuje pod zámkem a celý soubor naráz; rozbitý soubor nepřepíše."""
    sch = schema()
    nazev, _, k = klic.partition(".")
    if nazev not in sch:
        raise Chyba(f"neznámá sekce „{nazev}“ – zadej sekce.klíč (známé sekce: {', '.join(sch) or 'žádné'})")
    if k not in sch[nazev]:
        raise Chyba(f"neznámá volba „{klic}“ – v sekci {nazev} jsou: "
                    + ", ".join(f"{nazev}.{x}" for x in sch[nazev]))
    popis = sch[nazev][k]
    nova = None if hodnota == VYCHOZI else _prevod(klic, popis, hodnota)
    import zapis   # až tady: zapis.py mimo projekt ukončí proces, sekce() má jít volat odkudkoli
    with zapis.zamek("nastaveni"):
        existoval = os.path.exists(SOUBOR)
        d = _nacti()
        s = dict(_sekce_ze_souboru(d, nazev))
        if nova is None:
            s.pop(k, None)
        else:
            s[k] = nova
        if not existoval and not s:
            return None   # smazání volby, která nikde není: soubor nezakládat
        out = {"verze": d.get("verze", VERZE)}
        for x, v in d.items():
            if x != "verze":
                out[x] = v
        if s:
            out[nazev] = s
        else:
            out.pop(nazev, None)
        zapis.zapis_atomicky(SOUBOR, json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return nova


def ukaz(jen=None):
    """Vypíše volby; vrátí počet chyb (platné volby vypíše i tak)."""
    sch = schema()
    if jen is not None and jen not in sch:
        raise Chyba(f"neznámá sekce „{jen}“ (známé: {', '.join(sch) or 'žádné'})")
    d = _nacti()
    for x in d:
        if x != "verze" and x not in sch:
            varuj(f"neznámá sekce „{x}“ v data/nastaveni.json (novější skill?) – nechávám ji být.")
    chyby, zeptat = 0, False
    for nazev, klice in sch.items():
        if jen is not None and nazev != jen:
            continue
        try:
            radky = _hodnoty_sekce(d, nazev, klice)
        except Chyba as e:
            print(f"CHYBA: {e}", file=sys.stderr)
            chyby += 1
            continue
        for k, v, nastaveno, chyba in radky:
            popis = klice[k]
            info = f"{_povoleno(popis)} – {popis['popis']}"
            if chyba:
                print(f"CHYBA: {chyba}", file=sys.stderr)
                chyby += 1
            elif v is None:
                print(f"→ ZEPTEJ_SE {nazev}.{k}   (nenastaveno; {info})")
                zeptat = True
            else:
                print(f"{nazev}.{k} = {json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v}   "
                      f"({'nastaveno' if nastaveno else 'výchozí'}; {info})")
    if zeptat:
        print("Nenastavenou volbu nejdřív nabídni uživateli; ulož ji (nastaveni.py nastav <klíč> <hodnota>) "
              "jen když s uložením výslovně souhlasí.")
    return chyby


def main():
    a = sys.argv[1:]
    try:
        if a[:1] == ["ukaz"] and len(a) <= 2:
            sys.exit(1 if ukaz(a[1] if len(a) == 2 else None) else 0)
        if a[:1] == ["nastav"] and len(a) == 3:
            v = nastav(a[1], a[2])
            print(f"{a[1]} = {v}" if v is not None else f"{a[1]}: smazáno, platí výchozí hodnota")
            sys.exit(0)
    except Chyba as e:
        sys.exit(f"nastaveni.py: {e}")
    sys.exit(__doc__)


if __name__ == "__main__":
    main()
