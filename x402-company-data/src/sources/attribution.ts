import type { SourceAttribution, SourceId } from "../schema/company";

const META: Record<SourceId, Omit<SourceAttribution, "retrievedAt" | "cached">> = {
  REGON: {
    source: "REGON",
    name: "Baza Internetowa REGON (BIR1.1)",
    publisher: "Główny Urząd Statystyczny",
    url: "https://wyszukiwarkaregon.stat.gov.pl",
  },
  KRS: {
    source: "KRS",
    name: "Krajowy Rejestr Sądowy — Open API",
    publisher: "Ministerstwo Sprawiedliwości",
    url: "https://api-krs.ms.gov.pl",
  },
  CEIDG: {
    source: "CEIDG",
    name: "Centralna Ewidencja i Informacja o Działalności Gospodarczej — API",
    publisher: "Ministerstwo Rozwoju i Technologii",
    url: "https://dane.biznes.gov.pl",
  },
};

export function attribution(source: SourceId, fetchedAt: Date, cached: boolean): SourceAttribution {
  return { ...META[source], retrievedAt: fetchedAt.toISOString(), cached };
}
