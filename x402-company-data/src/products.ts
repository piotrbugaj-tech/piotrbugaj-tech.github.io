// Single source of truth for paid endpoints: prices, descriptions and I/O
// schemas. Feeds the x402 route config (incl. Bazaar discovery metadata),
// openapi.json, llms.txt and /.well-known/x402.

export const SERVICE_NAME = "PL Company Data";
export const SERVICE_TAGS = ["kyb", "company-data", "poland", "business-registry", "vat"];

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
      "Fast existence + status check of a Polish business by NIP, REGON or KRS against the official GUS REGON register: found, active, status (active / suspended / in_liquidation / in_bankruptcy / removed), official name and identifiers. Ideal for counterparty / invoice / KYB pre-checks.",
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
      "Full normalised company profile merged from official Polish registers (GUS REGON, KRS court register, CEIDG sole-trader register): name, legal form, status, registered address, PKD activity codes, registration dates, share capital, website; management board on request (include=representation).",
    queryParams: {
      ...ID_PARAMS,
      include: { type: "string", description: "Comma-separated extras. Supported: representation (KRS management board).", enum: ["representation"] },
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
      "Search Polish businesses by (part of) their name. Returns up to 20 candidates with identifiers (NIP/REGON/KRS), legal form, status and city — use the identifiers with /pl/company or /pl/company/verify.",
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
    id: "batch-verify",
    method: "POST",
    path: "/pl/company/verify/batch",
    price: "$0.003 per identifier (min $0.01)",
    unitPrice: 0.003,
    minPrice: 0.01,
    summary: "Verify up to 50 Polish companies in one paid call.",
    description:
      "Batch version of /pl/company/verify: send up to 50 NIP / REGON / KRS numbers, get existence + status for each. Priced per identifier ($0.003, minimum $0.01) — cheaper than single calls. Invalid identifiers are reported back and not charged (validation happens before payment).",
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
