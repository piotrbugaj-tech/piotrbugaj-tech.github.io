import type { SourceId } from "../schema/company";

/**
 * An upstream registry failed (network, 5xx, quota, protocol error).
 * Handlers turn this into a 502/503 — which also cancels x402 settlement, so
 * the agent is not charged for a request we could not serve.
 */
export class UpstreamError extends Error {
  constructor(
    readonly source: SourceId | "MF",
    message: string,
    readonly status?: number,
  ) {
    super(`${source}: ${message}`);
  }
}
