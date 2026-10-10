# x402-company-data: dane o polskich firmach dla agentów AI (x402)

Serwis HTTP (Cloudflare Worker) sprzedaje agentom AI dane z oficjalnych polskich rejestrów (GUS REGON, KRS, CEIDG, Biała Lista VAT, VIES). Płatność idzie przez **x402**: agent wywołuje endpoint, dostaje `402` z ceną, płaci w USDC na Base i ponawia żądanie. Nie ma kont, kluczy API ani subskrypcji.

> Status: **Etap 1 (Polska) gotowy do wdrożenia na testnet.** Testy na fixture'ach przechodzą (131), pełny płatny cykl działa w lokalnym runtime workerd. Brakuje kroków właściciela (domena, portfel, klucze) i jednego żywego wywołania każdego rejestru: sandbox, w którym to powstało, nie miał do nich dostępu. Szczegóły w [docs/DEPLOY.md](docs/DEPLOY.md).

## Endpointy i ceny

| Endpoint | Cena (USDC) | Kiedy agent tego używa |
|---|---|---|
| `GET /pl/company/verify?nip=` (lub `regon=` / `krs=`), opcjonalnie `&name=` | $0.005 | Czy firma istnieje i jest aktywna (np. przed opłaceniem faktury). |
| `GET /pl/company?nip=…&include=representation,vat` | $0.02 | Pełny, znormalizowany profil (REGON + KRS + CEIDG), opcjonalnie zarząd i VAT. |
| `GET /pl/company/search?name=&city=` | $0.01 | Znam tylko nazwę i szukam NIP/KRS (wyłącznie osoby prawne). |
| `GET /pl/vat/account-check?nip=&account=` | $0.01 | Czy rachunek jest na Białej Liście dla tego NIP dzisiaj. |
| `POST /pl/company/verify/batch` `{"nip":[…]}` | $0.003 × N (min $0.01), N ≤ 50 | Weryfikacja listy kontrahentów jednym wywołaniem. |

Darmowe: `/` (HTML lub JSON), `/openapi.json`, `/llms.txt`, `/.well-known/x402`, `/legal`, `/health`, `/icon.svg`.

**Zasady rozliczeń.** Wynikają z tego, że x402 anuluje settlement, gdy handler zwróci status ≥ 400. Agent **nie płaci**, gdy dostaje:
- 400: błędny identyfikator lub suma kontrolna (walidacja odbywa się przed płatnością);
- 404: profil lub wyszukiwanie bez wyniku;
- 429: limit zapytań;
- 451: sprzeciw RODO;
- 503: rejestr niedostępny.

Wyjątek: `verify` z wynikiem „nie istnieje” jest płatny, bo to odpowiedź na pytanie. Żądanie bez parametrów dostaje `402`, bo tak katalogi (CDP Bazaar, x402scan) sprawdzają endpoint.

## Jak to działa

```
agent ──GET /pl/company?nip=…──▶ walidacja (400 free) ─▶ rate limit (429) ─▶ opt-out (451)
                                 ─▶ x402 middleware: brak płatności → 402 + PAYMENT-REQUIRED (+ metadane Bazaar)
agent ──(podpis EIP-3009, PAYMENT-SIGNATURE)──▶ facilitator /verify ─▶ handler:
        KV cache ─miss─▶ REGON (SOAP) ∥ KRS (JSON) ∥ CEIDG ∥ Biała Lista ∥ VIES ─▶ normalizacja ─▶ scalenie
        ─▶ status < 400 ? facilitator /settle (USDC → PAY_TO) : brak settlementu
        ─▶ indeks nazw (D1/FTS5, tylko osoby prawne) w tle
```

- Wspólny schemat: [`src/schema/company.ts`](src/schema/company.ts) (`CompanyProfile`, `VerifyResult`).
- Precedencja źródeł:
  - KRS rozstrzyga dla podmiotów w KRS (nazwa, forma, kapitał, likwidacja/upadłość).
  - CEIDG rozstrzyga dla JDG.
  - REGON to szkielet dla wszystkich (zawieszenie, PKD z opisami, adres).
  - Wygrywa najbardziej „surowy” status.
- Cache w KV:
  - REGON: 12 h; KRS i CEIDG: 24 h; PKD: 7 dni; „nie znaleziono”: 1 h.
  - Biała Lista: do północy czasu warszawskiego.
  - Każda odpowiedź mówi, czy pochodzi z cache, i podaje czas pobrania.
