"""Hook PreToolUse (Claude Code): síťový přístup k archivům jen přes slusne.py (společný limit rychlosti) a žádné sudo.

Zastaví v Bashi:
  - sudo, sudoedit, su, doas, pkexec, run0 spouštěné Claudem – ani se souhlasem uživatele (příkaz dá uživateli, ten
    ho spustí sám, např. `! sudo apt install …`); viz sudo_duvod(),
  - curl / wget na web (kromě localhost), který nejde přes `tools/slusne.py curl`,
  - Python se síťovým importem (urllib, requests, http.client, socket…) – v `-c`, v heredocu nebo ve skriptu –,
    který neběží přes `tools/slusne.py` (nástroje v tools/ mají limit samy a projdou),
  - shellový skript mimo tools/ s curl/wget.
U WebFetch počká na volný termín webu a zablokovaný web (po 429/503) nepustí.
Je to textová heuristika, ne neprůstřelná ochrana – zachytí ale dočasné skripty, které si agent napíše sám.
Nastavení: .claude/settings.json projektu (zapisuje novy_projekt.py).

Hranice hlídání sudo: chrání před agentem, který ke sudo sklouzne (pokus `sudo -n apt-get install …` po souhlasu
s instalací), ne před cíleným útočníkem. Skutečná hranice je OS (sudo bez terminálu chce heslo); hook je důležitý tam,
kde má uživatel NOPASSWD nebo platné časové razítko sudo. Zbytkové riziko (hook nepozná): base64/printf/rev → `| sh`
bez slova sudo, `${x:0:4}`, `${!x}`, slovo složené z několika proměnných, `read S < f`, `$(cat f)`; příkaz v souboru,
který spouští jiný program (Makefile, package.json + npm run, crontab); upravený skript v tools/ (výjimka platí i pro
síť); odebrání hooku z .claude/settings.json; polkit a jiné cesty (systemd-run, machinectl shell, ssh root@…);
řetězce skládané v interpretu ("su"+"do"); co shlex rozebere jinak než bash (zamítá se jen při chybě shlexu).
"""
import json, os, re, shlex, sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)

SIT = re.compile(r"^\s*(?:import|from)\s+(?:urllib(?!\.parse\b)|requests|http\.client|http\b|httpx|aiohttp|socket|urllib3|pycurl)\b"
                 r"|\b(?:urllib\.request|requests\.(?:get|post|Session)|http\.client)\b", re.M)
CURL = re.compile(r"(?:^|[\s;&|(`'\"])(curl|wget)(?=\s)")
URL = re.compile(r"https?://([^/\s'\"]+)")
HOLY = re.compile(r"(?:^|\s)['\"]?(?!localhost\b)[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:cz|sk|at|de|eu|org|com|net|pl|hu)(?::\d+)?(?:[/?#]\S*)?['\"]?(?=\s|$)", re.I)
LOKAL = re.compile(r"^(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:\d+)?$")
PYTHON = re.compile(r"(?:^|[\s;&|(`/])(?:python3?(?:\.\d+)?|py(?:\s+-3)?)((?:\s+-[A-Za-z]+(?:\s+utf8)?)*)\s+(\S+)")
NAVOD = ("Síťový přístup k webům archivů jde jen přes tools/slusne.py (společný limit rychlosti – archivy jinak "
         "zablokují IP adresu uživatele). Spusť to takhle:\n"
         "  vlastní skript:  python3 -I tools/slusne.py pracovni/<skript>.py [argumenty]\n"
         "  curl:            python3 -I tools/slusne.py curl [argumenty]\n"
         "  hotový nástroj:  python3 -I tools/<nástroj>.py … (limit mají samy)\n"
         "Neobcházej to (jiný příkaz, prohlížeč ve smyčce). Smyčky dotazů na archiv nepiš vůbec – použij nástroj.")

