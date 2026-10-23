import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sonderDuree } from '../src/sonde.js';

function mockWorker(action) {
  const previous = globalThis.Worker;
  globalThis.Worker = class {
    postMessage() { queueMicrotask(() => action(this)); }
    terminate() { this.terminated = true; }
  };
  return () => { globalThis.Worker = previous; };
}

test('un module absent demande un rechargement sans accuser le fichier', async () => {
  const restore = mockWorker((worker) => worker.onerror({ message: '' }));
  try {
    await assert.rejects(sonderDuree(new File(['audio'], 'réunion.m4a')), (error) => {
      assert.equal(error.needsReload, true);
      assert.match(error.message, /Recharge la page/);
      assert.doesNotMatch(error.message, /Fichier illisible/);
      return true;
    });
  } finally { restore(); }
});

test('une vraie erreur de lecture après démarrage reste une erreur de fichier', async () => {
  const restore = mockWorker((worker) => {
    worker.onmessage({ data: { kind: 'ready' } });
    worker.onmessage({ data: { kind: 'probe-error', message: 'Format inconnu' } });
  });
  try {
    await assert.rejects(sonderDuree(new File(['audio'], 'réunion.m4a')), (error) => {
      assert.equal(error.needsReload, undefined);
      assert.equal(error.message, 'Format inconnu');
      return true;
    });
  } finally { restore(); }
});

test('le signal de démarrage ne perturbe pas une lecture réussie', async () => {
  const restore = mockWorker((worker) => {
    worker.onmessage({ data: { kind: 'ready' } });
    worker.onmessage({ data: { kind: 'probed', duration: 123 } });
  });
  try { assert.equal(await sonderDuree(new File(['audio'], 'réunion.m4a')), 123); }
  finally { restore(); }
});
test('une erreur d’exécution après démarrage ne fait pas croire à un module absent', async () => {
  const restore = mockWorker((worker) => {
    worker.onmessage({ data: { kind: 'ready' } });
    worker.onerror({ message: 'Erreur du décodeur' });
  });
  try {
    await assert.rejects(sonderDuree(new File(['audio'], 'réunion.m4a')), (error) => {
      assert.equal(error.needsReload, undefined);
      assert.equal(error.message, 'Erreur du décodeur');
      return true;
    });
  } finally { restore(); }
});
