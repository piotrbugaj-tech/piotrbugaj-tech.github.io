// Single source of truth for paid endpoints: prices, descriptions and I/O
// schemas. Feeds the x402 route config (incl. Bazaar discovery metadata),
// openapi.json, llms.txt and /.well-known/x402.

export const SERVICE_NAME = "PL Company Data";
export const SERVICE_TAGS = ["kyb", "company-data", "poland", "vat", "registry"];

export interface Product {
  id: string;
  method: "GET" | "POST";
  path: string;
  /** Fixed USD price, e.g. "$0.005". Batch uses unitPrice × n instead. */
  price: string;
  unitPrice?: number;
  minPrice?: number;
  summary: string;
  description: string;
  queryParams?: Record<string, { type: string; description: string; required?: boolean; example?: string; enum?: string[] }>;
  bodySchema?: Record<string, unknown>;
  bodyExample?: Record<string, unknown>;
  outputExample: unknown;
}

const ID_PARAMS = {
  nip: { type: "string", description: "Polish tax id (NIP), 10 digits; separators and PL prefix allowed.", example: "7740001454" },
  regon: { type: "string", description: "REGON statistical number, 9 or 14 digits." },
  krs: { type: "string", description: "KRS court register number, up to 10 digits." },
} as const;

const SOURCE_EXAMPLE = {
  source: "REGON",
  name: "Baza Internetowa REGON (BIR1.1)",
  publisher: "Główny Urząd Statystyczny",
  url: "https://wyszukiwarkaregon.stat.gov.pl",
  retrievedAt: "2026-10-10T09:12:44.000Z",
  cached: true,
};

export const VERIFY_EXAMPLE = {
  schemaVersion: "1.0",
  query: { kind: "nip", value: "7740001454" },
  found: true,
  active: true,
  status: "active",
  name: "ORLEN SPÓŁKA AKCYJNA",
  identifiers: { nip: "7740001454", regon: "610188201", krs: "0000028860" },
  legalForm: "joint_stock_company",
  isNaturalPerson: false,
  endedAt: null,
  checkedAt: "2026-10-10T09:12:44.000Z",
  sources: [SOURCE_EXAMPLE],
};

export const PROFILE_EXAMPLE = {
  schemaVersion: "1.0",
  country: "PL",
  identifiers: { nip: "7740001454", regon: "610188201", krs: "0000028860" },
  name: "ORLEN SPÓŁKA AKCYJNA",
  legalForm: { normalized: "joint_stock_company", label: "SPÓŁKA AKCYJNA" },
  isNaturalPerson: false,
  status: { code: "active", active: true, suspendedSince: null, resumedAt: null, endedAt: null },
  dates: { registered: "2001-06-26", started: "1993-12-07" },
  address: {
    street: "ul. Chemików",
    buildingNumber: "7",
    unitNumber: null,
    postalCode: "09-411",
    city: "Płock",
    postOffice: "Płock",
    commune: "M. Płock",
    county: "Płock",
    voivodeship: "MAZOWIECKIE",
    country: "PL",
    formatted: "ul. Chemików 7, 09-411 Płock",
  },
  pkd: {
    primary: { code: "19.20.Z", description: "Wytwarzanie produktów rafinacji ropy naftowej", primary: true },
    all: [{ code: "19.20.Z", description: "Wytwarzanie produktów rafinacji ropy naftowej", primary: true }],
  },
  contact: { website: "www.orlen.pl", email: null },
  capital: { amount: 1451177561.25, currency: "PLN" },
  representation: null,
  registries: {
    regon: { type: "P", silo: "6" },
    krs: { register: "P", registeredAt: "2001-06-26", lastEntryAt: "2026-09-30" },
    ceidg: null,
  },
  sources: [SOURCE_EXAMPLE, { ...SOURCE_EXAMPLE, source: "KRS", name: "Krajowy Rejestr Sądowy — Open API", publisher: "Ministerstwo Sprawiedliwości", url: "https://api-krs.ms.gov.pl" }],
  retrievedAt: "2026-10-10T09:12:44.000Z",
  warnings: [],
};

