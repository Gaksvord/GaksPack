# GaksPack public presets

This Cloudflare Worker stores public presets, one-use preset codes and optional local texture ZIP files. The Minecraft mod discovers `https://gakspack-presets.gaksvord.workers.dev` from the top-level `index.json` field `publishUrl`. Run `npm test` before deployment.

Deploy updates from this directory:

1. Run `npx wrangler login --device` and complete the Cloudflare login in your browser.
2. Run `npm test` and `npx wrangler deploy --dry-run`.
3. Run `npx wrangler deploy` and check `https://gakspack-presets.gaksvord.workers.dev/health`.

The free KV tier supports 25 MiB values, so the mod's 4 MiB texture upload limit fits. New shared presets can take a short time to appear globally because KV is eventually consistent. Keep account credentials out of the Minecraft mod.
