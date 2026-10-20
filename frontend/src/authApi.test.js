import { test } from 'node:test';
import assert from 'node:assert/strict';
import { getCurrentUser, loginUser, logoutUser, signupUser } from './authApi.js';

test('login posts credentials and returns safe user data', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async (url, options) => {
      assert.equal(url, '/api/auth/login');
      assert.equal(options.method, 'POST');
      assert.equal(options.credentials, 'same-origin');
      assert.deepEqual(JSON.parse(options.body), { email: 'test@example.com', password: ' sample password ' });
      return new Response(JSON.stringify({ id: 1, name: 'Test' }), { status: 200 });
    };
    assert.deepEqual(await loginUser('test@example.com', ' sample password '), { id: 1, name: 'Test' });
  } finally { globalThis.fetch = original; }
});

test('an unauthenticated /me response means no current user', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response('{}', { status: 401 });
    assert.equal(await getCurrentUser(), null);
    await assert.rejects(loginUser('test@example.com', 'wrong'), /Request failed \(401\)/);
  } finally { globalThis.fetch = original; }
});

test('signup sends its payload and logout uses POST with cookies', async () => {
  const original = globalThis.fetch;
  const requests = [];
  try {
    globalThis.fetch = async (url, options) => {
      requests.push({ url, options });
      return new Response('{}', { status: 200 });
    };
    const payload = { name: 'Test', email: 'test@example.com', password: 'sample-only-password' };
    await signupUser(payload);
    await logoutUser();
    assert.deepEqual(JSON.parse(requests[0].options.body), payload);
    assert.equal(requests[1].url, '/api/auth/logout');
    assert.equal(requests[1].options.method, 'POST');
    assert.equal(requests[1].options.credentials, 'same-origin');
  } finally { globalThis.fetch = original; }
});

test('backend failures are surfaced rather than mistaken for successful logout', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Please try again.' }), { status: 503 });
    await assert.rejects(logoutUser(), /Please try again/);
    globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
    await assert.rejects(getCurrentUser(), /Cannot reach the server/);
  } finally { globalThis.fetch = original; }
});
