import { api } from './api.js';

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


/** Encode une fenêtre du fichier et la fait écouter au serveur.
 *
 *  La sonde ne cherche pas à transcrire : elle veut savoir de qui et de
 *  quoi on parle, pour proposer le dossier Odoo qui servira de contexte
 *  à la vraie transcription. Cinq minutes suffisent, et le fichier ne
 *  quitte jamais la machine — seule cette fenêtre part.
 */
export function identifier(fichier, { audio, fenetre = 300, duree = 0 }) {
  // L'heure de *début* de l'enregistrement : la date du fichier est
  // celle de sa dernière écriture, donc la fin. Sur une réunion d'une
  // heure, viser la fin fait manquer la réunion elle-même.
  const moment = fichier.lastModified
    ? new Date(fichier.lastModified - (duree || 0) * 1000).toISOString()
    : '';
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL('./media-worker.js', import.meta.url), {
      type: 'module',
    });
    worker.onmessage = async ({ data }) => {
      if (data.kind === 'window-done') {
        worker.terminate();
        try {
          resolve(await api.probe(data.bytes, data.type, moment));
        } catch (error) {
          reject(error);
        }
      } else if (data.kind === 'window-error') {
        worker.terminate();
        reject(new Error(data.message));
      }
    };
    worker.onerror = (e) => { worker.terminate(); reject(new Error(e.message)); };
    worker.postMessage({
      kind: 'window',
      file: fichier,
      start: 0,
      end: duree ? Math.min(fenetre, duree) : fenetre,
      audio,
    });
  });
}