- Produkty (ceny, opisy, schematy) definiuje jedno źródło prawdy: [`src/products.ts`](src/products.ts). Z niego powstają trasy x402, OpenAPI, llms.txt i `/.well-known/x402`.

## Dane, licencje, RODO

- Analiza: [docs/research/01-licencje-i-limity.md](docs/research/01-licencje-i-limity.md).
  - Ponowne wykorzystanie jest dozwolone na podstawie ustawy o otwartych danych z 2021 r., pod warunkiem podania źródła i czasu pobrania oraz informacji o przetworzeniu.
  - Sprzedajemy przetworzenie danych w momencie zapytania, a nie bazę.
- **JDG (osoby fizyczne).** Domyślnie `NATURAL_PERSONS=minimal`: nie zwracamy imienia i nazwiska ani adresu ulicy, w zamian działa `?name=` (dopasowanie). Przełączenie na `full` to decyzja właściciela po konsultacji prawnej (precedens Bisnode).
- **KRS.** Używamy tylko Open API; dane osób są zamaskowane przez źródło. Nie korzystamy z Full API ani wyszukiwarki eKRS (art. 60a ustawy o KRS).
- **Opt-out.** Klucz `optout:nip:<NIP>` w KV powoduje darmowe 451. Nota informacyjna (art. 14 RODO) jest pod `/legal`; do uzupełnienia są dane administratora.

## Uruchomienie lokalne i testy

```bash
cd x402-company-data
npm install
npm test            # 131 testów: x402 e2e z prawdziwym klientem podpisującym, fixture'y rejestrów, SQLite FTS5
npm run typecheck
npm run smoke       # prawdziwy runtime workerd + lokalny fałszywy facilitator i REGON: 402 → płatność → 200
npm run dev         # wrangler dev (REGON_ENV=test używa publicznego klucza testowego GUS)
```

Test płatny przeciw wdrożonemu Workerowi na Base Sepolia, z jednorazowego klucza z USDC z https://faucet.circle.com:

```bash
BUYER_PRIVATE_KEY=0x… node scripts/pay-test.mjs "https://<worker>/pl/company/verify?nip=7740001454"
```

## Koszty operacyjne (szacunek, 10.2026)

| Pozycja | Koszt | Uwagi |
|---|---|---|
| Cloudflare Workers Free | $0 | 100 tys. req/dzień, **10 ms CPU/req**; KV Free ma niski dzienny limit zapisów (ok. 1 tys./dzień, sprawdź cennik). Wystarczy na start. |
| Cloudflare Workers Paid | $5/mies. | 10 mln req i 30 mln ms CPU w cenie, potem $0.30 za mln req. Warto, gdy ruch przekroczy kilkaset unikalnych zapytań dziennie. |
| Domena | ok. $10–15/rok (.com) | Potrzebna: x402-list odrzuca `workers.dev`, a własna domena wzmacnia zaufanie. |
| Klucze API (REGON, KRS, CEIDG, MF, VIES) | $0 | Wszystkie bezpłatne. REGON i CEIDG wymagają wniosku. |
| Facilitator CDP | 1000 tx/mies. gratis, potem ok. $0.001/tx | Gaz płaci facilitator. Przy `verify` za $0.005 opłata to 20% ceny; przy profilu 5%. **Potwierdź w portalu CDP.** |
| Opcjonalnie: stały egress IP (VPS w UE) | ok. €4–5/mies. | Tylko jeśli GUS wiąże klucz z IP albo limit MF per IP zacznie przeszkadzać. |
| Portfel keepalive | ok. $1 USDC na ok. 4 lata | Cotygodniowe wywołanie za $0.005; środki wracają do `PAY_TO`, koszt to tylko opłata facilitatora. |

Próg rentowności przy planie $5: ok. 250 profili albo 1000 weryfikacji miesięcznie.

## Dokumenty

- [DECISIONS.md](DECISIONS.md): dziennik decyzji (co, dlaczego, co odłożone)
- [docs/DEPLOY.md](docs/DEPLOY.md): wdrożenie krok po kroku i rejestracja w katalogach x402
- [docs/research/](docs/research/): licencje i limity, specyfikacje API źródeł, ekosystem x402 i discovery
- [docs/ETAP2-roadmap-UE.md](docs/ETAP2-roadmap-UE.md): plan Etapu 2 (UE), tylko plan

> Uwaga: projekt leży w podkatalogu repo GitHub Pages (`piotrbugaj-tech.github.io`). Po zmergowaniu do `main` jego pliki byłyby serwowane statycznie pod piotrbugaj.com. Przed merge'em warto przenieść go do osobnego repozytorium.
