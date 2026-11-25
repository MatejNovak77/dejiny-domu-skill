"""Podmínky portálů: co smí nástroj stáhnout a který obrázek smí do výstupu (tools/podminky.json).

Lidská verze s vysvětlením: reference/podminky.md. Jen veřejné zdroje, stav 3. 11. 2026, není to právní rada.

Použití (z kořene projektu):
  podminky.py <adresa | doména>   -> pravidla pro portál (stahování stránek, snímků, obrázky ve výstupu)
  podminky.py obrazky             -> výřezy ve vyrezy/, které podle podmínek potřebují souhlas archivu
Portál, který skill nezná, doplní projekt do data/podminky_projekt.json ({"portaly": {doména: položka}}, stejný tvar
jako tools/podminky.json); aktualizace nástrojů ho nepřepíše. Platí jen pro domény, které tools/podminky.json nemá.
Nástroje to volají samy: slusne.py před každým požadavkem, vyrez.py, kontrola.py a export_web.py.
"""
import json, os, sys, urllib.parse
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

SOUBOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "podminky.json")
PROJEKT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "podminky_projekt.json")
VOLNE = ("ano", "neresi")
VYREZ = ("ano", "neresi", "nekomercne", "souhlas", "ne")
_tabulka_skillu = None
_doplnky = None


def _najdi(tabulka, host):
    """Položka pro doménu i s www. a bez něj, jinak None."""
    return tabulka.get(host) or tabulka.get(host[4:] if host.startswith("www.") else "www." + host)


def chyba_polozky(x):
    if not isinstance(x, dict) or not x.get("nazev"):
        return "chybí 'nazev'"
    if x.get("vyrez") not in VYREZ:
        return f"'vyrez' musí být jedno z {', '.join(VYREZ)}"
    if not all(isinstance(x.get(k, True), bool) for k in ("dotazy", "obrazky")):
        return "'dotazy' a 'obrazky' musí být true nebo false"
    return None


def doplnky():
    """(platné, odmítnuté) z data/podminky_projekt.json: {doména: položka}, [(doména, důvod)]. Doménu, kterou skill zná,
    projekt nepřepíše: doplněk by jinak mohl uvolnit pravidlo archivu (stahování nebo zveřejnění)."""
    global _doplnky
    if _doplnky is None:
        try:
            with open(PROJEKT, encoding="utf-8-sig") as f:
                data = json.load(f).get("portaly", {})
        except FileNotFoundError:
            data = {}
        except (OSError, ValueError, AttributeError) as e:
            sys.exit(f"{PROJEKT} je poškozený ({e}). Oprav ho, nebo ho smaž, a pusť příkaz znovu.")
        platne, odmitnute = {}, []
        for host, x in data.items():
            host = host_z(host)
            if _najdi(tabulka_skillu(), host):
                odmitnute.append((host, "skill tento portál zná, platí jeho pravidlo"))
            elif c := chyba_polozky(x):
                odmitnute.append((host, c))
            else:
                platne[host] = x
        _doplnky = platne, odmitnute
    return _doplnky


def tabulka_skillu():
    global _tabulka_skillu
    if _tabulka_skillu is None:
        try:   # bez tabulky by nástroje tiše pustily stahování i zveřejnění, které archiv zakazuje
            with open(SOUBOR, encoding="utf-8") as f:
                _tabulka_skillu = json.load(f)["portaly"]
        except (OSError, ValueError, KeyError) as e:
            sys.exit(f"Tabulka podmínek archivů {SOUBOR} chybí nebo je poškozená ({e}). "
                     "Aktualizuj nástroje projektu (novy_projekt.py) a pusť příkaz znovu.")
    return _tabulka_skillu


def portaly():
    """Portály skillu a k nim doplňky projektu pro domény, které skill nezná."""
    return {**doplnky()[0], **tabulka_skillu()}


def host_z(adresa):
    a = (adresa or "").strip()
    if "://" not in a and "/" in a:
        a = "https://" + a
    return (urllib.parse.urlsplit(a).hostname if "://" in a else a).lower()


def pravidlo(adresa, text=""):
    """Pravidlo pro adresu (nebo doménu); text = zdroj/název pro výjimky. None = portál v tabulce není."""
    host = host_z(adresa)
    p = _najdi(portaly(), host)
    if p is None:
        return None
    p = dict(p, host=host)
    hledat = f"{adresa} {text}".lower()
    for v in p.get("vyjimky", []):
        if v["obsahuje"] in hledat:
            p.update({k: v[k] for k in v if k != "obsahuje"})
            break
    return p


class Zakazano(SystemExit):   # SystemExit: nástroje chytají Exception, tohle neproklouzne do opakování
    pass


