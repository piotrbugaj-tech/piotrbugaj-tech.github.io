import type { Cached } from "../lib/cache";
import type { ParsedId } from "../lib/ids";
import { statusFromName } from "../lib/normalize";
import { SCHEMA_VERSION, type EntityStatus, type VerifyResult } from "../schema/company";
import type { RegonCore } from "../services/regon";
import { statusFromDetails } from "../sources/regon/normalize";
import { attribution } from "../sources/attribution";

export function regonStatus(core: RegonCore): EntityStatus {
  if (core.details) return statusFromDetails(core.details);
  if (core.basic?.endedAt) return "removed";
  return statusFromName(core.basic?.name) ?? "unknown";
}

export function toVerifyResult(id: ParsedId, r: Cached<RegonCore>, now = new Date()): VerifyResult {
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
      identifiers: { nip: id.kind === "nip" ? id.value : null, regon: id.kind === "regon" ? id.value : null, krs: id.kind === "krs" ? id.value : null },
      legalForm: null,
      isNaturalPerson: null,
      endedAt: null,
      checkedAt: now.toISOString(),
      sources,
    };
  }
  const { basic, details } = core;
  const status = regonStatus(core);
  return {
    schemaVersion: SCHEMA_VERSION,
    query: id,
    found: true,
    active: status === "active",
    status,
    name: details?.name ?? basic.name,
    identifiers: {
      nip: basic.nip ?? details?.nip ?? null,
      regon: basic.regon,
      krs: id.kind === "krs" ? id.value : (details?.krs ?? null),
    },
    legalForm: details?.legalForm ?? (basic.type === "F" ? "sole_proprietorship" : null),
    isNaturalPerson: basic.type === "F" || basic.type === "LF",
    endedAt: details?.endedAt ?? details?.removedAt ?? basic.endedAt,
    checkedAt: now.toISOString(),
    sources,
  };
}
