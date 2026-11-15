#!/usr/bin/env python3
"""Hook commit-msg: kontrola Conventional Commits (viz CLAUDE.md).

Zapnutí po naklonování: ln -sf ../../tests/commit_msg.py .git/hooks/commit-msg
(V Pythonu a v tests/, protože adresář pluginů Anthropicu nepřijme shellové skripty mimo skill.)
"""
import re
import sys

TYPY = "feat fix docs refactor style test chore release"
SCOPE = "skill reference playbook nastroje web readme plugin"
VZOR = re.compile(rf"^({'|'.join(TYPY.split())})(\(({'|'.join(SCOPE.split())})\))?!?: .+")


def chyba(predmet):
    """Text chyby, nebo None, když je předmět commitu v pořádku."""
    if predmet.startswith(("Merge", "Revert", "fixup!", "squash!")):
        return None
    if not VZOR.match(predmet):
        return (f"Commit neodpovídá formátu <typ>(<scope>): <popis>\n"
                f"Typy: {TYPY}, scope: {SCOPE} (viz CLAUDE.md)\nZpráva: {predmet}")
    if len(predmet) > 80:
        return f"Předmět commitu má přes 80 znaků (cíl ~72), detaily patří do těla. Zpráva: {predmet}"
    return None


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as f:
        prvni = f.readline().rstrip("\n")
    text = chyba(prvni)
    if text:
        sys.exit(text)
