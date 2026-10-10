import type { Address, EntityStatus, LegalForm, PkdCode, Representation } from "../../schema/company";
import { buildAddress, clean, isoDate, normalizeLegalForm, statusFromName } from "../../lib/normalize";
import type { KrsOdpis, KrsRegister } from "./client";

export interface KrsDetails {
  krs: string;
  register: KrsRegister;
  name: string | null;
  legalFormLabel: string | null;
  legalForm: LegalForm;
  nip: string | null;
  regon: string | null;
  address: Address | null;
  website: string | null;
  email: string | null;
  capital: { amount: number; currency: string } | null;
  registeredAt: string | null;
  lastEntryAt: string | null;
  removedAt: string | null;
  /** "stan na dzień" of the extract. */
  stateAsOf: string | null;
  status: EntityStatus;
  pkd: PkdCode[];
  representation: Representation | null;
}

const obj = (v: unknown): Record<string, any> => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, any>) : {});
const arr = (v: unknown): Record<string, any>[] => (Array.isArray(v) ? v : v && typeof v === "object" ? [v as Record<string, any>] : []);
const nonEmpty = (v: unknown) => (Array.isArray(v) ? v.length > 0 : v && typeof v === "object" ? Object.keys(v).length > 0 : !!v);

/** "1 565 420 000,00" -> 1565420000 */
export function parsePlMoney(v: unknown): number | null {
  const s = clean(v)?.replace(/\s/g, "").replace(",", ".");
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function pkdItem(x: Record<string, any>, primary: boolean): PkdCode | null {
  const dz = clean(x.kodDzial);
  const kl = clean(x.kodKlasa);
  const pk = clean(x.kodPodklasa);
  if (!dz || !kl || !pk) return null;
  return { code: `${dz.padStart(2, "0")}.${kl.padStart(2, "0")}.${pk}`, description: clean(x.opis), primary };
}

/** Masked person as published by the Open API, e.g. "D**** O*****". */
function personLabel(p: Record<string, any>): string {
  const first = clean(obj(p.imiona).imie) ?? "";
  const last = clean(obj(p.nazwisko).nazwiskoICzlon) ?? clean(p.nazwa) ?? "";
  return `${first} ${last}`.trim() || "—";
}

export function krsStatus(odpis: Record<string, any>, name: string | null): EntityStatus {
  const header = obj(odpis.naglowekA);
  if (clean(header.dataWykreslenia) || clean(header.dataWykresleniaZRejestru)) return "removed";
  const d6 = obj(obj(odpis.dane).dzial6);
  if (nonEmpty(d6.postepowanieUpadlosciowe) || nonEmpty(d6.upadlosc)) return "in_bankruptcy";
  if (nonEmpty(d6.likwidacja)) return "in_liquidation";
  if (nonEmpty(obj(d6.rozwiazanieUniewaznienie).dataZakonczeniaLikwidacji)) return "removed";
  return statusFromName(name) ?? "active";
}

export function krsDetails(krs: string, { register, odpis }: KrsOdpis): KrsDetails {
  const header = obj(odpis.naglowekA);
  const dane = obj(odpis.dane);
  const d1 = obj(dane.dzial1);
  const podmiot = obj(d1.danePodmiotu);
  const sia = obj(d1.siedzibaIAdres);
  const siedziba = obj(sia.siedziba);
  const adres = obj(sia.adres);
  const name = clean(podmiot.nazwa);
  const formLabel = clean(podmiot.formaPrawna);
  const regon14 = clean(obj(podmiot.identyfikatory).regon);
  const capitalRaw = obj(obj(d1.kapital).wysokoscKapitaluZakladowego);
  const capitalAmount = parsePlMoney(capitalRaw.wartosc);

  const przedmiot = obj(obj(dane.dzial3).przedmiotDzialalnosci);
  const pkd = [
    ...arr(przedmiot.przedmiotPrzewazajacejDzialalnosci).map((x) => pkdItem(x, true)),
    ...arr(przedmiot.przedmiotPozostalejDzialalnosci).map((x) => pkdItem(x, false)),
  ].filter((x): x is PkdCode => x !== null);

  const rep = arr(obj(dane.dzial2).reprezentacja)[0];
  const representation: Representation | null = rep
    ? {
        body: clean(rep.nazwaOrganu),
        method: clean(rep.sposobReprezentacji),
        members: arr(rep.sklad).map((m) => ({ name: personLabel(m), role: clean(m.funkcjaWOrganie) })),
      }
    : null;

  const city = clean(adres.miejscowosc) ?? clean(siedziba.miejscowosc);
  return {
    krs,
    register,
    name,
    legalFormLabel: formLabel,
    legalForm: normalizeLegalForm(formLabel),
    nip: clean(obj(podmiot.identyfikatory).nip),
    // KRS publishes the 14-digit REGON with a "00000" local-unit suffix.
    regon: regon14 ? (regon14.length === 14 && regon14.endsWith("00000") ? regon14.slice(0, 9) : regon14) : null,
    address:
      city || clean(adres.ulica)
        ? buildAddress({
            street: clean(adres.ulica),
            buildingNumber: clean(adres.nrDomu),
            unitNumber: clean(adres.nrLokalu),
            postalCode: clean(adres.kodPocztowy),
            city,
            postOffice: clean(adres.poczta),
            commune: clean(siedziba.gmina),
            county: clean(siedziba.powiat),
            voivodeship: clean(siedziba.wojewodztwo),
            country: clean(adres.kraj) && clean(adres.kraj) !== "POLSKA" ? clean(adres.kraj) : "PL",
          })
        : null,
    website: clean(sia.adresStronyInternetowej),
    email: clean(sia.adresPocztyElektronicznej),
    capital: capitalAmount !== null ? { amount: capitalAmount, currency: clean(capitalRaw.waluta) ?? "PLN" } : null,
    registeredAt: isoDate(header.dataRejestracjiWKRS),
    lastEntryAt: isoDate(header.dataOstatniegoWpisu),
    removedAt: isoDate(header.dataWykreslenia ?? header.dataWykresleniaZRejestru),
    stateAsOf: isoDate(header.stanZDnia),
    status: krsStatus(odpis, name),
    pkd,
    representation,
  };
}
