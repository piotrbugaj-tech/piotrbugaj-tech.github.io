import type { Address, EntityStatus, LegalForm } from "../schema/company";

/** Uppercase, strip diacritics and collapse whitespace — for matching only. */
export function fold(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/ł/g, "l")
    .replace(/Ł/g, "L")
    .toUpperCase()
    .replace(/\s+/g, " ")
    .trim();
}

// Order matters: more specific patterns first ("KOMANDYTOWO-AKCYJNA" before "AKCYJNA").
const LEGAL_FORM_PATTERNS: Array<[RegExp, LegalForm]> = [
  [/OSOB[AY] FIZYCZN|OSOBY FIZYCZNE PROWADZACE/, "sole_proprietorship"],
  [/SPOLK[AIE] CYWILN/, "civil_partnership"],
  [/KOMANDYTOWO-? ?AKCYJN/, "limited_joint_stock_partnership"],
  [/PROST[AE]J? SPOLK[AIE] AKCYJN/, "simple_joint_stock_company"],
  [/SPOLK[AIE] EUROPEJSK/, "european_company"],
  [/AKCYJN/, "joint_stock_company"],
  [/OGRANICZONA ODPOWIEDZIALNOSCIA/, "limited_liability_company"],
  [/KOMANDYTOW/, "limited_partnership"],
  [/PARTNERSK/, "professional_partnership"],
  [/JAWN/, "general_partnership"],
  [/SPOLDZIELNI/, "cooperative"],
  [/FUNDACJ/, "foundation"],
  [/STOWARZYSZ/, "association"],
  [/PRZEDSIEBIORSTW[AO] PANSTWOW/, "state_enterprise"],
  [/ODDZIA[LŁ]/, "foreign_branch"],
  [/GMIN|POWIAT|WOJEWODZTW|JEDNOSTK[AIE] (BUDZETOW|SAMORZAD)|ORGAN(Y|OW)? (WLADZY|ADMINISTRACJI|KONTROLI)|SKARB PANSTWA/, "public_entity"],
];

export function normalizeLegalForm(...labels: Array<string | null | undefined>): LegalForm {
  for (const label of labels) {
    if (!label) continue;
    const f = fold(label);
    for (const [re, form] of LEGAL_FORM_PATTERNS) if (re.test(f)) return form;
  }
  return "other";
}

/**
 * Registers append "W LIKWIDACJI" / "W UPADŁOŚCI" to the official name, which
 * lets us detect these states even from sources that have no explicit flag.
 */
export function statusFromName(name: string | null | undefined): EntityStatus | null {
  if (!name) return null;
  const f = fold(name);
  if (/\bW UPADLOSCI\b/.test(f)) return "in_bankruptcy";
  if (/\bW LIKWIDACJI\b/.test(f)) return "in_liquidation";
  return null;
}

/** Empty strings from SOAP/XML become null. */
export function clean(v: unknown): string | null {
  if (v === undefined || v === null) return null;
  const s = String(v).trim();
  return s === "" ? null : s;
}

/** Accepts "2020-01-31", "2020-01-31T00:00:00", "31.01.2020"; returns YYYY-MM-DD or null. */
export function isoDate(v: unknown): string | null {
  const s = clean(v);
  if (!s) return null;
  let m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (m) return `${m[1]}-${m[2]}-${m[3]}`;
  m = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(s);
  if (m) return `${m[3]}-${m[2]}-${m[1]}`;
  return null;
}

/** "6201Z" | "62.01.Z" | "62.01 Z" -> "62.01.Z" */
export function normalizePkd(code: string | null | undefined): string | null {
  const c = clean(code)?.replace(/[.\s]/g, "").toUpperCase();
  if (!c) return null;
  const m = /^(\d{2})(\d{2})([A-Z])$/.exec(c);
  return m ? `${m[1]}.${m[2]}.${m[3]}` : clean(code);
}

export function formatAddress(a: Omit<Address, "formatted">): string | null {
  const streetPart = a.street
    ? `${a.street} ${a.buildingNumber ?? ""}${a.unitNumber ? "/" + a.unitNumber : ""}`.trim()
    : a.buildingNumber
      ? `${a.city ?? ""} ${a.buildingNumber}${a.unitNumber ? "/" + a.unitNumber : ""}`.trim()
      : null;
  const cityPart = [a.postalCode, a.postOffice ?? a.city].filter(Boolean).join(" ");
  const out = [streetPart, cityPart].filter((x) => x && x.length > 0).join(", ");
  return out.length > 0 ? out : null;
}

export function buildAddress(a: Omit<Address, "formatted" | "country"> & { country?: string | null }): Address {
  const base = { ...a, country: a.country ?? "PL" };
  return { ...base, formatted: formatAddress(base) };
}
