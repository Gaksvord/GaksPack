const DEVICE = /^[0-9a-f]{64}$/;
const SHA = /^[0-9a-f]{64}$/;
const CODE = /^[A-Z0-9]{8}$/;
const json = (value, status = 200) => Response.json(value, { status, headers: { "Cache-Control": "no-store" } });
const clean = (value, max) => typeof value === "string" ? value.replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, max) : "";

function presetFrom(input) {
  if (!input || typeof input !== "object" || Array.isArray(input)) return null;
  const name = clean(input.name, 48);
  const author = clean(input.author, 32);
  const device = clean(input.device, 64);
  if (!name || !author || !DEVICE.test(device)) return null;
  const styles = {};
  const local = {};
  const extras = {};
  for (const [key, value] of Object.entries(input.styles || {})) {
    if (/^[a-z0-9]{2,20}$/.test(key) && typeof value === "string" && value.length <= 100 && /^[a-zA-Z0-9_:.-]+$/.test(value)) styles[key] = value;
  }
  for (const [key, value] of Object.entries(input.local || {})) {
    if (/^[a-z0-9]{2,20}$/.test(key) && value && SHA.test(value.sha) && clean(value.name, 64)) local[key] = { sha: value.sha, name: clean(value.name, 64) };
  }
  for (const [key, value] of Object.entries(input.extras || {})) {
    if (/^[A-Z0-9_]{1,32}$/.test(key) && typeof value === "string" && value.length <= 256) extras[key] = value;
  }
  return { name, author, device, styles, local, extras };
}

async function readBody(request, limit = 65536) {
  if (Number(request.headers.get("content-length") || 0) > limit) throw new RangeError("Request is too large");
  const body = await request.text();
  if (body.length > limit) throw new RangeError("Request is too large");
  return JSON.parse(body);
}

async function presets(env, device) {
  const keys = await env.DATA.list({ prefix: "preset:", limit: 1000 });
  const records = await Promise.all(keys.keys.slice(0, 200).map(k => env.DATA.get(k.name, "json")));
  return Promise.all(records.filter(Boolean).map(async ({ device: owner, ...p }) => ({
    ...p,
    likes: p.likes || 0,
    applications: p.applications || 0,
    createdAt: p.createdAt || 0,
    mine: owner === device,
    liked: DEVICE.test(device || "") && !!await env.DATA.get(`like:${p.id}:${device}`),
  })));
}

async function newId(env) {
  for (let i = 0; i < 6; i++) {
    const id = crypto.getRandomValues(new Uint32Array(1))[0] & 0x7fffffff;
    if (id && !await env.DATA.get(`preset:${id}`)) return id;
  }
  throw new Error("Could not create an ID");
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    try {
      if (request.method === "GET" && path === "/health") return json({ ok: true, service: "GaksPack" });
      if (request.method === "GET" && path === "/whoami") return json({ role: "guest" });
      if (request.method === "POST" && path === "/ping") return json({ ok: true });
      if (request.method === "GET" && path === "/stats") return json({ online: 0, total: 0 });

      if (path === "/presets" && request.method === "GET") {
        return json({ presets: await presets(env, url.searchParams.get("device")) });
      }
      if (path === "/presets" && request.method === "POST") {
        const p = presetFrom(await readBody(request));
        if (!p) return json({ message: "Invalid preset" }, 400);
        const existing = await presets(env, p.device);
        if (existing.filter(x => x.mine).length >= 5) return json({ message: "Five public presets per player" }, 429);
        for (const file of Object.values(p.local)) {
          if (!await env.DATA.get(`file:${file.sha}`)) return json({ message: "A shared texture file is missing" }, 400);
        }
        const id = await newId(env);
        await env.DATA.put(`preset:${id}`, JSON.stringify({ id, likes: 0, applications: 0, createdAt: Date.now(), ...p }));
        return json({ id, message: "Preset shared" });
      }
      const metric = path.match(/^\/presets\/(\d+)\/(like|apply)$/);
      if (metric && request.method === "POST") {
        const id = Number(metric[1]);
        const body = await readBody(request);
        if (!DEVICE.test(body.device || "")) return json({ message: "Invalid request" }, 400);
        const preset = await env.DATA.get(`preset:${id}`, "json");
        if (!preset) return json({ message: "Preset not found" }, 404);
        if (metric[2] === "like") {
          const voteKey = `like:${id}:${body.device}`;
          if (!await env.DATA.get(voteKey)) {
            await env.DATA.put(voteKey, "1");
            preset.likes = (preset.likes || 0) + 1;
            await env.DATA.put(`preset:${id}`, JSON.stringify(preset));
          }
        } else {
          preset.applications = (preset.applications || 0) + 1;
          await env.DATA.put(`preset:${id}`, JSON.stringify(preset));
        }
        return json({ likes: preset.likes || 0, applications: preset.applications || 0 });
      }
      if (path === "/presets" && request.method === "DELETE") {
        const body = await readBody(request);
        if (!Number.isInteger(body.id) || !DEVICE.test(body.device || "")) return json({ message: "Invalid request" }, 400);
        const p = await env.DATA.get(`preset:${body.id}`, "json");
        if (!p || p.device !== body.device) return json({ message: "Preset not found" }, 404);
        await env.DATA.delete(`preset:${body.id}`);
        return json({ message: "Preset removed" });
      }
      if (path === "/lfile" && request.method === "POST") {
        if (Number(request.headers.get("content-length") || 0) > 4194304) return json({ message: "File exceeds 4 MB" }, 413);
        const bytes = await request.arrayBuffer();
        if (bytes.byteLength < 1 || bytes.byteLength > 4194304) return json({ message: "File exceeds 4 MB" }, 413);
        const digest = await crypto.subtle.digest("SHA-256", bytes);
        const sha = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("");
        await env.DATA.put(`file:${sha}`, bytes);
        return json({ sha });
      }
      if (request.method === "GET" && path.startsWith("/lfile/")) {
        const sha = path.slice(7);
        if (!SHA.test(sha)) return json({ message: "Invalid file" }, 400);
        const bytes = await env.DATA.get(`file:${sha}`, "arrayBuffer");
        return bytes ? new Response(bytes, { headers: { "Content-Type": "application/zip", "Cache-Control": "public, max-age=3600" } }) : json({ message: "File not found" }, 404);
      }
      if (path === "/presets/code" && request.method === "POST") {
        const p = presetFrom(await readBody(request));
        if (!p) return json({ message: "Invalid preset" }, 400);
        const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
        const code = Array.from(crypto.getRandomValues(new Uint8Array(8)), x => alphabet[x % alphabet.length]).join("");
        await env.DATA.put(`code:${code}`, JSON.stringify(p), { expirationTtl: 604800 });
        return json({ code });
      }
      if (path === "/presets/redeem" && request.method === "POST") {
        const code = clean((await readBody(request)).code, 8).toUpperCase();
        if (!CODE.test(code)) return json({ message: "Code not found" }, 404);
        const p = await env.DATA.get(`code:${code}`, "json");
        if (!p) return json({ message: "Code not found" }, 404);
        await env.DATA.delete(`code:${code}`);
        return json({ preset: p });
      }
      return json({ message: "Not found" }, 404);
    } catch (error) {
      if (error instanceof SyntaxError) return json({ message: "Invalid JSON" }, 400);
      if (error instanceof RangeError) return json({ message: error.message }, 413);
      return json({ message: "Server error" }, 500);
    }
  }
};
