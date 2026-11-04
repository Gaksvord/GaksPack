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

test('share, list, redeem and remove a preset', async () => {
  const preset = { name: 'Мой набор', author: 'Gaksvord', device, styles: { crystal: 'crystal_blue' }, local: {}, extras: {} };
  const publish = await call('/presets', 'POST', JSON.stringify(preset), { 'content-type': 'application/json' });
  assert.equal(publish.status, 200);
  const { id } = await publish.json();
  assert.ok(Number.isInteger(id));
  const list = await (await call('/presets?device=' + device)).json();
  assert.equal(list.presets.length, 1);
  assert.equal(list.presets[0].mine, true);
  assert.equal(list.presets[0].name, 'Мой набор');
  const code = await (await call('/presets/code', 'POST', JSON.stringify(preset))).json();
  assert.equal(code.code.length, 8);
  const redeemed = await (await call('/presets/redeem', 'POST', JSON.stringify({ code: code.code }))).json();
  assert.equal(redeemed.preset.name, 'Мой набор');
  const removed = await call('/presets', 'DELETE', JSON.stringify({ id, device }));
  assert.equal(removed.status, 200);
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
  assert.equal((await call('/presets', 'POST', 'null')).status, 400);
  assert.equal((await call('/presets', 'POST', '{')).status, 400);
  assert.equal((await call('/presets', 'POST', ' '.repeat(65537))).status, 413);
});
