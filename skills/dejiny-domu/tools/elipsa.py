"""Dům na mapě označený tmavě modrou elipsou s bílou září – do PDF a na web, aby čtenář dům našel na každé mapě.

Použití (z kořene projektu):
  elipsa.py <mapa.jpg> <klic> cx,cy,a,b[,uhel] [--popisek "čp. 12"] [--text x,y] [--pismo px]
  elipsa.py <mapa.jpg> <klic> --uvnitr "x,y x,y …" [--venku "x,y …"] […]
      cx,cy = střed elipsy, a,b = poloosy (vodorovná, svislá) v pixelech obrázku <mapa.jpg>; uhel = natočení
      ve stupních po směru hodinových ručiček (dům šikmo k ose mapy). Rozměr obrázku vypíše nástroj, když chybí čísla.
      --text x,y = levý horní roh popisku (výchozí vpravo nad elipsou); popisek spojí s elipsou vodicí čára.
      --pismo = výška písma v px (výchozí 1/30 šířky obrázku).
      Uloží zdroje/<klic>.jpg (plné rozlišení) a vyrezy/<klic>.jpg (max. 1800 px pro web) jako vyrez.py.
      --uvnitr/--venku = elipsu spočítá sám: rohy budov a parcely domu (uvnitr) a rohy sousedních budov (venku)
      v pixelech mapy; najde elipsu, která sousedy zasáhne co nejméně, a vypíše její čísla.
Elipsa obepíná celou parcelu domu, ne jen číslo. Co k parcele patří, rozhodují čáry hranic (stavení i dvůr až
po hranici), ne poloha čísla. Šikmou nebo protáhlou parcelu nelaď od oka, spočítej ji z --uvnitr/--venku
(od oka se elipsa točí dokola a stejně zasáhne souseda). Výsledek si VŽDY prohlédni ve zvětšení. Označ dům na všech mapách projektu
stejně (ne jen na některých) a do popisu mapy napiš „Dům je v modré elipse.“ Popisek jen výjimečně: zakrývá mapu
a číslo domu se v čase mění. Zdroj <mapa.jpg> musí být čistý (bez elipsy), ne zdroje/<klic>.jpg – ten se přepíše.
Do data/mapy.json k mapě zapiš do „poznamka“ příkaz s čísly, ať jde označení zopakovat (např. po exportu mapy ve větším rozlišení).
Potřebuje Pillow (python3 -m pip install pillow).
"""
import math, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I nepřidá složku skriptu sama
for _s in (sys.stdout, sys.stderr):   # UTF-8 výstup i na Windows bez -X utf8 (cp1250 neumí třeba „→“)
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
import podminky

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODRA, BILA = (22, 64, 140, 255), (255, 255, 255, 220)   # modrá: vidět na sépii, červeném katastru i ortofotu
PISMA = ("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "arialbd.ttf",
         "Arial Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf")
WEB_PX = 1800


def pismo(velikost):
    from PIL import ImageFont
    for p in PISMA:
        try:
            return ImageFont.truetype(p, velikost)
        except OSError:
            pass
    return ImageFont.load_default(size=velikost)   # bez diakritiky na některých systémech – zkontroluj popisek


def bod_elipsy(cx, cy, a, b, uhel, s):
    u = math.radians(uhel)
    return (cx + a * math.cos(s) * math.cos(u) - b * math.sin(s) * math.sin(u),
            cy + a * math.cos(s) * math.sin(u) + b * math.sin(s) * math.cos(u))


def nejblizsi_bod(cx, cy, a, b, uhel, cil):
    """Bod na obvodu elipsy nejblíž cíli (konec vodicí čáry u elipsy)."""
    return min((bod_elipsy(cx, cy, a, b, uhel, i / 180 * math.pi) for i in range(360)),
               key=lambda p: (p[0] - cil[0]) ** 2 + (p[1] - cil[1]) ** 2)


UVNITR, DOST_DALEKO, NEJDELSI = 0.97, 1.15, 1.5   # body domu kousek od čáry; dál od souseda už nepomáhá; viz spocitej()


def do_os_elipsy(p, cx, cy, c, s):
    """Bod p v souřadnicích elipsy (střed cx,cy, natočení dané cos c a sin s)."""
    dx, dy = p[0] - cx, p[1] - cy
    return dx * c + dy * s, -dx * s + dy * c


def vzdalenost(p, cx, cy, a, b, uhel):
    """Poměrná vzdálenost bodu od středu elipsy: < 1 uvnitř, 1 na čáře, > 1 venku."""
    u = math.radians(uhel)
    x, y = do_os_elipsy(p, cx, cy, math.cos(u), math.sin(u))
    return math.hypot(x / a, y / b)