NAVOD_SUDO = ("sudo/su/doas Claude nespouští ani se souhlasem. Dej uživateli přesný příkaz, ať ho spustí sám "
              "(v Claude Code `! sudo apt install …`, jinak v terminálu), a počkej. "
              "Neobcházej to jiným zápisem, skriptem ani proměnnou.")


def zamitni(proc, navod=NAVOD):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": f"{proc}\n\n{navod}"}}, ensure_ascii=False))
    sys.exit(0)


# --- sudo / su / doas ---------------------------------------------------------------------------------------------
ZV_SLOVA = ("sudo", "sudoedit", "su", "doas", "pkexec", "run0")
ZVRE = re.compile(r"(?<![\w-])(?:sudo|sudoedit|su|doas|pkexec|run0)(?![\w-])", re.I)   # re.I: SUDO na macOS (APFS)
ZV_PY = re.compile(r"['\"](?:[\w./-]*/)?(?:sudo|sudoedit|su|doas|pkexec|run0)(?=['\"\s])", re.I)
SPOUSTECE = {"env", "command", "builtin", "exec", "eval", "nohup", "setsid", "nice", "ionice", "stdbuf", "timeout",
             "xargs", "watch", "chroot", "unbuffer", "flock", "script", "busybox", "parallel", "bash", "sh", "dash",
             "zsh", "ksh", "fish", "source", ".", "perl", "ruby", "node", "awk", "find", "osascript", "function",
             "coproc"}
KLICOVA = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "time", "{", "}", "case", "esac"}
STROP = 64 * 1024
EXPANZE = re.compile(r"\$\{[^{}]*\}|\$\([^()]*\)|`[^`]*`|\$[A-Za-z_]\w*|\$[@*#?$!0-9-]")
PRIRAZENI = re.compile(r"^[A-Za-z_]\w*(?:\[[^]]*\])?\+?=(.*)$", re.S)
HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)\s*(?:'([^']*)'|\"([^\"]*)\"|\\?([^\s;&|<>()'\"]+))")
SKRIPT_SH = re.compile(r"(?:^|[\s;&|(])(?:bash|sh|zsh|dash|ksh|source|\.)\s+(?:-[A-Za-z]+\s+)*([^\s;&|<>()]+)")
SKRIPT_CESTA = re.compile(r"(?:^|[;&|(\n])\s*(\.{1,2}/[^\s;&|<>()'\"]+)")
PY_SLOVO = re.compile(r"^(?:python3?(?:\.\d+)?|py)$")


def _ansi_nebezpecne(cmd):
    """$'…' s escapem \\x \\u \\U \\c nebo osmičkovým – umí poskládat libovolná písmena ($'\\x73udo'). Lineárně."""
    i = cmd.find("$'")
    while i != -1:
        j = i + 2
        while j < len(cmd) and cmd[j] != "'":
            if cmd[j] == "\\":
                if j + 1 < len(cmd) and cmd[j + 1] in "xuUc01234567":
                    return True
                j += 2
            else:
                j += 1
        i = cmd.find("$'", j + 1)
    return False


def _zavorky(slovo, strop=64):
    """Rozvinutí složených závorek jako v bashi ({s,}udo → sudo udo, s{t..u}do); None = víc než strop tvarů
    nebo slovo delší než 16 KiB se závorkou (nejasné – kvůli času se nerozvíjí)."""
    if "{" not in slovo:
        return [slovo]
    if len(slovo) > 16384:
        return None
    hotove, fronta = [], [slovo]
    while fronta:
        s = fronta.pop()
        zasobnik, nalez = [], None
        for i, z in enumerate(s):
            if z == "{":
                zasobnik.append([i, []])
            elif z == "," and zasobnik:
                zasobnik[-1][1].append(i)
            elif z == "}" and zasobnik:
                zac, carky = zasobnik.pop()
                vnitrek = s[zac + 1:i]
                if carky:
                    hr = [zac] + carky + [i]
                    nalez = (zac, i, [s[a + 1:b] for a, b in zip(hr, hr[1:])])
                else:
                    m = re.fullmatch(r"(\w)\.\.(\w)", vnitrek)
                    if m and ord(m.group(2)) - ord(m.group(1)) in range(-200, 201):
                        a, b = ord(m.group(1)), ord(m.group(2))
                        krok = 1 if b >= a else -1
                        nalez = (zac, i, [chr(c) for c in range(a, b + krok, krok)])
                if nalez:
                    break
        if not nalez:
            hotove.append(s)
        else:
            zac, kon, alt = nalez
            fronta.extend(s[:zac] + a + s[kon + 1:] for a in alt)
        if len(hotove) + len(fronta) > strop:
            return None
    return hotove


