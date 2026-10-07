import assert from 'node:assert/strict';
import test from 'node:test';
import { cardBackground, cardAccent } from './card-colors.mjs';

test('uses a readable partner background and falls back on light or invalid colours', () => {
  assert.equal(cardBackground('#183030'), '#183030');
  assert.equal(cardBackground('#F0F5FA'), '#061b2b');
  assert.equal(cardBackground('red'), '#061b2b');
});

test('partner highlight remains if visible on the selected background', () => {
  assert.equal(cardAccent('#A8D8FF', '#183030'), '#A8D8FF');
  assert.equal(cardAccent('#182020', '#183030'), '#a8d8ff');
});