def spocitej(uvnitr, venku=()):
    """Elipsa (cx, cy, a, b, uhel) kolem bodů uvnitr, co nejdál od bodů venku; vrací i rezervu (<1 = zasáhne souseda).
    Hrubě po 3°, pak jemně kolem nejlepší. Mezi stejně dobrými (rezerva nad DOST_DALEKO) vybere menší elipsu.
    Poloosa nejvýš NEJDELSI× poloměr bodů uvnitř: jinak by se elipsa natáhla daleko za parcelu, jen aby minula sousedy."""
    def zkus(uhly, stredy):
        nej = None
        for uhel in uhly:
            u = math.radians(uhel)
            c, s = math.cos(u), math.sin(u)
            for cx, cy in stredy:
                vnitr = [do_os_elipsy(p, cx, cy, c, s) for p in uvnitr]
                vne = [do_os_elipsy(p, cx, cy, c, s) for p in venku]
                b_min = max(abs(y) for _, y in vnitr) / math.sqrt(UVNITR) + 1
                for k in range(10, 41):   # b od nejužší možné elipsy po 4× širší
                    b = b_min * k / 10
                    a = max(abs(x) / math.sqrt(UVNITR - (y / b) ** 2) for x, y in vnitr)
                    if max(a, b) > strop:
                        continue
                    rezerva = min((math.hypot(x / a, y / b) for x, y in vne), default=math.inf)
                    klic = (min(rezerva, DOST_DALEKO), -a * b)
                    if nej is None or klic > nej[0]:
                        nej = (klic, (cx, cy, a, b, uhel, rezerva))
        return nej[1]

    xs, ys = [p[0] for p in uvnitr], [p[1] for p in uvnitr]
    sx, sy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    r = max(max(xs) - min(xs), max(ys) - min(ys)) / 2
    strop = NEJDELSI * max(math.hypot(x - sx, y - sy) for x, y in uvnitr)
    mrizka = lambda x0, y0, krok, n: [(x0 + i * krok, y0 + j * krok) for i in range(-n, n + 1) for j in range(-n, n + 1)]
    cx, cy, _, _, uhel, _ = zkus(range(-90, 90, 3), mrizka(sx, sy, r / 10, 4))
    cx, cy, a, b, uhel, rezerva = zkus(range(uhel - 3, uhel + 4), mrizka(cx, cy, r / 40, 5))
    if b > a:   # delší osa jako a, úhel v rozsahu -90..90
        a, b, uhel = b, a, (uhel + 180) % 180 - 90
    return round(cx), round(cy), round(a), round(b), round(uhel), round(rezerva, 2)


