// Merges REGON + KRS (+ CEIDG when configured) into one CompanyProfile.
// Precedence: KRS is authoritative for KRS-registered entities (name, form,
// capital, liquidation/bankruptcy); REGON is the universal backbone (every
// entity, suspension dates, PKD with descriptions, mixed-case addresses).

import type { Cached } from "../lib/cache";
import type { ParsedId } from "../lib/ids";
import type { Policy } from "../policy";
import { SCHEMA_VERSION, type Address, type CompanyProfile, type EntityStatus, type SourceAttribution } from "../schema/company";
import { attribution } from "../sources/attribution";
import { UpstreamError } from "../sources/errors";
import type { KrsDetails } from "../sources/krs/normalize";
import { regonStatus } from "../views/verify";
import type { KrsService } from "./krs";
import type { RegonCore, RegonService } from "./regon";

const SEVERITY: EntityStatus[] = ["unknown", "active", "not_started", "suspended", "in_liquidation", "in_bankruptcy", "removed"];
export const mostSevere = (...s: Array<EntityStatus | null | undefined>): EntityStatus =>
  s.filter((x): x is EntityStatus => !!x).reduce<EntityStatus>((a, b) => (SEVERITY.indexOf(b) > SEVERITY.indexOf(a) ? b : a), "unknown");

export interface ProfileDeps {
  regon: RegonService;
  krs: KrsService;
}

export interface ProfileRequest {
  id: ParsedId;
  includeRepresentation: boolean;
  policy: Policy;
}

export type ProfileResult = { found: false } | { found: true; profile: CompanyProfile };

const settle = async <T>(p: Promise<T>): Promise<{ ok: true; value: T } | { ok: false; error: unknown }> => {
  try {
    return { ok: true, value: await p };
  } catch (error) {
    return { ok: false, error };
  }
};

/** City-level address only — used for natural persons (their business address is often home). */
function coarseAddress(a: Address | null): Address | null {
  if (!a) return null;
  return {
    street: null, buildingNumber: null, unitNumber: null, postalCode: null, postOffice: null,
    city: a.city, commune: a.commune, county: a.county, voivodeship: a.voivodeship, country: a.country,
    formatted: [a.city, a.voivodeship].filter(Boolean).join(", ") || null,
  };
}

export async function buildProfile(deps: ProfileDeps, req: ProfileRequest, now = new Date()): Promise<ProfileResult> {
  const { id, policy } = req;
  const warnings: string[] = [];
  const sources: SourceAttribution[] = [];

  // REGON always; KRS in parallel when we already know the KRS number.
  const regonP = settle(deps.regon.core(id));
  const krsEarlyP = id.kind === "krs" ? settle(deps.krs.details(id.value)) : null;
  const regonR = await regonP;
  const core: RegonCore | null = regonR.ok && regonR.value.value.found ? regonR.value.value : null;
  if (regonR.ok) sources.push(attribution("REGON", regonR.value.fetchedAt, regonR.value.cached));
  else warnings.push("REGON temporarily unavailable; profile built from other registers.");

  const krsNumber = id.kind === "krs" ? id.value : (core?.details?.krs ?? null);
  const krsR = krsEarlyP ? await krsEarlyP : krsNumber ? await settle(deps.krs.details(krsNumber)) : null;
  let krs: KrsDetails | null = null;
  if (krsR?.ok) {
    krs = krsR.value.value;
    if (krs) sources.push(attribution("KRS", krsR.value.fetchedAt, krsR.value.cached));
  } else if (krsR) warnings.push("KRS temporarily unavailable; capital, representation and court-register status may be missing.");

  if (!core && !krs) {
    // Nothing usable: an outage is a 503 (not charged), a clean miss is "not found".
    const failure = !regonR.ok ? regonR.error : krsR && !krsR.ok ? krsR.error : null;
    if (failure) throw failure instanceof UpstreamError ? failure : new UpstreamError("REGON", String(failure));
    return { found: false };
  }

  const basic = core?.basic ?? null;
  const details = core?.details ?? null;
  const natural = basic?.type === "F";
  const redact = natural && policy.naturalPersons === "minimal";

  // PKD: REGON report (has descriptions for everyone), KRS as fallback.
  let pkd = krs?.pkd ?? [];
  if (basic) {
    const pkdR = await settle(deps.regon.pkd(basic.regon, basic.type));
    if (pkdR.ok && pkdR.value.value.length) pkd = pkdR.value.value;
    else if (!pkdR.ok) warnings.push("REGON PKD report unavailable.");
  }

  const status = mostSevere(core ? regonStatus(core) : null, krs?.status);
  const address = details?.address ?? basic?.address ?? krs?.address ?? null;
  const name = krs?.name ?? details?.name ?? basic?.name ?? null;

  const profile: CompanyProfile = {
    schemaVersion: SCHEMA_VERSION,
    country: "PL",
    identifiers: {
      nip: basic?.nip ?? details?.nip ?? krs?.nip ?? (id.kind === "nip" ? id.value : null),
      regon: basic?.regon ?? krs?.regon ?? null,
      krs: krs?.krs ?? krsNumber,
    },
    name: redact ? null : name,
    legalForm: {
      normalized: natural ? "sole_proprietorship" : (krs?.legalForm ?? details?.legalForm ?? "other"),
      label: krs?.legalFormLabel ?? details?.legalFormLabel ?? null,
    },
    isNaturalPerson: natural,
    personalDataRedacted: redact,
    status: {
      code: status,
      active: status === "active",
      suspendedSince: status === "suspended" ? (details?.suspendedAt ?? null) : null,
      resumedAt: details?.resumedAt ?? null,
      endedAt: krs?.removedAt ?? details?.endedAt ?? details?.removedAt ?? basic?.endedAt ?? null,
    },
    dates: {
      registered: krs?.registeredAt ?? details?.registeredAt ?? null,
      started: details?.startedAt ?? null,
    },
    address: redact ? coarseAddress(address) : address,
    pkd: { primary: pkd.find((p) => p.primary) ?? null, all: pkd },
    contact: {
      website: natural ? null : (krs?.website ?? details?.website ?? null),
      email: natural ? null : (krs?.email ?? details?.email ?? null),
    },
    capital: krs?.capital ?? null,
    representation: req.includeRepresentation ? (krs?.representation ?? null) : null,
    registries: {
      regon: basic ? { type: basic.type, silo: basic.silo } : null,
      krs: krs ? { register: krs.register, registeredAt: krs.registeredAt, lastEntryAt: krs.lastEntryAt } : null,
      ceidg: null,
    },
    sources,
    retrievedAt: now.toISOString(),
    warnings,
    notice: policy.notice,
  };
  if (req.includeRepresentation && !krs) warnings.push("Representation is only available for KRS-registered entities.");
  return { found: true, profile };
}

export type { Cached };
