import { SERVICE_NAME } from "../products";
import type { DiscoveryContext } from "./openapi";

// Drafts from docs/research/01-licencje-i-limity.md §9–10.
// Placeholders [..] must be filled by the operator (and reviewed by a lawyer) before production.

export interface LegalContext extends DiscoveryContext {
  operator?: string;
  privacyContact?: string;
}

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export function legalHtml(ctx: LegalContext): string {
  const op = esc(ctx.operator || "[operator legal name, address, tax id]");
  const contact = esc(ctx.privacyContact || "[privacy contact e-mail]");
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(SERVICE_NAME)} — sources, terms, privacy</title>
<style>:root{--bg:#fff;--fg:#1a1a1a;--muted:#5c5c5c}@media (prefers-color-scheme:dark){:root{--bg:#121212;--fg:#ececec;--muted:#a0a0a0}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,sans-serif}main{max-width:820px;margin:0 auto;padding:32px 16px}h2{margin-top:2em}small,.m{color:var(--muted)}</style></head><body><main>
<h1>Sources, terms &amp; privacy</h1>

<h2 id="sources">Data sources</h2>
<ul>
<li><b>REGON</b> — Baza Internetowa REGON (BIR1.1), Główny Urząd Statystyczny.</li>
<li><b>KRS</b> — Krajowy Rejestr Sądowy, API Rejestrów Sądowych (Open API), Ministerstwo Sprawiedliwości. Personal data of board members stays in the masked form published by the source.</li>
<li><b>CEIDG</b> — Centralna Ewidencja i Informacja o Działalności Gospodarczej (API v3), when enabled.</li>
</ul>
<p>Re-use of public sector information under the Polish Act of 11 August 2021 on open data and the re-use of public sector information (Dz.U. 2023 poz. 1524). Every response names its sources, the time of retrieval and whether it came from our cache. Data has been <b>processed</b> (retrieved, normalised, merged). It is <b>not an official extract</b> (odpis), certificate or document, it is not published on behalf of or endorsed by the source institutions, and they bear no liability for the processed data.</p>
<p lang="pl" class="m">Dane przetworzone (pobrane, znormalizowane i scalone) z publicznych rejestrów. Nie stanowią odpisu z KRS, zaświadczenia ani dokumentu urzędowego i nie są publikowane w imieniu ani za zgodą wskazanych instytucji. Instytucje źródłowe nie ponoszą odpowiedzialności za dane po przetworzeniu.</p>

<h2 id="terms">Terms of use</h2>
<ul>
<li>Permitted use: counterparty verification, KYB, invoicing and tax due diligence, fraud prevention.</li>
<li>Not permitted: direct marketing, profiling of natural persons, building or reselling bulk copies of the registers.</li>
<li>Results are provided as-is on a best-effort basis. For legally binding purposes obtain an official extract from the register.</li>
<li>Payment is per call via x402. Invalid input (400), rate limiting (429), withheld data (451) and register outages (503) are not charged.</li>
</ul>

<h2 id="privacy">Privacy notice (Art. 14 GDPR)</h2>
<ol>
<li><b>Controller:</b> ${op}. Privacy contact: ${contact}.</li>
<li><b>Sources:</b> public registers listed above.</li>
<li><b>Categories of data:</b> business identification data of sole traders (tax id/NIP, REGON, business status, activity codes; name and business address only where disclosed by this service's policy), and functions (with masked names) of board members as published by the KRS Open API. We do not process PESEL numbers or home addresses.</li>
<li><b>Purposes and legal basis:</b> on-demand counterparty verification, safety of commercial transactions, tax due diligence and fraud prevention — Art. 6(1)(f) GDPR (legitimate interests of the controller and recipients).</li>
<li><b>Recipients:</b> businesses and their automated systems (AI agents) that paid for a lookup of a specific entity; our infrastructure provider acting as processor (Cloudflare, Inc.).</li>
<li><b>Transfers outside the EEA:</b> the infrastructure provider may process data in the USA under the EU–US Data Privacy Framework or Standard Contractual Clauses.</li>
<li><b>Retention:</b> no database is built. Data is fetched at query time and cached for at most 72 hours; technical logs without data content are kept up to 30 days.</li>
<li><b>Your rights:</b> access, rectification (errors in a register must be corrected with the register authority), erasure, restriction and the right to object (Art. 21). If your objection is upheld we add your identifier to an exclusion list and stop disclosing it. You may complain to the Prezes Urzędu Ochrony Danych Osobowych, ul. Stawki 2, 00-193 Warszawa.</li>
<li><b>Automated decisions:</b> none are made about you based solely on automated processing.</li>
</ol>
<p class="m"><small>${esc(SERVICE_NAME)} · <a href="${esc(ctx.baseUrl)}/">${esc(ctx.baseUrl)}</a></small></p>
</main></body></html>`;
}