def oznac(im, cx, cy, a, b, uhel=0.0, popisek="", text=None, velikost=None, cara=None):
    """Nakreslí do obrázku (RGBA) elipsu s bílou září, popisek a vodicí čáru. Čára v px, výchozí podle šířky obrázku."""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    cara = cara or max(3, round(im.width / 220))   # v PDF mapa ~120 mm široká → čára ~0,5 mm
    okraj = 5 * cara   # místo pro záři kolem elipsy
    w, h = int(2 * a + 2 * okraj), int(2 * b + 2 * okraj)

    def obrys(barva, sirka):   # PIL kreslí obrys dovnitř, širší obrys proto začíná dál od středu
        vrstva = Image.new("RGBA", (w, h), (255, 255, 255, 0))   # průhledná bílá, jinak rozmazání zešedne
        o = okraj - (sirka - cara)
        ImageDraw.Draw(vrstva).ellipse([o, o, w - o, h - o], outline=barva, width=sirka)
        return vrstva

    zare = obrys(BILA, round(1.5 * cara)).filter(ImageFilter.GaussianBlur(0.35 * cara))
    vnitrek = Image.new("L", (w, h), 0)   # záře jen ven, dům uvnitř elipsy nezakryje
    ImageDraw.Draw(vnitrek).ellipse([okraj + cara, okraj + cara, w - okraj - cara, h - okraj - cara], fill=255)
    zare.putalpha(ImageChops.subtract(zare.getchannel("A"), vnitrek))
    for vrstva in (zare, obrys(MODRA, cara)):
        vrstva = vrstva.rotate(-uhel, expand=True, resample=Image.BICUBIC)
        im.alpha_composite(vrstva, (int(cx - vrstva.width / 2), int(cy - vrstva.height / 2)))
    if not popisek:
        return im
    f = pismo(velikost or max(14, im.width // 30))
    if text is None:   # vpravo nad elipsou
        text = (cx + a + f.size, cy - b - f.size)
    d = ImageDraw.Draw(im)
    l, t, r, bt = d.textbbox(text, popisek, font=f)
    stred_textu = ((l + r) / 2, (t + bt) / 2)
    cil = (l - f.size / 6 if stred_textu[0] >= cx else r + f.size / 6, stred_textu[1])   # bok popisku blíž elipse
    zacatek = nejblizsi_bod(cx, cy, a, b, uhel, cil)
    d.line([zacatek, cil], fill=BILA, width=round(1.5 * cara))
    d.line([zacatek, cil], fill=MODRA, width=max(2, round(cara * 2 / 3)))
    d.text(text, popisek, font=f, fill=MODRA, stroke_width=max(2, f.size // 14), stroke_fill=(255, 255, 255))
    return im


def cisla(text, kolik, co):
    try:
        v = [float(x) for x in text.split(",")]
    except ValueError:
        v = []
    if len(v) not in kolik:
        sys.exit(f"{co}: „{text}“ – čekám {' nebo '.join(map(str, kolik))} čísel oddělených čárkou (pixely)")
    return v


def body(text):
    """„x,y x,y …“ → [(x, y), …]"""
    return [tuple(cisla(b, (2,), "bod")) for b in text.split()]


def volba(a, nazev):
    if nazev not in a:
        return None
    i = a.index(nazev)
    if i + 1 >= len(a):
        sys.exit(f"{nazev}: chybí hodnota")
    hodnota = a[i + 1]
    del a[i:i + 2]
    return hodnota


def main(a):
    if len(a) < 2:
        sys.exit(__doc__)
    if not os.path.exists(os.path.join(ROOT, "data", "STAV.md")):   # ze složky skillu by zapisoval do skillu
        sys.exit(f"elipsa.py: {ROOT} není složka projektu (chybí data/STAV.md). "
                 "Spusť projektovou kopii z kořene projektu: python3 -I tools/elipsa.py …")
    try:
        from PIL import Image
    except ImportError:
        sys.exit("Chybí Pillow: python3 -m pip install pillow")
    a = list(a)
    popisek, text, velikost = volba(a, "--popisek") or "", volba(a, "--text"), volba(a, "--pismo")
    uvnitr, venku = volba(a, "--uvnitr"), volba(a, "--venku")
    src, klic = a[0], a[1]
    if not re.fullmatch(r"[\w.-]+", klic):
        sys.exit(f"Klíč „{klic}“: jen písmena, číslice, _ - . (z něj je název souboru)")
    full, small = os.path.join(ROOT, "zdroje", klic + ".jpg"), os.path.join(ROOT, "vyrezy", klic + ".jpg")
    if os.path.abspath(src) in (os.path.abspath(full), os.path.abspath(small)):
        sys.exit(f"{src}: tohle je výstup, kreslil bys elipsu přes elipsu. Čistou mapu dej nejdřív jinam (např. pracovni/mapy/)")
    im = Image.open(src)
    if uvnitr:
        cx, cy, osa_a, osa_b, uhel, rezerva = spocitej(body(uvnitr), body(venku or ""))
        print(f"elipsa {cx},{cy},{osa_a},{osa_b},{uhel}" + (f" – zasáhne souseda (rezerva {rezerva})" if rezerva < 1 else ""))
    elif len(a) < 3:
        sys.exit(f"{src}: {im.width}×{im.height} px – zadej cx,cy,a,b[,uhel] nebo --uvnitr v pixelech tohoto obrázku")
    else:
        cx, cy, osa_a, osa_b, *uhel = cisla(a[2], (4, 5), "elipsa")
        uhel = uhel[0] if uhel else 0.0
    im = im.convert("RGBA")
    oznac(im, cx, cy, osa_a, osa_b, uhel, popisek,
          tuple(cisla(text, (2,), "--text")) if text else None, int(velikost) if velikost else None)
    im = im.convert("RGB")
    for p in (full, small):
        os.makedirs(os.path.dirname(p), exist_ok=True)
    im.save(full, quality=90)
    if max(im.size) > WEB_PX:
        im.thumbnail((WEB_PX, WEB_PX), Image.LANCZOS)
    im.save(small, quality=88)
    print("uloženo:", full, "a", small, "– prohlédni si, jestli elipsa obepíná celou parcelu domu")
    stav, zprava = podminky.posoud_obrazek(ROOT, klic)
    if stav == "souhlas":
        print(f"POZOR – PODMÍNKY: {zprava}\nŘekni to uživateli.")
    elif stav == "pozor":
        print(f"upozornění: {zprava}")


if __name__ == "__main__":
    main(sys.argv[1:])
