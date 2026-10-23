import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createDraftSession, packFile, unpackFile } from '../src/draft-storage.js';

function environment() {
  const records = new Map(), locks = new Set();
  return { records, store: { list: async (owner) => [...records.values()].filter((r) => r.key.startsWith(`${owner}\0`)),
    put: async (r) => records.set(r.key, structuredClone(r)), delete: async (key) => records.delete(key) },
    claim: async (key) => { if (locks.has(key)) return null; locks.add(key); return () => locks.delete(key); },
    session: () => { const values = new Map(); return { getItem: (k) => values.get(k), setItem: (k, v) => values.set(k, v) }; } };
}
const value = (name) => ({ entries: [{ id: name }], contexts: [] });
test('réouverture et rechargement conservent la dernière sélection, les retraits et le compte', async () => {
  const env = environment(), session = env.session();
  const first = createDraftSession({ ...env, session }); await first.open('robin');
  await first.save(value('ancien')); await first.save(value('dernier')); first.close();
  const reload = createDraftSession({ ...env, session });
  assert.deepEqual(await reload.open('robin'), value('dernier'));
  await reload.save({ entries: [], contexts: [] }); reload.close();
  const other = createDraftSession({ ...env, session: env.session() });
  assert.equal(await other.open('autre'), null); other.close();
  const reopened = createDraftSession({ ...env, session: env.session() });
  assert.equal(await reopened.open('robin'), null); reopened.close();
});
test('un deuxième onglet ne reprend pas une file encore ouverte, même avec session copiée', async () => {
  const env = environment(), session = env.session();
  const first = createDraftSession({ ...env, session }); await first.open('robin'); await first.save(value('premier'));
  const second = createDraftSession({ ...env, session }); assert.equal(await second.open('robin'), null);
  await second.save(value('second')); second.close();
  const third = createDraftSession({ ...env, session: env.session() });
  assert.deepEqual(await third.open('robin'), value('second')); third.close(); first.close();
});
test('une panne de stockage n’annonce pas un succès et ne fait pas revenir une ancienne sélection', async () => {
  const env = environment(); const session = createDraftSession({ ...env, session: env.session() });
  await session.open('robin'); await session.save(value('ancien'));
  env.store.put = async () => { throw new Error('QuotaExceededError'); };
  await assert.rejects(session.save(value('nouveau')), /Quota/);
  assert.equal(env.records.size, 0); session.close();
});
test('le fichier restauré contient les octets, l’ordre interne, les repères et les réglages', async () => {
  const a = new File(['premier'], 'a.m4a'), b = new File(['second'], 'b.m4a');
  const merged = new File(['ensemble'], 'réunion.m4a'); merged.mergedParts = [b, a];
  merged.audioParts = [{ name: 'b.m4a', start: 0, end: 10 }]; merged.draftState = { debut: 2, client: 'Essai', dossier: { id: 42, auto: true } };
  const restored = unpackFile(packFile(merged));
  assert.equal(await restored.text(), 'ensemble');
  assert.deepEqual(await Promise.all(restored.mergedParts.map((f) => f.text())), ['second', 'premier']);
  assert.deepEqual(restored.audioParts, merged.audioParts); assert.equal(restored.draftState.debut, 2); assert.equal(restored.draftState.dossier.auto, false);
  assert.equal(merged.draftState.dossier.auto, true);
});
