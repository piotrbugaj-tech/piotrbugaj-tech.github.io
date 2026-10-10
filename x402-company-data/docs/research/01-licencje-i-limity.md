# 01 — Licencje, limity i ryzyko RODO dla źródeł danych o polskich firmach

> **Status:** research / due diligence, **nie jest poradą prawną**. Stan na **2026-10-10**.
> **Metodologia i zastrzeżenie dot. weryfikacji:** w tym środowisku zarówno `curl`, jak i narzędzie WebFetch nie mogły połączyć się z hostami `*.gov.pl`, `europa.eu`, `wikipedia.org` (proxy 403 / DNS ENOTFOUND). Wszystkie cytaty poniżej pochodzą z **wyciągów wyszukiwarki (WebSearch) z podanych URL-i**, a nie z bezpośredniego pobrania strony. Oznaczenia:
> - **[V]** zweryfikowane: ten sam fakt lub cytat pojawia się w wyciągu ze strony oficjalnej (gov.pl, isap, nsa, uodo, europa.eu) albo w kilku niezależnych źródłach.
> - **[S]** źródło wtórne: blog, kancelaria, serwis komercyjny. Wymaga sprawdzenia w źródle pierwotnym.
> - **[I]** wniosek własny (inferencja), bez bezpośredniego źródła.
>
> Przed uruchomieniem produkcji trzeba **ręcznie otworzyć i zarchiwizować (PDF/zrzut ekranu z datą)** strony oznaczone w sekcji „Do zrobienia przed produkcją”.

---

## TL;DR

| Źródło | Klucz / rejestracja | Limity (opublikowane) | Komercyjne ponowne wykorzystanie | Ryzyko danych osobowych | Werdykt |
|---|---|---|---|---|---|
| **KRS Open API** (MS, `api-krs.ms.gov.pl`) | **Nie.** Otwarte, bezpłatne, bez konta **[V]** | **Brak opublikowanych limitów** **[I]**. Trzeba się samemu ograniczać i cache'ować | **Tak.** Ustawa o otwartych danych. Warunki MS: źródło, czas wytworzenia i pozyskania **[V]** | **Niskie.** Imiona, nazwiska i PESEL osób fizycznych są **zanonimizowane** w API **[V]** | 🟢 **GREEN** |
| **GUS REGON BIR1.1/1.2** (`api.stat.gov.pl`) | **Tak.** Bezpłatny klucz produkcyjny, mailowo `regon_bir@stat.gov.pl`. Klucz testowy jest publiczny **[V]** | 8:00–16:59: **120/min, 6 000/h, 3/s**. W nocy (22:00–5:59) do **10 000/h**. Przekroczenie oznacza ostrzeżenie, nie natychmiastową blokadę **[V/S]** | **Tak.** Rejestr REGON jest jawny (art. 45 u.s.p.). Warunki GUS: źródło, czas, informacja o przetworzeniu **[V]** | **Średnie** dla osób fizycznych (JDG: imię, nazwisko, adres działalności). Niskie dla osób prawnych | 🟢/🟡 **GREEN** dla podmiotów KRS, **YELLOW** dla JDG. Pełny regulamin BIR nieprzeczytany |
| **CEIDG API v3** (Hurtownia Danych, `dane.biznes.gov.pl`) | **Tak.** Konto biznes.gov.pl, wniosek podpisany (PZ/e-dowód/kwalifikowany), akceptacja oświadczenia o ochronie danych osobowych, klucz zamieniany na JWT **[V/S]** | **50 żądań / 3 min** oraz **1 000 żądań / 60 min** (oba limity naraz). Po przekroczeniu limitu 3-minutowego: pauza 180 s **[V]**. Teza o „~500/h” jest **nieaktualna** (stan z 2021 r.) | **Tak.** Art. 48 ust. 2 ustawy o CEIDG odsyła do ustawy o otwartych danych **[V]** | **Wysokie.** Każdy wpis to osoba fizyczna. Precedens **Bisnode** (art. 14 RODO, 943 470 zł, prawomocny wyrok NSA z 19.09.2023) | 🟡 **YELLOW** |
| **Biała Lista VAT** (MF, `wl-api.mf.gov.pl`) | **Nie** **[V]** | **search: 100 zapytań/dzień, maks. 30 podmiotów w zapytaniu. check: 5 000 podmiotów/dzień.** Po wyczerpaniu możliwa blokada do 0:00 **[V]**. Limit liczony prawdopodobnie per IP **[S]** | **Tak.** Warunki MF: źródło, czas, informacja o przetworzeniu. MF nie odpowiada za dane po przetworzeniu **[V]** | **Średnie/wysokie.** Pełne imiona i nazwiska członków zarządu, prokurentów i wspólników, rachunki JDG **[V]** | 🟢 **GREEN** dla `check` (NIP + rachunek), 🟡 **YELLOW** dla `search` (reprezentanci, rachunki) |
| **VIES** (KE, REST/SOAP) | **Nie** **[V]** | **Brak opublikowanych limitów.** Globalny limit współbieżności per państwo (`MS_MAX_CONCURRENT_REQ`) **[S]** | **Tak.** Polityka ponownego wykorzystania KE (Decyzja 2011/833/UE, CC BY 4.0). Disclaimer KE **[V/S]** | **Niskie/średnie.** Nazwa i adres; dla JDG to dane osobowe | 🟢 **GREEN** |

**Wniosek ogólny:**

- **MVP oparte na podmiotach z KRS** (KRS Open API + REGON dla osób prawnych + Biała Lista `check` + VIES) jest **prawnie bezpieczne** (GREEN), pod warunkiem atrybucji, zakazu wprowadzania w błąd i krótkiego cache.
- **Dane JDG** (CEIDG oraz REGON/Biała Lista dla osób fizycznych) są **legalne do ponownego wykorzystania jako ISP**. Pełnią jednak obowiązki administratora z RODO, w szczególności **art. 14**. To jest jedyny realny „bloker”, który wymaga decyzji właściciela i najlepiej krótkiej konsultacji z polskim prawnikiem.

---

## 1. KRS — API Rejestrów Sądowych (Open API), Ministerstwo Sprawiedliwości

