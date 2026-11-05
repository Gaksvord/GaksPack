# GaksPack public presets

This Cloudflare Worker stores public presets, one-use preset codes and optional local texture ZIP files. The Minecraft mod discovers `https://gakspack-presets.gaksvord.workers.dev` from the top-level `index.json` field `publishUrl`. Run `npm test` before deployment.

Publishing and liking require a GaksPack account. Usernames contain 1–20 Latin letters or digits; passwords are stored as salted PBKDF2 hashes. The mod saves a session token locally and never saves the password. Applying a preset as a guest is allowed and does not increase its application count. There is no password recovery because accounts have no email address.

Registration is limited to one account per game installation every five minutes. Each account can publish one preset every ten minutes; removing a preset does not reset this timer.

For each game installation, three incorrect passwords lock login for 3, then 5, 10, 20, 40 and 60 minutes. Later blocks stay at 60 minutes. A successful login after the block expires resets the sequence.

Deploy updates from this directory:

1. Run `npx wrangler login --device` and complete the Cloudflare login in your browser.
2. Run `npm test` and `npx wrangler deploy --dry-run`.
3. Run `npx wrangler deploy` and check `https://gakspack-presets.gaksvord.workers.dev/health`.

The free KV tier supports 25 MiB values, so the mod's 4 MiB texture upload limit fits. New shared presets can take a short time to appear globally because KV is eventually consistent. Keep account credentials out of the Minecraft mod.