export const PRODUCTS: Product[] = [
  {
    id: "verify",
    method: "GET",
    path: "/pl/company/verify",
    price: "$0.005",
    summary: "Does this Polish company exist and is it active?",
    description:
      "Use when you have a Polish NIP, REGON or KRS number and need to know if the business exists and is active (e.g. before paying an invoice or onboarding a supplier). Checks the official GUS REGON register: found, active, status (active/suspended/in_liquidation/in_bankruptcy/removed), name, identifiers; optional ?name= match. Invalid ids get a free 400.",
    queryParams: { ...ID_PARAMS },
    outputExample: VERIFY_EXAMPLE,
  },
  {
    id: "company",
    method: "GET",
    path: "/pl/company",
    price: "$0.02",
    summary: "Unified Polish company profile (REGON + KRS + CEIDG).",
    description:
      "Use when you need the full picture of a Polish company (KYB, due diligence, CRM enrichment). One normalised JSON merged from official registers (GUS REGON + KRS court register): name, legal form, status, address, PKD activity codes, dates, share capital, website; board roles and signing rules with include=representation. Not found = free 404.",
    queryParams: {
      ...ID_PARAMS,
      include: {
        type: "string",
        description: "Comma-separated extras: representation (KRS board roles + signing rules), vat (Polish VAT status from the MF white list + EU VAT validity from VIES).",
        example: "vat",
      },
    },
    outputExample: PROFILE_EXAMPLE,
  },
  {
    id: "search",
    method: "GET",
    path: "/pl/company/search",
    price: "$0.01",
    summary: "Find Polish companies by name.",
    description:
      "Use when you only know a Polish company's name and need its NIP/REGON/KRS. Returns up to 20 legal-entity candidates with identifiers, legal form, status and city; feed the ids into /pl/company or /pl/company/verify. No match = free 404.",
    queryParams: {
      name: { type: "string", description: "Company name or fragment (min. 3 characters).", required: true, example: "orlen" },
      city: { type: "string", description: "Optional city filter." },
      limit: { type: "integer", description: "Max results, 1-20 (default 10)." },
    },
    outputExample: {
      query: { name: "orlen", city: null },
      results: [
        { name: "ORLEN SPÓŁKA AKCYJNA", identifiers: { nip: "7740001454", regon: "610188201", krs: "0000028860" }, legalForm: "joint_stock_company", status: "active", city: "Płock", source: "KRS" },
      ],
      sources: [SOURCE_EXAMPLE],
    },
  },
  {
    id: "account-check",
    method: "GET",
    path: "/pl/vat/account-check",
    price: "$0.01",
    summary: "Is this bank account on the Polish VAT white list for this NIP?",
    description:
      "Use when an agent is about to pay a Polish invoice by bank transfer and must confirm the account belongs to the payee on the Ministry of Finance VAT white list (Biała Lista) today. Returns assigned true/false plus the MF request id. Invalid NIP/account checksums get a free 400.",
    queryParams: {
      nip: { type: "string", description: "Payee NIP (10 digits).", required: true, example: "7740001454" },
      account: { type: "string", description: "Polish bank account: 26-digit NRB or PL IBAN; spaces allowed.", required: true, example: "PL61109010140000071219812874" },
    },
    outputExample: {
      schemaVersion: "1.0",
      query: { nip: "7740001454", account: "PL61 **** 2874" },
      assigned: true,
      date: "2026-10-10",
      whiteListRequestId: "abc12-xyz34",
      whiteListRequestDateTime: "10-10-2026 11:58:05",
      sources: [{ source: "MF_WL", name: "Wykaz podatników VAT (Biała Lista) — API", publisher: "Ministerstwo Finansów / Szef KAS", url: "https://wl-api.mf.gov.pl", retrievedAt: "2026-10-10T09:58:05.000Z", cached: false }],
    },
  },
  {
    id: "batch-verify",
    method: "POST",
    path: "/pl/company/verify/batch",
    price: "$0.003 per identifier (min $0.01)",
    unitPrice: 0.003,
    minPrice: 0.01,
    summary: "Verify up to 50 Polish companies in one paid call.",
    description:
      "Use when you must check a list of Polish counterparties at once (invoice runs, supplier lists). Up to 50 NIP/REGON/KRS numbers per call, existence + status for each, $0.003 per valid identifier (min $0.01). Invalid ids are reported back and not charged.",
    bodySchema: {
      type: "object",
      properties: {
        nip: { type: "array", items: { type: "string" }, maxItems: 50 },
        regon: { type: "array", items: { type: "string" }, maxItems: 50 },
        krs: { type: "array", items: { type: "string" }, maxItems: 50 },
      },
      description: "At least one list; total identifiers 1-50.",
    },
    bodyExample: { nip: ["7740001454", "5250007738"] },
    outputExample: { count: 2, results: [VERIFY_EXAMPLE], invalid: [] },
  },
];

export const productById = (id: string) => PRODUCTS.find((p) => p.id === id)!;