def _normalizuj(text):
    """Text, jak by ho mohl poskládat bash: bez pokračování řádku, $'…' → '…', bez expanzí, uvozovek a zpětných lomítek."""
    t = text.replace("\\\n", "").replace("$'", "'").replace('$"', '"')
    return re.sub(r"[\\'\"]", "", EXPANZE.sub("", t))


def _ma_zv(text):
    """Předfiltr: ZV slovo v textu doslova, po normalizaci (bez uvozovek a expanzí) nebo po rozvinutí závorek."""
    if ZVRE.search(text):
        return True
    n = _normalizuj(text)
    if ZVRE.search(n):
        return True
    for slovo in n.split():
        if "{" not in slovo or ("," not in slovo and ".." not in slovo):
            continue
        tvary = _zavorky(slovo)
        if tvary is None or any(ZVRE.search(t) for t in tvary):
            return True
    return False


def _skripty(cmd, cwd, hloubka):
    """R4: obsah spouštěných souborů mimo tools/ (shell projde celou kontrolou, Python hledá literál 'sudo')."""
    kandidati = [("sh", m.group(1)) for m in SKRIPT_SH.finditer(cmd)]
    kandidati += [("sh", m.group(1)) for m in SKRIPT_CESTA.finditer(cmd)]
    for m in PYTHON.finditer(cmd):
        kandidati.append(("py", m.group(2)))
    pocet = 0
    for druh, cesta in kandidati:
        cesta = cesta.strip("\"'")
        if not cesta or cesta.startswith(("-", "<")) or v_tools(cesta, cwd):
            continue
        plna = os.path.join(cwd, os.path.expanduser(cesta))
        if not os.path.isfile(plna):
            continue
        pocet += 1
        if pocet > 10:
            return "příliš mnoho spouštěných souborů ke kontrole sudo"
        text = obsah(cesta, cwd)
        if druh == "py" or cesta.endswith(".py"):
            if ZV_PY.search(text):
                return f"skript {cesta} volá sudo/su"
        elif hloubka < 3 and sudo_duvod(text, cwd, hloubka + 1):
            return f"skript {cesta} volá sudo/su"
    return None


def _heredocy(text):
    """(text bez těl heredoců, True když tělo obsahuje ZV slovo)."""
    zbyle, cekam, zv = [], [], False
    for radek in text.split("\n"):
        if cekam:
            pomlcka, znacka = cekam[0]
            if (radek.lstrip("\t") if pomlcka else radek) == znacka:
                cekam.pop(0)
            elif _ma_zv(radek):
                zv = True
            continue
        zbyle.append(radek)
        for m in HEREDOC.finditer(radek):
            cekam.append((m.group(1), next(g for g in m.groups()[1:] if g is not None)))
    return "\n".join(zbyle), zv


def _je_hranice(tok):
    return bool(tok) and set(tok) <= set(";&|()<>") and ("(" in tok or ")" in tok or not set(tok) & set("<>"))


def _je_presmerovani(tok):
    return bool(tok) and set(tok) <= set("<>&|") and bool(set(tok) & set("<>"))


