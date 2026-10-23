import { test } from 'node:test';
import assert from 'node:assert/strict';
import { archiver } from '../src/archivage.js';

test('l’archive reçoit le fichier assemblé intact sans second encodage', async () => {
  const previousFetch = globalThis.fetch;
  const previousWorker = globalThis.Worker;
  const previousStorage = Object.getOwnPropertyDescriptor(navigator, 'storage');
  const requests = [];
  try {
    Object.defineProperty(navigator, 'storage', { configurable: true, value: {
      getDirectory: async () => ({ getFileHandle: async () => ({}), removeEntry: async () => {} }),
    } });
    globalThis.Worker = class { constructor() { throw new Error('Un deuxième encodage a démarré'); } };
    globalThis.fetch = async (url, options) => {
      requests.push({ url, ...options });
      return new Response(JSON.stringify({ morceau: 1024 }), { status: 200 });
    };
    const merged = new File(['audio assemblé'], 'réunion.m4a', { type: 'audio/mp4' });
    merged.mergedParts = [new File(['a'], 'a.m4a'), new File(['b'], 'b.m4a')];
    await archiver({ fichier: merged, cible: { cle: 'test', jobId: 7 }, audio: true });
    assert.deepEqual(requests.map((r) => r.method), ['POST', 'PUT']);
    assert.equal(JSON.parse(requests[0].body).taille, merged.size);
    assert.equal(await requests[1].body.text(), await merged.text());
  } finally {
    globalThis.fetch = previousFetch;
    globalThis.Worker = previousWorker;
    if (previousStorage) Object.defineProperty(navigator, 'storage', previousStorage);
    else delete navigator.storage;
  }
});
