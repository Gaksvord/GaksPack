const DEVICE = /^[0-9a-f]{64}$/;
const SHA = /^[0-9a-f]{64}$/;
const CODE = /^[A-Z0-9]{8}$/;
const NICK = /^[A-Za-z0-9]{1,20}$/;
const SESSION_TTL = 2592000;
const json = (value, status = 200) => Response.json(value, { status, headers: { "Cache-Control": "no-store" } });
const clean = (value, max) => typeof value === "string" ? value.replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, max) : "";
const hex = bytes => Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
const random = size => hex(crypto.getRandomValues(new Uint8Array(size)));
async function sha(value) { return hex(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)))); }
async function passwordHash(password, salt) {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveBits"]);
  return hex(new Uint8Array(await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt: new TextEncoder().encode(salt), iterations: 100000 }, key, 256)));
}
async function account(request, env) {
  const token = (request.headers.get("authorization") || "").match(/^Bearer ([0-9a-f]{64})$/)?.[1];
  if (!token) return null;
  return env.DATA.get(`session:${await sha(token)}`, "json");
}
async function session(env, nick) {
  const token = random(32);
  await env.DATA.put(`session:${await sha(token)}`, JSON.stringify({ nick }), { expirationTtl: SESSION_TTL });
  return token;
}

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

async function presets(env, device, user = null) {
  const keys = await env.DATA.list({ prefix: "preset:", limit: 1000 });
  const records = await Promise.all(keys.keys.slice(0, 200).map(k => env.DATA.get(k.name, "json")));
  return Promise.all(records.filter(Boolean).map(async ({ device: owner, ...p }) => ({
    ...p,
    likes: p.likes || 0,
    applications: p.applications || 0,
    createdAt: p.createdAt || 0,
    mine: p.owner ? p.owner === user?.nick : owner === device,
    liked: !!user && !!await env.DATA.get(`like:${p.id}:${user.nick.toLowerCase()}`),
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
      if (path === "/auth/register" && request.method === "POST") {
        const body = await readBody(request, 4096);
        if (!NICK.test(body.nick || "") || typeof body.password !== "string" || body.password.length < 1 || body.password.length > 512) return json({ message: "Invalid username or password" }, 400);
        const key = `user:${body.nick.toLowerCase()}`;
        if (await env.DATA.get(key)) return json({ message: "Username already taken" }, 409);
        const salt = random(16);
        await env.DATA.put(key, JSON.stringify({ nick: body.nick, salt, hash: await passwordHash(body.password, salt) }));
        return json({ nick: body.nick, token: await session(env, body.nick) });
      }
      if (path === "/auth/login" && request.method === "POST") {
        const body = await readBody(request, 4096);
        if (!NICK.test(body.nick || "") || typeof body.password !== "string") return json({ message: "Invalid username or password" }, 400);
        const attemptKey = `authfail:${(request.headers.get("cf-connecting-ip") || "local").slice(0, 64)}:${body.nick.toLowerCase()}`;
        const attempts = Number(await env.DATA.get(attemptKey) || 0);
        if (attempts >= 8) return json({ message: "Too many login attempts" }, 429);
        const user = await env.DATA.get(`user:${body.nick.toLowerCase()}`, "json");
        if (!user || user.hash !== await passwordHash(body.password, user.salt)) {
          await env.DATA.put(attemptKey, String(attempts + 1), { expirationTtl: 600 });
          return json({ message: "Invalid username or password" }, 401);
        }
        await env.DATA.delete(attemptKey);
        return json({ nick: user.nick, token: await session(env, user.nick) });
      }
      if (path === "/auth/me" && request.method === "GET") {
        const user = await account(request, env);
        return user ? json({ nick: user.nick }) : json({ message: "Login required" }, 401);
      }
      if (path === "/auth/logout" && request.method === "POST") {
        const token = (request.headers.get("authorization") || "").match(/^Bearer ([0-9a-f]{64})$/)?.[1];
        if (token) await env.DATA.delete(`session:${await sha(token)}`);
        return json({ message: "Signed out" });
      }
      if (request.method === "GET" && path === "/whoami") return json({ role: "guest" });
      if (request.method === "POST" && path === "/ping") return json({ ok: true });
      if (request.method === "GET" && path === "/stats") return json({ online: 0, total: 0 });

      if (path === "/presets" && request.method === "GET") {
        return json({ presets: await presets(env, url.searchParams.get("device"), await account(request, env)) });
      }
      if (path === "/presets" && request.method === "POST") {
        const user = await account(request, env);
        if (!user) return json({ message: "Login required" }, 401);
        const p = presetFrom(await readBody(request));
        if (!p) return json({ message: "Invalid preset" }, 400);
        p.author = user.nick;
        p.owner = user.nick;
        const existing = await presets(env, p.device, user);
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
        const user = await account(request, env);
        if (!user) return metric[2] === "apply" ? json({ counted: false }) : json({ message: "Login required" }, 401);
        const id = Number(metric[1]);
        const preset = await env.DATA.get(`preset:${id}`, "json");
        if (!preset) return json({ message: "Preset not found" }, 404);
        if (metric[2] === "like") {
          const voteKey = `like:${id}:${user.nick.toLowerCase()}`;
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
        if (!Number.isInteger(body.id)) return json({ message: "Invalid request" }, 400);
        const p = await env.DATA.get(`preset:${body.id}`, "json");
        const user = await account(request, env);
        if (!p || (p.owner ? p.owner !== user?.nick : p.device !== body.device)) return json({ message: "Preset not found" }, 404);
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
