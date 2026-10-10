# Wdrożenie krok po kroku

Kolejność: testnet (Base Sepolia, bez prawdziwych pieniędzy), potem mainnet (Base), potem rejestracja w katalogach. Komendy uruchamiasz w `x402-company-data/`.

## 0. Decyzje i konta po Twojej stronie

- [ ] **Nazwa usługi i domena.** Np. `api.<twoja-domena>`. Potrzebne https na własnej domenie, bo katalogi odrzucają `*.workers.dev`. Nazwę wyświetlaną zmienisz w `SERVICE_NAME` w `src/products.ts`.
- [ ] **Portfel odbiorczy `PAY_TO`** (adres EVM na Base). Najlepiej świeży, tylko do przychodów. Klucza prywatnego **nie** dajesz Workerowi.
- [ ] **Konto Cloudflare.** Na start wystarczy plan Free; Paid ($5/mies.) przy większym ruchu.
- [ ] **Klucz produkcyjny GUS REGON.** E-mail do `regon_bir@stat.gov.pl`. Zapytaj, czy klucz jest wiązany z IP: Workers nie mają stałego IP.
- [ ] (Opcjonalnie) **token CEIDG.** Konto na biznes.gov.pl, potem dane.biznes.gov.pl, sekcja „Dane po API”. Przeczytaj i zarchiwizuj warunki.
- [ ] **Klucz CDP** (Secret API key, Ed25519) z portalu Coinbase Developer Platform, potrzebny dopiero na mainnet.
- [ ] **Administrator danych** (firma/JDG, adres, e-mail ds. prywatności) do noty RODO pod `/legal`.
- [ ] **Decyzja RODO dla JDG.** Domyślnie `NATURAL_PERSONS=minimal`; `full` tylko po konsultacji prawnej (zob. `DECISIONS.md`).

## 1. Zasoby Cloudflare

```bash
npx wrangler login
npx wrangler kv namespace create CACHE              # wklej id do wrangler.jsonc → kv_namespaces
npx wrangler d1 create company-index                # wklej database_id do wrangler.jsonc → d1_databases
npx wrangler d1 migrations apply company-index --remote
```

Bindingi `ratelimits` mają stałe `namespace_id` (40201, 40202). Jeśli kolidują z innymi Workerami na koncie, zmień je na unikalne.

## 2. Konfiguracja testnetu

W `wrangler.jsonc` → `vars`:

```jsonc
"PAY_TO": "0xTwójAdres",
"NETWORK": "eip155:84532",                       // Base Sepolia
"FACILITATOR_URL": "https://x402.org/facilitator",
"PUBLIC_BASE_URL": "https://api.twoja-domena.pl",
"REGON_ENV": "prod",                             // "test" = publiczne dane testowe GUS
"CONTACT_EMAIL": "kontakt@twoja-domena.pl",
"OPERATOR_NAME": "Nazwa, adres, NIP",
"PRIVACY_CONTACT": "privacy@twoja-domena.pl"
```

Sekrety:

```bash
npx wrangler secret put REGON_API_KEY
npx wrangler secret put CEIDG_API_TOKEN          # opcjonalnie
```

Wdrożenie i domena: `npx wrangler deploy`, potem w panelu Cloudflare: Workers → x402-company-data → Settings → Domains → Add custom domain.

## 3. Sprawdzenie testnetu

```bash
curl -s https://api.twoja-domena.pl/health | jq      # ok/ready + checks (bez sekretów)
curl -si "https://api.twoja-domena.pl/pl/company/verify?nip=7740001454" | head -20   # 402 + PAYMENT-REQUIRED
```

**Żywe wywołania źródeł.** Sandbox, w którym powstał kod, nie miał do nich dostępu. Sprawdź każde źródło jednym zapytaniem:
- REGON: `verify`.
- KRS: `company?krs=28860`.
- CEIDG: `company` dla NIP-u JDG.
- Biała Lista i VIES: `company?...&include=vat` oraz `vat/account-check`.

Rozbieżności z fixture'ami zgłoś: parsery są tolerancyjne, ale nazwy pól warto potwierdzić (lista otwartych punktów w `docs/research/02-api-zrodel.md`).

Płatność testowa: jednorazowy klucz plus testowe USDC z https://faucet.circle.com (sieć Base Sepolia, ETH niepotrzebne).

```bash
BUYER_PRIVATE_KEY=0x… node scripts/pay-test.mjs "https://api.twoja-domena.pl/pl/company/verify?nip=7740001454"
BUYER_PRIVATE_KEY=0x… node scripts/pay-test.mjs "https://api.twoja-domena.pl/pl/company/verify/batch" '{"nip":["7740001454","5250007738"]}'
```

