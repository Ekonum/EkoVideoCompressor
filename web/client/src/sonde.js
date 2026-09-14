/** Sonde la durée d'un fichier sans charger Mediabunny sur le fil
 *  principal : le worker le fait et se retire aussitôt.
 */
export function sonderDuree(fichier) {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL('./media-worker.js', import.meta.url), {
      type: 'module',
    });
    worker.onmessage = ({ data }) => {
      if (data.kind === 'probed') { worker.terminate(); resolve(data.duration); }
      else if (data.kind === 'probe-error') { worker.terminate(); reject(new Error(data.message)); }
    };
    worker.onerror = (e) => { worker.terminate(); reject(new Error(e.message)); };
    worker.postMessage({ kind: 'probe', file: fichier });
  });
}