### 1.1 Dostęp, klucz, koszt
- **[V]** Komunikat MS z **8 marca 2022 r.** „Uruchomienie otwartego API Krajowego Rejestru Sądowego” (https://www.gov.pl/web/sprawiedliwosc/uruchomienie-otwartego-api-krajowego-rejestru-sadowego): MS uruchomiło pierwszą usługę udostępniania danych KRS przez API, na podstawie ustawy o otwartych danych z 2021 r. Zakres danych „odpowiada odpisom aktualnym i pełnym wydawanym przez Centralną Informację KRS, **z uwzględnieniem RODO**”.
- **[V]** Endpointy (https://prs.ms.gov.pl/krs/openApi):
  - `GET https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{krs}?rejestr={P|S}&format=json`
  - `GET https://api-krs.ms.gov.pl/api/krs/OdpisPelny/{krs}?rejestr={P|S}&format=json`
  - usługa „Biuletyn”, czyli lista numerów KRS zmienionych w danym dniu lub godzinie.
- **[V/S]** Nie wymaga konta ani klucza i jest bezpłatne (otwarteapi.pl, dane-firm.pl, nip24.pl).
- **[V]** Anonimizacja. Wyciąg z PRS: „pobrane poprzez API dane osób fizycznych ujawnionych w rejestrze są **zanonimizowane w zakresie imion, nazwisk i ich numerów PESEL**”. Przykład z praktyki **[S]**: nazwisko w postaci `N**********`, imię `P****`, PESEL `7**********`. Zachowana jest pierwsza litera lub cyfra (raport PARP, dane-firm.pl).
- **Brak wyszukiwania po nazwie** w Open API **[V/S]**. Dostępne są tylko zapytania po numerze KRS oraz biuletyn zmian.

### 1.2 Limity
- **[I]** Nie znalazłem żadnego opublikowanego limitu zapytań ani regulaminu SLA dla Open API. Rekomendacja: własny limiter (np. ≤ 2 req/s globalnie), cache, backoff na 429/5xx.

### 1.3 Licencja i warunki
- **[V]** Strona MS „Ponowne wykorzystywanie” (https://www.gov.pl/web/sprawiedliwosc/ponowne-wykorzystywanie): „Każdy ma prawo do ponownego wykorzystywania informacji sektora publicznego na zasadach określonych w ustawie z dnia 11 sierpnia 2021 r. o otwartych danych i ponownym wykorzystywaniu informacji sektora publicznego”. Warunki MS obejmują „obowiązek poinformowania o źródle pochodzenia, czasie wytworzenia i pozyskania informacji od Ministerstwa Sprawiedliwości”.
- **[V/S]** NSA (III OSK 4558/21, 30.11.2021, sprawa serwisu publikującego dane z KRS): „ustawa o KRS nie zawiera wyłączeń odnośnie ponownego wykorzystania informacji sektora publicznego”. Wynika z tego, że ponowne wykorzystanie danych KRS, także komercyjne, jest dopuszczalne.
- **Jawność:** art. 8 ust. 1 ustawy o KRS: „Rejestr jest jawny” **[I: brzmienie znane, nie pobrane w tej sesji]**.

### 1.4 Nowelizacja KRS z 2025 r. i art. 60a (ważne!)
- **[V]** Ustawa z 26 września 2025 r. o zmianie ustawy o KRS oraz niektórych innych ustaw, **Dz.U. 2025 poz. 1556**, ogłoszona 14.11.2025, w życiu od **29.11.2025** (https://isap.sejm.gov.pl/isap.nsf/download.xsp/WDU20250001556/O/D20251556.pdf).
  - **Art. 4 ust. 4c** (w brzmieniu z wyciągu): „Centralna Informacja udostępnia podmiotom, które uzyskały zgodę, o której mowa w ust. 4d, bezpłatnie informacje z Rejestru za pośrednictwem usług sieciowych.” Zgodę wydaje **Minister Sprawiedliwości w drodze decyzji administracyjnej** (ust. 4d). Dotyczy to podmiotów publicznych i podmiotów realizujących zadania publiczne. Jest to tzw. **„Full API”** z nieanonimizowanymi danymi.
  - **Art. 60a**: „Kto bez uprawnienia uzyskuje z Rejestru informację za pośrednictwem usług sieciowych, podlega grzywnie, karze ograniczenia wolności albo pozbawienia wolności do lat 2.”
- **[V/S]** Open API pozostaje dostępne dla każdego bez zgody i zwraca dane zanonimizowane (prawo.pl, dane-firm.pl). Art. 60a dotyczy nieuprawnionego dostępu do usług sieciowych wymagających zgody.
- **Wnioski praktyczne [I]:**
  1. Korzystamy **wyłącznie** z publicznego Open API. **Nie** używamy cudzych poświadczeń do Full API.
  2. **Nie** scrapujemy wyszukiwarki eKRS (`wyszukiwarka-krs.ms.gov.pl`, chronionej CAPTCHA). Obchodzenie zabezpieczeń może zostać zakwalifikowane jako dostęp „bez uprawnienia” (art. 60a KRS, art. 267 kk).
  3. **Nie de-anonimizujemy** zamaskowanych osób z KRS, np. przez automatyczne „doklejanie” pełnych nazwisk z innych źródeł do zamaskowanych pól KRS. Nie jest to wprost zakazane. Działa jednak wbrew celowi, dla którego MS anonimizuje dane, i zwiększa ryzyko RODO.

### 1.5 Dane osobowe
- Niskie ryzyko: osoby w zarządzie, wspólnicy i prokurenci są zamaskowani. Ryzyko rezydualne pojawia się, gdy nazwa (firma) spółki zawiera imię i nazwisko (np. „Jan Kowalski sp. z o.o.”, sp. j., sp. k.). To nadal dane osobowe, ale to jawna firma przedsiębiorcy.
- Nasz JSON **nie jest „odpisem z KRS”**. Moc dokumentów urzędowych mają wydruki i odpisy z Centralnej Informacji (art. 4 ust. 3 i 4aa ustawy o KRS) **[V/S]**. Nie wolno nazywać naszego wyniku „odpisem”.

**Werdykt KRS: 🟢 GREEN.**

---

## 2. GUS — REGON, usługa BIR1.1 (i BIR1.2)

### 2.1 Dostęp, klucz, koszt
- **[V]** Portal API GUS, https://api.stat.gov.pl/Home/RegonApi. Usługa „Dostęp do danych rejestrowych REGON poprzez usługę sieciową – interfejsy API” (BIR1 = Baza Internetowa REGON 1) jest dostępna dla administracji oraz **podmiotów komercyjnych** („dane ogólnodostępne”). Wniosek o klucz produkcyjny składa się mailowo na **regon_bir@stat.gov.pl**. Telefony: 22 608-36-39 i 22 608-33-74. Wersje: **1.1** (od maja 2019) i **1.2** (od grudnia 2024).
- **[S]** We wniosku podaje się nazwę, REGON, NIP, adres, osobę kontaktową, **publiczny adres IP** i przybliżoną liczbę jednoczesnych użytkowników. Klucz przychodzi po około 5 dniach roboczych i jest **bezpłatny** (kcserwis.pl/klucz-gus-bir, brokerdanych.pl).
- **[V/S]** Klucz testowy `abcde12345abcde12345` łączy się ze środowiskiem testowym z niepełnymi, zanonimizowanymi danymi.
- **[S]** Klucz bywa przypisany do konkretnej wersji usługi (1.1 albo 1.2).
- **[V/S]** Wyszukiwanie (`DaneSzukajPodmioty`) działa **tylko po identyfikatorach**: Regon, Nip, Krs, Regony9zn, Regony14zn, Nipy, Krsy. **Nie ma wyszukiwania po nazwie.**

### 2.2 Limity (z portalu GUS i instrukcji BIR)
- **[V]** Wyciąg z api.stat.gov.pl i jego powtórzenia (forum.dmplaza.eu, docs.plusworkflow.pl):
  - **8:00–16:59**: **6 000 wywołań/h, 120/min, 3/s**.
  - Godziny popołudniowe i poranne: wyższe progi.
  - **22:00–5:59**: **10 000/h** (wariant wyższy: 200/min).
  - „**Przekroczenie limitów nie skutkuje natychmiastową blokadą dostępu**”. Użytkownicy przekraczający limity są o tym informowani.
- **[S]** Starsza instrukcja z 2014 r. podawała 150/min i 3/s, więc rozbieżność wynika z wersji. Obowiązują wartości z portalu.
- **[S]** Sesja (`sid`) wygasa po około 60 minutach bezczynności.

### 2.3 Regulamin / warunki
- **[V]** Instrukcja techniczna BIR1 dla podmiotów komercyjnych zawiera rozdział „**Regulamin korzystania z usługi**”: „Korzystanie z Usługi BIR1 (…) wiąże się z **akceptacją niniejszego regulaminu (wraz z późniejszymi zmianami)**”. Niedostępność usługi spowodowana „niestosowaniem się do Regulaminu korzystania z usługi” obciąża usługobiorcę.
- ⚠️ **Nie udało się uzyskać pełnej treści regulaminu**, w tym ewentualnych klauzul o dalszym udostępnianiu i odpowiedzialności. Regulamin jest w ZIP-ie z instrukcją na api.stat.gov.pl. **Do przeczytania i zarchiwizowania przed produkcją.** W żadnym z przejrzanych źródeł nie trafiłem na zakaz komercyjnego dalszego udostępniania danych z BIR **[I]**. Wiele firm (dataport.pl, nip24, MGBI, Transparent Data) oferuje płatne API nad BIR.
- **[V]** BIP GUS, „Ponowne wykorzystywanie informacji sektora publicznego” (https://bip.stat.gov.pl/kontakt/ponowne-wykorzystywanie-informacji-sektora-publicznego/): „Podmiot ponownie wykorzystujący informację publiczną pochodzącą z Głównego Urzędu Statystycznego jest zobowiązany do: **poinformowania o źródle, czasie wytworzenia i pozyskania informacji z GUS; poinformowania o przetworzeniu informacji ponownie wykorzystywanej.**” *(ang.: credit GUS as source, give creation/acquisition time, disclose that the data was processed.)*

### 2.4 Podstawa ustawowa (ustawa o statystyce publicznej z 29.06.1995)
- **[V]** **Art. 45 ust. 1** (brzmienie po nowelizacji z grudnia 2025 r., Dz.U. 2025 poz. 1792, wg wyciągu): „W zakresie numeru identyfikacyjnego REGON oraz informacji, o których mowa w art. 42 ust. 3 pkt 1–4, 5 lit. a–i, j tiret pierwsze oraz lit. k i l, a także pkt 6 i 9, **z wyłączeniem numeru PESEL i adresu zamieszkania osoby fizycznej prowadzącej działalność gospodarczą, jeżeli nie został wskazany jako adres wykonywania działalności, rejestr REGON jest jawny i dostępny dla osób trzecich**.” Udostępnia się także telefon, e-mail i www, „o ile podmiot je poda”.
- **[V]** Art. 45 ust. 3: wyciągi i zestawienia na indywidualne zamówienie są **odpłatne**. Art. 45a: GUS udostępnia te informacje na swojej stronie lub przez ePUAP. Art. 44 nakłada na rejestry obowiązek posługiwania się numerem REGON.
- **[I]** Wniosek: dane z BIR są jawne. Masowe odtwarzanie całej bazy przez BIR byłoby obchodzeniem płatnych zestawień z art. 45 ust. 3 i limitów usługi. Nasz model zapytań na żądanie tego nie robi.

### 2.5 Ryzyko techniczne dla Cloudflare Workers
- **[S/I]** GUS prosi we wniosku o publiczny IP. Workers nie mają stałego adresu egress (wyjątek: płatne opcje dedykowanego egress lub proxy). **Trzeba potwierdzić z GUS, czy klucz jest wiązany z IP.** Jeśli tak, potrzebny jest stały egress (np. mały VPS/proxy w UE).

**Werdykt GUS: 🟢 GREEN dla osób prawnych; 🟡 YELLOW dla JDG (RODO) i do czasu przeczytania regulaminu BIR.**

---

## 3. CEIDG — Hurtownia Danych CEIDG i Biznes.gov.pl, API v3

### 3.1 Dostęp
- **[V/S]** Potrzebne są konto na biznes.gov.pl i **wniosek o dostęp** do Hurtowni, uwierzytelniony profilem zaufanym, e-dowodem lub podpisem kwalifikowanym. „Dostęp do Hurtowni danych uzyskasz, jeśli zaakceptujesz **oświadczenie o ochronie i przetwarzaniu danych osobowych**” (poradnikprzedsiebiorcy.pl, dane.biznes.gov.pl/pl/portal/034872). Klucz przychodzi mailem i jest używany jako **JWT** w nagłówku `Authorization: Bearer` **[V]**. Bezpłatnie.
- **[V]** Od **1 października 2025** dostęp do danych CEIDG przez API Hurtowni jest możliwy wyłącznie przez **API HD v3**. Wersja v2 była utrzymywana do 30.09.2025 (komunikat cytowany przez support.hogart.com.pl/news/5).
- **[V]** Dokumentacja: „DOKUMENTACJA DLA INTEGRATORÓW (API V3) HURTOWNI DANYCH CEIDG I BIZNES.GOV.PL” v1.0/v1.1 (https://pliki.biznes.gov.pl/akademia/20250117/HD%20CEIDG%20-%20API%20v3%20HD%20-%20Dokumentacja%20dla%20integrator%C3%B3w%20v1.1.pdf).
- API v3 obsługuje wyszukiwanie m.in. po nazwie, NIP, REGON i imieniu i nazwisku **[S]**. To jedyne oficjalne API z wyszukiwaniem po nazwie, ale dotyczy tylko JDG.

### 3.2 Limity (zweryfikowane)
- **[V]** Dokumentacja v3: dwa jednoczesne limity, **50 żądań w okresie 3 minut** oraz **1000 żądań w okresie 60 minut**. Żaden nie może zostać przekroczony. Po przekroczeniu limitu 3-minutowego następuje **pauza 180 s liczona od ostatniego żądania**. Dokumentacja zaleca odstęp około 3,6 s między żądaniami.
- **[S]** Liczba „~500/h” pochodzi z 2021 r. (Medium, Transparent Data) i jest **nieaktualna**.
- **[V]** Dokument architektury ministerstwa: API Gateway może nakładać limity transferu i liczby żądań, więc wartości per użytkownik mogą się różnić.
- **Pojemność [I]:** ~1 000 świeżych zapytań/h, czyli ~24 000/dobę na token. Więcej tokenów na jeden podmiot w celu obejścia limitu to ryzyko naruszenia warunków. **Nie rekomenduję.**

### 3.3 Podstawa prawna ponownego wykorzystania (ustawa z 6.03.2018 o CEIDG i Punkcie Informacji dla Przedsiębiorcy)
- **[V]** **Art. 48 ust. 2** (wg lexlege.pl / arslege.pl): „Do ponownego wykorzystywania danych CEIDG udostępnionych zgodnie z ust. 1 stosuje się przepisy ustawy z dnia 11 sierpnia 2021 r. o otwartych danych i ponownym wykorzystywaniu informacji sektora publicznego”. W pierwotnej wersji z 2018 r. było to odesłanie do ustawy z 2016 r. Numeracja ustępów różni się między wersjami, więc **sprawdzić w ISAP**.
- **[V/S]** Art. 47 ust. 1: CEIDG udostępnia dane nieodpłatnie także w innej formie, na warunkach uzgodnionych z ministrem. To podstawa Hurtowni i API. Art. 44 ust. 1: publikacja na stronie CEIDG z wyjątkiem danych niepodlegających udostępnieniu (art. 43 ust. 1).
- **[V]** Domyślne warunki ministra ds. gospodarki (MRiT, https://www.gov.pl/web/rozwoj-technologia/uzyskaj-informacje-publiczna-do-ponownego-wykorzystania): podać źródło (pełna nazwa lub skrót ministerstwa), **czas wytworzenia i pozyskania**, **informację o przetworzeniu**. Ministerstwo nie odpowiada za treść informacji po przetworzeniu. Bezpłatnie. *(Uwaga: kompetencje „gospodarki” mogły po rekonstrukcji rządu w 2025 r. przejść do innego ministerstwa. Część komunikatów API v3 jest cytowana jako „komunikat MF”. **[I]** Do sprawdzenia, kto jest obecnie administratorem CEIDG.)*

### 3.4 Zmiany od 14.10.2026 (za 4 dni!)
- **[V/S]** Ustawa z **13 marca 2026 r.** o zmianie ustawy o CEIDG i PIP oraz niektórych innych ustaw (**Dz.U. 2026 poz. 507**). Wydziela **adres e-mail** jako osobne pole (pkt 6b). Według dane-firm.pl **[S]** dodaje art. 43 ust. 1a, zgodnie z którym **dane kontaktowe (telefon, e-mail) są udostępniane tylko za zgodą przedsiębiorcy**. Logika odwraca się z „sprzeciwu” na „zgodę”. Od 14.10.2026 obowiązuje nowy CEIDG-1, a od 1.11.2026 rejestracja JDG odbywa się wyłącznie elektronicznie.
- **Konsekwencja [I]:** dane kontaktowe JDG traktować jako **opcjonalne i wrażliwe na zgodę**. Domyślnie ich **nie zwracamy** i nie cache'ujemy dłużej niż profil.

### 3.5 Ryzyko danych osobowych: wysokie
Każdy rekord CEIDG dotyczy osoby fizycznej. Firma JDG obejmuje z mocy prawa jej imię i nazwisko (art. 43⁴ KC). Szczegóły i obowiązki: sekcja 6.

**Werdykt CEIDG: 🟡 YELLOW.** Prawnie dopuszczalne, ale wymaga pakietu RODO (art. 14 + LIA + minimalizacja) i decyzji właściciela.

---

## 4. Ministerstwo Finansów — Wykaz podatników VAT („Biała Lista”), API `wl-api.mf.gov.pl`

### 4.1 Dostęp i limity
- **[V]** Strona KAS „API Wykazu podatników VAT” (https://www.gov.pl/web/kas/api-wykazu-podatnikow-vat): „Korzystanie z API jest limitowane. Przy wykorzystaniu metody „search” możesz złożyć **100 zapytań dziennie o maksymalnie 30 podmiotów jednocześnie**, natomiast przy wykorzystaniu metody „check” możecie zapytać o **5000 podmiotów**.” „Po wyczerpaniu jednego z limitów dostęp do API może być zablokowany do godziny 0:00.”
  - Produkcja: `https://wl-api.mf.gov.pl`, test: `https://wl-test.mf.gov.pl`. Bez klucza i bezpłatnie. Specyfikacja v1.4.0 (10.01.2020).
  - **[S]** Limit liczony **per adres IP** (github.com/pwasniowski/mcp-wl-vat, który podaje „stan 01.01.2025”). Wcześniejsze limity z 2019 r. (10 zapytań/dzień) są nieaktualne.
- **[V]** Do masowej weryfikacji służy **plik płaski** (https://www.gov.pl/web/kas/plik-plaski). Jest publikowany codziennie. NIP i rachunek są zapisane jako **skróty SHA-512**, plik waży ~200 MB (7z), dostępne jest archiwum z 30 dni. „Brak danych w pliku płaskim nie może być podstawą do stwierdzenia niewystępowania podatnika.”

### 4.2 Dane w wykazie (art. 96b ust. 3 ustawy o VAT)
- **[V]** Wykaz obejmuje m.in. NIP, REGON, PESEL podmiotu (jeśli ma), status VAT oraz „imiona i nazwiska osób wchodzących w skład organu uprawnionego do reprezentowania podmiotu oraz ich numery identyfikacji podatkowej lub numery PESEL”, prokurentów i wspólników, a także **numery rachunków rozliczeniowych**. W praktyce API zwraca reprezentantów z imieniem, nazwiskiem i często `nip`. `pesel` bywa `null` **[S]**.
- **To oznacza pełne, niezamaskowane nazwiska członków zarządu.** Biała Lista dostarcza więc więcej danych osobowych niż KRS Open API.

### 4.3 Licencja i warunki
- **[V]** MF, „Ponowne wykorzystywanie” (https://www.gov.pl/web/finanse/ponowne-wykorzystywanie). Gdy nie określono innych warunków, należy: podać **źródło** (pełna nazwa MF lub skrót „MF”), **czas wytworzenia i pozyskania**, **poinformować o przetworzeniu**, a przy utworach i bazach danych podać autora, o ile jest znany. **MF nie ponosi odpowiedzialności** za treść informacji po przetworzeniu (dostępność, poprawność, aktualność, kompletność, jakość). Bezpłatnie.
- Komercyjne ponowne wykorzystanie jest dozwolone. Takie usługi to standard rynkowy (systemy ERP, banki, MGBI, Transparent Data).

### 4.4 Uwagi produktowe
- **[I]** Wartość dla kupującego to sprawdzenie **na dzień płatności**, czy rachunek kontrahenta jest w wykazie (art. 117ba Ordynacji podatkowej, art. 15d CIT, art. 22p PIT). Wynik dotyczący rachunku cache'ujemy **maksymalnie do końca dnia (Europe/Warsaw)**. Zawsze zwracamy `requestDateTime` i `requestId` z MF, z informacją, że zapytanie wykonał nasz serwis, a nie kupujący. Nie twierdzimy, że nasz wynik zastępuje własną weryfikację kupującego dla celów podatkowych.
- **[I] Ryzyko techniczne:** Workers wychodzą do sieci z **współdzielonych IP Cloudflare**. Jeśli limit MF jest per IP, inni klienci Cloudflare mogą go „zjadać”, a nasze zapytania mogą dostawać blokadę. Rotowanie IP **w celu obejścia** limitu MF to zły pomysł (ryzyko blokady, argument o nadużyciu). Rozwiązanie: stały egress + `check` + plik płaski dla `check` rachunków (offline, bez limitu, zawiera tylko skróty, czyli minimalizacja RODO).

**Werdykt Biała Lista: 🟢 GREEN dla `check` i pliku płaskiego; 🟡 YELLOW dla `search` z reprezentantami i rachunkami (RODO, limity).**

---

## 5. VIES (Komisja Europejska)

- **[V]** Disclaimer VIES (https://ec.europa.eu/taxation_customs/vies/disclaimer.html):
  - „The Commission accepts **no responsibility or liability whatsoever** with regard to the information obtained using this site.”
  - „It is the responsibility of the Member States (…) to keep their databases complete, accurate and up to date.”
  - Wynik nie stanowi porady i „does not change any obligations imposed on taxable persons in relation to intra-Community supplies”.
  - „Due to data protection, the national authorities will not supply the name and address corresponding to a VAT number (…)”. Część państw, w tym PL, w praktyce zwraca nazwę i adres.
  - Zalecenie: „keep track of your validation in case of tax control”. Cel serwisu to potwierdzanie ważności numeru VAT na podstawie art. 31 rozporządzenia Rady (UE) 904/2010.
- **[S]** REST: `https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number` (swagger: `ec.europa.eu/assets/taxud/vow-information/swagger_publicVAT.yaml`). Bez klucza i bezpłatnie. **Brak opublikowanego limitu.** Błąd `MS_MAX_CONCURRENT_REQ` oznacza globalny limit współbieżności dla danego państwa, niezależny od IP. Wsparcie VIES zaleca ponowienie po kilku sekundach lub minutach.
- **[V/S]** Ponowne wykorzystanie treści KE: polityka z **Decyzji Komisji 2011/833/UE**, treści UE domyślnie na **CC BY 4.0** (wymagane przypisanie i oznaczenie zmian). Nie znalazłem zakazu komercyjnego lub automatycznego korzystania z VIES. Wiele komercyjnych walidatorów VAT działa na VIES.
- `consultationNumber` jest zwracany tylko, gdy podano `requesterVat`. Jako dowód wiąże on **zapytującego** (nas), nie kupującego **[I]**.

**Werdykt VIES: 🟢 GREEN** (z disclaimerem, atrybucją, krótkim cache i retry z backoffem).

---

## 6. RODO — analiza dla naszego modelu

### 6.1 Czy przetwarzamy dane osobowe?
- **Tak**, gdy zwracamy dane JDG (CEIDG, REGON, Biała Lista dla osób fizycznych), pełne nazwiska reprezentantów i prokurentów z Białej Listy albo nazwy spółek osobowych zawierające nazwiska. Dane o działalności JDG są danymi osobowymi przedsiębiorcy **[V]**: „Według dominującej interpretacji dane osób fizycznych prowadzących działalność wpisanych do CEIDG również podlegają ochronie RODO”. Potwierdzają to sprawa Bisnode i NSA.
- Pobranie, normalizacja, scalanie, cache i przekazanie kupującemu to **przetwarzanie**, w którym jesteśmy **administratorem** (sami ustalamy cele i sposoby). Kupujący, czyli operator agenta, staje się **odrębnym administratorem** po otrzymaniu danych **[I]**. Model „procesora” jest niewykonalny przy anonimowych płatnościach x402, bo brak umowy powierzenia z art. 28.

### 6.2 Sprawa Bisnode: chronologia i rozstrzygnięcia
| Etap | Data / sygnatura | Rozstrzygnięcie |
|---|---|---|
| Decyzja Prezesa UODO | **15.03.2019, ZSPR.421.3.2018** | Kara **943 470 zł** dla Bisnode Polska (obecnie Dun & Bradstreet) za niewykonanie obowiązku z **art. 14 RODO** wobec ok. **6,6 mln** osób, których dane pozyskano z **CEIDG** (oraz KRS i REGON). Spółka wysłała informację mailem tylko tym osobom, które miały e-mail w CEIDG. Wobec pozostałych powołała się na **art. 14 ust. 5 lit. b** (niewspółmierny wysiłek, koszt listów rzędu 30 mln zł) i ograniczyła się do informacji na swojej stronie **[V]**. |
| WSA w Warszawie | **11.12.2019, II SA/Wa 1030/19** | Częściowe uchylenie. WSA potwierdził obowiązek informacyjny wobec osób **aktualnie prowadzących lub zawieszonych** JDG. Uchylił decyzję co do osób, które **w przeszłości** prowadziły działalność, oraz co do **wysokości kary** (do ponownego ustalenia). „Opublikowanie obowiązku informacyjnego jedynie w serwisie internetowym spółki zostało uznane za niewystarczające.” Wysoki koszt wysyłki pocztą „nie może przesądzać” o niewspółmiernym wysiłku **[V]**. |
| **NSA** | **19.09.2023, III OSK 2538/21** (https://orzeczenia.nsa.gov.pl/doc/44C12DED71) | **Oddalenie skargi kasacyjnej Bisnode** (koszty 5 400 zł na rzecz PUODO). Wyrok prawomocny. Teza z omówień: pozyskanie danych z rejestrów publicznych **nie zwalnia** z obowiązku informacyjnego. Wyjątki od przejrzystości, w tym „niewspółmierny wysiłek”, należy **interpretować zawężająco**. Spółka „nie powinna wskazywać na »niewspółmiernie duży wysiłek« z uwagi na to, że **pozyskiwanie i obrót danymi osobowymi jest jednym z kluczowych elementów działalności**” **[V/S]**. |
| Po NSA | — | Sprawa wraca do PUODO tylko w zakresie uchylonym przez WSA (byli przedsiębiorcy, wysokość kary). **Nie znalazłem** informacji o nowej decyzji co do kwoty w latach 2024–2026 **[I]**. |

- Kontrast: decyzja PUODO z **30.01.2019** w sprawie **rejestr.io** (Fundacja ePaństwo) uznała za **zgodne z prawem** gromadzenie danych z KRS i ich **odpłatne** udostępnianie w internecie na podstawie prawnie uzasadnionego interesu **[S]** (prawo.pl „RODO nie utrudnia przetwarzania danych z jawnych rejestrów publicznych”, dziennik.pl). Komentatorzy wskazują, że kluczowa różnica to **zakres danych**: KRS (spółki, funkcje) wobec CEIDG (osoby fizyczne). NSA III OSK 4558/21 (30.11.2021) potwierdził dopuszczalność publikacji danych z KRS (imię, nazwisko, funkcja, bez PESEL) przez serwis internetowy.
- **[I]** Nie znalazłem nowszych (2024–2026) wytycznych UODO dedykowanych wywiadowniom gospodarczym lub ponownemu wykorzystaniu rejestrów. Linia z Bisnode pozostaje wiodąca.

### 6.3 Podstawa prawna: art. 6 ust. 1 lit. f
- Prawnie uzasadniony interes administratora i odbiorców: bezpieczeństwo obrotu, weryfikacja kontrahenta (KYB), przeciwdziałanie oszustwom, należyta staranność VAT. Interes ten jest silny **[I]**. Wymaga **udokumentowanego testu równowagi (LIA)**. Wspierają go jawność rejestrów (art. 8 KRS, art. 45 u.s.p., art. 44 CEIDG) i to, że dane dotyczą sfery zawodowej.
- Ustawa o otwartych danych **art. 6 ust. 2** **[V]**: „Prawo do ponownego wykorzystywania informacji sektora publicznego podlega ograniczeniu ze względu na tajemnicę przedsiębiorstwa lub prywatność osoby fizycznej, **w tym ochronę danych osobowych**.” Jawność rejestru nie wyłącza więc RODO.
- **Słabość LIA w naszym modelu [I]:** odbiorcy są **anonimowymi agentami**, więc nie znamy celu kupującego. Mitygacje: (a) **Terms of Use** w odpowiedzi 402 i na `/legal`, ograniczające cele dozwolone (weryfikacja kontrahenta, KYB, fakturowanie, compliance) i **zakazujące** marketingu bezpośredniego, profilowania osób fizycznych i budowania baz; (b) **brak eksportu masowego**; (c) limity per portfel płatnika; (d) brak wyszukiwania po imieniu i nazwisku osoby jako takiej.

### 6.4 Art. 14 RODO: co konkretnie nas obowiązuje
- Art. 14 ust. 1–2: informacja dla osoby, której dane pozyskano nie od niej. Obejmuje tożsamość administratora, cele, podstawę, kategorie danych, odbiorców, transfery, okres przechowywania, prawa, **źródło** i prawo do skargi do PUODO.
- Art. 14 ust. 3: „w rozsądnym terminie”, najpóźniej w ciągu miesiąca. Jeśli dane mają być **ujawnione innemu odbiorcy**, informacja jest należna **najpóźniej przy pierwszym ujawnieniu**. W naszym modelu ujawnienie następuje natychmiast, przy pierwszym zapytaniu o daną JDG.
- **Art. 14 ust. 5 lit. b** (niewspółmierny wysiłek) wymaga też „odpowiednich środków ochrony (…), w tym **udostępnienia informacji publicznie**”. Po Bisnode/NSA powołanie się na lit. b przez podmiot, którego **głównym biznesem jest sprzedaż danych**, jest **ryzykowne**. Szczególnie gdy istnieje tani kanał kontaktu, np. e-mail z CEIDG.
- **Argumenty odróżniające nasz model od Bisnode [I]:** brak budowania bazy (zapytania na żądanie, krótki TTL), brak marketingu, niewielka i nieprzewidywalna liczba osób, minimalny zakres danych. Argumenty te **zmniejszają** ryzyko, ale **nie gwarantują** skutecznego powołania się na lit. b.
- **Rekomendowana, obronna strategia [I]:**
  1. **Publiczna nota informacyjna** (art. 14) na `/legal` i `/privacy`, w PL i EN. To minimum w każdym scenariuszu.
  2. **Dla JDG:** jeśli w CEIDG jest publicznie udostępniony e-mail, **wysyłamy krótką informację art. 14 e-mailem** przy pierwszym ujawnieniu danych danej osoby. Robimy to raz na osobę na 12 miesięcy, przechowując tylko hash NIP i datę wysyłki. Tak zrobił Bisnode w zakresie, którego UODO **nie** kwestionował. Dla pozostałych osób dokumentujemy ocenę z art. 14 ust. 5 lit. b. Po 14.10.2026 e-maile będą publiczne tylko za zgodą, więc liczba adresów spadnie, a argument z lit. b dla reszty się wzmacnia.
  3. **Albo (wariant najbezpieczniejszy):** endpointy dla JDG zwracają **tylko dane niezbędne do weryfikacji**, np. `verify` przyjmuje od kupującego `expectedName` i zwraca `nameMatches: true/false` bez wypisywania imienia i nazwiska. Pełny profil JDG jest dostępny tylko za flagą z deklaracją celu. Przetwarzanie nadal ma miejsce, ale ryzyko i skala ujawnień są minimalne.
- **Rejestr czynności przetwarzania (art. 30):** **wymagany**. Zwolnienie dla podmiotów < 250 osób nie ma zastosowania, bo przetwarzanie nie jest sporadyczne.
- **DPIA (art. 35):** **[I] rekomendowana** w wersji „lite”. Łączymy zbiory z wielu rejestrów (kryterium „dopasowywanie lub łączenie zbiorów danych” z wytycznych WP248 i listy PUODO) potencjalnie na dużą skalę.
- **IOD/DPO (art. 37):** **[I]** raczej nie jest obowiązkowy (to nie „monitorowanie” osób). Ocenę należy udokumentować.
- **Prawa osób:** sprostowanie jest możliwe przez wskazanie rejestru źródłowego, z naszą korektą cache. Usunięcie lub sprzeciw (art. 17 i 21): obsługujemy **listę wykluczeń** (hash NIP lub PESEL po stronie osoby), z której dane nie są zwracane. Wymagany jest kontakt mailowy na `/legal`.
- **Retencja i cache:** przechowywanie danych w cache to przetwarzanie, więc TTL musi być **uzasadniony i krótki**. Proponowane wartości są w sekcji 7.3. Logi przechowujemy **bez treści odpowiedzi**, tylko z identyfikatorem zapytania, hashem NIP, czasem i hashem portfela, przez 30–90 dni.
- **Transfery:** Cloudflare (US) działa jako podmiot przetwarzający. Potrzebne są DPA Cloudflare oraz DPF/SCC. Cache warto trzymać w regionie UE, jeśli plan to umożliwia **[I]**.

### 6.5 Ochrona baz danych (sui generis)
- **[S/I]** Ustawa o otwartych danych i dyrektywa 2019/1024 ograniczają wykonywanie praw sui generis przez podmioty publiczne w celu blokowania ponownego wykorzystania. **Rozporządzenie wykonawcze (UE) 2023/138 (HVD)**, stosowane od 2024 r., obejmuje kategorię **„Spółki i ich własność”**. Nakłada na państwa obowiązek bezpłatnego udostępniania podstawowych danych rejestrów spółek przez API na licencji **CC BY 4.0 lub równoważnej** **[V/S]**. Wspiera to legalność naszego modelu dla danych spółek.

---

## 7. REKOMENDACJE

### 7.1 Werdykty per źródło
| Źródło | Werdykt | Uzasadnienie (skrót) |
|---|---|---|
| KRS Open API | 🟢 GREEN | Otwarte, bez klucza. Ponowne wykorzystanie dozwolone (NSA III OSK 4558/21). Osoby zamaskowane. Wymogi: atrybucja MS, „nie jest odpisem”, nie de-anonimizować, nie używać Full API, nie scrapować eKRS. |
| GUS BIR1.1/1.2 | 🟢 / 🟡 | Darmowy klucz, jawny rejestr, znane limity. 🟡 do czasu przeczytania regulaminu BIR i wyjaśnienia kwestii IP. JDG podlega RODO. |
| CEIDG API v3 | 🟡 YELLOW | Legalne ponowne wykorzystanie (art. 48 ust. 2). Limity 50/3 min i 1000/h. 100% danych osobowych, precedens Bisnode. Zmiany od 14.10.2026 (dane kontaktowe tylko za zgodą). |
| Biała Lista | 🟢 `check` / 🟡 `search` | `check` i plik płaski (hash) to idealna minimalizacja. `search` zwraca pełne nazwiska reprezentantów i rachunki JDG. Ostre limity dzienne (100×30 / 5000). Problem współdzielonego IP. |
| VIES | 🟢 GREEN | Bez klucza, CC BY 4.0, disclaimer KE. Ograniczona dostępność (`MS_MAX_CONCURRENT_REQ`). |

### 7.2 Zgodny model produktu
1. **Przedmiot sprzedaży to usługa, nie baza.** Agent płaci za **pobranie w czasie rzeczywistym, normalizację, scalenie, walidację i krzyżową weryfikację** (query-time processing) danych **jednego wskazanego podmiotu**. Nie płaci za odsprzedaż zrzutu bazy. Komunikujemy to w ToS i opisie endpointów.
2. **Brak eksportu masowego.** `batch-verify` ograniczamy do np. 50 NIP na wywołanie, zwraca tylko statusy (bez danych osobowych). Stosujemy limity per portfel płatnika (np. ≤ 5 000 rekordów/dobę) i wykrywanie enumeracji (sekwencyjne NIP/KRS).
3. **Brak wyszukiwania osób.** `search` po nazwie: dla spółek (KRS) z własnego indeksu nazw spółek budowanego z Biuletynu KRS (to dane podmiotów, nie osób). Dla JDG z CEIDG v3, ale tylko gdy zapytanie zawiera dodatkowy filtr (miejscowość lub PKD). Wyniki są ograniczone do nazwy, NIP i statusu. Nie oferujemy wyszukiwania po samym imieniu i nazwisku.
4. **Minimalizacja danych osobowych:**
   - **Spółki (KRS):** zarząd i reprezentacja domyślnie jako **funkcja + zamaskowane dane w postaci z KRS Open API** oraz sposób reprezentacji. Pełne imiona i nazwiska z Białej Listy są dostępne **tylko za flagą** `include=representatives`, z deklaracją celu (`purpose=kyb|contract|invoice`) i zapisem w logu.
   - **JDG:** domyślnie `verify` z `nameMatches` (bez zwracania imienia i nazwiska) plus status, PKD, adres **wykonywania działalności**. Pełna firma (imię i nazwisko) jest zwracana tylko w endpointach profilu, za flagą i w zgodzie z art. 14 (patrz 6.4). **Nie** zwracamy telefonu ani e-maila (od 14.10.2026 udostępniane są tylko za zgodą). **Nigdy** nie zwracamy PESEL ani adresu zamieszkania.
   - **Rachunki bankowe:** preferujemy tryb **„sprawdź rachunek”**: kupujący podaje rachunek, my zwracamy `true/false`, korzystając z `check` lub pliku płaskiego. Pełna lista rachunków jest dostępna tylko za flagą.
5. **Cache (TTL):**

   | Dane | TTL |
   |---|---|
   | Status VAT / rachunek z Białej Listy | do końca dnia (Europe/Warsaw), maks. 24 h |
   | VIES | ≤ 24 h |
   | Odpis KRS (dane spółki) | 24 h (inwalidacja przez Biuletyn KRS) |
   | REGON / CEIDG (dane JDG) | ≤ 24–72 h |
   | Indeks nazw spółek | bez TTL (to dane podmiotów, nie osób) |
   | Dane z listy wykluczeń | usuwane natychmiast |

   Każda odpowiedź podaje `retrievedAt` i `cacheAgeSeconds`.
6. **Atrybucja w każdej odpowiedzi** (`meta.sources[]`): nazwa rejestru, wydawca, URL źródła, `retrievedAt`, „stan na dzień” ze źródła, informacja o przetworzeniu, link do `/legal`. Spełnia to warunki MS, GUS, MF i MRiT (źródło, czas wytworzenia i pozyskania, przetworzenie) oraz CC BY 4.0 dla VIES.
7. **Brak sugerowania oficjalności:** nie używamy godła, logotypów gov.pl, MS, GUS ani KAS ani nazw typu „Oficjalne API KRS”. Nie nazywamy wyniku „odpisem”, „zaświadczeniem” ani „potwierdzeniem z Białej Listy”. Dodajemy disclaimer, że wynik nie ma mocy dokumentu urzędowego.
8. **Uczciwość co do limitów źródeł:** nie obchodzimy limitów (wiele kluczy CEIDG, rotacja IP do MF). Przy wyczerpaniu limitu zwracamy `503` z `Retry-After` albo dane z cache z oznaczeniem wieku.
9. **Pakiet RODO:** nota art. 14 (poniżej), RCP (art. 30), LIA, DPIA-lite, procedura obsługi żądań (≤ 30 dni), lista wykluczeń, DPA z Cloudflare, mail `privacy@…`.

### 7.3 Prawdziwe blokery (wymagają decyzji właściciela lub prawnika)
1. **Decyzja: czy w MVP obsługujemy dane JDG (CEIDG, osoby fizyczne).**
   - Jeśli **nie**, MVP oparte na KRS jest GREEN i można startować.
   - Jeśli **tak**, trzeba wybrać strategię art. 14: (a) e-mail art. 14 tam, gdzie e-mail jest jawny, plus nota publiczna i udokumentowane lit. b dla reszty, albo (b) tryb weryfikacji bez ujawniania nazwiska.
   - Rekomenduję **krótką konsultację z polskim prawnikiem RODO** przed uruchomieniem pełnych profili JDG. Precedens Bisnode dotyczy dokładnie tego scenariusza.
2. **Przeczytanie i zarchiwizowanie regulaminu BIR (GUS) i oświadczenia Hurtowni CEIDG** przy składaniu wniosków. Nie udało się ich pobrać w tej sesji. Jeśli zawierają zakaz dalszego udostępniania, werdykt dla danego źródła zmienia się na RED.
3. **Kwestia stałego IP egress:** czy klucz GUS jest wiązany z IP, oraz limity MF per IP. To decyzja architektoniczna i kosztowa (stały egress w UE). Nie jest to problem prawny, ale bez niej źródła mogą nie działać niezawodnie.
4. **Podmiot prowadzący serwis (administrator danych):** dane firmy, adres w UE, kontakt do spraw danych osobowych. Bez tego nie da się opublikować noty art. 14.

*(Nie są blokerami: brak klucza w KRS/MF/VIES, komercyjny charakter usługi, płatność w USDC/x402, krótkie cache. Wszystkie są zgodne z ustawą o otwartych danych przy spełnieniu warunków atrybucji.)*

### 7.4 Do zrobienia przed produkcją (checklista weryfikacyjna)
- [ ] Ręcznie otworzyć i zarchiwizować: prs.ms.gov.pl/krs/openApi; api.stat.gov.pl/Home/RegonApi wraz z ZIP instrukcji BIR (rozdz. „Regulamin”); bip.stat.gov.pl (warunki ponownego wykorzystywania); gov.pl/web/kas/api-wykazu-podatnikow-vat; gov.pl/web/finanse/ponowne-wykorzystywanie; dokumentację CEIDG v3 v1.1 i oświadczenie Hurtowni; disclaimer VIES.
- [ ] Sprawdzić w ISAP aktualne brzmienie: art. 4 ust. 4c–4m i art. 60a ustawy o KRS (Dz.U. 2025 poz. 1556); art. 43, 44, 47 i 48 ustawy o CEIDG po Dz.U. 2026 poz. 507; art. 45 u.s.p. po Dz.U. 2025 poz. 1792; art. 6 i 15 ustawy o otwartych danych.
- [ ] Ustalić, który minister jest obecnie organem właściwym dla CEIDG, i odpowiednio wpisać atrybucję.

---

## 8. Ustawa o otwartych danych: kluczowe przepisy (Dz.U. 2021 poz. 1641, t.j. Dz.U. 2023 poz. 1524)
- **Art. 6 ust. 2 [V]:** ograniczenie ze względu na tajemnicę przedsiębiorstwa lub prywatność osoby fizycznej, „w tym ochronę danych osobowych”. Nie dotyczy informacji o osobach pełniących funkcje publiczne w związku z ich pełnieniem.
- **Art. 14 ust. 1 [V/S]:** informacje sektora publicznego udostępnia się w celu ponownego wykorzystywania **bezwarunkowo**, z wyjątkami przewidzianymi w ustawie.
- **Art. 15 ust. 1 [V/S]:** podmiot zobowiązany **może określić warunki** ponownego wykorzystywania, dotyczące w szczególności:
  - pkt 1: **obowiązku poinformowania o źródle, czasie wytworzenia i pozyskania** informacji;
  - pkt 2: **obowiązku informowania o przetworzeniu**;
  - pkt 3: zakresu **odpowiedzialności** podmiotu zobowiązanego;
  - pkt 4: warunków dla informacji **zawierających dane osobowe**.

  Warunki muszą być „obiektywne, proporcjonalne i niedyskryminacyjne”. MS, GUS, MF i MRiT skorzystały z pkt 1–3.
- **Zakaz wprowadzania w błąd / sugerowania oficjalności [I]:** wynika z warunków odpowiedzialności (pkt 3), z art. 5 RODO (rzetelność i prawidłowość) oraz z prawa nieuczciwej konkurencji. Ujęte w modelu (7.2 pkt 7).

---

## 9. Snippet JSON: atrybucja i licencja (do każdej odpowiedzi)

```json
{
  "meta": {
    "service": "x402-company-data",
    "generatedAt": "2026-10-10T12:00:00Z",
    "notAnOfficialDocument": true,
    "disclaimer": {
      "pl": "Dane przetworzone (pobrane, znormalizowane i scalone) przez x402-company-data z publicznych rejestrów. Nie stanowią odpisu z KRS, zaświadczenia ani dokumentu urzędowego i nie są publikowane w imieniu ani za zgodą wskazanych instytucji. Instytucje źródłowe nie ponoszą odpowiedzialności za dane po przetworzeniu.",
      "en": "Data retrieved, normalised and merged by x402-company-data from public registers. Not an official extract, certificate or document; not published on behalf of or endorsed by the source institutions, which bear no liability for the processed data."
    },
    "sources": [
      {
        "id": "krs",
        "name": "Krajowy Rejestr Sądowy – API Rejestrów Sądowych (Open API)",
        "publisher": "Ministerstwo Sprawiedliwości",
        "url": "https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/0000000000?rejestr=P&format=json",
        "sourceStateAsOf": "2026-10-09",
        "retrievedAt": "2026-10-10T11:58:03Z",
        "cacheAgeSeconds": 117,
        "processing": "normalizacja pól, mapowanie słowników, scalenie z innymi źródłami; dane osób fizycznych pozostawione w postaci zanonimizowanej przez źródło"
      },
      {
        "id": "regon",
        "name": "Rejestr REGON – usługa BIR1.1",
        "publisher": "Główny Urząd Statystyczny",
        "url": "https://api.stat.gov.pl/Home/RegonApi",
        "retrievedAt": "2026-10-10T11:58:04Z",
        "cacheAgeSeconds": 0,
        "processing": "konwersja SOAP/XML do JSON, normalizacja adresu i PKD"
      },
      {
        "id": "vat-whitelist",
        "name": "Wykaz podatników VAT (Biała Lista) – API",
        "publisher": "Ministerstwo Finansów / Szef KAS",
        "url": "https://wl-api.mf.gov.pl/",
        "sourceRequestId": "abc12-xyz34",
        "sourceRequestDateTime": "10-10-2026 11:58:05",
        "retrievedAt": "2026-10-10T11:58:05Z",
        "cacheAgeSeconds": 0,
        "processing": "wybrane pola; zapytanie wykonane przez x402-company-data, nie przez odbiorcę"
      },
      {
        "id": "vies",
        "name": "VIES VAT number validation",
        "publisher": "European Commission (data from national tax administrations)",
        "url": "https://ec.europa.eu/taxation_customs/vies/",
        "licence": "© European Union – reuse under Commission Decision 2011/833/EU (CC BY 4.0); see VIES disclaimer",
        "retrievedAt": "2026-10-10T11:58:06Z",
        "cacheAgeSeconds": 0
      }
    ],
    "reuseBasis": "Ponowne wykorzystywanie informacji sektora publicznego na podstawie ustawy z dnia 11 sierpnia 2021 r. o otwartych danych i ponownym wykorzystywaniu informacji sektora publicznego (Dz.U. 2023 poz. 1524 t.j.), z zachowaniem warunków podmiotów zobowiązanych (źródło, czas wytworzenia i pozyskania, informacja o przetworzeniu).",
    "personalData": {
      "containsPersonalData": false,
      "notice": "https://<host>/legal#privacy",
      "permittedUse": "Counterparty verification, KYB, invoicing and tax due-diligence only. No direct marketing, no profiling of natural persons, no bulk database building. See https://<host>/legal#terms"
    },
    "terms": "https://<host>/legal#terms"
  }
}
```

Uwagi: pole `containsPersonalData` ustawiamy dynamicznie (`true` dla JDG i reprezentantów). `sourceStateAsOf` bierzemy z pola „stan na dzień” w odpisie KRS, jeśli jest dostępne.

---

## 10. Nota informacyjna (art. 14 RODO): projekt do `/legal#privacy`

> Szablony do uzupełnienia w miejscach `[…]`. Przed publikacją potrzebna jest weryfikacja prawnika (zob. 7.3).

### 10.1 Wersja polska

**Informacja o przetwarzaniu danych osobowych pozyskanych z rejestrów publicznych (art. 14 RODO)**

1. **Administrator:** [nazwa / imię i nazwisko przedsiębiorcy], [adres], NIP [..], prowadzący serwis x402-company-data. Kontakt w sprawach danych osobowych: [privacy@domena].
2. **Źródła danych:** jawne rejestry publiczne: Krajowy Rejestr Sądowy (API Ministerstwa Sprawiedliwości), rejestr REGON (GUS, usługa BIR), Centralna Ewidencja i Informacja o Działalności Gospodarczej (Hurtownia Danych CEIDG), Wykaz podatników VAT (Ministerstwo Finansów), system VIES (Komisja Europejska).
3. **Kategorie danych:** dane identyfikujące działalność gospodarczą osób fizycznych (imię i nazwisko w firmie przedsiębiorcy, NIP, REGON, adres wykonywania działalności, PKD, status działalności i status VAT, rachunki rozliczeniowe ujawnione w Wykazie podatników VAT) oraz imiona i nazwiska i funkcje członków organów i prokurentów podmiotów, w zakresie ujawnionym w tych rejestrach. **Nie przetwarzamy numerów PESEL ani adresów zamieszkania.**
4. **Cele i podstawa prawna:** udostępnianie na żądanie zweryfikowanej informacji o kontrahencie w celu weryfikacji kontrahentów, bezpieczeństwa obrotu gospodarczego, należytej staranności podatkowej i przeciwdziałania oszustwom. Podstawą jest **art. 6 ust. 1 lit. f RODO** (prawnie uzasadniony interes administratora i odbiorców danych). Ponowne wykorzystanie odbywa się na zasadach ustawy z 11 sierpnia 2021 r. o otwartych danych i ponownym wykorzystywaniu informacji sektora publicznego.
5. **Odbiorcy:** podmioty i ich systemy automatyczne (agenci AI), które opłaciły zapytanie o konkretny podmiot, oraz nasi dostawcy infrastruktury działający jako podmioty przetwarzające (Cloudflare, Inc.).
6. **Przekazywanie poza EOG:** dostawca infrastruktury może przetwarzać dane w USA na podstawie decyzji stwierdzającej odpowiedni stopień ochrony (EU–US Data Privacy Framework) lub standardowych klauzul umownych.
7. **Okres przechowywania:** dane nie są gromadzone w bazie. Są pobierane z rejestru przy zapytaniu i przechowywane w pamięci podręcznej najwyżej [24–72] godziny. Logi techniczne bez treści danych przechowujemy [30–90] dni.
8. **Prawa:** dostęp do danych, sprostowanie (dane korygujemy zgodnie z rejestrem źródłowym, a błędy w rejestrze należy zgłaszać organowi prowadzącemu rejestr), usunięcie, ograniczenie przetwarzania oraz **sprzeciw** z przyczyn związanych ze szczególną sytuacją (art. 21 RODO). Po uwzględnieniu sprzeciwu wpisujemy Twój NIP na listę wykluczeń i przestajemy udostępniać Twoje dane. Masz prawo wnieść skargę do **Prezesa Urzędu Ochrony Danych Osobowych** (ul. Stawki 2, 00-193 Warszawa).
9. **Zautomatyzowane decyzje:** nie podejmujemy wobec Ciebie decyzji opartych wyłącznie na zautomatyzowanym przetwarzaniu, w tym profilowaniu.
10. **Obowiązek podania danych:** nie dotyczy. Dane pochodzą z rejestrów publicznych.

### 10.2 English version

**Information on processing of personal data obtained from public registers (Art. 14 GDPR)**

1. **Controller:** [legal name], [address], tax ID [..], operator of the x402-company-data service. Privacy contact: [privacy@domain].
2. **Sources:** public Polish and EU registers: National Court Register (Ministry of Justice API), REGON register (Statistics Poland, BIR service), CEIDG business register (CEIDG Data Warehouse), VAT taxpayer list (“White List”, Ministry of Finance), and VIES (European Commission).
3. **Categories of data:** business identification data of sole traders (name as part of the business name, tax ID/NIP, REGON, business address, activity codes, business and VAT status, bank accounts disclosed in the VAT list), and names and functions of board members and commercial proxies of entities, as disclosed in those registers. **We do not process PESEL numbers or home addresses.**
4. **Purposes and legal basis:** providing verified, on-demand information about business counterparties for counterparty verification, safety of commercial transactions, tax due diligence and fraud prevention. The legal basis is **Art. 6(1)(f) GDPR** (legitimate interests of the controller and of recipients). Re-use takes place under the Polish Act of 11 August 2021 on open data and the re-use of public sector information.
5. **Recipients:** businesses and their automated systems (AI agents) that paid for a lookup of a specific entity, and our infrastructure providers acting as processors (Cloudflare, Inc.).
6. **Transfers outside the EEA:** our infrastructure provider may process data in the USA under the EU–US Data Privacy Framework adequacy decision or Standard Contractual Clauses.
7. **Retention:** we do not build a database. Data is fetched from the register at query time and cached for at most [24–72] hours. Technical logs without data content are kept for [30–90] days.
8. **Your rights:** access, rectification (we follow the source register; errors in the register must be corrected with the register authority), erasure, restriction, and the **right to object** on grounds relating to your particular situation (Art. 21 GDPR). If your objection is upheld, we add your tax ID to an exclusion list and stop disclosing your data. You may lodge a complaint with the Polish supervisory authority, **Prezes Urzędu Ochrony Danych Osobowych** (ul. Stawki 2, 00-193 Warsaw).
9. **Automated decision-making:** we make no decisions about you based solely on automated processing, including profiling.
10. **Obligation to provide data:** not applicable. The data comes from public registers.

---

## 11. Źródła (URL)

**KRS**
- https://prs.ms.gov.pl/krs/openApi
- https://prs.ms.gov.pl/krs
- https://www.gov.pl/web/sprawiedliwosc/uruchomienie-otwartego-api-krajowego-rejestru-sadowego
- https://samorzad.gov.pl/web/gov/api-krajowego-rejestru-sadowego
- https://www.gov.pl/web/sprawiedliwosc/ponowne-wykorzystywanie
- https://www.prawo.pl/biznes/krs-online-full-api-tylko-z-decyzja-ministra,535138.html
- https://orka.sejm.gov.pl/proc10.nsf/ustawy/1311_u.htm
- https://isap.sejm.gov.pl/isap.nsf/download.xsp/WDU20250001556/O/D20251556.pdf
- https://www.prawo.pl/akty/dz-u-2025-1556,22197264.html
- https://ktw.legal/rewolucja-cyfrowa-w-krs-co-zmienia-nowelizacja-z-listopada-2025-r/
- https://www.gardocki.pl/nowelizacja-ustawy-o-krs-wchodzi-w-zycie/
- https://czasopismo.legeartis.org/2025/11/pobranie-danych-krajowego-rejestru-sadowego-interfejs-api-nieuprawnione-przestepstwo/
- https://dane-firm.pl/poradnik/jak-pobrac-dane-z-krs
- https://www.parp.gov.pl/storage/publications/pdf/Mozliwosci-wykorzystania-danych-rejestrowych_FINAL.pdf
- https://otwarteapi.pl/en/krs
- https://czasopismo.legeartis.org/2021/12/przetwarzanie-danych-osobowych-jawnego-publicznego-rejestru-krs-serwis-internetowy-wyrok/

**GUS / REGON**
- https://api.stat.gov.pl/Home/RegonApi
- https://bip.stat.gov.pl/kontakt/ponowne-wykorzystywanie-informacji-sektora-publicznego/
- https://docs.plusworkflow.pl/confluence/download/attachments/11405709/regon%20-%20instrukcja%20techniczna%20BIR1%20dla%20podmiot%C3%B3w%20komercyjnych%20v011a.pdf
- http://freshmind.other.s3.amazonaws.com/BIR1.pdf
- https://forum.dmplaza.eu/viewtopic.php?t=235
- https://kcserwis.pl/klucz-gus-bir/
- https://brokerdanych.pl/blog/gus-api-bir-jak-pobierac-dane-firm-z-rejestru-regon
- https://github.com/arasstall/gus-bir1-proxy
- https://www.npmjs.com/package/bir1
- https://lexlege.pl/ustawa-o-statystyce-publicznej/rozdzial-6-standardy-klasyfikacyjne-i-krajowe-rejestry-urzedowe/5287/
- https://monitorpolski.gov.pl/D2025000179201.pdf (Dz.U. 2025 poz. 1792, zmiana u.s.p.)

**CEIDG**
- https://pliki.biznes.gov.pl/akademia/20250117/HD%20CEIDG%20-%20API%20v3%20HD%20-%20Dokumentacja%20dla%20integrator%C3%B3w%20v1.1.pdf
- https://pliki.biznes.gov.pl/akademia/Hurtownia_danych/HD%20CEIDG%20-%20API%20v3%20HD%20-%20Dokumentacja%20dla%20integrator%C3%B3w%20v1.0.pdf
- https://dane.biznes.gov.pl/pl/portal/034872
- https://akademia.biznes.gov.pl/hurtownia-danych-instrukcje-i-dokumentacja/
- https://support.hogart.com.pl/news/5
- https://dane-firm.pl/poradnik/jak-pobrac-dane-z-ceidg
- https://medium.com/blog-transparent-data/rejestr-ceidg-nie-zniknie-api-ceidg-te%C5%BC-nie-bcbace1050ef
- https://lexlege.pl/centr-ewid-inf-o-dzial-gosp/art-48/
- https://arslege.pl/udostepnianie-danych-i-informacji-ceidg-organom-panstwowym/k1699/a111155/
- https://www.prawo.pl/akty/dz-u-2026-507,22257221.html
- https://orka.sejm.gov.pl/proc10.nsf/ustawy/2076_u.htm
- https://poradnikprzedsiebiorcy.pl/-zmiany-w-ceidg-co-musi-wiedziec-kazdy-przedsiebiorca
- https://www.gov.pl/web/rozwoj-technologia/uzyskaj-informacje-publiczna-do-ponownego-wykorzystania

**Biała Lista VAT**
- https://www.gov.pl/web/kas/api-wykazu-podatnikow-vat
- https://wl-api.mf.gov.pl/
- https://www.gov.pl/web/kas/plik-plaski
- https://www.podatki.gov.pl/media/5745/specyfikacja-techniczna-pliku-plaskiego_20200826.pdf
- https://www.gov.pl/web/finanse/ponowne-wykorzystywanie
- https://github.com/pwasniowski/mcp-wl-vat/blob/main/README.md
- https://crn.pl/aktualnosci/biala-lista-vat-limit-zapytan-pozostanie/
- https://lexlege.pl/ustawa-o-podatku-od-towarow-i-uslug/art-96b/

**VIES / UE**
- https://ec.europa.eu/taxation_customs/vies/disclaimer.html
- https://ec.europa.eu/taxation_customs/vies/
- https://taxation-customs.ec.europa.eu/vies-vat-information-exchange-system_en
- https://vatvalidate.eu/vies-errors
- https://data.europa.eu/copyright-notice
- https://data.europa.eu/en/news-events/news/high-value-datasets-what-has-changed-and-what-will-come-next

**Ustawa o otwartych danych**
- https://isap.sejm.gov.pl/isap.nsf/download.xsp/WDU20210001641/T/D20211641L.pdf
- https://orka.sejm.gov.pl/proc9.nsf/ustawy/1338_u.htm
- https://lexlege.pl/ponowne-wykorz-inf-sekt-publ/art-6/
- https://www.traple.pl/ochrona-danych-osobowych-a-otwieranie-danych-i-ponowne-wykorzystywanie-informacji-sektora-publicznego/
- https://czasopismo.legeartis.org/2021/09/ustawa-otwartych-danych-ponownym-wykorzystywaniu-informacji-sektora-publicznego/

**RODO / Bisnode / UODO**
- https://orzeczenia.nsa.gov.pl/doc/44C12DED71 (NSA III OSK 2538/21, 19.09.2023)
- https://uodo.gov.pl/pl/138/2827
- https://www.prawo.pl/biznes/pierwsza-kara-nalozona-przez-uodo-na-bisnode-wyrok-nsa,523262.html
- https://www.prawo.pl/biznes/final-w-sprawie-pierwszej-kary-nalozonej-przez-uodo-nsa-przyznal-racje-urzedowi,523600.html
- https://www.prawo.pl/biznes/wyrok-wsa-w-sprawie-decyzji-uodo-dotyczacej-bisnode,496537.html
- https://lexdigital.pl/uchylenie-decyzji-puodo/
- https://niebezpiecznik.pl/post/pierwsza-polska-i-milionowa-kara-za-rodo-byla-zasadna-wyrok-nsa/
- https://www.soczko.pl/iod-soczko-partnerzy/blog-ochrona-danych/pierwsza-w-polsce-kara-za-naruszenie-przepisow-rodo/
- https://www.poradyodo.pl/orzeczenia/nsa-obowiazek-informacyjny-rodo-takze-w-przypadku-zbierania-danych-z-rejestrow-publicznych-12377.html
- https://palestra.pl/pl/czasopismo/wydanie/5-2019/artykul/nalozenie-administracyjnej-kary-pienieznej-za-niezrealizowanie-obowiazku-informacyjnego-przy-pozyskiwaniu-danych-z-publicznie-dostepnych-zrodel-glosa-do-ostatecznej-decyzji-prezesa-urzedu-ochrony-danych-osobowych-z-15.03.2019-r.-zspr.421.3.2018
- https://gospodarka.dziennik.pl/news/artykuly/594845,rodo-pierwsza-kara-bisnode-epanstwo.html
- https://www.prawo.pl/biznes/rodo-nie-utrudnia-przetwarzania-danych-z-jawnych-rejestrow,373892.html
- https://www.rp.pl/prawo-dla-ciebie/art39555811-sad-fundacja-publikujac-dane-narodowca-nie-naruszyla-prawa
