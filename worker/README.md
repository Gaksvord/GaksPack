# GaksPack public presets

This Cloudflare Worker stores public presets, one-use preset codes and optional local texture ZIP files. The Minecraft mod uses the URL in the top-level `index.json` field `publishUrl`. Run `npm test` before deployment.

Deploy once from this directory:

1. Run `npx wrangler login` and complete the Cloudflare login in your browser.
2. Run `npx wrangler kv namespace create gakspack-presets`. Copy the returned namespace ID into `wrangler.jsonc` in place of `REPLACE_WITH_KV_NAMESPACE_ID`.
3. Run `npx wrangler deploy`. Check the printed `https://...workers.dev/health` URL.
4. Put the Worker URL (without `/health`) into `index.json` as `publishUrl` and publish that change. Clients then discover the server automatically.

The free KV tier supports 25 MiB values, so the mod's 4 MiB texture upload limit fits. New shared presets can take a short time to appear globally because KV is eventually consistent. Keep the namespace ID and account credentials out of the Minecraft mod.