def zkontroluj_stahovani(adresa, co):
    """adresa = celá adresa nebo doména (výjimky podle cesty jen s celou adresou); co = 'dotaz' nebo 'obr'.
    Zakázaný portál → Zakazano s návodem, co dělat místo toho."""
    p = pravidlo(adresa)
    host = p["host"] if p else ""
    if not p:
        return
    smi = p.get("dotazy", True) if co == "dotaz" else p.get("obrazky", True)
    if smi:
        return
    druh = "stránky" if co == "dotaz" else "snímky"
    raise Zakazano(f"PODMÍNKY: {p['nazev']} ({host}) nástrojům nedovoluje stahovat {druh} – {p.get('proc', '')}.\n"
                   f"NEOBCHÁZEJ to jiným nástrojem, curl ani prohlížečem řízeným skriptem. Jak dál: {p.get('jinak') or 'reference/podminky.md'}\n"
                   f"Řekni to uživateli. Podrobnosti: reference/podminky.md")


def _jload(root, name, default):
    p = os.path.join(root, "data", name)
    try:
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def zdroj_obrazku(root, klic):
    """(adresa, text, záznam) obrázku podle dat projektu, nebo (None, '', None)."""
    svazky = _jload(root, "svazky.json", {})
    for z in _jload(root, "zaznamy.json", []):
        if z.get("klic") == klic:
            s = svazky.get(z.get("svazek", ""), {})
            adresa = z.get("odkaz") or s.get("url") or s.get("portal") or ""
            return adresa or None, f"{s.get('svazek', '')} {z.get('nazev', '')}", z
    for m in _jload(root, "mapy.json", []):
        if m.get("img") == klic:
            return m.get("url") or None, f"{m.get('zdroj', '')} {m.get('nazev', '')}", m
    for d in _jload(root, "dokumenty.json", []):
        if d.get("img") == klic:
            return d.get("url") or d.get("odkaz") or None, f"{d.get('zdroj', '')} {d.get('popis', '')}", d
    return None, "", None


def posoud_obrazek(root, klic):
    """(stav, zpráva): stav 'ok' | 'pozor' (jen nevýdělečně / zdroj neznámý) | 'souhlas' (bez souhlasu nezveřejňovat)."""
    adresa, text, polozka = zdroj_obrazku(root, klic)
    if polozka is not None and polozka.get("souhlas"):
        return "ok", f"souhlas: {polozka['souhlas']}"
    if not adresa and polozka is not None:   # položka bez odkazu: vlastní fotka nebo materiál od uživatele
        return "ok", "bez odkazu na portál (vlastní materiál)"
    if not adresa:
        return "pozor", ("zdroj obrázku v datech nenajdu (odkaz v zaznamy.json, url v mapy.json nebo dokumenty.json) – "
                         "u obrázku z archivu ověř podmínky v reference/podminky.md")
    p = pravidlo(adresa, text)
    if not p:
        return "pozor", f"portál {host_z(adresa)} v tabulce podmínek není – ověř jeho podmínky, než obrázek zveřejníš"
    if p["vyrez"] in VOLNE:
        return "ok", f"{p['nazev']}: {p.get('proc', '')}"
    if p["vyrez"] == "nekomercne":
        return "pozor", f"{p['nazev']}: jen nevýdělečně – {p.get('proc', '')}"
    return "souhlas", (f"{p['nazev']}: obrázek bez souhlasu nezveřejňovat – {p.get('proc', '')}. "
                       f"Na neveřejný web (za heslem) může. Se souhlasem archivu ho zapiš k položce: pole „souhlas“ "
                       f"(kdo a kdy, např. „SOA Třeboň, e-mail 5. 11. 2026“) přes zapis.py.")


def main(a):
    if not a or a[0] in ("-h", "--help"):
        sys.exit(__doc__)
    if a[0] == "obrazky":
        root = os.getcwd()
        d = os.path.join(root, "vyrezy")
        nic = True
        for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if fn.endswith(".jpg"):
                stav, zprava = posoud_obrazek(root, fn[:-4])
                if stav != "ok":
                    nic = False
                    print(f"{fn[:-4]}: {zprava}")
        if nic:
            print("Všechny výřezy se podle podmínek smí zveřejnit.")
        return
    p = pravidlo(a[0], " ".join(a[1:]))
    if not p:
        print(f"{host_z(a[0])}: v tabulce podmínek není – podmínky ověř na webu portálu (reference/podminky.md).")
        return
    ano = lambda b: "ano" if b else "NE"
    print(f"{p['nazev']} ({p['host']})\n  nástroj smí stahovat stránky: {ano(p.get('dotazy', True))}, snímky: {ano(p.get('obrazky', True))}"
          f"\n  obrázek do výstupu: {p['vyrez']}\n  proč: {p.get('proc', '')}")
    if p.get("jinak"):
        print(f"  jak dál: {p['jinak']}")


if __name__ == "__main__":
    main(sys.argv[1:])