Oczekiwane: `paid -> 200`, `receipt.success: true`, transakcja widoczna na https://sepolia.basescan.org.

## 4. Mainnet (Base)

1. Sekrety CDP:
   ```bash
   npx wrangler secret put CDP_API_KEY_ID
   npx wrangler secret put CDP_API_KEY_SECRET
   ```
   Format: base64 64 bajty (Ed25519) albo PEM (ES256).
2. W `vars` ustaw `"NETWORK": "eip155:8453"` i `"FACILITATOR_URL": "https://api.cdp.coinbase.com/platform/v2/x402"`, potem `npx wrangler deploy`. Facilitator x402.org obsługuje tylko testnety; `/health` pokaże `facilitatorMatchesNetwork: false`, jeśli o tym zapomnisz.
3. Walidacja CDP (darmowa, bez klucza):
   ```bash
   curl -s -X POST https://api.cdp.coinbase.com/platform/v2/x402/validate -H 'content-type: application/json' \
     -d '{"url":"https://api.twoja-domena.pl/pl/company/verify","method":"GET"}'
   ```
   Oczekiwane: `valid: true`, `simulation.outcome: "accepted"`. Powtórz dla każdego endpointu (batch: `"method":"POST"`).
4. **Jedna prawdziwa płatność** na każdy endpoint (`scripts/pay-test.mjs` z portfela z kilkoma USDC na Base). Pierwszy settlement przez CDP z rozszerzeniem `bazaar` dodaje endpoint do **CDP Bazaar / agentic.market**; z niego czerpią Tanod, x402scan i 402index.
5. Sprawdzenie listingu: `curl -s "https://api.cdp.coinbase.com/platform/v2/x402/discovery/merchant?payTo=<PAY_TO>"`.
6. Keepalive, żeby listing nie wygasł po ok. 30 dniach:
   ```bash
   npx wrangler secret put KEEPALIVE_PRIVATE_KEY
   ```
   Użyj osobnego portfela z ok. $1 USDC. Cron w `wrangler.jsonc` co poniedziałek robi jedno płatne wywołanie `verify`.

## 5. Rejestracja w katalogach (po mainnecie)

- [ ] **CDP Bazaar / agentic.market.** Automatycznie po kroku 4.4. Wyróżniona „kuratorowana” sekcja agentic.market jest redakcyjna: wymaga ok. 30 dni ruchu i ≥ 99% dostępności.
- [ ] **x402scan.** https://www.x402scan.com/resources/register, „Add Server” z `https://api.twoja-domena.pl`. Czyta `/openapi.json` (`x-payment-info`), potem `/.well-known/x402`. Lokalna walidacja: `npx -y @agentcash/discovery api.twoja-domena.pl -v`.
- [ ] **402index.io.** Rejestracja:
  ```bash
  for p in /pl/company/verify /pl/company /pl/company/search /pl/vat/account-check /pl/company/verify/batch; do
    curl -s -X POST https://402index.io/api/v1/register -H 'content-type: application/json' -d "{\"url\":\"https://api.twoja-domena.pl$p\"}"; done
  ```
  Przejęcie listingu: `POST /api/v1/claim`, potem ustaw sekret `INDEX402_VERIFY_TOKEN` (serwujemy go pod `/.well-known/402index-verify.txt`), potem `POST /api/v1/claim/verify`.
- [ ] **x402-list.com.** Formularz albo `POST /api/v1/submit` (własna domena, recenzja ręczna, 1 zgłoszenie na e-mail na 7 dni).
- [ ] **x402.org/ecosystem.** Procesu nie udało się potwierdzić; zapytaj na Discordzie lub Slacku x402 albo otwórz issue w `x402-foundation/x402`.
- [ ] Później: endpoint MCP plus rejestr MCP (`mcp-publisher`), osobny kanał dystrybucji.

Sygnały rankingowe Bazaar to unikalni płacący, świeżość wywołań, kompletność metadanych i stabilne 402. Unikaj przerw: 5xx na sondach obniża pozycję.

## 6. Operacje

- **Sprzeciw RODO (art. 21).** Zablokuj NIP:
  ```bash
  npx wrangler kv key put --binding CACHE "optout:nip:<NIP>" "data/zgłoszenie" --remote
  ```
  Endpointy zwracają wtedy 451 bez opłaty.
- **Logi.** `npx wrangler tail`; observability jest włączone w `wrangler.jsonc`.
- **Ceny.** Zmieniasz je w `src/products.ts` (jedno miejsce); OpenAPI, llms.txt i 402 aktualizują się same.
- **Przychody.** Saldo USDC na `PAY_TO` (basescan) oraz panel x402scan dla Twojego adresu.
