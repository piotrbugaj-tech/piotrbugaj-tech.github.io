// CEIDG v3 -> unified types. Data minimisation: only the business-side fields are
// read. Owner contact data (phone, e-mail), citizenship, correspondence address and
// the owner's own identifiers are deliberately never touched; the owner's name only
// ever appears inside the business name (`nazwa`), as the register publishes it.

import type { Address, EntityStatus, PkdCode } from "../../schema/company";
import { buildAddress, clean, isoDate, normalizePkd } from "../../lib/normalize";

export interface CeidgDetails {
  id: string | null;
  /** Original `status` enum from CEIDG. */
  statusRaw: string | null;
  status: EntityStatus;
  name: string | null;
  nip: string | null;
  regon: string | null;
  address: Address | null;
  pkd: PkdCode[];
  startedAt: string | null;
  suspendedAt: string | null;
  resumedAt: string | null;
  endedAt: string | null;
  removedAt: string | null;
}

export interface CeidgSearchHit {
  name: string;
  nip: string | null;
  regon: string | null;
  status: EntityStatus;
  city: string | null;
}

const obj = (v: unknown): Record<string, any> => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, any>) : {});

export function ceidgStatus(raw: unknown): EntityStatus {
  switch (clean(raw)?.toUpperCase()) {
    case "AKTYWNY":
    case "WYLACZNIE_W_FORMIE_SPOLKI": // runs only as a partner of a civil partnership
      return "active";
    case "ZAWIESZONY":
      return "suspended";
    case "WYKRESLONY":
      return "removed";
    case "OCZEKUJE_NA_ROZPOCZECIE_DZIALANOSCI": // sic: the enum is also served as ..._DZIALALNOSCI
    case "OCZEKUJE_NA_ROZPOCZECIE_DZIALALNOSCI":
      return "not_started";
    default:
      return "unknown";
  }
}

function country(v: unknown): string {
  const c = clean(v)?.toUpperCase();
  if (!c || c === "POLSKA" || c === "POLAND") return "PL";
  return /^[A-Z]{2}$/.test(c) ? c : "PL";
}

function postalCode(v: unknown): string | null {
  const c = clean(v);
  return c && /^\d{5}$/.test(c) ? `${c.slice(0, 2)}-${c.slice(2)}` : c;
}

function businessAddress(a: unknown): Address | null {
  const x = obj(a);
  const addr = buildAddress({
    street: clean(x.ulica),
    buildingNumber: clean(x.budynek),
    unitNumber: clean(x.lokal),
    postalCode: postalCode(x.kod),
    city: clean(x.miasto),
    postOffice: null,
    commune: clean(x.gmina),
    county: clean(x.powiat),
    voivodeship: clean(x.wojewodztwo),
    country: country(x.kraj),
  });
  return addr.formatted || addr.city || addr.postalCode ? addr : null;
}

/** v3 serves `{kod, nazwa}`; v2 served plain strings. */
function pkdParts(v: unknown): { code: string; description: string | null } | null {
  const o = obj(v);
  const code = normalizePkd(typeof v === "string" ? v : clean(o.kod ?? o.code));
  return code ? { code, description: clean(o.nazwa ?? o.opis) } : null;
}

function pkdList(raw: Record<string, any>): PkdCode[] {
  const main = pkdParts(raw.pkdGlowny);
  const out: PkdCode[] = main ? [{ ...main, primary: true }] : [];
  const items = Array.isArray(raw.pkd) ? raw.pkd : [];
  for (const item of items) {
    const p = pkdParts(item);
    if (p && !out.some((x) => x.code === p.code)) out.push({ ...p, primary: false });
  }
  return out;
}

export function ceidgDetails(raw: Record<string, any>): CeidgDetails {
  const owner = obj(raw.wlasciciel);
  const statusRaw = clean(raw.status);
  return {
    id: clean(raw.id),
    statusRaw,
    status: ceidgStatus(statusRaw),
    name: clean(raw.nazwa),
    nip: clean(owner.nip),
    regon: clean(owner.regon),
    address: businessAddress(raw.adresDzialalnosci),
    pkd: pkdList(raw),
    startedAt: isoDate(raw.dataRozpoczecia),
    suspendedAt: isoDate(raw.dataZawieszenia),
    resumedAt: isoDate(raw.dataWznowienia),
    endedAt: isoDate(raw.dataZakonczenia),
    removedAt: isoDate(raw.dataWykreslenia),
  };
}

export function ceidgSearchHit(raw: Record<string, any>): CeidgSearchHit {
  const owner = obj(raw.wlasciciel);
  return {
    name: clean(raw.nazwa) ?? "",
    nip: clean(owner.nip),
    regon: clean(owner.regon),
    status: ceidgStatus(raw.status),
    city: clean(obj(raw.adresDzialalnosci).miasto),
  };
}
