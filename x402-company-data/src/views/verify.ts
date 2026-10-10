import type { Cached } from "../lib/cache";
import type { ParsedId } from "../lib/ids";
import { matchName } from "../lib/namematch";
import { statusFromName } from "../lib/normalize";
import type { Policy } from "../policy";
import { SCHEMA_VERSION, type EntityStatus, type VerifyResult } from "../schema/company";
import type { RegonCore } from "../services/regon";
import { statusFromDetails } from "../sources/regon/normalize";
import { attribution } from "../sources/attribution";

export function regonStatus(core: RegonCore): EntityStatus {
  if (core.details) return statusFromDetails(core.details);
  if (core.basic?.endedAt) return "removed";
  return statusFromName(core.basic?.name) ?? "unknown";
}

export function toVerifyResult(id: ParsedId, r: Cached<RegonCore>, policy: Policy, nameQuery?: string, now = new Date()): VerifyResult {
  const core = r.value;
  const sources = [attribution("REGON", r.fetchedAt, r.cached)];
  if (!core.found || !core.basic) {
    return {
      schemaVersion: SCHEMA_VERSION,
      query: id,
      found: false,
      active: false,
      status: "not_found",
      name: null,
      personalDataRedacted: false,
      nameMatch: null,
      identifiers: { nip: id.kind === "nip" ? id.value : null, regon: id.kind === "regon" ? id.value : null, krs: id.kind === "krs" ? id.value : null },
      legalForm: null,
      isNaturalPerson: null,
      endedAt: null,
      checkedAt: now.toISOString(),
      sources,
      notice: policy.notice,
    };
  }
  const { basic, details } = core;
  const status = regonStatus(core);
  const natural = basic.type === "F" || basic.type === "LF";
  const name = details?.name ?? basic.name;
  const redact = natural && policy.naturalPersons === "minimal";
  return {
    schemaVersion: SCHEMA_VERSION,
    query: id,
    found: true,
    active: status === "active",
    status,
    name: redact ? null : name,
    personalDataRedacted: redact,
    nameMatch: nameQuery ? matchName(nameQuery, name) : null,
    identifiers: {
      nip: basic.nip ?? details?.nip ?? null,
      regon: basic.regon,
      krs: id.kind === "krs" ? id.value : (details?.krs ?? null),
    },
    legalForm: details?.legalForm ?? (natural ? "sole_proprietorship" : null),
    isNaturalPerson: natural,
    endedAt: details?.endedAt ?? details?.removedAt ?? basic.endedAt,
    checkedAt: now.toISOString(),
    sources,
    notice: policy.notice,
  };
}
