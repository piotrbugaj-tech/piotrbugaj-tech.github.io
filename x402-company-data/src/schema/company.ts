// Unified, source-agnostic company schema (v1).
// Every registry adapter (REGON, KRS, CEIDG; later EU registries) maps into
// these types, so agents get one shape regardless of where the data came from.

export const SCHEMA_VERSION = "1.0";

/** Normalised lifecycle status. */
export type EntityStatus =
  | "active"
  | "suspended" // zawieszona działalność (CEIDG / REGON)
  | "in_liquidation" // w likwidacji
  | "in_bankruptcy" // w upadłości
  | "removed" // wykreślona / zakończona działalność
  | "not_started" // zarejestrowana, działalność jeszcze nie rozpoczęta
  | "unknown";

/** Normalised legal form, independent of the language of the registry. */
export type LegalForm =
  | "sole_proprietorship" // jednoosobowa działalność gospodarcza (osoba fizyczna)
  | "civil_partnership" // spółka cywilna
  | "general_partnership" // spółka jawna
  | "professional_partnership" // spółka partnerska
  | "limited_partnership" // spółka komandytowa
  | "limited_joint_stock_partnership" // spółka komandytowo-akcyjna
  | "limited_liability_company" // spółka z o.o.
  | "simple_joint_stock_company" // prosta spółka akcyjna
  | "joint_stock_company" // spółka akcyjna
  | "european_company" // SE
  | "cooperative" // spółdzielnia
  | "foundation" // fundacja
  | "association" // stowarzyszenie
  | "state_enterprise" // przedsiębiorstwo państwowe
  | "foreign_branch" // oddział przedsiębiorcy zagranicznego
  | "public_entity" // JST, urzędy, jednostki budżetowe
  | "other";

export type SourceId = "REGON" | "KRS" | "CEIDG" | "MF_WL" | "VIES";

export interface SourceAttribution {
  source: SourceId;
  /** Human-readable name of the official register. */
  name: string;
  publisher: string;
  url: string;
  /** When the data was fetched from the register (ISO 8601). */
  retrievedAt: string;
  /** True when served from our cache rather than fetched for this request. */
  cached: boolean;
}

export interface Address {
  street: string | null;
  buildingNumber: string | null;
  unitNumber: string | null;
  postalCode: string | null;
  city: string | null;
  postOffice: string | null;
  commune: string | null; // gmina
  county: string | null; // powiat
  voivodeship: string | null; // województwo
  /** ISO 3166-1 alpha-2. */
  country: string;
  /** One-line address, e.g. "ul. Chemików 7, 09-411 Płock". */
  formatted: string | null;
}

export interface PkdCode {
  /** PKD 2007 code in dotted form, e.g. "62.01.Z". */
  code: string;
  description: string | null;
  primary: boolean;
}

export interface Identifiers {
  nip: string | null;
  regon: string | null;
  krs: string | null;
}

export interface StatusInfo {
  code: EntityStatus;
  /** Convenience flag: true only when code === "active". */
  active: boolean;
  suspendedSince: string | null;
  resumedAt: string | null;
  endedAt: string | null;
}

export interface Representation {
  /** Name of the body, e.g. "ZARZĄD". */
  body: string | null;
  /** Rules of representation as written in KRS (sposób reprezentacji). */
  method: string | null;
  members: Array<{ name: string; role: string | null }>;
}

/** VAT registration (returned with include=vat). */
export interface VatInfo {
  /** Polish VAT register (MF "Biała Lista") for today: active | exempt | not_registered; null if unknown/unavailable. */
  status: "active" | "exempt" | "not_registered" | null;
  /** EU VAT (VIES) validity; null when VIES / the national system was unavailable. */
  euVatValid: boolean | null;
  /** Number of settlement bank accounts published in the white list (accounts themselves are not returned). */
  bankAccountsCount: number | null;
  hasVirtualAccounts: boolean | null;
  /** MF request id — evidence of the white-list query performed by this service. */
  whiteListRequestId: string | null;
  checkedAt: string;
}

/** Result of comparing a caller-supplied name (?name=) with the registered name. */
export interface NameMatch {
  score: number;
  result: "match" | "partial" | "mismatch";
}

export interface CompanyProfile {
  schemaVersion: typeof SCHEMA_VERSION;
  country: "PL";
  identifiers: Identifiers;
  /** Official name; null when withheld for a natural person (see personalDataRedacted). */
  name: string | null;
  legalForm: {
    normalized: LegalForm;
    /** Original label from the register, e.g. "SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ". */
    label: string | null;
  };
  /** True for sole proprietors: the record describes a natural person (GDPR-relevant). */
  isNaturalPerson: boolean;
  /** True when personal data (name, street address) was withheld for a natural person. */
  personalDataRedacted: boolean;
  status: StatusInfo;
  dates: {
    /** Date of entry into the primary register (KRS / CEIDG / REGON). */
    registered: string | null;
    /** Date business activity started. */
    started: string | null;
  };
  address: Address | null;
  pkd: { primary: PkdCode | null; all: PkdCode[] };
  contact: { website: string | null; email: string | null };
  /** Share capital (KRS only). */
  capital: { amount: number; currency: string } | null;
  /** Management board / representation (KRS only; returned when include=representation). */
  representation: Representation | null;
  /** VAT status (returned when include=vat). */
  vat: VatInfo | null;
  registries: {
    regon: { type: string | null; silo: string | null } | null;
    krs: { register: "P" | "S"; registeredAt: string | null; lastEntryAt: string | null } | null;
    ceidg: { id: string | null; status: string | null } | null;
  };
  sources: SourceAttribution[];
  retrievedAt: string;
  /** Non-fatal issues, e.g. a secondary register was temporarily unavailable. */
  warnings: string[];
  /** Processed data from public registers — not an official extract. Link to terms/privacy. */
  notice: string;
}

export interface VerifyResult {
  schemaVersion: typeof SCHEMA_VERSION;
  query: { kind: "nip" | "regon" | "krs"; value: string };
  /** The identifier exists in the register. */
  found: boolean;
  /** Found and currently active (not suspended, removed, in liquidation or bankruptcy). */
  active: boolean;
  status: EntityStatus | "not_found";
  /** Registered name; null when not found or withheld for a natural person (see personalDataRedacted). */
  name: string | null;
  personalDataRedacted: boolean;
  /** Present when the request included ?name= */
  nameMatch: NameMatch | null;
  identifiers: Identifiers;
  legalForm: LegalForm | null;
  isNaturalPerson: boolean | null;
  endedAt: string | null;
  checkedAt: string;
  sources: SourceAttribution[];
  notice: string;
}

export interface SearchHit {
  name: string;
  identifiers: Identifiers;
  legalForm: LegalForm | null;
  status: EntityStatus;
  city: string | null;
  source: SourceId;
}
