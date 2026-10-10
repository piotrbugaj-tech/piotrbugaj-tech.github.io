import type { Address, EntityStatus, LegalForm, PkdCode } from "../../schema/company";
import { buildAddress, clean, isoDate, normalizeLegalForm, normalizePkd, statusFromName } from "../../lib/normalize";
import type { RegonRecord } from "./client";

/** Row of DaneSzukajPodmioty, normalised. */
export interface RegonBasic {
  regon: string;
  nip: string | null;
  name: string;
  /** P = legal entity / civil partnership, F = natural person, LP/LF = local units. */
  type: string | null;
  /** 1 CEIDG, 2 agricultural, 3 other, 4 removed before 2014-11-08, 6 legal entity. */
  silo: string | null;
  endedAt: string | null;
  address: Address;
}

export function basicFromSearch(r: RegonRecord): RegonBasic {
  return {
    regon: clean(r.Regon) ?? "",
    nip: clean(r.Nip),
    name: clean(r.Nazwa) ?? "",
    type: clean(r.Typ),
    silo: clean(r.SilosID),
    endedAt: isoDate(r.DataZakonczeniaDzialalnosci),
    address: buildAddress({
      street: clean(r.Ulica),
      buildingNumber: clean(r.NrNieruchomosci),
      unitNumber: clean(r.NrLokalu),
      postalCode: clean(r.KodPocztowy),
      city: clean(r.Miejscowosc),
      postOffice: clean(r.MiejscowoscPoczty),
      commune: clean(r.Gmina),
      county: clean(r.Powiat),
      voivodeship: clean(r.Wojewodztwo),
    }),
  };
}

/** Which full report describes this entity (null = no meaningful report, e.g. local units). */
export function reportFor(basic: Pick<RegonBasic, "type" | "silo">) {
  if (basic.type === "P") return { main: "BIR11OsPrawna", pkd: "BIR11OsPrawnaPkd" } as const;
  if (basic.type === "F") {
    const main =
      basic.silo === "2"
        ? "BIR11OsFizycznaDzialalnoscRolnicza"
        : basic.silo === "3"
          ? "BIR11OsFizycznaDzialalnoscPozostala"
          : basic.silo === "4"
            ? "BIR11OsFizycznaDzialalnoscSkreslonaDo20141108"
            : "BIR11OsFizycznaDzialalnoscCeidg";
    return { main, pkd: "BIR11OsFizycznaPkd" } as const;
  }
  return null;
}

// GUS field-name casing drifts between reports (e.g. ...ZRegon vs ...zRegon), so
// look keys up case-insensitively.
const lowered = new WeakMap<RegonRecord, Map<string, string>>();
function lc(r: RegonRecord): Map<string, string> {
  let m = lowered.get(r);
  if (!m) {
    m = new Map(Object.entries(r).map(([k, v]) => [k.toLowerCase(), v]));
    lowered.set(r, m);
  }
  return m;
}
/** Field accessor for praw_/fiz_ prefixed report fields. */
const f = (r: RegonRecord, prefix: string, key: string) => clean(lc(r).get(`${prefix}_${key}`.toLowerCase()));

export interface RegonDetails {
  name: string | null;
  shortName: string | null;
  nip: string | null;
  krs: string | null;
  legalFormLabel: string | null;
  legalForm: LegalForm;
  isNaturalPerson: boolean;
  registeredAt: string | null;
  startedAt: string | null;
  suspendedAt: string | null;
  resumedAt: string | null;
  endedAt: string | null;
  removedAt: string | null;
  bankruptcyAt: string | null;
  address: Address | null;
  website: string | null;
  email: string | null;
}

function addressFromReport(r: RegonRecord, p: string): Address | null {
  const city = f(r, p, "adSiedzMiejscowosc_Nazwa");
  if (!city && !f(r, p, "adSiedzKodPocztowy")) return null;
  const pc = f(r, p, "adSiedzKodPocztowy");
  return buildAddress({
    street: f(r, p, "adSiedzUlica_Nazwa"),
    buildingNumber: f(r, p, "adSiedzNumerNieruchomosci"),
    unitNumber: f(r, p, "adSiedzNumerLokalu"),
    // GUS returns postal codes without the dash ("09411").
    postalCode: pc && /^\d{5}$/.test(pc) ? `${pc.slice(0, 2)}-${pc.slice(2)}` : pc,
    city,
    postOffice: f(r, p, "adSiedzMiejscowoscPoczty_Nazwa"),
    commune: f(r, p, "adSiedzGmina_Nazwa"),
    county: f(r, p, "adSiedzPowiat_Nazwa"),
    voivodeship: f(r, p, "adSiedzWojewodztwo_Nazwa"),
    country: f(r, p, "adSiedzKraj_Symbol") ?? "PL",
  });
}

