import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createPreparer } from '../src/preparation.js';

const tick = () => new Promise((resolve) => setImmediate(resolve));
const file = (name) => new File(['audio'], name, { type: 'audio/mp4', lastModified: 1700000000000 });
function harness(identify) {
  return createPreparer({ snapshot: async (f) => f, durationOf: async () => 60,
    identify, settings: async () => ({ audio: {} }) });
}
test('l’ouverture partage la recherche en cours puis réutilise le contexte prêt', async () => {
  let finish;
  let calls = 0;
  const store = harness(() => { calls++; return new Promise((resolve) => { finish = resolve; }); });
  const input = file('réunion.m4a');
  store.schedule([input]);
  await tick();
  const foreground = store.prepare(input);
  finish({ hints: { summary: 'Le bon dossier' } });
  assert.equal((await foreground).hints.summary, 'Le bon dossier');
  assert.equal((await store.prepare(input)).hints.summary, 'Le bon dossier');
  assert.equal(calls, 1);
});
test('réordonner ou retirer une attente prend effet avant la recherche suivante', async () => {
  const calls = [];
  let finish;
  const store = harness((f) => {
    calls.push(f.name);
    return calls.length === 1 ? new Promise((resolve) => { finish = resolve; }) : Promise.resolve({});
  });
  const a = file('a.m4a'), b = file('b.m4a'), c = file('c.m4a');
  store.schedule([a, b, c]);
  await tick();
  store.schedule([c]);
  finish({});
  await tick(); await tick();
  assert.deepEqual(calls, ['a.m4a', 'c.m4a']);
});
test('un échec ne bloque pas la file et peut se réessayer à l’ouverture', async () => {
  let attempts = 0;
  const store = harness(async () => {
    if (++attempts === 1) throw new Error('Réseau coupé');
    return { hints: { summary: 'Retrouvé' } };
  });
  const input = file('réunion.m4a');
  store.schedule([input]);
  await tick();
  assert.equal(store.get(input).status, 'error');
  assert.equal((await store.prepare(input, { retry: true })).hints.summary, 'Retrouvé');
});
test('changer la date ne reprend pas le contexte de la date précédente', async () => {
  let calls = 0;
  const store = harness(async (_file, options) => { calls++; return { moment: options.moment }; });
  const input = file('réunion.m4a');
  await store.prepare(input, { moment: '2026-10-21T12:59:00.000Z' });
  assert.equal((await store.prepare(input, { moment: '2026-10-22T12:59:00.000Z' })).moment,
    '2026-10-22T12:59:00.000Z');
  assert.equal(calls, 2);
});

test('un contexte restauré est réutilisé sans recherche ni dépôt Odoo automatique', async () => {
  const first = harness(async () => ({ clues: { resume: 'Réunion' }, investigation: { auto: true, record: { id: 42 } } }));
  const input = file('réunion.m4a'); await first.prepare(input);
  const saved = first.export([input]);
  const restored = harness(() => assert.fail('le contexte existe déjà'));
  restored.restore(saved); const result = await restored.prepare(input, { moment: saved[0].moment });
  assert.equal(result.clues.resume, 'Réunion'); assert.equal(result.investigation.auto, false);
  assert.equal(result.investigation.record.id, 42);
});
