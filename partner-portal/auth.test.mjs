import assert from 'node:assert/strict';
import test from 'node:test';
import { hashPassword, verifyPassword, createSessionToken, tokenHash, sameOrigin } from './auth.mjs';

test('passwords are salted and verified without storing plaintext', async () => {
  const a = await hashPassword('long-password-123');
  const b = await hashPassword('long-password-123');
  assert.notEqual(a, b);
  assert(await verifyPassword('long-password-123', a));
  assert.equal(await verifyPassword('wrong-password', a), false);
  assert.equal(await verifyPassword('long-password-123', 'bad'), false);
});

test('sessions use unpredictable tokens and unsafe requests need same origin', () => {
  assert.notEqual(createSessionToken(), createSessionToken());
  assert.equal(tokenHash('a').length, 64);
  assert(sameOrigin(new Request('https://example.org/api', { headers: { Origin: 'https://example.org' } })));
  assert(!sameOrigin(new Request('https://example.org/api', { headers: { Origin: 'https://evil.example' } })));
});
