import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createArchivedResumer } from '../src/resume.js';

test('la reprise conserve le plan et n’envoie que les fenêtres manquantes, même après double clic', async () => {
  let finish, message, jobs = 0;
  const plan = { status: 'erreur', chunks: [{ index: 0, start: 0, end: 30 }, { index: 1, start: 30, end: 60 }],
    missing_chunks: [1], audio: { codec: 'mp3' } };
  const resume = createArchivedResumer({ job: async () => { jobs++; return plan; },
    startWorker: (onMessage) => { finish = onMessage; return { postMessage: (m) => { message = m; }, terminate() {} }; } });
  const file = { remote: { url: '/api/jobs/42/video' } };
  const first = resume(42, file), duplicate = resume(42, file);
  assert.equal(first, duplicate); await new Promise(setImmediate);
  assert.deepEqual(message, { file, jobId: 42, chunks: plan.chunks, audio: plan.audio, pending: [1], offset: 0 });
  finish({ data: { kind: 'done' } }); await first; assert.equal(jobs, 1); assert.equal(resume.isBusy(), false);
});
test('aucun encodage si tout est déjà envoyé ; la finalisation seule peut reprendre', async () => {
  let finalized = 0;
  const resume = createArchivedResumer({ job: async () => ({ status: 'a_finaliser', missing_chunks: [] }),
    finalize: async () => finalized++, startWorker: () => assert.fail('pas de réencodage') });
  await resume(42, {}); assert.equal(finalized, 1);
});
test('un échec de reprise reste réessayable sans nouvelle réunion', async () => {
  const resume = createArchivedResumer({ job: async () => { throw new Error('Hors ligne'); } });
  await assert.rejects(resume(42, {}), /Hors ligne/); assert.equal(resume.isBusy(), false);
  await assert.rejects(resume(42, {}), /Hors ligne/);
});
