# HANDOFF v2: dokończenie researchu strategii piotrbugaj.com

Data: 16.10.2026. Dla nowej sesji Claude Code na gałęzi `claude/new-session-g6rgky` repo `piotrbugaj-tech/piotrbugaj-tech.github.io`. Katalog roboczy: `strategia/`.

## 1. Co już jest (nie powtarzaj)

- `strategia_top10.md` — dokument główny (podsumowanie, sekcje 0–6, szablony, plan portfolio, poprawki strony, „Status weryfikacji i co dokończyć" na końcu). Kompletny; po researchu wymaga tylko aktualizacji liczb, dat i listy luk.
- `media.md` — 33 redakcje; 16 potwierdzonych, 4 częściowo, 13 „nie sprawdzono".
- `nagrody_eventy.md` — 21 konkursów + 7 PL, 29 wydarzeń, kalendarz; 11 luk w sekcji „Luki weryfikacyjne".
- `klienci_marki.md`, `klienci_pracownie.md`, `klienci_hotele.md` — 18 / 17 / 18 wierszy + rezerwy + „Do dokończenia" na końcu każdego.
- `klienci_50.md` — zbiorcza tabela 50 wierszy generowana skryptem `tools/merge_klienci.py` z trzech plików powyżej (po zmianach w źródłach uruchom: `cd strategia && python3 tools/merge_klienci.py`; sekcja wstępna i „Pierwsze 10 celów" zostają).
- `fotografowie_uzupelnienie.md` — Vercruysse, Salvaing, Bjerre-Poulsen + agencje; luki w sekcji 5.10.
- `HANDOFF_piotrbugaj_strategia.md` — oryginalny prompt użytkownika, audyt strony, 13 fotografów (poprzednia sesja).

## 2. Ograniczenia środowiska (ustalone 16.10.2026)

- **WebFetch nie działa** (błąd DNS, omija proxy); `curl` z kontenera jest odrzucany przez proxy (403) dla hostów redakcji, marek, hoteli i piotrbugaj.com. Najpierw jeden test WebFetch na dowolnym URL; jeśli nadal nie działa, pracuj wyłącznie na WebSearch (snippety oficjalnych stron).
- **Limit WebSearch: 200 wywołań na turę, wspólny dla wszystkich subagentów.** Poprzednio 6 równoległych agentów wyczerpało go w kilka minut. Teraz: **maksymalnie 3 agenty, każdy z twardym limitem 55 wyszukiwań**, orkiestrator zachowuje ~30 na własne poprawki. Nie obchodź limitu (żadnych czytników, archiwów, proxy).
- Zasady treści: po polsku; nie wymyślaj nazwisk, adresów, cen, dat; tylko adresy ogólne (press@/info@/office@/formularz) z oficjalnych stron; przy braku potwierdzenia pisz „unverified"; każdy wiersz ze źródłem (URL).

## 3. Luki do zamknięcia (priorytet malejący)

### Agent A — `media.md` (limit 55 wyszukiwań)
1. 13 wierszy „nie sprawdzono": Label Magazine, Design Alive, Whitemad, Magazif, Architektura-murator (PL — najważniejsze), BauNetz / BauNetz ID, Schöner Wohnen, Dear Magazine (DE), Living Corriere, Interni, Casa Vogue (IT/BR), Architizer, Archello. Dla każdego: oficjalna ścieżka submisji (adres/formularz), wymagania, czy od fotografów, profil fotografa, priorytet, źródło.
2. 4 „unverified": AD (które edycje DE/ES/FR/IT/US mają publiczną ścieżkę), Elle Decoration Polska, Abitare, Cereal.
3. Odczytać ze stron oficjalnych adresy: Divisare photo reports (divisare.com/submit), Sight Unseen (sightunseen.com/submissions).
4. Lista dodatkowa (jeśli zostanie budżet): IGNANT, Leibal, Est Living, The Local Project, Ark Journal.
Zapisz do `media.md` (podmień wiersze, zaktualizuj licznik w intro i usuń sekcję „Do zrobienia w kolejnej sesji" lub zostaw tylko to, co nadal otwarte).

### Agent B — `nagrody_eventy.md` (limit 55)
1. Architectural Photography Awards (WAF/Sto): zasady, opłata, terminy edycji 2026/2027; miasto i daty WAF 2026.
2. architekturbild (Europejska Nagroda Fotografii Architektury): temat, termin, opłata edycji 2027.
3. Opłaty IPA i TIFA (tylko dla kompletności).
4. Dokładne daty 2027 (strony oficjalne): Salone del Mobile + Euroluce, Fuorisalone, Maison&Objet (I 2027), Stockholm Furniture Fair, 3daysofdesign, Clerkenwell Design Week, Arena Design/Meble Polska, Łódź Design Festival, Gdynia Design Days, Open House Warszawa, Independent Hotel Show (Amsterdam 2027, London 2026/27), Sleep + Eat 2026, 4 Design Days / Property Design Awards 2027, Warsaw Home & Living 2027, Designblok 2027; potwierdzenie ORGATEC 20–23.10.2026; status imm cologne 2027.
5. Konferencje hotelowe w PL (Hotelarz / Hotel Meeting / inne) — czy istnieją edycje 2026/27.
6. Ostatnia próba: czy istnieje profesjonalny polski konkurs fotografii architektury (SARP, festiwale foto z kategorią architektura).
Zapisz do `nagrody_eventy.md` (podmień statusy orientacyjnie → potwierdzone, zaktualizuj „Kalendarz 12 miesięcy" i sekcję luk).

### Agent C — `klienci_*.md` (limit 55)
1. Pracownie (17): oficjalna domena + adres ogólny lub URL formularza; credits dla Mistovia (Rozkoszyny 2025, Plener Istebna 2025), Agnieszka Owsiany (Botaniczna), Mesura (Aesop Diagonal), Note Design Studio (Tarkett 2025), Mobius (Loop House 2024).
2. Marki: adresy/strony prasowe dla Chors, TON, Javorina, Frama, Woud, e15, Muuto, AQForm (adres), Brokis (PR Kit URL); kredyty fotografów dla Noti, Comforty, Tylko (jeśli publiczne).
3. Hotele (15 z `klienci_50.md`): strona press/PR/kontakt lub adres ogólny: PURO, Hotel Warszawa (Likus), Nobu Warsaw, Hotel Verte / Budizol, H15 Palace / Dobry Hotel, Arche Hotels, Autor Rooms, The Hoxton Kraków / Ennismore, Wilmina, Château Royal Berlin, Michelberger, The Julius Prague, Vipp Guesthouses, Hotel Sanders, Ett Hem.
4. Jeśli zostanie budżet: `fotografowie_uzupelnienie.md` §5.10 — VIEW Pictures, Taverne Agency, GAP Interiors, Narratives, TAKE Agency, reprezentacja na salvalopez.com (Rocafort / Artist Management).
Zapisz do plików źródłowych (podmień komórki „unverified"/„niepotw."), potem uruchom `tools/merge_klienci.py`.

### Orkiestrator (po agentach, ~30 wyszukiwań rezerwy)
1. Zaktualizuj `strategia_top10.md`: sekcja 3.1 (wiersz „Rynek PL" — ścieżki PL), 3.2 (APA, architekturbild: opłaty i terminy), 3.5 (daty potwierdzone), 6.2 (licznik potwierdzonych redakcji), „Status weryfikacji i co dokończyć" (usuń zamknięte luki, zostaw otwarte). Nie zmieniaj werdyktu ani struktury.
2. Sprawdź spójność tabel (każdy wiersz = liczba kolumn nagłówka).
3. `git add strategia && git commit && git push -u origin claude/new-session-g6rgky`. Nie twórz PR, nie pushuj na main.
4. Raport końcowy po polsku: co potwierdzono, co nadal „unverified", 3 najważniejsze zmiany w dokumencie.

## 4. Czego nie robić
- Nie powtarzaj audytu strony ani researchu 13 fotografów.
- Nie dopisuj nowych klientów ani redakcji ponad listy; zamykaj luki.
- Nie zmieniaj plików poza `strategia/`.
