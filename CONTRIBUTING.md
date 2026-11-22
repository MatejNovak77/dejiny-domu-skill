# Jak přispět

Díky, že chcete skill vylepšit. Issue i pull request jsou vítané.

## Co přijmu rád
- opravy chyb ve výsledcích (špatně přečtený pramen, chybný odkaz, rozbitý nástroj);
- nástroje ke čtení dalších portálů a archivů, pokud to jejich podmínky dovolují;
- zrychlení nebo zlevnění práce (méně tokenů, méně kliknutí), když se nezhorší výsledek;
- bezpečnostní opravy.

## Co nepřijmu
- obcházení ochrany portálů proti robotům, vyšší tempo než dovoluje omezovač, stahování v rozporu s podmínkami
  archivu nebo s robots.txt (`skills/dejiny-domu/reference/podminky.md` a `portaly.md`);
- skutečné adresy, čísla popisná, signatury a jména ze soukromých domů v příkladech a testech (použijte Lniště nebo
  smyšlené „Dlouhá 12, Horní Lhota“);
- nové závislosti, hooky nebo síťová volání bez zdůvodnění.

Ne každá dobrá věc se do skillu hodí. Skill má zůstat jednoduchý. Když ji nepřijmu, napíšu proč.

## Pull request
- Jedna věc na PR. U větší změny nejdřív issue, ať se domluvíme, než strávíte čas kódem.
- Do popisu: jaký problém to řeší a příklad, kdy nastal (portál, typ domu, co vyšlo špatně).
- Commity podle `CLAUDE.md` (Conventional Commits, česky).
- `python3 -m unittest discover tests` musí projít; nové chování nástroje má mít test.
- Verzi neměňte, vydání dělám sám.

Než PR přijmu, vyzkouším ho na hotových domech s funkcí i bez ní. Může to pár dní trvat.

## Licence
Příspěvky jsou pod licencí MIT jako celý skill (`LICENSE`) a smí se použít i komerčně.
