# ETAP 2 — Roadmapa ekspansji z Polski na resztę Europy

> **Status:** dokument planistyczny (bez kodu), stan na **2026-10-10**. Nie jest poradą prawną.
> **Zakres:** rozszerzenie płatnego (x402, USDC na Base) API danych o firmach dla agentów AI z Polski (Etap 1: `/pl/company/{verify,search,verify/batch}` i `/pl/company`) na kolejne kraje, z zachowaniem jednego znormalizowanego schematu (`src/schema/company.ts`, `SCHEMA_VERSION = "1.0"`) i modelu zgodnego z `docs/research/01-licencje-i-limity.md` (pobranie w czasie zapytania + normalizacja, krótki cache, atrybucja, minimalizacja danych osób fizycznych).

## Jak czytać oznaczenia pewności (ważne, bo to ogranicza wiarygodność dokumentu)

W tej sesji **żaden host rządowy ani rejestrowy nie był osiągalny** (WebFetch: `getaddrinfo ENOTFOUND` dla `recherche-entreprises.api.gouv.fr`, `data.brreg.no`, `avoindata.prh.fi`, `developers.kvk.nl`, `kbopub.economie.fgov.be`, `developer-specs.company-information.service.gov.uk`, `www.data.gouv.fr` itd.). Osiągalny był tylko GitHub (raw). Wszystkie fakty pochodzą więc z **wyciągów wyszukiwarki (WebSearch)**, a nie z bezpośredniego pobrania stron. Oznaczenia:

- **[V]** — fakt podany w wyciągu ze **strony oficjalnej** (URL w sekcji 8) albo potwierdzony w kilku niezależnych źródłach. Mimo to nie otwierałem tych stron osobiście; przed produkcją trzeba je otworzyć i zarchiwizować (jak w dokumencie 01).
- **[S]** — źródło wtórne (blog, wrapper, dostawca komercyjny, listing MCP/Apify). Wymaga weryfikacji.
- **[I]** — wniosek własny lub wiedza ogólna, **niesprawdzona w tej sesji**.

Wszystko, co dotyczy limitów i licencji, a nie ma [V], należy traktować jako hipotezę do sprawdzenia „żywym wywołaniem” (sekcja 5) i lekturą oficjalnych warunków.

---

## 1. TL;DR — kolejność krajów (fale)

**Zasada priorytetyzacji:** wielkość rynku (popyt agentów na KYB/enrichment) × otwartość danych (darmowe, bez umowy, jawna licencja) × łatwość (REST/JSON, wyszukiwanie po nazwie, mały narzut RODO).

| Fala | Okno | Kraje / źródła | Jednozdaniowe uzasadnienie |
|---|---|---|---|
| **Fala 0 — fundament** | 12.10–06.11.2026 | Refaktor schematu 1.1 + router `country`, **VIES (27 państw + XI)**, **GLEIF LEI**; równolegle złożenie wniosków o dostęp (AT, EE, SE, DK, IE, CH) | Daje od razu „pokrycie UE” w trybie `verify` (ważność VAT + nazwa/adres tam, gdzie państwo je zwraca) i globalną ścieżkę właścicielską (LEI parent) — przy minimalnym koszcie i zerowym ryzyku licencyjnym; wnioski o dostęp mają tygodniowe czasy oczekiwania, więc trzeba je złożyć od razu. |
| **Fala 1 — „bez tarcia”** | listopad–grudzień 2026 | **FR** (recherche-entreprises, fallback INSEE), **UK** (Companies House), **NO** (Brønnøysund), **FI** (PRH/YTJ), **CZ** (ARES) | Duże lub strategiczne rynki, API darmowe, bez umowy (UK: darmowy klucz), jawne licencje (LO 2.0 / OGL / NLOD / CC BY 4.0), wyszukiwanie po nazwie; FR jest rynkiem, w którym już są konkurenci (więc trzeba tam być, ale z lepszym schematem). |
| **Fala 2 — „wymaga formalności”** | styczeń–luty 2027 | **SE** (Bolagsverket HVD API), **DK** (CVR), **EE** (RIK), **SK** (RPO), **AT** (Firmenbuch HVD, jeśli licencja IWG pozwoli na odsprzedaż wyników), opcjonalnie **CH** (Zefix) | Darmowe, ale wymagają rejestracji/umowy/wniosku (od 5 dni do ~4 tygodni) lub mają niejasne warunki; mniejsze rynki lub dłuższa ścieżka prawna. |
| **Fala 3 — „bramki decyzyjne” (płatne lub zamknięte)** | II kwartał 2027 i dalej | **BE** (KBO: CSV open data albo płatne WS), **NL** (KVK API — płatne), **DE** (brak oficjalnego darmowego API — tylko partner lub HVD), **IE** (CRO), **LV/LT** (bulk), **ES/IT/PT** (tylko VIES+LEI do czasu otwarcia), **UA** (EDR, opcjonalnie) | Duże rynki (DE, NL, IT, ES), ale dane zamknięte lub płatne tak, że przy cenie ~$0.03/wywołanie marża jest ujemna lub licencja nie pozwala na odsprzedaż; wymagają decyzji właściciela (sekcja 7). |
| **Poza zakresem** | — | OpenCorporates, North Data i podobni agregatorzy jako zależność | Licencje share-alike / drogie plany / zakaz lub ograniczenie dalszej odsprzedaży (sekcja 2.3). |

**Najważniejsze wnioski w trzech zdaniach:** (1) Fale 0–1 dają 8 krajów z darmowych, jawnie licencjonowanych źródeł w ~8 tygodni. (2) **Niemcy — największy rynek — nie mają oficjalnego darmowego API** (portal Handelsregister ma limit 60 zapytań/h i ogranicza automatyczne pobieranie); nie wolno ich „scrape'ować”, a obowiązek HVD (od 9.06.2024) nie ma — według tego, co znalazłem — jeszcze potwierdzonej implementacji API. (3) W Holandii i Belgii oficjalne API jest płatne (BE: 50 EUR za 2 000 zapytań = 0,025 EUR/zapytanie [V]), więc przy cenie ~$0.02–0.03 nie da się ich obsłużyć bez wyższej ceny lub bez bulk open data.

---

## 2. Tabela porównawcza źródeł

Legenda kolumn: **Klucz** = czy potrzebny klucz/umowa; **Free?** = koszt dla nas; **Priorytet** = fala (0–3) lub „—”. Wysiłek: **S** ≈ 2–4 osobodni (adapter + fixtures + testy + żywa weryfikacja), **M** ≈ 5–8, **L** ≈ 10+ albo zależny od zewnętrznych decyzji.

### 2.1 Poziom UE / globalny

