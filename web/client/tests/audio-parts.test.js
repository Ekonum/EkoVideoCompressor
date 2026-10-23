import { test } from 'node:test';
import assert from 'node:assert/strict';
import { clipAudioParts } from '../src/audio-parts.js';

const parts = [{ name: 'premier.m4a', start: 0, end: 10.066 }, { name: 'suite.m4a', start: 10.066, end: 20.132 }];
test('les repères suivent le rognage et les durées réelles encodées', () => {
  assert.deepEqual(clipAudioParts(parts, 5, 15), [
    { name: 'premier.m4a', start: 0, end: 5.066000000000001 },
    { name: 'suite.m4a', start: 5.066000000000001, end: 10 },
  ]);
  assert.deepEqual(clipAudioParts(parts, 12, 16), [{ name: 'suite.m4a', start: 0, end: 4 }]);
  assert.deepEqual(parts[0], { name: 'premier.m4a', start: 0, end: 10.066 });
});
test('une ancienne réunion ou des repères incohérents restent sans chapitres', () => {
  for (const data of [undefined, {}, [{ name: 'a', start: -1, end: 4 }], [...parts, { name: 'x', start: 4, end: 6 }]]) {
    assert.deepEqual(clipAudioParts(data), []);
  }
  assert.deepEqual(clipAudioParts(parts, 10, 5), []);
});
