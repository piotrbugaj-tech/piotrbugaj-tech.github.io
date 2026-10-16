#!/usr/bin/env python3
"""Scala klienci_marki.md + klienci_pracownie.md + klienci_hotele.md w klienci_50.md.
Uruchom z katalogu strategia/: python3 tools/merge_klienci.py
Zachowuje sekcje wstępne z obecnego klienci_50.md (do nagłówka '## Tabela zbiorcza'),
podmienia tylko tabelę zbiorczą i rezerwę hotelową.
"""
import re, pathlib
here = pathlib.Path(__file__).resolve().parent.parent

def rows(path, ncols):
    out = []
    for l in (here / path).read_text(encoding='utf-8').splitlines():
        if l.startswith('| ') and re.match(r'\|\s*\d+\s*\|', l):
            c = [x.strip() for x in l.strip().strip('|').split('|')]
            if len(c) == ncols:
                out.append(c)
    return out

marki = rows('klienci_marki.md', 11)[:18]      # # Nazwa Kraj Segment Poziom Dlaczego Kto Kontakt Fot Źródło Status
prac  = rows('klienci_pracownie.md', 11)[:17]  # # Nazwa Kraj Szczebel Segment Dlaczego Kto Kontakt Fot Źródła Status
hot   = rows('klienci_hotele.md', 10)[:18]     # # Nazwa Kraj Segment Dlaczego Kto Kontakt Fot Źródło Status
HOT_RESERVE = {'Raffles', 'Experimental', 'Design Hotels'}
REASONS = {
 'Raffles': 'Sieć luksusowa z centralnym PR Accor; brak podpisanego fotografa („TBC” w Wallpaper*); niska osiągalność i słabe dopasowanie do „design press”.',
 'Experimental': 'Grupa butikowa FR/IT/PT z własnym zespołem brand i studiem Chzon; otwarcia 2026–27 daleko od Warszawy; brak potwierdzonych credits.',
 'Design Hotels': 'Platforma członkowska, nie klient: kuratoruje zdjęcia dostarczone przez hotele, własnych autorów zleca tylko do książek. Droga prowadzi przez hotel-członka.',
}
norm = []
for r in marki:
    lvl = {'A': 'R', 'B': 'R/A', 'C': 'A'}.get(r[4], r[4])
    norm.append(['Marka', r[1], r[2], r[3], lvl, r[5], r[6], r[7], r[8], r[9], r[10]])
for r in prac:
    norm.append(['Pracownia', r[1], r[2], r[4], r[3], r[5], r[6], r[7], r[8], r[9], r[10]])
hot_res = []
for r in hot:
    if any(k in r[1] for k in HOT_RESERVE):
        hot_res.append(r); continue
    lvl = 'R' if ('PL' in r[2] or 'DE –' in r[2] or 'CZ' in r[2]) else 'A'
    norm.append(['Hotel', r[1], r[2], r[3], lvl, r[4], r[5], r[6], r[7], r[8], r[9]])

hdr = '| # | Segment | Nazwa | Kraj / miasto | Profil | Szczebel | Dlaczego pasuje | Kto zleca zdjęcia | Publiczny kontakt | Fotografowie w credits | Źródło | Status |'
sep = '|---|---|---|---|---|---|---|---|---|---|---|---|'
table = '\n'.join([hdr, sep] + ['| ' + ' | '.join([str(i)] + r) + ' |' for i, r in enumerate(norm, 1)])
res = ''
if hot_res:
    res = '\n\n### Hotele przeniesione do rezerwy (pełne wiersze w `klienci_hotele.md`)\n\n| Nazwa | Kraj | Dlaczego w rezerwie |\n|---|---|---|\n'
    for r in hot_res:
        key = [k for k in REASONS if k in r[1]][0]
        res += f'| {r[1]} | {r[2]} | {REASONS[key]} |\n'

target = here / 'klienci_50.md'
old = target.read_text(encoding='utf-8')
head = old.split('## Tabela zbiorcza')[0]
target.write_text(head + '## Tabela zbiorcza (' + str(len(norm)) + ')\n\n' + table + res + '\n', encoding='utf-8')
print('rows:', len(norm), '| reserve:', len(hot_res))
