import { api } from './api.js';
import { startMediaWorker } from './media-worker-client.js';

/** Ne recrée ni réunion, ni plan de découpage, ni contexte. */
export function createArchivedResumer({ job, finalize, startWorker }) {
  const running = new Map();
  function resume(jobId, file, onProgress = () => {}) {
    if (running.has(jobId)) return running.get(jobId);
    const task = (async () => {
      const plan = await job(jobId);
      if (plan.status === 'cancelled') throw new Error('Cette transcription a été interrompue.');
      if (!plan.missing_chunks.length) {
        if (plan.status === 'a_finaliser') await finalize(jobId);
        return;
      }
      await new Promise((resolve, reject) => {
        let worker;
        const finish = (error) => { worker?.terminate(); if (error) reject(error); else resolve(); };
        worker = startWorker(({ data }) => {
          if (data.kind === 'error') finish(new Error(data.message));
          else if (data.kind === 'done') finish();
          else onProgress(data);
        }, finish);
        worker?.postMessage({ file, jobId, chunks: plan.chunks, audio: plan.audio,
          pending: plan.missing_chunks, offset: 0 });
      });
    })().finally(() => running.delete(jobId));
    running.set(jobId, task);
    return task;
  }
  resume.isBusy = () => running.size > 0;
  return resume;
}
export const resumeArchived = createArchivedResumer({ job: api.job, finalize: api.finalize, startWorker: startMediaWorker });

if (typeof window !== 'undefined') window.addEventListener('beforeunload', (event) => {
  if (resumeArchived.isBusy()) { event.preventDefault(); event.returnValue = ''; }
});