/**
 * Normalises BIR11OsPrawna / BIR11OsFizycznaDzialalnosc* report rows.
 * For natural persons `general` is the BIR11OsFizycznaDaneOgolne row (NIP lives there).
 */
export function detailsFromReport(main: RegonRecord, general?: RegonRecord): RegonDetails {
  const p = Object.keys(main).some((k) => k.startsWith("praw_")) ? "praw" : "fiz";
  const natural = p === "fiz";
  const formLabel = natural
    ? f(general ?? main, p, "szczegolnaFormaPrawna_Nazwa") ?? "OSOBY FIZYCZNE PROWADZĄCE DZIAŁALNOŚĆ GOSPODARCZĄ"
    : f(main, p, "szczegolnaFormaPrawna_Nazwa") ?? f(main, p, "podstawowaFormaPrawna_Nazwa");
  const registry = f(main, p, "rodzajRejestruEwidencji_Nazwa") ?? f(main, p, "RodzajRejestru_Nazwa");
  const regNo = f(main, p, "numerWRejestrzeEwidencji");
  return {
    name: f(main, p, "nazwa"),
    shortName: f(main, p, "nazwaSkrocona"),
    nip: f(main, p, "nip") ?? (general ? f(general, p, "nip") : null),
    krs: regNo && registry && /PRZEDSI[EĘ]BIORC|STOWARZYSZE|KRS|S[AĄ]DOW/i.test(registry) && /^\d{1,10}$/.test(regNo) ? regNo.padStart(10, "0") : null,
    legalFormLabel: formLabel,
    legalForm: natural ? "sole_proprietorship" : normalizeLegalForm(formLabel, f(main, p, "podstawowaFormaPrawna_Nazwa")),
    isNaturalPerson: natural,
    registeredAt: isoDate(f(main, p, "dataWpisuDoRejestruEwidencji")) ?? isoDate(f(main, p, "dataWpisuDoRegon") ?? f(main, p, "dataWpisuDzialalnosciDoRegon")),
    startedAt: isoDate(f(main, p, "dataRozpoczeciaDzialalnosci")) ?? isoDate(f(main, p, "dataPowstania")),
    suspendedAt: isoDate(f(main, p, "dataZawieszeniaDzialalnosci")),
    resumedAt: isoDate(f(main, p, "dataWznowieniaDzialalnosci")),
    endedAt: isoDate(f(main, p, "dataZakonczeniaDzialalnosci")),
    removedAt: isoDate(f(main, p, "dataSkresleniaZRegon") ?? f(main, p, "dataSkresleniaDzialalnosciZRegon") ?? f(main, p, "dataSkresleniaPodmiotuZRegon")),
    bankruptcyAt: isoDate(f(main, p, "dataOrzeczeniaOUpadlosci")),
    address: addressFromReport(main, p),
    // Contact details of natural persons are personal data: we do not expose them.
    website: natural ? null : f(main, p, "adresStronyinternetowej"),
    email: natural ? null : f(main, p, "adresEmail"),
  };
}

export function statusFromDetails(d: Pick<RegonDetails, "name" | "suspendedAt" | "resumedAt" | "endedAt" | "removedAt" | "bankruptcyAt">): EntityStatus {
  if (d.removedAt || d.endedAt) return "removed";
  if (d.suspendedAt && (!d.resumedAt || d.resumedAt < d.suspendedAt)) return "suspended";
  const byName = statusFromName(d.name);
  if (byName) return byName;
  if (d.bankruptcyAt) return "in_bankruptcy";
  return "active";
}

export function pkdFromReport(rows: RegonRecord[]): PkdCode[] {
  const out: PkdCode[] = [];
  for (const r of rows) {
    const code = normalizePkd(clean(r.praw_pkdKod) ?? clean(r.fiz_pkd_Kod) ?? clean(r.fiz_pkdKod));
    if (!code) continue;
    const primary = (clean(r.praw_pkdPrzewazajace) ?? clean(r.fiz_pkd_Przewazajace) ?? clean(r.fiz_pkdPrzewazajace)) === "1";
    if (out.some((x) => x.code === code)) continue;
    out.push({ code, description: clean(r.praw_pkdNazwa) ?? clean(r.fiz_pkd_Nazwa) ?? clean(r.fiz_pkdNazwa), primary });
  }
  return out.sort((a, b) => Number(b.primary) - Number(a.primary));
}
