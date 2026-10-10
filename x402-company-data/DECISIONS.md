# Dziennik decyzji

Krótko: co zrobiono, dlaczego i co odłożono. Najnowsze wpisy na górze.

## 2026-10-10 — Etap 1 (Polska), sesja startowa

### Architektura i stack
- **Własny Worker z `@x402/hono` v2.28, nie `x402-proxy-template` Cloudflare.** Szablon to proxy przed originem, oparty na starym `x402-hono` v1: nie ma metadanych Bazaar ani ceny dynamicznej. My potrzebujemy obu (discovery, batch). Kod: `src/payments.ts`.
- **Jedna definicja produktów** (`src/products.ts`). Z niej powstają konfiguracja tras x402 (z rozszerzeniem Bazaar), `openapi.json`, `llms.txt`, `/.well-known/x402` i strona `/`. Ceny i opisy zmienia się w jednym miejscu.
- **Klient REGON tylko na `fetch`, bez biblioteki SOAP.** BIR1.1 to SOAP 1.2 i MTOM. Wynik wyciągamy regexem z `<…Result>` i parsujemy `fast-xml-parser`. Biblioteki Node SOAP nie działają na Workers.
- **Facilitator CDP przez własny JWT (WebCrypto, Ed25519/ES256)** zamiast `@coinbase/x402`. Oficjalny helper działa na Workers, ale ciągnie `@coinbase/cdp-sdk` (axios, Solana). Nasz kod ma 80 linii, a test potwierdza, że podpisy weryfikują się kryptograficznie.
- **Weryfikacja w prawdziwym runtime.** `npm run smoke` uruchamia `wrangler dev` (workerd) z lokalnym fałszywym facilitatorem i REGON i przechodzi pełny płatny cykl.

### Płatności i uczciwość wobec agenta
- **Walidacja przed płatnością.** Błędny NIP/REGON/KRS (zła suma kontrolna) dostaje darmowe 400.
- **Gołe żądanie bez parametrów dostaje 402.** Sondy katalogów (CDP `/validate`, x402scan, 402index) muszą zobaczyć 402, inaczej endpoint nie zostanie zindeksowany.
- **Status ≥ 400 = brak opłaty.** Potwierdzone w źródle `@x402/hono`: settlement jest anulowany. Dlatego:
  - awaria rejestru → 503;
  - profil lub wyszukiwanie bez wyniku → 404 (darmowe);
  - sprzeciw RODO → 451;
  - limit IP → 429.
- **`verify` dla nieistniejącego NIP jest płatne.** Odpowiedź „nie istnieje” jest tu produktem.
- **Batch: cena dynamiczna** = $0.003 × liczba poprawnych identyfikatorów, minimum $0.01. Liczona z body przed płatnością; błędne identyfikatory nie są liczone.
- **Fail-closed.** Bez `PAY_TO` płatne trasy zwracają 503 i nigdy nie oddają danych za darmo.

### Dane i prawo (na podstawie `docs/research/01-licencje-i-limity.md`)
- **Model zgodny z licencjami.** Sprzedajemy pobranie, normalizację i scalenie danych w momencie zapytania, a nie bazę. Każda odpowiedź ma źródła, czas pobrania, flagę cache i notę „nie jest odpisem”. Krótki cache (12–24 h). Nie ma eksportu masowego.
- **KRS: tylko Open API** (`OdpisAktualny`). Nigdy Full API ani wyszukiwarka eKRS z CAPTCHA, bo od 29.11.2025 grozi za to art. 60a ustawy o KRS. Imiona i nazwiska zarządu zostają zamaskowane przez źródło, my ich nie odkrywamy.
- **JDG (osoby fizyczne): tryb `NATURAL_PERSONS=minimal` domyślnie.**
  - Zwracamy istnienie, status, identyfikatory, PKD i miasto. Nie zwracamy imienia i nazwiska ani adresu ulicy.
  - Zamiast nazwy oferujemy `?name=`, które zwraca dopasowanie (`match`/`partial`/`mismatch`).
  - Powód: precedens Bisnode (UODO 2019, prawomocnie NSA 2023) dotyczący art. 14 RODO. Przełączenie na `full` to **decyzja właściciela po konsultacji prawnej**.
- **Wyszukiwanie po nazwie tylko dla osób prawnych.** KRS i GUS nie mają wyszukiwarki po nazwie, a wyszukiwanie osób fizycznych po nazwisku odpada (RODO). Indeks D1/FTS5 budujemy z podmiotów, które serwis i tak rozwiązuje. Spółki cywilne pomijamy, bo ich nazwy to zwykle nazwiska wspólników.
- **Opt-out (art. 21 RODO):** klucz `optout:{nip|regon|krs}:{wartość}` w KV oznacza darmowe 451.

### Wzbogacenia (dodane w tej sesji)
- **CEIDG.** Działa tylko z tokenem (`CEIDG_API_TOKEN`).
  - Dla JDG to rejestr źródłowy: status z CEIDG ma pierwszeństwo przed REGON, który bywa opóźniony. CEIDG służy też za fallback, gdy REGON leży.
  - Lokalny strażnik limitu: binding `UPSTREAM_LIMITER`, 8 zapytań/min. Limit CEIDG to 1000/h oraz 50 na 3 min.
  - W trybie `minimal` imię, nazwisko i ulica i tak nie są zwracane.
- **Biała Lista VAT.**
  - `include=vat` w profilu zwraca status VAT na dziś i liczbę rachunków. Same numery rachunków nie są zwracane.
  - Osobny płatny endpoint `/pl/vat/account-check` ($0.01) sprawdza, czy rachunek jest przypisany do NIP. W cache trzymamy tylko hash NIP+rachunek.
  - Limity MF (search 100/dzień, check 5000/dzień) są **liczone per IP**, a Workers mają współdzielony egress.
  - Przy blokadzie (WL-191) serwis zwraca 503 bez opłaty do północy. Jeśli ruch urośnie, potrzebny będzie **stały egress IP**, czyli decyzja kosztowa.
- **VIES.** W `include=vat` dochodzi `euVatValid`. Niedostępność systemu krajowego daje `null`, a nie fałszywe „invalid”.

### Odłożone (świadomie)
- **Masowe zasilenie indeksu wyszukiwania** (np. przejście po KRS przez Biuletyn). Wymaga decyzji prawnej i operacyjnej (obciążenie API MS). Na razie indeks rośnie organicznie.
- **Endpoint MCP i A2A AgentCard.** Mają sens po starcie REST. Rejestr MCP to kolejny kanał dystrybucji.
- **Drugi facilitator (PayAI, Solana).** `accepts` przyjmuje tablicę, więc można go dodać później bez zmian w API.
- **Etap 2 (UE).** Jest tylko plan (`docs/ETAP2-roadmap-UE.md`), implementacja czeka na potwierdzenie.

### Ograniczenia tej sesji
- Sandbox nie miał dostępu do `*.gov.pl`, `ec.europa.eu`, `x402.org` ani `coinbase.com` (polityka sieci środowiska).
- Dlatego klienci źródeł są testowani na fixture'ach. Tylko odpowiedź `Zaloguj` REGON jest dosłowna (z repo GusApi), reszta to rekonstrukcje z dokumentacji, oznaczone w plikach.
- **Przed produkcją trzeba wykonać jedno żywe wywołanie każdego źródła** (lista w `docs/research/02-api-zrodel.md`, sekcja otwartych punktów).
