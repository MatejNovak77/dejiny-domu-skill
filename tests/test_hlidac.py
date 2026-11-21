"""Testy hlídání sudo/su/doas v hooku tools/hlidac.py (sudo_duvod). Bez sítě; jeden test spouští celý hook."""
import json, os, shutil, subprocess, sys, tempfile, time, unittest

KOREN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(KOREN, "skills", "dejiny-domu", "tools")
sys.path.insert(0, TOOLS)
import hlidac  # noqa: E402

BLOKUJE = [
    "sudo -n apt-get install -y tesseract-ocr", "su -c 'apt install x'", "doas apt install x", "pkexec apt install x",
    "run0 apt install x", "sudoedit /etc/hosts", "sudo apt install x | tail", "bash -c 'sudo apt install x'",
    'sh -c "a; sudo x"', "zsh -c 'sudo x'", "eval 'sudo x'", "env sudo x", "env A=1 sudo x", "echo $(sudo id)",
    "echo `sudo id`", 'echo "$(sudo id)"', "true; sudo x", "true;sudo x", "true && sudo x", "false || sudo x",
    "echo x | sudo tee f", "true\nsudo x", "S=sudo; $S apt install x", 'S="sudo apt"; $S install x',
    "read S <<< sudo; $S apt", "/usr/bin/sudo x", "command sudo x", "exec sudo x", "nohup sudo x", "timeout 5 sudo x",
    "nice -n 5 sudo x", "echo x | xargs sudo", "find . -exec sudo x {} ;",
    "python3 -c \"import subprocess; subprocess.run(['sudo', 'x'])\"",
    "python3 - <<'E'\nimport subprocess\nsubprocess.run(['sudo', 'x'])\nE", "bash <<E\nsudo x\nE",
    "s''udo x", "s\\udo x", '"sudo" x', "if true; then sudo x; fi", "( sudo x )", "{ sudo x; }", "alias s=sudo",
    "echo sudo x | sh", "$(which sudo) x", "echo a#;sudo y", "SUDO x", "s$()udo x", "s${X}udo x", "{s,}udo x",
    "s{u,}do x", "s$''udo x", 's$""udo x', "alias s=$'sudo'", "alias s=s$()udo", "s\\\nudo x", "for i in 1; do sudo x; done", "time sudo x", "! sudo x",
]
PROPUSTI = [
    "grep sudo f", 'grep -rn "sudo apt" reference/', 'echo "sudo apt install tesseract-ocr"', "cat /etc/sudoers",
    "ls /usr/bin/sudo", "which sudo", "man sudo", "git log --grep sudo", "ls pracovni/sudoku",
    "python3 -I tools/ocr.py stav 2>&1 | head", "python3 -I tools/ocr_hledej.py hledej Gansbauden",
    'python3 -I tools/zapis.py denik "instalace: příkaz sudo apt install dal jsem uživateli"',
    "git status && npm run build", "ls -la", "echo hi", "cd pracovni && ls", "python3 -m unittest discover tests",
    "grep -c su f", 'python3 -I "$CLAUDE_PROJECT_DIR/tools/zapis.py" denik "sudo apt install x dá uživatel"', "printf '%s\\n' a", 'echo "$HOME"', "cat pracovni/x.md | head -5",
]
STREDNIK = ["python3 -I tools/zapis.py denik 'neprovedena; sudo spustí uživatel'", "grep 'pokyn; sudo apt' f",
            'echo "instaluj: x; sudo apt install tesseract-ocr"']


class SudoTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hlidac_sudo_")
        os.makedirs(os.path.join(self.tmp, "tools"))
        os.makedirs(os.path.join(self.tmp, "pracovni"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def duvod(self, cmd):
        return hlidac.sudo_duvod(cmd, self.tmp)

    def pis(self, jmeno, text):
        with open(os.path.join(self.tmp, jmeno), "w", encoding="utf-8") as f:
            f.write(text)

    def hook(self, cmd):
        vstup = {"tool_name": "Bash", "cwd": self.tmp, "tool_input": {"command": cmd}}
        p = subprocess.run([sys.executable, "-I", os.path.join(TOOLS, "hlidac.py")], input=json.dumps(vstup),
                           capture_output=True, text=True, env=dict(os.environ, SLUSNE_DIR=self.tmp))
        self.assertEqual(p.returncode, 0, p.stderr)
        if not p.stdout.strip():
            return "povoleno", ""
        v = json.loads(p.stdout)["hookSpecificOutput"]
        return v["permissionDecision"], v["permissionDecisionReason"]

    def test_blokuje(self):
        for cmd in BLOKUJE:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.duvod(cmd))

    def test_presmerovani_na_zacatku(self):
        for cmd in ("2>/dev/null sudo -n apt-get install x", ">x sudo y", "> x sudo y", "<f sudo y", "2>&1 sudo y",
                    "{fd}>x sudo y", "A=1 sudo y", "A=1 2>/dev/null >x sudo y"):
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.duvod(cmd))

    def test_propusti(self):
        for cmd in PROPUSTI:
            with self.subTest(cmd=cmd):
                self.assertIsNone(self.duvod(cmd))

    def test_strednik_v_uvozovkach(self):
        for cmd in STREDNIK:
            with self.subTest(cmd=cmd):
                self.assertIsNone(self.duvod(cmd))
                self.assertIsNotNone(self.duvod(cmd.replace("'", "").replace('"', "")))   # bez uvozovek = příkaz

    def test_nerozebratelne(self):
        self.assertIsNotNone(self.duvod("echo 'sudo x"))
        self.assertIsNotNone(self.duvod("$'\\x73udo' apt install x"))
        for esc in ("\\x73", "\\u0073", "\\U00000073", "\\163", "\\cA"):
            self.assertIsNotNone(self.duvod(f"echo $'{esc}'"), esc)
        self.assertIsNotNone(self.duvod("sudo x; " + "a" * hlidac.STROP))
        self.assertIsNotNone(self.duvod("{" + "a," * 200 + "}x" + " sudo"))   # moc tvarů závorek
        self.assertIsNone(self.duvod("echo 'x"))
        self.assertIsNone(self.duvod("echo $'a\\nb'"))
        # celý hook: ANSI-C kontrola běží PŘED předfiltrem (review R2)
        self.assertEqual(self.hook("$'\\x73udo' apt")[0], "deny")

    def test_skript_ze_souboru(self):
        for jmeno, text in (("pracovni/i.sh", "sudo apt install x\n"), ("pracovni/i", "true && sudo x\n"),
                            ("pracovni/x.py", "import subprocess\nsubprocess.run(['sudo', 'x'])\n"),
                            ("pracovni/ok.sh", "echo ok\n"), ("pracovni/ok", "ls\n"), ("pracovni/ok.py", "print(1)\n"),
                            ("tools/t.sh", "sudo x\n")):
            self.pis(jmeno, text)
        for cmd in ("bash pracovni/i.sh", "sh pracovni/i", "source pracovni/i.sh", ". pracovni/i",
                    "./pracovni/i", "cd . && ./pracovni/i.sh", "python3 pracovni/x.py", "python3 -I pracovni/x.py a"):
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(self.duvod(cmd))
        for i in range(11):
            self.pis(f"pracovni/k{i}.sh", "echo ok\n")
        self.assertIsNotNone(self.duvod(" && ".join(f"bash pracovni/k{i}.sh" for i in range(11))))   # strop souborů
        self.assertIsNone(self.duvod(" && ".join(f"bash pracovni/k{i}.sh" for i in range(10))))
        for cmd in ("bash pracovni/ok.sh", "sh pracovni/ok", "source pracovni/ok.sh", ". pracovni/ok", "./pracovni/ok",
                    "python3 pracovni/ok.py", "bash tools/t.sh", "grep sudo pracovni/i.sh", "cat ./pracovni/i.sh"):
            with self.subTest(cmd=cmd):
                self.assertIsNone(self.duvod(cmd))   # tools/t.sh = zbytkové riziko (výjimka pro nástroje)

    def test_casovy_limit(self):
        mb, kb = 1_000_000, hlidac.STROP - 100
        vstupy = [";" * mb, "a" * mb, "'" + "a" * mb, "$(" * (mb // 2), "${a" * (mb // 3), "{a," * (mb // 3),
                  "`a" * (mb // 2), "cat <<E\n" + "x\n" * (mb // 2), "$'" + "a" * mb,
                  "sudo " + ";" * kb, "sudo " + "a" * kb, "sudo '" + "a" * kb + "'", "sudo $(" * (kb // 7),
                  "cat <<E\n" + "x\n" * (kb // 2) + "E\nsudo x"]
        # strop ≥ 10× změřeného (1 MB ≤ 0,28 s, 64 KiB ≤ 0,07 s, Mac M-series): odliší lineární od kvadratického
        vstupy += ["a{" * (mb // 2), "sudo " + "{a,b}" * (kb // 5), "\\\n" * (mb // 2)]
        for cmd in vstupy:
            with self.subTest(zacatek=cmd[:12], delka=len(cmd)):
                t = time.monotonic()
                self.duvod(cmd)
                self.assertLess(time.monotonic() - t, 3.0 if len(cmd) > hlidac.STROP else 1.0)

    def test_hlaska_a_sit(self):
        rozh, duvod = self.hook("sudo -n apt-get install -y tesseract-ocr")
        self.assertEqual(rozh, "deny")
        self.assertIn("! sudo", duvod)
        self.assertNotIn("slusne.py", duvod)
        rozh, duvod = self.hook("curl https://www.mza.cz/")
        self.assertEqual(rozh, "deny")
        self.assertIn(hlidac.NAVOD, duvod)
        rozh, duvod = self.hook('python3 -c "import urllib.request; urllib.request.urlopen(\'https://www.mza.cz\')"')
        self.assertEqual(rozh, "deny")
        self.assertIn(hlidac.NAVOD, duvod)
        self.assertEqual(self.hook("curl -s http://localhost:4321/")[0], "povoleno")
        self.assertEqual(self.hook("grep -rn 'sudo apt' reference/")[0], "povoleno")


if __name__ == "__main__":
    unittest.main()
