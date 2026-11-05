import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/index.js';

const data = new Map();
const env = { DATA: {
  async get(key, type) {
    const value = data.get(key);
    if (value === undefined) return null;
    if (type === 'json') return JSON.parse(value);
    return value;
  },
  async put(key, value) { data.set(key, value); },
  async delete(key) { data.delete(key); },
  async list({ prefix }) { return { keys: [...data.keys()].filter(k => k.startsWith(prefix)).map(name => ({ name })) }; }
} };
const base = 'https://gakspack-test.workers.dev';
const device = 'a'.repeat(64);
const call = (path, method = 'GET', body, headers) => worker.fetch(new Request(base + path, { method, body, headers }), env);
let registrationNumber = 0;
const register = async nick => {
  const device = (++registrationNumber).toString(16).padStart(64, 'a');
  const response = await call('/auth/register', 'POST', JSON.stringify({ nick, password: 'пароль с пробелами 123', device }));
  assert.equal(response.status, 200);
  return { authorization: `Bearer ${(await response.json()).token}`, device };
};

test('share, list, redeem and remove a preset', async () => {
  const auth = await register('GaksTestOne');
  const preset = { name: 'Мой набор', author: 'Gaksvord', device, styles: { crystal: 'crystal_blue' }, local: {}, extras: {} };
  const publish = await call('/presets', 'POST', JSON.stringify(preset), auth);
  assert.equal(publish.status, 200);
  const { id } = await publish.json();
  assert.ok(Number.isInteger(id));
  const list = await (await call('/presets?device=' + device, 'GET', undefined, auth)).json();
  assert.equal(list.presets.length, 1);
  assert.equal(list.presets[0].mine, true);
  assert.equal(list.presets[0].name, 'Мой набор');
  assert.equal(list.presets[0].author, 'GaksTestOne');
  const code = await (await call('/presets/code', 'POST', JSON.stringify(preset))).json();
  assert.equal(code.code.length, 8);
  const redeemed = await (await call('/presets/redeem', 'POST', JSON.stringify({ code: code.code }))).json();
  assert.equal(redeemed.preset.name, 'Мой набор');
  const removed = await call('/presets', 'DELETE', JSON.stringify({ id, device }), auth);
  assert.equal(removed.status, 200);
  assert.equal((await call('/presets', 'POST', JSON.stringify(preset), auth)).status, 429);
  assert.equal((await (await call('/presets?device=' + device)).json()).presets.length, 0);
});

test('stores and retrieves a local texture file by SHA-256', async () => {
  const bytes = new TextEncoder().encode('PK test zip bytes');
  const uploaded = await (await call('/lfile', 'POST', bytes)).json();
  assert.match(uploaded.sha, /^[0-9a-f]{64}$/);
  const downloaded = await call('/lfile/' + uploaded.sha);
  assert.equal(downloaded.status, 200);
  assert.deepEqual(new Uint8Array(await downloaded.arrayBuffer()), bytes);
});

test('rejects malformed preset requests without a server error', async () => {
  const auth = await register('GaksTestBad');
  assert.equal((await call('/presets', 'POST', 'null', auth)).status, 400);
  assert.equal((await call('/presets', 'POST', '{', auth)).status, 400);
  assert.equal((await call('/presets', 'POST', ' '.repeat(65537), auth)).status, 413);
});

test('likes toggle and applications count once per account, excluding the author', async () => {
  const auth = await register('GaksTestTwo');
  const voter = await register('GaksVoter');
  const preset = { name: 'Votes', author: 'Gaksvord', device, styles: {}, local: {}, extras: {} };
  const { id } = await (await call('/presets', 'POST', JSON.stringify(preset), auth)).json();
  const vote = JSON.stringify({ device: 'b'.repeat(64) });
  assert.equal((await (await call(`/presets/${id}/like`, 'POST', vote, auth)).json()).counted, false);
  assert.equal((await (await call(`/presets/${id}/apply`, 'POST', vote, auth)).json()).counted, false);
  assert.equal((await (await call(`/presets/${id}/like`, 'POST', vote, voter)).json()).liked, true);
  assert.equal((await (await call(`/presets/${id}/apply`, 'POST', vote, voter)).json()).counted, true);
  assert.equal((await (await call(`/presets/${id}/apply`, 'POST', vote, voter)).json()).counted, false);
  const guest = await (await call(`/presets/${id}/apply`, 'POST', vote)).json();
  assert.equal(guest.counted, false);
  const list = await (await call('/presets?device=' + 'b'.repeat(64), 'GET', undefined, voter)).json();
  const result = list.presets.find(p => p.id === id);
  assert.equal(result.likes, 1);
  assert.equal(result.applications, 1);
  assert.equal(result.liked, true);
  assert.ok(result.createdAt > 0);
  assert.equal((await (await call(`/presets/${id}/like`, 'POST', vote, voter)).json()).liked, false);
  const after = await (await call('/presets?device=' + 'b'.repeat(64), 'GET', undefined, voter)).json();
  assert.equal(after.presets.find(p => p.id === id).likes, 0);
  await call('/presets', 'DELETE', JSON.stringify({ id, device }), auth);
});

test('publishing and voting require login', async () => {
  const preset = { name: 'Guest', author: 'Spoofed', device, styles: {}, local: {}, extras: {} };
  assert.equal((await call('/presets', 'POST', JSON.stringify(preset))).status, 401);
  assert.equal((await call('/presets/1/like', 'POST', '{}')).status, 401);
  assert.equal((await call('/auth/register', 'POST', JSON.stringify({ nick: 'Ник', password: 'x' }))).status, 400);
  assert.equal((await call('/auth/login', 'POST', JSON.stringify({ nick: 'GaksTestOne', password: 'wrong', device }))).status, 401);
});

test('account can sign in again and logout revokes the session', async () => {
  const auth = await register('A1');
  const login = await call('/auth/login', 'POST', JSON.stringify({ nick: 'a1', password: 'пароль с пробелами 123', device: auth.device }));
  assert.equal(login.status, 200);
  const second = { authorization: `Bearer ${(await login.json()).token}` };
  assert.equal((await call('/auth/me', 'GET', undefined, second)).status, 200);
  await call('/auth/logout', 'POST', undefined, auth);
  assert.equal((await call('/auth/me', 'GET', undefined, auth)).status, 401);
  assert.equal((await call('/auth/me', 'GET', undefined, second)).status, 200);
  assert.equal((await call('/auth/register', 'POST', JSON.stringify({ nick: 'A2', password: 'other', device: auth.device }))).status, 429);
});

test('three wrong passwords escalate 3, 5, 10, 20, 40, 60 minutes and correct login resets', async () => {
  const auth = await register('LockProbe');
  const key = `authlock:${auth.device}`;
  const bad = JSON.stringify({ nick: 'LockProbe', password: 'wrong', device: auth.device });
  for (const minutes of [3, 5, 10, 20, 40, 60, 60]) {
    assert.equal((await call('/auth/login', 'POST', bad)).status, 401);
    assert.equal((await call('/auth/login', 'POST', bad)).status, 401);
    const locked = await call('/auth/login', 'POST', bad);
    assert.equal(locked.status, 429);
    assert.equal((await locked.json()).retryAfter, minutes * 60);
    const state = JSON.parse(data.get(key));
    state.until = Date.now() - 1;
    data.set(key, JSON.stringify(state));
  }
  const good = await call('/auth/login', 'POST', JSON.stringify({ nick: 'LockProbe', password: 'пароль с пробелами 123', device: auth.device }));
  assert.equal(good.status, 200);
  assert.equal(data.has(key), false);
});
