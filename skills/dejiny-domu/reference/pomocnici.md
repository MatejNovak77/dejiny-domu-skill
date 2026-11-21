# Pomocníci (subagenti): na jakém modelu

Volbu modelu pomocníků drží projekt v `data/nastaveni.json`, sekce `pomocnici`. Ruční úpravou souboru ho neměň,
jen nástrojem:

```
python3 -I tools/nastaveni.py ukaz pomocnici
python3 -I tools/nastaveni.py nastav pomocnici.rukopisy opus      # jen se souhlasem uživatele s uložením
python3 -I tools/nastaveni.py nastav pomocnici.rukopisy vychozi   # volbu smaže, příště se zase zeptáš
```

| Klíč | Kdy | Výchozí |
|---|---|---|
| `pomocnici.rukopisy` | pomocník bude číst **snímky ručně psaného textu**: matriky, gruntovní a pozemkové knihy, sčítací operáty, rukopisné kroniky, cokoli v kurentu | nenastaveno → zeptej se |
| `pomocnici.ostatni` | tištěné zdroje, OCR texty, procházení portálů a katalogů | `sonnet` |

Nejasné (tisk s rukopisnými poznámkami, smíšený svazek) = rukopis.

## Před každým kolem pomocníků
1. Spusť `python3 -I tools/nastaveni.py ukaz pomocnici`.
2. Je u klíče hodnota (`pomocnici.rukopisy = opus`)? Pusť pomocníky na tom modelu a řekni to uživateli jednou větou
   („pomocníci poběží na Opusu podle nastavení projektu“). Znovu se neptej.
3. Řádek `→ ZEPTEJ_SE pomocnici.rukopisy` a kolo čte rukopisy? Nejdřív **nabídka** níže. Spoj ji se schválením
   velkého kola (kredity), ať se uživatel neptá dvakrát. Nic nespouštěj a nic nezapisuj, dokud neodpoví.
   V jedné konverzaci se ptej nejvýš jednou; volbu, kterou ti dal, použij pro všechna další kola té konverzace.

## Nabídka (při první práci pomocníků s rukopisy)
Řekni uživateli vlastními slovy, krátce a srozumitelně:
- **Sonnet** je levnější, **Opus** čte ručně psané písmo spolehlivěji. Příklad z projektu Husí Boudy (Krkonoše,
  listopad 2026): pomocníci na Sonnetu „četli kurent v matrikách výrazně hůř (zkomolená křestní jména, záměny
  příjmení, přehlédnuté zápisy); ověření stálo skoro tolik práce jako čtení“. Pomocník na Opusu měl při ověření
  **145/146** zápisů křtů správně (1 chyba v datu). Číslo pro Sonnet neuváděj, žádné změřené není.
- **Cena:** Opus je **zhruba dvakrát dražší** než Sonnet (ceník Anthropicu
  https://platform.claude.com/docs/en/about-claude/pricing, poměr ověřen 21. 11. 2026 pro Claude Opus 5.5
  a Sonnet 5.5). Přesné částky neuváděj. Nabídni, že aktuální ceník ověříš: když uživatel chce, přečti oficiální
  ceník a řekni, co platí teď; bez přístupu na web to řekni. U jiného modelu než Sonnet a Opus žádný poměr netvrď,
  jen nabídni ověření ceníku. S předplatným (Pro, Max) se neplatí za tokeny, ale Opus podle
  https://claude.com/pricing čerpá limit jinak než Sonnet („How fast you reach a limit depends on the model you use“);
  o kolik, oficiální stránky neuvádějí. Ceník se mění: když od data ověření uplynulo víc než pár měsíců, řekni to.
- **Zkouška:** můžeš to vyzkoušet na malé dávce (níže), ať se uživatel rozhodne podle vlastních pramenů.
- Zeptej se na **dvě věci zvlášť**: (1) který model teď, (2) „Mám volbu uložit do nastavení projektu, ať se příště
  neptám?“

Co s odpovědí:
| Uživatel řekne | Co uděláš |
|---|---|
| model **a** jednoznačně „ano, ulož / zapamatuj si to“ | `nastaveni.py nastav pomocnici.rukopisy <model>` a potvrď mu to |
| jen model („teď Opus“), nebo „neukládej“ | použij model pro tuto konverzaci, **nic neukládej**; řekni, že se příště zeptáš znovu |
| „nevím“, „je mi to jedno“ | toto kolo `sonnet`, nic neukládej, nabídni zkoušku |
| „vyzkoušej to“ | zkouška (níže), pak znovu obě otázky |
| jiný model (Haiku, Fable, model jiného hostitele) | použij ho, poměr ceny netvrď, nabídni ověření ceníku; ukládej jen po „ulož“ |

Bez výslovného souhlasu s uložením nikdy `nastav` nespouštěj. Volba modelu sama souhlasem s uložením není.

## Zkouška na malé dávce
1. Vyber ~10 snímků z kola (víc ne, viz `matriky.md` → nenačtené snímky), ideálně s několika zápisy.
2. Pusť dva pomocníky se **stejným zadáním**, jeden na Sonnetu do `pracovni/pom_<úkol>_sonnet/`, druhý na Opusu
   do `pracovni/pom_<úkol>_opus/`. Zadání jako u běžného kola (u každého snímku rok, číslo domu, první jméno;
   do `data/` nic).
3. Porovnej výstupy. Každý **rozdílný** zápis a 3 shodné ověř sám na snímku (`tools/overit.py`).
4. Ukaž tabulku: zápisů celkem, správně, chybná jména, chybná data, přehlédnuté zápisy – pro každý model. Řekni,
   kolik zkouška stála (zhruba dvě dávky po 10 snímcích, jedna z nich za cenu Opusu).
5. Pak obě otázky z nabídky (model, uložit?).

## Jak model předat hostiteli
Hodnota v nastavení je název modelu, jak ho zná hostitel (nástroj ji ukládá malými písmeny); předej ji beze změny.
V Claude Code ukládej a předávej alias (`sonnet`, `opus`, `haiku`, `fable`) jako parametr `model` nástroje Agent –
plné ID ani `inherit` parametr nebere (https://code.claude.com/docs/en/sub-agents, 21. 11. 2026); bez parametru
pomocník běží na modelu hlavní konverzace.
**Záložní postup:** hostitel volbu modelu pomocníka nemá, nebo název modelu odmítne (např. organizace model
nepovoluje, chyba „issue with the selected model“)? Řekni to uživateli jednou větou, pusť pomocníky na výchozím
modelu hostitele a u volby `opus` nabídni, že rukopisy přečteš sám v hlavní konverzaci. Nastavení neměň.

## Změna volby
Uživatel chce volbu změnit nebo smazat („příště se zase ptej“): s jeho souhlasem `nastav pomocnici.rukopisy <model>`,
nebo `… vychozi`. `pomocnici.ostatni` měň jen na přání uživatele, nenabízej to.
