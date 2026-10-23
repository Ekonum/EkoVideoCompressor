/** Un échec du module ne prouve rien sur la lisibilité du fichier. */
export class MediaModuleUnavailableError extends Error {
  constructor() {
    super('Le module audio de cette page n’a pas pu démarrer. Recharge la page pour réessayer avec la version actuelle.');
    this.name = 'MediaModuleUnavailableError';
    this.needsReload = true;
  }
}

export function startMediaWorker(onMessage, onError) {
  let worker;
  let ready = false;
  try {
    worker = new Worker(new URL('./media-worker.js', import.meta.url), { type: 'module' });
  } catch {
    onError(new MediaModuleUnavailableError());
    return null;
  }
  worker.onmessage = (event) => {
    if (event.data.kind === 'ready') ready = true;
    else onMessage(event);
  };
  worker.onerror = (event) => {
    worker.terminate();
    onError(ready ? new Error(event.message || 'Le traitement audio a échoué.') : new MediaModuleUnavailableError());
  };
  return worker;
}
