// White list -> unified types. GDPR minimisation: the register also lists
// representatives, partners, prokurents (full names, sometimes PESEL/NIP),
// addresses and account numbers. None of that is copied; accounts are only counted.

import { clean, fold, isoDate } from "../../lib/normalize";
import type { WlCheck, WlMeta } from "./client";

export interface VatStatusInfo {
  /** null: the NIP is not in the register at all, or MF sent a status we do not know. */
  vatStatus: "active" | "exempt" | "not_registered" | null;
  nip: string | null;
  regon: string | null;
  krs: string | null;
  registrationLegalDate: string | null;
  removalDate: string | null;
  restorationDate: string | null;
  hasVirtualAccounts: boolean | null;
  accountsCount: number;
  requestId: string | null;
  requestDateTime: string | null;
}

export interface AccountCheck {
  assigned: boolean;
  requestId: string | null;
  requestDateTime: string | null;
}

function vatStatus(raw: unknown): VatStatusInfo["vatStatus"] {
  const s = clean(raw);
  switch (s && fold(s)) {
    case "CZYNNY":
      return "active";
    case "ZWOLNIONY":
      return "exempt";
    case "NIEZAREJESTROWANY":
      return "not_registered";
    default:
      return null;
  }
}

/** `queriedNip` fills `nip` when MF has no subject for it. */
export function vatStatusInfo(subject: Record<string, any> | null, meta: WlMeta, queriedNip: string | null = null): VatStatusInfo {
  const s = subject ?? {};
  return {
    vatStatus: vatStatus(s.statusVat),
    nip: clean(s.nip) ?? queriedNip,
    regon: clean(s.regon),
    krs: clean(s.krs),
    registrationLegalDate: isoDate(s.registrationLegalDate),
    removalDate: isoDate(s.removalDate),
    restorationDate: isoDate(s.restorationDate),
    hasVirtualAccounts: typeof s.hasVirtualAccounts === "boolean" ? s.hasVirtualAccounts : null,
    accountsCount: Array.isArray(s.accountNumbers) ? s.accountNumbers.length : 0,
    requestId: meta.requestId,
    requestDateTime: meta.requestDateTime,
  };
}

export function accountCheck(r: WlCheck): AccountCheck {
  return { assigned: r.accountAssigned, requestId: r.requestId, requestDateTime: r.requestDateTime };
}