| Kraj / zasięg | Źródło | API | Klucz | Free? | Limity | Licencja ponownego wykorzystania | Szukanie po nazwie | Ryzyko RODO | Wysiłek | Priorytet |
|---|---|---|---|---|---|---|---|---|---|---|
| UE (27 + XI) | **VIES** (KE) | REST `https://ec.europa.eu/taxation_customs/vies/rest-api/` (w kodzie już użyty; zob. `docs/research/02-api-zrodel.md` §5) | nie [V] | tak [V] | brak opublikowanych; globalny limit współbieżności per państwo (`MS_MAX_CONCURRENT_REQ`) [V/S] | Decyzja KE 2011/833/UE, CC BY 4.0 + disclaimer VIES [V/S] | nie | niskie/średnie (dla JDG nazwa+adres to dane osobowe) | S | **0** |
| UE | **BRIS / e-Justice „Find a company”** | **Nie znalazłem API dla deweloperów**; jest portal (wyszukiwanie w czasie rzeczywistym w rejestrach państw), kontakt `just-bris-helpdesk@ec.europa.eu` [V] | — | portal bezpłatny dla użytkownika [V] | — | brak informacji | tak (web) | — | — | **— (nie scrape'ować; zapytać helpdesk o dostęp maszynowy)** |
| Świat (w tym UE) | **GLEIF LEI** | REST `https://api.gleif.org/api/v1/` (lei-records, fuzzy completions, relacje parent/child) | nie [S] | tak [S] | brak liczbowego limitu w dokumentacji; praktyka ~60/min [S — strony wrapperów MCP], backoff na 429/503 | zbiory GLEIF są udostępniane jako **CC0** [I — niezweryfikowane w tej sesji] | tak (fuzzy) | niskie (podmioty prawne) | S | **0** |
| UE | **HVD — Rozporządzenie wykonawcze (UE) 2023/138** | meta-podstawa: zbiory „Spółki i ich własność” mają być bezpłatne, maszynowo czytelne i dostępne przez API/bulk, stosowanie od **9.06.2024** [V — EUR-Lex/vLex w wyciągach] | — | tak | — | „CC BY 4.0 lub mniej restrykcyjna” [S/I — Art. 2/załącznik do sprawdzenia] | — | — | — | podstawa prawna całej strategii |

### 2.2 Państwa

| Kraj | Źródło | API | Klucz | Free? | Limity | Licencja | Szukanie po nazwie | Ryzyko RODO | Wysiłek | Priorytet |
|---|---|---|---|---|---|---|---|---|---|---|
| **FR** | Annuaire des Entreprises / **API Recherche d'entreprises** (DINUM) | `https://recherche-entreprises.api.gouv.fr/search?q=…` (dok. `/docs/`), SIREN: `q=siren:…`; filtry `code_postal`, `code_naf` [V — repo search-api, kod na MIT] | nie [V] | tak [V] | **7 zapytań/s na IP + 30/s na ASN**, HTTP 429 + `Retry-After`; DINUM może obniżyć [V — wyciąg z dok. oficjalnej] | Dane Sirene: **Licence Ouverte 2.0** [V/S]; pokrycie licencją pól z RNE (dirigeants) przez to API — **do potwierdzenia** [I] | tak | **średnie**: dirigeants (pełne nazwy), EI z „diffusion partielle”; podmioty „non-diffusibles” niedostępne [V] | M | **1** |
| FR | **INSEE API Sirene** (`portail-api.insee.fr`) | REST, wielokryterialne (Lucene-like) | konto + subskrypcja = klucz [V/S] | tak [S] | **30 zapytań/min** (INSEE może zmienić) [V — strona INSEE w wyciągu]; „nowa API Sirene” zapowiedziana (czerwiec 2026), bez daty [V] | **Licence Ouverte 2.0**, atrybucja: źródło + data ostatniej aktualizacji; nie sugerować oficjalności [V/S] | tak | średnie (EI: maskowanie przy `diffusion partielle`) | S–M | **1 (fallback)** |
| FR | **RNE (INPI)** | API/FTP INPI (`data.inpi.fr`) | konto | tak [S] | ? | **odrębna licencja INPI** („Licence de réutilisation des informations de l'INPI”), nie LO 2.0 [V — wyciąg] | ? | wysokie (akty, statuty, osoby) | L | **— (używać tylko pośrednio przez API DINUM)** |
| **UK** | **Companies House Public Data API** | `https://api.company-information.service.gov.uk` (+ Streaming API, bulk) | **darmowy klucz** (konto na developer hub) [V/S] | tak [V] | **600 zapytań / 5 min na aplikację**, 429 do końca okna; ban bez ostrzeżenia za systematyczne przekraczanie [V — developer guidelines] | Dane rejestru: brak ograniczeń CH, odpowiedzialność za RODO po stronie użytkownika [S — forum CH]; „Free Company Data Product” na **OGL v3.0** [S]; OGL nie obejmuje danych osobowych [I] | tak (`/search/companies`) | **średnie/wysokie**: officers (data urodzenia miesiąc/rok, adres korespondencyjny), PSC; od 2025–26 nowe pola weryfikacji tożsamości [V/S] | S–M | **1** |
| **DE** | Handelsregister (`handelsregister.de`) / Unternehmensregister | **Brak oficjalnego darmowego API** [S]; jest portal webowy | — | wgląd w pojedyncze rejestry bezpłatny (§ 9 HGB) [V/S] | **≤ 60 wyszukań/odczytów na godzinę** (Nutzungsordnung), zwolnienie przez whitelist IP na wniosek do Servicestelle AG Hagen [V/S]; § 52 HRV: automatyczny odczyt tylko pojedynczych kart rejestrowych, **bez celowego wyszukiwania osób fizycznych** [V — wyciąg z gesetze-im-internet.de] | HVD (§ 9 DNG, kategoria 5) — obowiązek bezpłatnego API **od 9.06.2024**, ale **nie znalazłem potwierdzonej implementacji** [S — wniosek IFG na FragDenStaat] | tak (web) | wysokie (osoby fizyczne w rejestrze) | L / zablokowane | **3 (watch)** |
| DE (alternatywy) | OffeneRegister.de / OpenRegister.de / handelsregister.ai | snapshot 2019 (OffeneRegister, dane dzielone przez OpenCorporates), płatne API (OpenRegister, handelsregister.ai) [S] | tak | nie / snapshot | — | niejasne (share-alike OpenCorporates; dawny operator portalu zakazywał dalszych użyć) [S] | tak | wysokie | M (integracja) + prawnik | **3 (tylko jako partner po sprawdzeniu licencji odsprzedaży)** |
| **NL** | **KVK** (Handelsregister) | `api.kvk.nl` (Basisprofiel, Zoeken, Naamgeving) — subskrypcja; oraz **Open Dataset Basis Bedrijfsgegevens** `https://opendata.kvk.nl/api/v1/hvds/basisbedrijfsgegevens/kvknummer` | klucz + subskrypcja (API); open dataset bez klucza [V/S] | **API płatne** (stała opłata miesięczna + opłata za zapytanie; **taryfy nie udało się pobrać**) [V/S]; open dataset darmowy [V] | open dataset: **100 zapytań / 5 min**; API: do ~100 zapytań/s i 300 000/miesiąc (FAQ, bez daty) [V/S] | open dataset: **CC BY 4.0**, **tylko BV i NV**, **bez nazwy i bez numeru KVK**, tylko 2 pierwsze cyfry kodu pocztowego [V] — **bezużyteczny do verify** | API tak (Zoeken) | niskie–średnie | M | **3** |
| **BE** | **KBO/BCE** (FPS Economy) | (a) **Open Data** — darmowy plik CSV (aktywne podmioty, ograniczone dane) + pliki aktualizacji; (b) **Public Search Web Services**; (c) „complete file” | (b),(c) umowa | (a) tak; (b) **50 EUR / 2 000 zapytań**; (c) bezpłatnie niekomercyjnie, **komercyjnie 30 000 EUR/rok** [V — strona economie.fgov.be, aktualizacja 4.11.2025] | — | warunki dla (a) nieodczytane; (b)/(c) umowa licencyjna [V] | (b) tak | niskie–średnie | M | **3** |
| **CZ** | **ARES** REST API (MF ČR) | `ares.gov.cz` — Katalog veřejných služeb (v06–v08 2023, wersja ang. 16.02.2024) [V]; w praktyce `…/ekonomicke-subjekty-v-be/rest/…` [I — ścieżka niesprawdzona] | nie [S] | tak [S] | **nieopublikowane** (opaque throttling, możliwe bany IP) [S]; dla aplikacji webowej MF wspomina próg ~500 zapytań/min/użytkownik [V] | warunki provozu MF; ARES od 2018 na liście źródeł otwartych danych [V — Lupa.cz]; informacja „orientacyjna, nie jest dowodem w sądzie” [V]; dokładna licencja **do potwierdzenia** | tak | średnie (živnostníci, statutární orgán) | S–M | **1** |
| **SK** | **RPO** (Štatistický úrad SR) | `https://api.statistics.sk/rpo/v1/…` (search/detail) [S] | nie [S] | tak [S] | ? ; zapytania po IČO bywają wolne/timeouty [S] | **CC BY 4.0** [S] | tak | średnie (statutárne orgány, spoločníci) | M | **2** |
| **EE** | **e-Business Register (RIK)**, avaandmed | API XML + pliki open data; od **1.10.2022 dane bezpłatne dla wszystkich** [V] | **umowa** (rozpatrzenie ~5 dni roboczych) [V/S] | tak [V] | **50 000 odpowiedzi/dzień**, 20 żądań o dokumenty/min/IP [S] | **CC BY 4.0** [S — nie znalazłem na stronach RIK] | tak | średnie (beneficjenci rzeczywiści: dane o UBO mogą być ograniczane od 2026 [S, sprzeczne]) | M | **2** |
| **LV** | **Uzņēmumu reģistrs (UR)** | open data na `data.gov.lv` (CSV, codziennie) + API (REST/SOAP; OAuth2 JWT wg [S]) | zależy | tak | ? | **CC0** [S] | tak | średnie (osoby w UBO/oficerowie; dane osób fizycznych za eID) | M | **3** |
| **LT** | **Registrų centras — JAR** | open data + wyszukiwarka (limit 100 wyszukań/dzień bez umowy) [S] | umowa dla szczegółów | częściowo | 100/dzień (web) [S] | **CC BY 4.0** [S] | tak | średnie | M | **3** |
| **DK** | **CVR** (Erhvervsstyrelsen) | „system-til-system” i CVR-webservices — **bezpłatne** [V]; Elasticsearch `distribution.virk.dk/cvr-permanent` wymaga loginu z `cvrselvbetjening@erst.dk` (dok. ES 6.x, możliwa nieaktualność) [S]; migracja CVR do „VR database” zapowiedziana [V] | **tak (login/umowa)** | tak [V] | ? | brak jasnej licencji w wyciągach — **do ustalenia** | tak | średnie (enkeltmandsvirksomhed) | M | **2** |
| **NO** | **Enhetsregisteret** (Brønnøysundregistrene) | `https://data.brreg.no/enhetsregisteret/api/{enheter,underenheter,roller}` (OpenAPI na `…/api/docs/`) [V/S] | **nie** („nie trzeba się rejestrować”) [V] | tak [V] | nieopublikowane [I] | **NLOD** (Norsk lisens for offentlige data; wersja 2.0 wg [S]) [V] | tak | niskie–średnie: dystrybucje bez danych osobowych są publiczne, `roller` zwraca osoby (przez numer org.) [V] | S | **1** |
| **FI** | **PRH / YTJ open data** | `https://avoindata.prh.fi/opendata-ytj-api/v3/companies?name=…&businessId=…&location=…` (+ rejestr zgłoszeń, sprawozdania iXBRL) [V/S] | **nie** [V/S] | tak [V] | brak opublikowanych [S]; dane aktualizowane **raz dziennie** [V] | **CC BY 4.0**; wymagane wskazanie źródła; zakaz użycia logo PRH/YTJ i naśladowania layoutu [V] | tak | **niskie**: tylko podmioty z rejestru handlowego, **bez przedsiębiorców indywidualnych**, bez e-mail/telefonu [V] | S | **1** |
| **SE** | **Bolagsverket — Värdefulla datamängder** (z SCB) | REST; start **3.02.2025**; OAuth2 client credentials, `…/vardefulla-datamangder/v1` [V/S — biblioteka] | **rejestracja klienta (kundanmälan), bez umowy** [V] | tak [V] | nieznane (wzmianka o limitach) [S] | oficjalnie nie odczytana; wg [S] CC0 (Bolagsverket/SCB) — **do potwierdzenia**; pełne „Företagsinformation API” jest płatne, z zakazem odsprzedaży [S] | **niepewne** (prawdopodobnie tylko po numerze org.) [I] | średnie: enskild firma ma numer org. = personnummer [I] | M | **2** |
| **AT** | **Firmenbuch — HVD WebService** (BMJ/JustizOnline) | maszynowy interfejs, bezpłatny od **I 2025** po **wniosku i akceptacji** (ok. 4 tygodnie) [V/S] | **wniosek + klucz** [S] | tak [V] | ? | **umowa IWG (stan VII.2024)**: dane osobowe tylko w związku z celami Firmenbuch; **licencji nie wolno przenosić na sublicencjobiorców** [V — wyciąg] → **ryzyko dla modelu odsprzedaży** | ? | średnie | M + prawnik | **3 (po opinii prawnej)** |
| **IE** | **CRO** | Open Services API (klucz; onboarding przez support CRO); portal Open Data (wybrane zbiory); bulk płatny (sprzeczne kwoty 31 000 / 78 500 EUR/rok) [V/S] | klucz | podstawowy profil – tak [S]; bulk – nie | ? | nie znaleziono | tak („contains”) | średnie | M | **3** |
| **CH** (EFTA) | **Zefix** | Zefix PublicREST (Basic Auth) i UID (SOAP, 20/min wg [S]) | dane logowania mailem do `zefix@bj.admin.ch` [S] | tak | ? | ? | tak | średnie | M | **2 (opcjonalnie)** |
| **ES** | Registro Mercantil / BORME | **brak oficjalnego API**; `opendata.registradores.org` (web, WAF blokuje datacenter) [S] | — | wgląd częściowo | — | — | — | — | L | **3 (tylko VIES+LEI)** |
| **IT** | Registro Imprese / InfoCamere | **płatne**, umowa dla masowego dostępu; darmowe tylko statystyki (Movimprese) [V/S] | umowa | nie | — | — | — | — | L | **— (VIES+LEI)** |
| **PT** | Registo Comercial (IRN) | brak publicznego API; „certidão permanente” płatna (25–154 EUR) [V] | — | nie | — | — | — | — | L | **— (VIES+LEI)** |
| **UA** (poza UE) | EDR — zbiory otwarte (`data.gov.ua`) | pliki/zbiory; wymóg ustawowy atrybucji z linkiem do administratora [V — ogólne zasady otwartych danych] | nie | tak | — | ustawowa atrybucja, nie CC [V] | brak API na pierwszym rzucie | średnie; kontekst wojenny/sankcyjny | M | **3 (opcjonalnie)** |

### 2.3 Agregatory — świadomie unikamy jako zależności

| Agregator | Dlaczego nie |
|---|---|
| **OpenCorporates** | Darmowy klucz tylko na zasadach **share-alike** (ODbL, atrybucja, licencjonowanie pochodnych na tych samych zasadach, dowód użycia); do zastosowań komercyjnych/własnościowych **płatny plan** [V — oficjalne warunki i cennik]. Cennik API: 500 wywołań/mies. = 2 250 GBP/rok, 2 500/mies. = 6 600 GBP/rok, 5 000/mies. = 12 000 GBP/rok [V]. Przeliczenie: 12 000 GBP / 60 000 wywołań rocznie ≈ **0,20 GBP za wywołanie** (ok. 7× cena rynkowa) [I]. Dodatkowo licencja OC obejmuje tylko prawa do bazy, nie licencje rejestrów źródłowych [S]. |
| **North Data** | API tylko w płatnych pakietach dla przedsiębiorców (B2B), licencja użytkowa „na czas współpracy”, wyniki z automatycznej analizy z zastrzeżeniem możliwych błędów [V — AGB]; ceny niejawne (oferty pośredników od ~500 USD/mies. [S]). Brak prawa do odsprzedaży danych dalej; zależność od jednego prywatnego dostawcy. |
| **handelsregister.ai, OpenRegister.de, Pappers, Dun & Bradstreet itp.** | Płatne, odrębne licencje; dopuszczalne najwyżej jako opcjonalny partner dla DE po opinii prawnej o prawie odsprzedaży. |

### 2.4 Konkurencja (z listingu x402 Bazaar i okolic)

- Rynek „company enrichment” w Bazaar: ~71 ofert na 40 hostach, mediana ceny ~$0.03 (dane zadania). W `docs/research/03-x402-i-discovery.md` migawka Tanod z 2026-10-09: mediana $0.027, p25 $0.01, p75 $0.10 [S].
- **Konkurent FR (SIREN)** w Bazaar — endpoint ze ścieżką-parametrem (cdp-sdk #787) [S, doc 03].
- **Sirenic** — API pay-per-call „oficjalnych danych francuskich i europejskich” (INSEE Sirene, INPI RNE, inne rejestry; wg listingów 12 krajów, m.in. BE, UK, NO, EE, LV, GLEIF), x402 na Base (USDC/EURC), **podpisane odpowiedzi Ed25519**, ceny **$0.001–$1.00**, nie pobiera opłaty za błędne żądania; OpenAPI, MCP, A2A [S — Product Hunt, mcpservers.org, glama.ai]. To najbliższy konkurent Etapu 2; warto rozważyć **podpisywanie odpowiedzi** jako funkcję wyrównującą (sekcja 7).

---

## 3. Proponowany projekt API Etapu 2

### 3.1 Zasady

1. **Zero zmian łamiących dla `/pl/*`.** Kształt odpowiedzi PL pozostaje identyczny; wszystko nowe jest dodatkiem (wersja schematu 1.1, zmiana „minor”). Aliasy PL zostają bezterminowo.
2. **Walidacja identyfikatora przed płatnością** (jak dziś: nieprawidłowy NIP = darmowy 400). Dla każdego kraju: normalizacja + suma kontrolna tam, gdzie jest prosta (tabela 3.4). Nieznany = 404 bezpłatnie (jak dziś).
3. **Trasy statyczne, nie parametry ścieżki** (błąd Bazaar z `pathParams` — cdp-sdk #787, doc 03): `/fr/company`, a nie `/company/:country/:id`.
4. **Jedna cena „mentalna” dla agenta**, różnicowana tylko tam, gdzie upstream kosztuje (BE, NL).

### 3.2 Układ tras (rekomendacja hybrydowa)

**A. Trasy krajowe — kanoniczne, do odkrywalności w Bazaar i MCP** (po jednym wpisie na kraj i funkcję):

```
GET  /{cc}/company/verify        (cc = pl, fr, gb, no, fi, cz, …)
GET  /{cc}/company
GET  /{cc}/company/search
POST /{cc}/company/verify/batch   (tylko kraje o niskim koszcie upstream)
```

Parametry identyfikatorów typowane per kraj (czytelne dla agentów i dla walidacji przed płatnością): PL `nip|regon|krs` (bez zmian), FR `siren|siret|vat`, GB `number`, CZ `ico`, NO `orgnr`, FI `businessId`, DK `cvr`, SE `orgnr`, BE `enterprise`, SK `ico`, EE `regcode`, AT `fn`. Każdy kraj akceptuje też `vat=` z prefiksem (patrz 3.3).

**B. Trasy ogólne — wygoda dla agentów, jeden wpis w katalogu:**

```
GET  /eu/company/verify?country=FR&id=…     lub  ?vat=FR12345678901
GET  /eu/company?country=FR&id=…&type=siren
GET  /eu/company/search?country=FR&name=…
GET  /eu/vat/verify?vat=…                    (czysty VIES, najtańszy)
GET  /eu/lei?lei=…  oraz  /eu/lei/search?name=…   (GLEIF, z include=parents)
```

Trasy ogólne są cienkimi routerami do tych samych adapterów; cena wynika z tabeli stawek kraju (funkcja ceny z kontekstem — to już działa dla batcha). Zalety: 1 wpis dla agentów „którzy nie wiedzą, jaki kraj”; wady: opisy w Bazaar muszą być ogólne — dlatego A pozostaje kanoniczne.

**Nazwa usługi:** dziś `SERVICE_NAME = "PL Company Data"`; po Fali 1 zmienić na „EU Company Data” (limit ≤ 32 znaki ASCII w Bazaar), tagi + kraje.

### 3.3 Autodetekcja identyfikatora

- **Numer VAT z prefiksem** (`FR…`, `CZ…`, `EL…`, `XI…`): prefiks → kraj → walidacja formatu → VIES (zawsze dostępny) → jeśli mamy adapter i numer VAT pozwala wyprowadzić numer rejestrowy, to także rejestr.
  - Wyprowadzalne deterministycznie: **FR** (VAT = `FR` + 2 cyfry klucza + SIREN), **CZ** (`CZ` + IČO dla podmiotów prawnych), **DK** (`DK` + CVR), **FI** (`FI` + Y-tunnus bez myślnika), **BE** (`BE` + KBO 10 cyfr), **NO** (`NO` + org.nr + `MVA`), **SE** (`SE` + org.nr + `01`), **AT** (`ATU` + 8 cyfr to VAT, **nie** numer Firmenbuch).
  - **Nie** wyprowadzalne: DE (HRB/HRA ≠ USt-IdNr.), NL (KVK 8 cyfr ≠ BTW), SK (IČ DPH ≠ IČO), EE (kod rejestrowy ≠ KMKR), UK (numer spółki ≠ GB VAT), ES/IT/PT.
  - W takich krajach `vat=` daje tylko VIES (`verify`), a pełny profil wymaga `id` rejestrowego.
- **Bez prefiksu:** wymagamy `country` (bezpłatny 400, jeśli brak). Nie zgadujemy po długości — numery PL (10 cyfr), BE (10 cyfr), CZ/SK (8 cyfr), DK/NL/FI (8 cyfr) kolidują.
- Wyjątki prefiksów: Grecja = `EL` (ISO `GR`), Irlandia Północna = `XI`, Wielka Brytania nie jest w VIES.

### 3.4 Sumy kontrolne i formaty (wszystkie [I] — standardowe algorytmy, do pokrycia testami z kodami z rejestrów)

| Kraj | Identyfikator | Format / suma kontrolna |
|---|---|---|
| PL (istnieje) | NIP, REGON, KRS | mod 11 / mod 11 / brak (w `src/lib/ids.ts`) |
| FR | SIREN (9), SIRET (14) | Luhn (SIRET: wyjątek La Poste) |
| UK | company number | 8 znaków (2 litery prefiksu + 6 cyfr lub 8 cyfr), bez sumy kontrolnej |
| CZ, SK | IČO | 8 cyfr, mod 11 (wagi 8..2) |
| NO | organisasjonsnummer | 9 cyfr, mod 11 (wagi 3,2,7,6,5,4,3,2) |
| DK | CVR | 8 cyfr, mod 11 (wagi 2,7,6,5,4,3,2,1; suma ≡ 0 mod 11) |
| FI | Y-tunnus | 7 cyfr + cyfra kontrolna (mod 11, wagi 7,9,10,5,8,4,2), zapis `1234567-8` |
| SE | organisationsnummer | 10 cyfr, Luhn |
| BE | KBO/BCE | 10 cyfr, ostatnie 2 = 97 − (pierwsze 8 mod 97) |
| EE | registrikood | 8 cyfr, mod 11 (dwuprzebiegowy) |
| AT | Firmenbuchnummer | cyfry + litera kontrolna (bez prostej sumy) |
| NL | KVK-nummer | 8 cyfr, brak publicznej sumy kontrolnej |
| DE | Register + sąd + numer (np. HRB 12345, AG München) | brak sumy kontrolnej |
| LEI | ISO 17442 | 20 znaków, mod 97-10 |

### 3.5 Jak uogólniają się cztery funkcje

| Funkcja | Dziś (PL) | Etap 2 |
|---|---|---|
| **verify** | NIP/REGON/KRS → found/active/status/name | jak PL; `query.kind` rozszerzone do `string` (np. `siren`, `vat`, `number`); źródło „najtańsze wystarczające” (np. FR: API DINUM, UK: CH, DE/NL/BE bez adaptera: VIES). `nameMatch` z normalizacją znaków diakrytycznych i sufiksów formy prawnej per kraj (SA/SAS, Ltd/Limited, Oy/Oyj, AS/ASA, s.r.o./a.s., GmbH/AG). |
| **profile** (`/company`) | merge GUS+KRS+CEIDG | merge **per kraj** (FR: Sirene+RNE przez DINUM; UK: profile + opcjonalnie officers/PSC; CZ: ARES ekonomické subjekty + VR) + opcjonalnie `include=lei` (parent), `include=vat` (VIES). Jedna odpowiedź = jeden schemat. |
| **search** | po nazwie; CEIDG z filtrem | lokalne API wyszukiwania (FR, UK, NO, FI, CZ, SK, EE, DK). Kraje bez wyszukiwania (SE, DE bez partnera): 501 bezpłatnie z kodem `search_not_supported`. Limit 20 wyników, tylko podmioty prawne; osoby fizyczne tylko z dodatkowym filtrem (miejscowość/kod) jak w PL. |
| **batch verify** | ≤ 50 NIP, $0.005/szt. | `POST /{cc}/company/verify/batch` tylko dla krajów z tanim upstreamem i bez ryzyka RODO (statusy bez nazw dla osób fizycznych); `POST /eu/vat/verify/batch` (VIES, ≤ 50) — **uwaga na `MS_MAX_CONCURRENT_REQ`**, więc kolejkowanie per państwo. Brak batcha dla krajów z limitem 30/min (INSEE) — używać DINUM. |

### 3.6 Zmiany schematu (wersja 1.1, wyłącznie addytywne dla PL)

| # | Zmiana | Uwagi |
|---|---|---|
| 1 | `country`: `"PL"` → `CountryCode` (ISO 3166-1 alpha-2; `GB`, `NO`, `CH` dopuszczone) | PL zawsze `"PL"`. |
| 2 | `identifiers`: dziś `{nip, regon, krs}` → **mapa otwarta** `Record<IdType, string \| null>` + nowe pola uniwersalne `primaryId: {type, value}`, `vat`, `lei`, opcjonalnie `euid` (European Unique Identifier z BRIS) | Dla PL nic się nie zmienia (te same trzy klucze + `vat` jako dodatek). Dla pozostałych krajów klucze lokalne (`siren`, `siret`, `companyNumber`, `ico`, `orgnr`, `businessId`, `cvr`, …). Typ TS jako unia dyskryminowana po `country`. |
| 3 | `pkd` → **`activities: { scheme, primary, all }`** (obok zachowanego `pkd` dla PL) | `scheme` ∈ `NACE_REV2`, `PKD_2007`, `NAF_REV2`, `UK_SIC_2007`, `CZ_NACE`, `SNI_2007`, `TOL_2008`, … Nie zakładać mapowania 1:1 po zmianie na NACE Rev. 2.1 (krajowe klasyfikacje przechodzą różnie [I]); zawsze zwracać `scheme` i kod oryginalny + pole `nace` (4 cyfry), gdy przeliczenie jest pewne (PKD 2007 `62.01.Z` → NACE `62.01`; NAF `62.01Z` → `62.01`; UK SIC `62012` → `62.01`) [I]. |
| 4 | `legalForm`: dodać `code` + `codeScheme` (preferencja **ISO 20275 ELF** z GLEIF, w przeciwnym razie kod krajowy) i rozszerzyć `LegalForm` o ≤ 6 wartości (`limited_by_guarantee`, `economic_interest_grouping`, `public_limited_company_other`…; nieznane → `other` + `label`) | Tabela mapowania per kraj w repozytorium (CSV/JSON), z testem pokrycia. |
| 5 | `status`: dodać `statusRaw` (oryginał) + **tabela mapowania per kraj** na `EntityStatus`; dodać `in_restructuring` (UK administration/CVA, FR sauvegarde/redressement) | Nowa wartość enum = zmiana minor wymagająca wzmianki w changelogu. PL nigdy jej nie emituje. |
| 6 | `address`: pola PL-specyficzne (`commune`, `county`, `voivodeship`) zostają (null poza PL); dodać `region` | |
| 7 | `registries`: PL-obiekt zostaje; dodać `registryRefs: Array<{id, name, number, url}>` | |
| 8 | `SourceId` → otwarty łańcuch ze słownikiem (`INSEE_SIRENE`, `FR_RECHERCHE`, `CH_UK`, `BRREG`, `PRH_YTJ`, `ARES`, `GLEIF`, …); `SourceAttribution` dodać `licence {name, url}`, `attributionText`, `dataAsOf` | Atrybucja z sekcji 6 trafia do każdej odpowiedzi (`sources[]`). |
| 9 | `representation` → zostaje; dodać `include=officers` (UK, FR, CZ, NO, SK, DK, EE) z minimalizacją: **imię i nazwisko + rola + data objęcia funkcji**; bez dat urodzenia, adresów prywatnych, numerów osobistych | `personalDataRedacted` obejmuje także brak officerów. |
| 10 | `notice`: wersje per kraj + link do `/legal` (nota art. 14 RODO rozszerzona na wszystkie kraje) | |
| 11 | `VerifyResult.query.kind` i `SearchHit.source` → `string` | |
| 12 | Nowe pola `lei: { lei, ultimateParent?, directParent? }` (opcjonalne) | Unikalna wartość: łańcuch właścicielski z GLEIF Level 2. |

Wersjonowanie: nagłówek `X-Schema-Version` i `schemaVersion: "1.1"`; JSON Schema w `/openapi.json` z `additionalProperties` dozwolonym dla map; test kontraktowy „PL-fixtures 1.0 przechodzi walidację schematu 1.1”.

### 3.7 Infrastruktura wspólna

- **Limiter per upstream** (np. Durable Object) z budżetem w górę (FR: 7/s/IP **i 30/s/ASN** — ASN Cloudflare jest wspólny dla wielu workerów, więc limit ASN może być zużywany przez innych [I]; UK: 600/5 min na klucz = ~2/s; INSEE: 30/min; GUS/MF/CEIDG jak w Etapie 1).
- **Stały egress w UE** (mały VPS/proxy) jako opcja dla źródeł z limitami per IP (FR, ewentualnie ARES, DE-whitelist). Decyzja kosztowa — sekcja 7.
- **Cache** (TTL jak w doc 01 §7.2 pkt 5): dane rejestrowe 24 h, VIES ≤ 24 h, GLEIF 24 h, listy wykluczeń natychmiast; `stale-while-error` z flagą `cached:true` i `ageSeconds`.
- **Wyjątki dla zasady „bez eksportu masowego”:** nie budujemy własnych kopii baz osób; jedyny dopuszczalny indeks to **nazwy podmiotów prawnych** (jak dla KRS w Etapie 1), jeśli licencja bulk na to pozwala (FR Sirene stock, FI, NO, CZ) — decyzja per kraj.
- **Podpisywanie odpowiedzi** (Ed25519, jak konkurent) — opcjonalnie, S/M; rozważyć w Fali 1.

---

## 4. Sugestia cen

**Dane wejściowe:** mediana rynku ~$0.03 (zadanie), $0.027 / p25 $0.01 / p75 $0.10 (doc 03) [S]; Etap 1 PL: verify $0.005, search $0.01, profile $0.02, batch $0.005/szt.; konkurent Sirenic $0.001–$1.00 [S]. Koszt upstreamu w Falach 0–2 ≈ 0 (darmowe API); koszt Workers pomijalny; opłaty facilitatora x402/CDP — **do sprawdzenia** [I] (przy $0.005 mogą istotnie wpływać na marżę).

| Poziom | Funkcja | Cena | Uwagi |
|---|---|---|---|
| **T0** | `/eu/vat/verify` (czysty VIES) | **$0.005** | porównywalne z PL verify; największy wolumen |
| **T1** | `/{cc}/company/verify` (kraje z darmowym upstreamem) | **$0.005** | bez zmian względem PL |
| **T2** | `/{cc}/company` (profil, jedno źródło) | **$0.02** | poniżej mediany rynku, spójne z PL |
| **T2+** | profil wieloźródłowy (np. FR Sirene+RNE, UK + PSC-summary) lub `include=lei` | **$0.03** | w okolicy mediany |
| **T3** | `include=officers` | **+$0.01** (łącznie $0.03–0.04) | pokrywa koszt zgodności RODO (log, wykluczenia) |
| **S** | `/{cc}/company/search` | **$0.01** | jak PL; płatne również „0 wyników”? — rekomendacja: 404 bezpłatny (jak dziś) |
| **B** | batch verify | **$0.005/szt.**, ≤ 50, minimalna cena = 1 szt. | tylko kraje bez limitu 30/min |
| **L** | `/eu/lei` + parent chain | **$0.02** | unikalne dane właścicielskie |
| **P (premium upstream)** | BE (jeśli WS: 0,025 EUR/zapytanie [V]), NL (taryfa KVK nieznana) | **≥ $0.06–0.08** (po poznaniu taryfy) lub **wcale** | przy cenie $0.02–0.03 marża byłaby ujemna; dopuścić tylko jako tryb „premium” lub przez bulk open data |

Zasady: (1) jedna stawka na funkcję w całej UE (prostota dla agentów), wyjątek tylko tier P; (2) bez przecen „startowych” (niszczą mediany i trudno je podnosić); (3) darmowe 4xx przed paywallem (walidacja formatu, brak kraju) — jak dziś; (4) eksperyment A/B: T2 $0.02 vs $0.03 po 4 tygodniach danych o konwersji w Bazaar.

---

## 5. Plan wdrożenia per fala

Estymacje w osobodniach (1 deweloper + asystent AI). Zawsze: fixtures z **żywych odpowiedzi** (w Etapie 1 część fixtures była „RECONSTRUCTED”, doc 02 — tym razem nagrywać z prawdziwych wywołań), testy kontraktowe schematu, aktualizacja OpenAPI/llms.txt/Bazaar.

### Fala 0 — fundament (12.10–06.11.2026; ~12–16 osobodni + równoległa administracja)

| Zadanie | Wysiłek | Uwagi |
|---|---|---|
| Schemat 1.1 + `activities`, `identifiers` (mapa), `legalForm.code`, `statusRaw`, tabele mapowań (statusy, formy prawne) per kraj | M | Test: fixtures PL 1.0 nadal zielone. |
| Router `/{cc}/…` i `/eu/…`, walidacja przed płatnością per kraj (sekcja 3.4), wykrywanie VAT | M | Funkcja ceny z kontekstem już istnieje (batch). |
| Limiter per upstream + stały egress (decyzja) | S–M | Zależne od decyzji właściciela. |
| VIES uogólniony na 27 + XI (z kolejką per państwo i obsługą `MS_MAX_CONCURRENT_REQ`) | S | Rozróżnić „nieprawidłowy” od „niedostępny”. |
| GLEIF: lookup, search, parent chain | S | Mapowanie ELF → `legalForm`. |
| **Administracja (dzień 1):** wnioski AT (IWG/HVD), umowa EE, rejestracja SE (kundanmälan), DK (login CVR), IE (klucz CRO), CH (Zefix), klucz UK (Companies House), konto INSEE, **zapytanie do DINUM o limity i dopuszczenie ASN**, zapytanie IFG/HVD do BfJ (DE), zapytanie do `just-bris-helpdesk@ec.europa.eu` o dostęp maszynowy | — | Czasy: AT ~4 tyg. [S], EE ~5 dni roboczych [S]. |

**Ryzyka:** limit współbieżności VIES, niespójne zwroty nazw (część państw zwraca „---”) [I]; rozbieżność typów w schemacie przy zmianie enumów (testy konsumentów).

**Żywe wywołania do weryfikacji:** VIES REST (kody błędów, pola dla DE/ES/FR/IT), GLEIF (nagłówki limitów, relacje parent), czas odpowiedzi z Workers, zachowanie przy `MS_MAX_CONCURRENT_REQ`.

### Fala 1 — FR, UK, NO, FI, CZ (listopad–grudzień 2026; ~20–28 osobodni)

| Kraj | Wysiłek | Kluczowe punkty |
|---|---|---|
| **FR** | M (4–6 d) | Główne źródło: `recherche-entreprises.api.gouv.fr`; fallback INSEE (30/min – tylko jako awaryjne). Obsługa `diffusion partielle` / niediffusible (zwracać „nie znaleziono” lub zredagowane). Pola: SIREN, SIRET siège, NAF, forme juridique, dirigeants (osoby fizyczne — za flagą), kapitał (jeśli jest). Mapowanie statusu (A/C → active/removed). |
| **UK** | S–M (3–5 d) | Klucz w sekretach; limiter 600/5 min; endpointy `/company/{n}`, `/search/companies`, `/company/{n}/officers` (za flagą; bez DOB), `/persons-with-significant-control` (opcjonalnie, osoby fizyczne — ostrożnie). Statusy: active/dissolved/liquidation/administration/… → tabela mapowań. |
| **NO** | S (2–3 d) | `enheter`/`underenheter`, `roller` tylko za flagą (osoby); nazwy z diakrytykami; NACE (`naeringskode`); status (konkurs, avvikling, tvangsavvikling). |
| **FI** | S (2–3 d) | `v3/companies`; TOL 2008 jako `scheme`; formy prawne; pamiętać o braku JDG; zakaz logo PRH. |
| **CZ** | S–M (3–5 d) | ARES v3: podstawowe dane, VR (statutární orgán) za flagą; throttling nieudokumentowany → konserwatywny limiter (np. 2–3 req/s) i cache 24 h. |

**Ryzyka:** FR – limity per IP/ASN z Workers; wspólne IP Cloudflare; zgodność licencyjna pól z RNE; UK – nieuniwersalność OGL wobec danych osobowych i konieczność oceny UK GDPR (przedstawiciel w UK?) [I]; CZ – opaque throttling i bany; NO/FI – brak oficjalnych limitów (ryzyko cichego throttlingu).

**Żywe wywołania do weryfikacji (checklista):**
1. FR: nagłówki `Retry-After`/limit; czy 7/s dotyczy IP workera czy ASN w praktyce; pole `statut_diffusion`; czy dirigeants są zwracani dla EI; jak wygląda `nombre_etablissements`; porównanie z INSEE dla 20 SIREN; pokrycie licencją (dokumentacja api.gouv.fr, strona data.gouv.fr API).
2. UK: nagłówki `X-Ratelimit-*`; zachowanie przy 429; zawartość `officers` po zmianach weryfikacji tożsamości; czy `search/companies` ma stabilne limity.
3. NO: formy odpowiedzi `enheter` (HAL JSON), paginacja, kody statusów konkurs/avvikling, filtrowanie `roller`.
4. FI: `v3/companies` — parametry `name`, `businessId`, `location`, `companyForm`, `mainBusinessLine`; stabilność; czy są nagłówki limitów; format formy prawnej (kody + opisy w 3 językach).
5. CZ: ścieżki ARES v3 (`ekonomicke-subjekty`, `ekonomicke-subjekty-vr`, `vyhledat`), kody odpowiedzi 429/403, pole CZ-NACE, ograniczenia długości wyszukiwania.

### Fala 2 — SE, DK, EE, SK, (AT), (CH) (styczeń–luty 2027; ~25–35 osobodni)

| Kraj | Wysiłek | Kluczowe punkty / bramki |
|---|---|---|
| **SE** | M | OAuth2 client credentials (token endpoint z biblioteki [S] — zweryfikować w dokumentacji portal.api.bolagsverket.se); brak wyszukiwania po nazwie? → tylko `verify`/`company` po numerze org.; **wykluczyć enskild firma (personnummer)**; licencja do potwierdzenia (CC0 vs inna). |
| **DK** | M | Dostęp (system-til-system) – login wg [S]; Elasticsearch vs Datafordeler; formaty (zagnieżdżone, wielojęzyczne); kolejne zmiany migracji CVR→VR zapowiedziane [V]. |
| **EE** | M | Umowa (czas rozpatrzenia ~5 dni rob.); XML API; dzienny limit 50 000 odpowiedzi [S]; dane UBO ograniczać/pomijać (zmiany 2026 [S]). |
| **SK** | M | Stabilność IČO (timeouty [S]) → wyszukiwanie po nazwie jako główna ścieżka; statutárne orgány i spoločníci za flagą. |
| **AT** | M + prawnik | Zależny od decyzji o licencji IWG: zakaz sublicencji [V] ⇒ ryzyko dla odsprzedaży odpowiedzi anonimowym kupującym; ewentualna odpowiedź BMJ na pytanie wprost. |
| **CH (Zefix)** | M | Dane logowania mailem; kontrakt dla EFTA; opcjonalnie. |

**Żywe wywołania:** DK (czy login/umowa są nadal wymagane i w jakiej technologii: ES vs Datafordeler), SE (struktura odpowiedzi, czy jest `search`, limity), EE (pola, limity dzienne), SK (czas odpowiedzi IČO vs nazwa), AT (opis interfejsu dostępny po uzyskaniu licencji).

### Fala 3 — bramki decyzyjne (II kwartał 2027; zależnie od decyzji)

| Kraj | Opcje | Rekomendacja robocza |
|---|---|---|
| **DE** | (a) czekać na HVD API Unternehmensregister; (b) whitelist IP z AG Hagen (wniosek z zakresem i celem) – ale § 52 HRV zabrania celowego wyszukiwania osób, a Nutzungsordnung ogranicza automatyzację; (c) partner płatny (OpenRegister, handelsregister.ai) – tylko z prawem odsprzedaży; (d) VIES+LEI jako minimum | **(d) teraz, (a) obserwacja** (wniosek IFG + monitoring); (c) tylko po opinii prawnej. **Nie scrape'ować** (ryzyko karne wskazywane przez operatorów portalu: §§ 303a, 303b StGB [S]). |
| **NL** | KVK API (płatne) lub tylko VIES+LEI | Pobrać aktualną taryfę (developers.kvk.nl → tarieven); uruchamiać tylko w tier P z ceną ≥ koszt + marża. Open dataset HVD nie nadaje się do verify (brak nazwy i numeru). |
| **BE** | CSV open data (indeks nazw podmiotów, jeśli licencja pozwala) albo WS 50 EUR / 2 000 zapytań [V] | Rozważyć bulk CSV w D1/R2 (dane podmiotów prawnych, nie osób); sprawdzić warunki użycia pliku open data (licencja „complete file” za 30 000 EUR/rok jest odrębna). |
| **IE** | klucz CRO API + podstawowy profil | Uruchomić, jeśli klucz darmowy i warunki pozwalają na komercyjne użycie. |
| **LV / LT** | pliki open data (CC0 / CC BY 4.0 wg [S]) | Opcjonalnie, niski priorytet. |
| **ES / IT / PT** | tylko VIES + LEI | Do czasu otwarcia API (HVD). |
| **UA** | opcjonalnie | Wymaga oceny sankcyjnej/reputacyjnej; niski priorytet. |

### Kamienie milowe i bramki jakości

1. **Koniec Fali 0 (06.11.2026):** 100% fixtures PL 1.0 przechodzi schemat 1.1; VIES+GLEIF live; wszystkie wnioski złożone.
2. **Koniec Fali 1 (ok. 18.12.2026):** 5 krajów live na Base mainnet, wpisy w Bazaar (CDP), x402scan, 402index; nota RODO art. 14 rozszerzona.
3. **Bramka prawna przed Falą 2:** opinia prawnika UE/PL/UK (sekcja 7) – oceny dla UK GDPR, AT (sublicencja), SE/DK (licencje).
4. **Bramka kosztowa przed Falą 3:** decyzja o płatnych źródłach i stałym egressie.

---

## 6. Lista kontrolna prawna/zgodności per kraj

**Reguła ogólna (dziedziczona z doc 01):** (1) sprzedajemy usługę przetwarzania w czasie zapytania (pobranie, normalizacja, scalenie), nie zrzut bazy; (2) atrybucja w `sources[]` każdej odpowiedzi: nazwa rejestru, wydawca, URL, `retrievedAt`, `dataAsOf`, informacja o przetworzeniu, licencja; (3) brak sugerowania oficjalności (godła, logotypy, „odpis”); (4) krótki cache, logi bez treści odpowiedzi; (5) minimalizacja danych osób fizycznych; (6) lista wykluczeń; (7) brak obchodzenia limitów i zabezpieczeń.

**Dyrektywa 2019/1024 i HVD:** dane z kategorii „Spółki i ich własność” powinny być bezpłatne, przez API, na „CC BY 4.0 lub mniej restrykcyjnej” licencji, od 9.06.2024 [V/S]. Dyrektywa dopuszcza czasowe wyjątki od bezpłatności (maks. 2 lata na wniosek organu) [S]; jeśli liczyć od 9.06.2024, miałyby wygasnąć ok. 9.06.2026 — to potencjalny argument w korespondencji z DE, BE, IT [I; do sprawdzenia w przepisach krajowych]. Nie oznacza to, że dane osobowe w tych zbiorach są wolne od RODO.

| Kraj | Licencja / warunki | Proponowana atrybucja w odpowiedzi (do weryfikacji tekstu u źródła) | RODO / ograniczenia | Do zrobienia |
|---|---|---|---|---|
| **UE — VIES** | CC BY 4.0 (Decyzja 2011/833/UE) + disclaimer VIES [V/S] | „© European Union — VIES VAT number validation. Processed by …; no liability of the Commission.” | JDG: nazwa/adres to dane osobowe | Linkować disclaimer; zachować `requestIdentifier`; cache ≤ 24 h. |
| **GLEIF** | CC0 [I] | „Source: GLEIF (Global Legal Entity Identifier Foundation), retrieved <date>.” | podmioty prawne | Potwierdzić CC0 na stronie GLEIF; niewymagana atrybucja, ale przyjmujemy ją dobrowolnie. |
| **FR** | **Licence Ouverte 2.0** (Etalab) — atrybucja: źródło + data ostatniej aktualizacji; zakaz sugerowania oficjalności [V/S] | „Source : Insee — base Sirene, via API Recherche d'entreprises (DINUM), Licence Ouverte 2.0, mise à jour : <date>. Données traitées par …” | EI z „diffusion partielle”: maskowanie nazwiska/adresu; „non-diffusibles” – nie zwracamy; dirigeants — pełne nazwy | Potwierdzić, czy dane z RNE serwowane przez API DINUM są objęte LO 2.0 czy licencją INPI [V — INPI ma własną licencję]; zapisać regulamin API DINUM; uwzględnić rejestr czynności i wykluczenia. |
| **UK** | **OGL v3.0** dla Free Company Data Product [S]; zasady dostępu API (guidelines) [V]; OGL nie obejmuje danych osobowych [I] | „Contains public sector information licensed under the Open Government Licence v3.0. Source: Companies House.” | UK GDPR: officers/PSC; rozważyć przedstawiciela w UK (art. 27 UK GDPR) [I] | Zarchiwizować developer guidelines i API terms; sprawdzić „Acceptable use”; ocena LIA dla UK. |
| **NO** | **NLOD** (2.0 wg [S]) [V] | „Contains data under the Norwegian Licence for Open Government Data (NLOD) distributed by Brønnøysundregistrene.” | Brak rejestracji; dystrybucje bez danych osobowych są publiczne, `roller` zwracają osoby (EOG — RODO obowiązuje) [V] | Sprawdzić tekst NLOD i strony brreg.no „Datasett og API”; role tylko za flagą. |
| **FI** | **CC BY 4.0**; wymagane wskazanie źródła; zakaz logo PRH/YTJ i naśladowania layoutu [V] | „Source: Finnish Patent and Registration Office (PRH), Business Information System open data, CC BY 4.0. Modified: normalised.” | Brak JDG w danych — niskie ryzyko | Zarchiwizować stronę avoindata.prh.fi/en i warunki; kontakt avoindata@prh.fi. |
| **CZ** | Warunki provozu ARES (MF ČR); informacja orientacyjna, nie dowód sądowy [V]; licencja otwartych danych — do potwierdzenia | „Zdroj: ARES — Ministerstvo financí ČR (administrativní registr ekonomických subjektů).” | živnostníci (osoby fizyczne), statutární orgány | Napisać do `aresmfcr@mfcr.cz` (pytanie o limity i licencję); zarchiwizować podmínky provozu. |
| **SK** | CC BY 4.0 [S] | „Zdroj: Register právnických osôb, Štatistický úrad SR.” | osoby w orgánach i jako wspólnicy | Potwierdzić licencję i limity w dokumentacji ŠÚ SR. |
| **EE** | Dane bezpłatne od 1.10.2022 [V]; API/zbiory zawierają tylko dane publiczne; CC BY 4.0 wg [S] | „Source: e-Business Register (RIK), <date>, CC BY 4.0.” | Umowa API (warunki użytkowania); dane UBO — zmiany 2026 [S] | Podpisać umowę, zarchiwizować warunki; nie udostępniać UBO bez weryfikacji stanu prawnego. |
| **LV** | CC0 [S] | „Source: Register of Enterprises of the Republic of Latvia (open data).” | dane osób za eID | Potwierdzić na data.gov.lv. |
| **LT** | CC BY 4.0 [S] | „Source: State Enterprise Centre of Registers (JAR), <date>.” | limity wyszukiwarki 100/dzień [S] | Potwierdzić warunki. |
| **DK** | Dane CVR bezpłatne w ramach system-til-system [V]; licencja nieodczytana | „Source: CVR — Erhvervsstyrelsen.” | enkeltmandsvirksomhed → właściciel jest osobą | Ustalić licencję i warunki loginu; zarchiwizować. |
| **SE** | HVD – dostęp bez umowy po rejestracji [V]; licencja CC0 vs inna [S] | „Source: Bolagsverket and Statistics Sweden (SCB), valuable datasets.” | enskild firma = personnummer → wykluczyć | Zarchiwizować „Värdefulla datamängder” i warunki; sprawdzić tekst licencji. |
| **AT** | Umowa IWG (VII.2024): dane osobowe tylko w związku z celami Firmenbuch, brak sublicencji [V] | zgodnie z umową | osoby w Firmenbuch | **Bramka prawna**; wniosek o licencję/HVD; pytanie do BMJ o odsprzedaż w modelu pay-per-call. |
| **BE** | Open Data CSV darmowy; WS 50 EUR/2 000; „complete file” komercyjnie 30 000 EUR/rok [V] | wg umowy | niskie–średnie | Pobrać warunki pliku open data; decyzja kosztowa. |
| **NL** | Open dataset: CC BY 4.0 [V] (tylko BV/NV, bez nazwy); API: umowa i taryfa KVK | „Source: KVK Handelsregister Open Dataset, CC BY 4.0” | niskie–średnie | Zdecydować, czy w ogóle (sekcja 7). |
| **DE** | Nutzungsordnung portalu: ≤ 60 odczytów/h, ograniczenia automatyzacji; HRV § 52; HVD niepotwierdzone | — | wysokie | Nie scrape'ować; IFG; ewentualnie whitelist/partner po opinii prawnej. |
| **IE** | warunki CRO API (nieodczytane) | wg warunków | średnie | Zarchiwizować. |
| **CH / UA** | Zefix: dane logowania; UA: ustawowa atrybucja | — | średnie | Warunki do odczytania. |

**Wspólne obowiązki RODO przy ekspansji (rozszerzenie doc 01 §6):** nota informacyjna art. 14 (PL/EN + języki rynków wiodących, minimum EN), zaktualizowany rejestr czynności (art. 30) i DPIA-lite o dodatkowe kraje, mechanizm obsługi żądań (art. 15–21) i lista wykluczeń na poziomie UE, ocena transferów (UK, CH, NO), brak profilowania osób, brak wyszukiwania po osobie.

---

## 7. Pytania otwarte do właściciela (decyzje)

**Pieniądze i infrastruktura**
1. Czy akceptujemy **stały egress w UE** (VPS/proxy, kilka–kilkadziesiąt EUR/mies.)? Wpływa na FR (limit per IP/ASN), ARES, ewentualne DE.
2. **Budżet na źródła płatne:** BE (0,025 EUR/zapytanie), NL (taryfa KVK nieznana), OpenRegister/handelsregister.ai dla DE? Domyślna rekomendacja: **nie w Falach 0–2**.
3. **Polityka cenowa dla tier P** (≥ $0.06–0.08) lub rezygnacja z BE/NL do czasu bulk/HVD.
4. Czy dodać **podpisywanie odpowiedzi** (Ed25519) jako odpowiedź na funkcję konkurenta (Sirenic)?

**Prawo**
5. **Opinia prawna** (jeden zakres: RODO UE + UK GDPR + licencje): budżet i termin (rekomendacja: przed Falą 2, najlepiej przed Falą 1 dla UK/FR). Kluczowe pytania: art. 14 dla oficerów (UK/FR/CZ/NO), przedstawiciel w UK, sublicencja w AT, licencja RNE/DINUM, odsprzedaż danych SE/DK.
6. **Podmiot prawny i administrator danych** — z doc 01 nadal blokujące: nazwa, adres w UE, kontakt `privacy@…`.
7. Czy w Etapie 2 w ogóle zwracamy **dane osób fizycznych (officers)** z UK/FR/CZ/NO? Rekomendacja: domyślnie **nie**, tylko za `include=officers` z `purpose=` i logiem.

**Priorytety produktowe**
8. **UK i NO/CH** (poza UE) w zakresie „Europa”? Rekomendacja: tak (UK to największy otwarty rynek w Europie).
9. **Niemcy**: czy czekamy na HVD, składamy wniosek o whitelist IP, czy szukamy partnera? (największa luka rynkowa).
10. **Własne indeksy nazw** (D1/R2, z bulk Sirene/PRH/NO/CZ) dla szybkiego `search` — odstępstwo od „czystego query-time”; dopuszczalne dla podmiotów prawnych?
11. **Nazewnictwo i dystrybucja:** jedna usługa „EU Company Data” czy osobne wpisy per kraj w Bazaar? (rekomendacja: A + B z sekcji 3.2).
12. **Tłumaczenia not prawnych** (FR/DE/…): wystarczy EN + PL?
13. Czy Ukraina (EDR) wchodzi w zakres?
14. Kto zajmie się **administracją wniosków** (AT, EE, SE, DK, IE, CH, DINUM, BfJ) w Fali 0 — to ścieżka krytyczna czasowo.

---

## 8. Źródła

> Wszystkie URL-e poniżej pojawiły się w wynikach wyszukiwania w tej sesji; **żadnej strony rządowej nie otwierałem bezpośrednio** (brak dostępu z środowiska). Pozycje oznaczone „(nie otwarte)” znam z wiedzy ogólnej i nie były sprawdzane.

**Dokumenty wewnętrzne**
- `/home/user/piotrbugaj-tech.github.io/x402-company-data/src/schema/company.ts`
- `/home/user/piotrbugaj-tech.github.io/x402-company-data/docs/research/01-licencje-i-limity.md`
- `/home/user/piotrbugaj-tech.github.io/x402-company-data/docs/research/02-api-zrodel.md`
- `/home/user/piotrbugaj-tech.github.io/x402-company-data/docs/research/03-x402-i-discovery.md`

**UE / globalnie**
- Rozporządzenie wykonawcze (UE) 2023/138 (HVD): https://eur-lex.europa.eu/eli/reg_impl/2023/138/oj
- e-Justice „Find a company” (BRIS): https://e-justice.europa.eu/topics/registers-business-insolvency-land/business-registers-search-company-eu/general-information-find-company_en
- VIES: https://ec.europa.eu/taxation_customs/vies/ ; disclaimer: https://ec.europa.eu/taxation_customs/vies/disclaimer.html
- GLEIF API (nie otwarte): https://api.gleif.org/api/v1/ ; opisy wtórne: https://jentic.com/apis/gleif , https://mcp.so/servers/gleif-mcp-server
- Dyrektywa 2019/1024: https://eur-lex.europa.eu/eli/dir/2019/1024/oj (nie otwarte)

**Francja**
- API Recherche d'entreprises (dok.): https://recherche-entreprises.api.gouv.fr/docs/
- Strona API na data.gouv.fr: https://www.data.gouv.fr/dataservices/api-recherche-dentreprises
- Repozytorium search-api (otwarte przez GitHub raw): https://github.com/annuaire-entreprises-data-gouv-fr/search-api
- Annuaire des Entreprises — API: https://annuaire-entreprises.data.gouv.fr/donnees/api-entreprises
- INSEE — Sirene Open Data (aktualności 06.2026): https://www.insee.fr/fr/information/9019311 ; https://www.insee.fr/fr/information/3587074
- Base Sirene na data.gouv.fr: https://www.data.gouv.fr/datasets/base-sirene-des-entreprises-et-de-leurs-etablissements-siren-siret/informations
- Licence Ouverte 2.0: https://www.data.gouv.fr/pages/legal/licences/etalab-2.0
- INPI — API i FTP: https://www.inpi.fr/ressources/propriete-intellectuelle/acces-aux-api-et-ftp ; licencja RNE: https://inpi.fr/sites/default/files/Licence données RNE_2024_0.pdf
- Niediffusion EI: https://www.justice.fr/fiche/rendre-donnees-entreprise-non-diffusibles-entreprise-individuelle-micro-entreprise-publiquement

**Wielka Brytania**
- Rate limiting: https://developer-specs.company-information.service.gov.uk/guides/rateLimiting
- Developer guidelines: https://developer.company-information.service.gov.uk/developer-guidelines
- Forum CH (licencje, limity): https://forum.companieshouse.gov.uk/t/companies-house-api-limits/8626 ; https://forum.companieshouse.gov.uk/t/commercial-questions/4080 ; https://forum.companieshouse.gov.uk/t/is-data-provided-under-the-ocs/4513
- Weryfikacja tożsamości (zmiany API): https://forum.companieshouse.gov.uk/t/officers-and-persons-with-significant-control-resource-specification-update/12087 ; https://www.goqdos.com/news/companies-house-changes-in-2026

**Niemcy**
- bundesAPI/handelsregister (limity i uwagi prawne): https://github.com/bundesAPI/handelsregister
- HRV § 52: https://www.gesetze-im-internet.de/hdlregvfg/__52.html
- IFG ws. HVD Unternehmensregister: https://fragdenstaat.de/anfrage/antrag-nach-ss-1-informationsfreiheitsgesetz-ifg-umsetzung-von-ss-9-dng-vo-eu-2023-138-fuer-das-unternehmensregister/
- OffeneRegister: https://offeneregister.de/ ; OpenRegister docs: https://docs.openregister.de/sources/handelsregister.md ; handelsregister.ai: https://handelsregister.ai/en/blog/firmendaten-per-api ; Handelsregister portal PDF: https://www.handelsregister.de/rp_web/div/info-lang/EN_Registerportal.pdf

**Austria**
- JustizOnline — reuse (IWG): https://justizonline.gv.at/jop/web/iwg
- BMJ — Weiterverwendung: https://www.bmj.gv.at/service/weiterverwendung-von-informationen.html
- Umowa IWG Firmenbuch (VII.2024): https://bmj.gv.at/dam/jcr:9dbdf2de-70d6-46b9-b5c1-c5e1e4e15ce6/iwg-vereinbarung_firmenbuch_Stand%20Juli%202024.pdf

**Holandia / Belgia**
- KVK Open Dataset API: https://developers.kvk.nl/documentation/open-dataset-basis-bedrijfsgegevens-api ; zbiór: https://data.overheid.nl/en/dataset/kvk-handelsregister-open-dataset-basis-bedrijfsgegevens
- KVK API (zamówienie, FAQ): https://www.kvk.nl/producten-bestellen/kvk-api/ ; https://developers.kvk.nl/faq/apis
- KBO — ponowne wykorzystanie i ceny: https://economie.fgov.be/en/themes/enterprises/crossroads-bank-enterprises/services-everyone/public-data-available-reuse ; open data: https://kbopub.economie.fgov.be/kbo-open-data

**Czechy / Słowacja**
- ARES — MF ČR: https://mf.gov.cz/cs/ministerstvo/informacni-systemy/ares--administrativni-registr-ekonomicky
- Katalog služeb (v08, 2023): https://mf.gov.cz/assets/attachments/2023-08-01_ARES-Technicka-dokumentace-Katalog-verejnych-sluzeb_v08.pdf ; wersja EN: https://www.mfcr.cz/assets/attachments/2024-02-16_ARES-Technical-documentation-Catalog-of-public-services.pdf
- Lupa.cz o ARES i otwartych danych: https://www.lupa.cz/clanky/ares-jako-otevrena-data-ministerstvo-financi-slo-cestou-nejmensiho-odporu/
- RPO (SK): https://docs.topograph.co/essentials/slovakia ; https://mirri.gov.sk/wp-content/uploads/2023/09/SU-SR-RPO-005.pdf ; https://mcp.so/servers/sk-registers-mcp

**Kraje bałtyckie**
- Estonia — open data: https://abiinfo.rik.ee/en/e-business-register-queries/open-data-e-business-register ; bezpłatny dostęp: https://abiinfo.rik.ee/en/uudised/e-business-register-data-now-available-everyone-free-charge ; API: https://avaandmed.ariregister.rik.ee/en/single-query
- Łotwa: https://data.gov.lv/dati/eng/dataset/uz ; https://www.ur.gov.lv/en
- Litwa (opis wtórny): https://lemreveal.com/how-to/is-registry-free/lithuania

**Nordycy**
- Norwegia: https://www.brreg.no/?p=40812 ; https://data.norge.no/en/datasets/68d08f28-a16d-4fab-a953-ed4ab08ce2e2/central-coordinating-register-for-legal-entities ; dok. API: https://data.brreg.no/enhetsregisteret/api/docs/index.html (nie otwarte)
- Finlandia: https://avoindata.prh.fi/en ; https://prh.fi/en/asiakastiedotteet/2024/open-data-revamped.html ; https://prh.fi/en/asiakastiedotteet/2025/open-data-interface.html ; https://avoindata.fi/data/en/dataset/prh-avoin-data ; https://scoris.eu/blog/finnish-company-data-prh/
- Szwecja: https://bolagsverket.se/apierochoppnadata/hamtaforetagsinformation/vardefulladatamangder.5294.html ; https://bolagsverket.se/apierochoppnadata/nyheterochreleaser/2025/vardefulladatamangderlanserasden3februarimerdataforsammakostnad.5504.html ; SCB: https://www.scb.se/vara-tjanster/bestall-data-och-statistik/foretagsregistret/vardefulla-datamangder--grundlaggande-foretagsinformation/ ; licencje (wtórnie): https://tic.io/oppna-data ; auth (biblioteka): https://repo.hex.pm/preview/bolagsverket_ex/0.1.0/guides/authentication.md
- Dania: https://erhvervsstyrelsen.dk/hent-oplysninger-fra-cvr ; https://erhvervsstyrelsen.dk/kom-godt-igang-med-elasticSearch ; https://erhvervsstyrelsen.dk/det-centrale-virksomhedsregister-cvr

**Pozostałe**
- Irlandia (CRO): https://www.cro.ie/Services/Access-to-CRO-Data ; https://cro.ie/services-and-help/cro-support-services/
- Hiszpania: https://datos.gob.es/es/aplicaciones/openmercantil ; https://www.kyckr.com/blog/spain-business-registry-search
- Włochy: https://zephira.ai/italian-company-registry-data-how-to-search-the-registro-imprese-in-2026/ ; https://www.kyckr.com/blog/the-italian-business-register-2025-update
- Portugalia: https://eportugal.gov.pt/en/servicos/pedir-a-certidao-permanente-do-registo-comercial
- Szwajcaria (Zefix): https://companydata.com/zefix-api/ (wtórne) ; https://www.zefix.admin.ch (nie otwarte)
- Ukraina: https://data.gov.ua (zasady otwartych danych; konkretny zbiór EDR nie potwierdzony)

**Agregatory i konkurencja**
- OpenCorporates — warunki i cennik: https://opencorporates.com/terms-of-use-2/ ; https://opencorporates.com/pricing/
- North Data — AGB/API: https://northdata.de/_agb ; https://github.com/northdata/api/
- Sirenic (x402): https://www.producthunt.com/products/sirenic ; https://mcpservers.org/servers/sirenic-eu/sirenic-examples
