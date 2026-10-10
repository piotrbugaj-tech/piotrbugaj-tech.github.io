import { createApp } from "./app";
import type { Env } from "./env";
import { keepalive } from "./keepalive";

const app = createApp();

export default {
  fetch: app.fetch,
  async scheduled(_event: ScheduledController, env: Env, ctx: ExecutionContext) {
    ctx.waitUntil(keepalive(env, (req) => Promise.resolve(app.fetch(req, env, ctx))));
  },
} satisfies ExportedHandler<Env>;