def _python_spousteni(args, cwd):
    """True, když python nespouští nástroj z tools/ (-c, -m, -, vlastní skript, interaktivně)."""
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-X", "-W"):
            i += 2
        elif a == "-" or re.match(r"-[A-Za-z]*[cm]", a):
            return True
        elif a.startswith("-"):
            i += 1
        else:
            a = re.sub(r"^\$(?:CLAUDE_PROJECT_DIR\b|\{CLAUDE_PROJECT_DIR\})", lambda _: cwd, a)
            return not (a.endswith(".py") and v_tools(a, cwd))
    return True


def sudo_duvod(cmd, cwd, hloubka=0):
    """Důvod zamítnutí, když Bash příkaz spouští sudo/su/doas (i přes `bash -c`, proměnnou, skript…), jinak None."""
    # 0a. ANSI-C $'…' s nebezpečným escapem – PŘED předfiltrem ($'\\x73udo' slovo sudo neobsahuje)
    if _ansi_nebezpecne(cmd):
        return "nejasný zápis $'…' (escape \\x, \\u, \\c nebo osmičkový) – nejde ověřit, že nespouští sudo"
    # R4: spouštěné soubory (i když příkaz sám slovo sudo nemá)
    duvod = _skripty(cmd, cwd, hloubka)
    if duvod:
        return duvod
    # 0b. předfiltr: bez ZV slova (ani poskládaného) není co hlídat
    if not _ma_zv(cmd):
        return None
    if len(cmd) > STROP:
        return "příliš dlouhý příkaz se slovem sudo/su"
    # 1. heredocy
    text, zv = _heredocy(cmd.replace("\\\n", ""))
    if zv:
        return "sudo/su v heredocu"
    # 2. tokeny s ohledem na uvozovky
    text = text.replace("$'", "'").replace('$"', '"')
    text = re.sub(r"\$\(\s*\)|``", "", text)   # prázdné $( ) a `` se rozvinou na nic
    lex = shlex.shlex(text.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        tokeny = list(lex)
    except ValueError:
        return "nerozebratelný příkaz se slovem sudo/su (neuzavřená uvozovka)"
    zv_kdekoli = ZVRE.search(_normalizuj(text)) or ZVRE.search(text)
    # R2, R2b – na všech tokenech
    for tok in tokeny:
        m = PRIRAZENI.match(tok)
        if m and m.group(1).split() and ZVRE.fullmatch(os.path.basename(m.group(1).split()[0])):
            return f"přiřazení sudo/su do proměnné ({tok})"
        if ("$(" in tok or "`" in tok or "<(" in tok) and ZVRE.search(tok):
            return "sudo/su v substituci příkazu"
    # 3. segmenty a slovo příkazu
    segmenty, akt = [], []
    for tok in tokeny:
        if _je_hranice(tok):
            segmenty.append(akt)
            akt = []
        else:
            akt.append(tok)
    segmenty.append(akt)
    for seg in segmenty:
        i = 0
        while i < len(seg):
            t = seg[i]
            if t in KLICOVA or PRIRAZENI.match(t):
                i += 1
            elif _je_presmerovani(t):
                i += 2
            elif re.fullmatch(r"\d+|\{\w+\}", t) and i + 1 < len(seg) and _je_presmerovani(seg[i + 1]):
                i += 3
            else:
                break
        if i >= len(seg):
            continue
        slovo, args = seg[i], seg[i + 1:]
        tvary = _zavorky(slovo)
        if tvary is None:
            return "nejasné slovo příkazu (složené závorky)"
        for tvar in tvary:
            jmeno = os.path.basename(tvar)
            if ZVRE.fullmatch(jmeno):                                     # R1
                return f"příkaz {jmeno}"
            if "$" in tvar or "`" in tvar:                                # R3: příkaz z proměnné
                return f"příkaz z proměnné ({tvar}) v příkazu se slovem sudo/su"
            if zv_kdekoli and (jmeno.lower() in SPOUSTECE
                               or (PY_SLOVO.match(jmeno) and _python_spousteni(args, cwd))):   # R3: spouštěč
                return f"{jmeno} v příkazu se slovem sudo/su (mohl by ho spustit)"
    return None


def v_tools(cesta, cwd):
    p = os.path.realpath(os.path.join(cwd, os.path.expanduser(cesta)))
    return os.path.dirname(p) == os.path.realpath(os.path.join(cwd, "tools")) or os.path.dirname(p) == TOOLS


def obsah(cesta, cwd):
    try:
        with open(os.path.join(cwd, os.path.expanduser(cesta)), encoding="utf-8", errors="replace") as f:
            return f.read(500_000)
    except OSError:
        return ""


def jen_lokalni(text):
    hosty = URL.findall(text)
    return bool(hosty) and all(LOKAL.match(h) for h in hosty)


def bash(cmd, cwd):
    duvod = sudo_duvod(cmd, cwd)
    if duvod:
        zamitni(duvod, NAVOD_SUDO)
    # curl / wget mimo `slusne.py curl`
    for m in CURL.finditer(cmd):
        pred = cmd[max(0, m.start() - 30):m.start() + 1]
        if re.search(r"slusne\.py[\"']?\s*$", pred):
            continue
        zbytek = re.split(r"[;&|\n]", cmd[m.end():], maxsplit=1)[0]
        if URL.search(zbytek) and not jen_lokalni(zbytek):
            zamitni(f"{m.group(1)} na web mimo slusne.py")
        if HOLY.search(zbytek):   # www.mza.cz/… bez https:// (curl ji vezme jako http://)
            zamitni(f"{m.group(1)} na web mimo slusne.py")
        if not URL.search(zbytek) and "$" in zbytek:   # adresa v proměnné – nevíme kam, raději ne
            zamitni(f"{m.group(1)} s adresou v proměnné mimo slusne.py")
    # Python
    for m in PYTHON.finditer(cmd):
        volby, cil = m.group(1) or "", m.group(2).strip("\"'")
        if re.search(r"(?:^|/)slusne\.py$", cil):
            continue
        if cil.startswith("-c") or re.search(r"\s-[A-Za-z]*c$", volby.rstrip()):
            kod = cmd[m.end():]
        elif cil == "-" or cil.startswith("<<") or "<<" in cmd[m.end():m.end() + 40]:
            kod = cmd[m.end():]   # heredoc / stdin: text za příkazem
        elif cil.endswith(".py") and not v_tools(cil, cwd):
            kod = obsah(cil, cwd)
        else:
            continue   # nástroj z tools/ (limit má sám), python -m …, python bez skriptu
        if SIT.search(kod) and not jen_lokalni(kod):
            zamitni("Python se síťovým importem mimo slusne.py")
    # shellové skripty mimo tools/
    for m in re.finditer(r"(?:^|[\s;&|(])(?:bash|sh|zsh)\s+(\S+\.sh)\b", cmd):
        if not v_tools(m.group(1), cwd) and CURL.search(" " + obsah(m.group(1), cwd)):
            zamitni(f"skript {m.group(1)} volá curl/wget mimo slusne.py")


def webfetch(url):
    import urllib.parse, slusne
    host = urllib.parse.urlsplit(url).hostname or ""
    if not host or LOKAL.match(host):
        return
    try:
        slusne.pockej(host, slusne.druh(url), nejdele=40, adresa=url)   # hook má timeout 60 s – po něm by WebFetch prošel bez limitu
    except (slusne.Zablokovano, slusne.Fronta, slusne.Ochrana, slusne.podminky.Zakazano) as e:
        zamitni(str(e))


def main():
    try:
        d = json.load(sys.stdin)
    except ValueError:
        return
    vstup = d.get("tool_input") or {}
    if d.get("tool_name") == "Bash":
        bash(vstup.get("command", ""), d.get("cwd") or os.getcwd())
    elif d.get("tool_name") == "WebFetch":
        webfetch(vstup.get("url", ""))


if __name__ == "__main__":
    main()
