const temporaryFiles = new Set();
// Ces fichiers ne servent qu'à cet onglet. Le navigateur ne garantit
// pas les tâches asynchrones à sa fermeture : le nettoyage reste tenté.
if (typeof window !== 'undefined') window.addEventListener('pagehide', (event) => {
  if (!event.persisted) navigator.storage.getDirectory().then((root) =>
    Promise.all([...temporaryFiles].map((name) => root.removeEntry(name).catch(() => {})))).catch(() => {});
});

/** Assemblage local : les originaux restent intacts et ne sont pas envoyés. */
export async function mergeAudioFiles(files, { onProgress = () => {}, signal } = {}) {
  const root = await navigator.storage.getDirectory();
  const name = `joined-${crypto.randomUUID()}.m4a`;
  temporaryFiles.add(name);
  temporaryFiles.add(`${name}.part`);
  const handle = await root.getFileHandle(name, { create: true });
  let worker;
  try {
    const result = await new Promise((resolve, reject) => {
      worker = new Worker(new URL('./merge-audio-worker.js', import.meta.url), { type: 'module' });
      const abort = () => { worker.terminate(); reject(new DOMException('Assemblage annulé.', 'AbortError')); };
      const finish = (callback, value) => {
        signal?.removeEventListener('abort', abort);
        worker.terminate();
        callback(value);
      };
      worker.onmessage = ({ data }) => {
        if (data.kind === 'progress') onProgress(data);
        else if (data.kind === 'done') finish(resolve, data);
        else if (data.kind === 'error') finish(reject, new Error(data.message));
      };
      worker.onerror = (error) => finish(reject, new Error(error.message || 'Le module audio n’a pas pu démarrer. Recharge la page puis réessaie.'));
      signal?.addEventListener('abort', abort, { once: true });
      if (signal?.aborted) return abort();
      worker.postMessage({ files, handle, temporaryName: `${name}.part` });
    });
    const blob = await handle.getFile();
    const file = new File([blob], `${files[0].name.replace(/\.[^.]+$/, '')} — réunion complète.m4a`, {
      type: 'audio/mp4',
      // Le formulaire déduit le début de la date de fin : le début de la
      // première partie doit rester le même après l'assemblage.
      lastModified: files[0].lastModified + (result.duration - result.firstDuration) * 1000,
    });
    file.mergedParts = files;
    return file;
  } catch (error) {
    await root.removeEntry(name).catch(() => {});
    temporaryFiles.delete(name);
    throw error;
  } finally {
    worker?.terminate();
    await root.removeEntry(`${name}.part`).catch(() => {});
    temporaryFiles.delete(`${name}.part`);
  }
}
