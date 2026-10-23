import { useEffect, useState } from 'react';
import { preparation } from './preparation.js';
import { fileKey, uniqueFiles } from './organizer.js';
import { browserDraftStore, claimBrowserDraft, createDraftSession, packFile, unpackFile } from './draft-storage.js';

/** Les fichiers déposés en attendant d'être lancés.
 *
 *  Déposer dix enregistrements d'un coup ne doit pas obliger à tout
 *  régler d'un coup : le premier s'ouvre dans le formulaire, les autres
 *  attendent ici, visibles dans la bibliothèque, et passent un à un.
 *
 *  Une copie privée au navigateur permet de retrouver la préparation.
 *  Chaque onglet et chaque compte garde sa propre file.
 */

const MEDIA_EXTENSIONS = /\.(m4a|mp3|wav|aac|flac|ogg|opus|weba|mp4|m4v|mov|mkv|webm|avi)$/i;

let queue = [];
let launchRequest = null;
const subscribers = new Set();

let currentDraft = null;
let persistence = null, opening = null, saveTimer = null;
let persistenceError = '';
let pendingWrites = 0;
const notify = () => subscribers.forEach((callback) => callback());
function saveDraft() {
  if (!persistence) return;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    saveTimer = null; pendingWrites++;
    const files = uniqueFiles([...(currentDraft ? [currentDraft] : []), ...queue.map((entry) => entry.file)]);
    const entries = files.map((file) => ({ id: queue.find((entry) => entry.file === file)?.id || `queued-${crypto.randomUUID()}`, file: packFile(file) }));
    persistence.save({ entries, contexts: preparation.export(files) })
      .then(() => { if (persistenceError) { persistenceError = ''; notify(); } })
      .catch(() => { persistenceError = 'Cette file reste disponible dans cet onglet uniquement.'; notify(); })
      .finally(() => { pendingWrites--; notify(); });
    notify();
  }, 150);
  notify();
}
export function openFileQueue(owner) {
  return opening ||= (async () => {
    try {
      if (!owner) throw new Error('Compte inconnu.');
      persistence = createDraftSession({ store: browserDraftStore(), claim: claimBrowserDraft, session: sessionStorage });
      const saved = await persistence.open(owner);
      if (saved) {
        preparation.restore(saved.contexts);
        queue = saved.entries.map((entry) => ({ id: entry.id, file: unpackFile(entry.file) }));
        notify();
        preparation.schedule(queue.map((entry) => entry.file));
      }
      preparation.subscribe(saveDraft);
    } catch {
      persistence = null; persistenceError = 'Cette file reste disponible dans cet onglet uniquement.';
    }
  })();
}
export function setCurrentDraft(file, state) {
  currentDraft = file;
  if (file) {
    const remaining = queue.filter((entry) => fileKey(entry.file) !== fileKey(file));
    if (remaining.length !== queue.length) { queue = remaining; notify(); }
  }
  if (file && state) file.draftState = { ...state };
  saveDraft();
}
export function useDraftSaving() {
  useFileQueue();
  return Boolean(saveTimer || pendingWrites);
}
if (typeof window !== 'undefined') window.addEventListener('beforeunload', (event) => {
  if ((currentDraft || queue.length) && (saveTimer || pendingWrites || persistenceError)) {
    event.preventDefault(); event.returnValue = '';
  }
});
export function useQueuePersistence() {
  useFileQueue();
  return persistenceError;
}

function publish(next) {
  queue = next;
  subscribers.forEach((notify) => notify());
  preparation.schedule(queue.map((entry) => entry.file));
  saveDraft();
}

/** L'organisation se valide en une fois : aucun fichier ne disparaît
 *  pendant qu'on déplace ou assemble des morceaux dans la fenêtre. */
export function replaceQueue(files) {
  const previous = new Map(queue.map((entry) => [entry.file, entry]));
  publish(uniqueFiles(files).map((file) => previous.get(file) || {
    id: `queued-${crypto.randomUUID()}`, file,
  }));
}

/** Un fichier audio ou vidéo — le navigateur ne donne pas toujours le
 *  type, l'extension sert de repli. */
export function isMedia(file) {
  return /^(audio|video)\//.test(file.type || '') || MEDIA_EXTENSIONS.test(file.name || '');
}

/** Une réunion à retraiter, comme un fichier de la file.
 *
 *  Sa vidéo est déjà en stockage froid : le navigateur la relit de là,
 *  par plages, au lieu de demander le fichier d'origine — souvent jeté
 *  depuis. L'objet a le nom, le poids et la date d'un `File`, et dit en
 *  plus où lire, et quelle réunion il retraite. */
export function remoteFile(job) {
  const date = Date.parse(String(job.meeting_date || '').replace(' ', 'T'));
  return {
    name: job.filename,
    size: job.video_bytes,
    audioParts: job.audio_parts || [],
    type: '',
    // La date sert à distinguer deux réunions de même nom ; c'est
    // `meetingDate` qui date la réunion à l'écran de lancement.
    lastModified: Number.isNaN(date) ? 0 : date,
    remote: {
      jobId: job.job_id,
      url: `/api/jobs/${job.job_id}/video`,
      meetingDate: job.meeting_date || null,
    },
  };
}

/** Ajoute des fichiers, sans doublon : le même fichier déposé deux fois
 *  n'attend qu'une fois. */
export function enqueue(files, { front = false } = {}) {
  const known = new Set(queue.map((e) => fileKey(e.file)));
  const added = uniqueFiles(files)
    .filter((file) => !known.has(fileKey(file)))
    .map((file) => ({ id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, file }));
  if (added.length) publish(front ? [...added, ...queue] : [...queue, ...added]);
  return added.length;
}

export function removeFromQueue(id) {
  publish(queue.filter((e) => e.id !== id));
}

/** Retire et rend le prochain fichier — ou celui demandé. */
export function takeNext(id = null) {
  const entry = id ? queue.find((e) => e.id === id) : queue[0];
  if (!entry) return null;
  currentDraft = entry.file;
  publish(queue.filter((e) => e !== entry));
  return entry.file;
}

/** « Lancer » depuis la bibliothèque : l'écran de lancement le reprend
 *  en s'ouvrant. */
export function requestLaunch(id) {
  launchRequest = id;
}

/** Ouvre tout de suite dans l'écran de lancement, devant la file. */
export function launch(file) {
  enqueue([file], { front: true });
  const entry = queue.find((e) => fileKey(e.file) === fileKey(file));
  if (entry) requestLaunch(entry.id);
}

export function consumeLaunchRequest() {
  const id = launchRequest;
  launchRequest = null;
  return id ? takeNext(id) : null;
}

export function useFileQueue() {
  const [, refresh] = useState(0);
  useEffect(() => {
    const notify = () => refresh((n) => n + 1);
    subscribers.add(notify);
    return () => subscribers.delete(notify);
  }, []);
  return queue;
}

/** Un fichier est-il en train d'être glissé au-dessus de la page ? Les
 *  événements de glisser arrivent par paires entrée/sortie sur chaque
 *  élément traversé : on compte, plutôt que de clignoter. */
export function useFileDrag() {
  const [dragging, setDragging] = useState(false);
  useEffect(() => {
    let depth = 0;
    const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files');
    const enter = (e) => { if (hasFiles(e)) { depth += 1; setDragging(true); } };
    const leave = (e) => { if (hasFiles(e)) { depth = Math.max(0, depth - 1); if (!depth) setDragging(false); } };
    // Lâché à côté de la zone, le navigateur ouvrirait le fichier à la
    // place de l'application : on l'en empêche partout.
    const over = (e) => { if (hasFiles(e)) e.preventDefault(); };
    const drop = (e) => { if (hasFiles(e)) e.preventDefault(); depth = 0; setDragging(false); };
    window.addEventListener('dragenter', enter);
    window.addEventListener('dragleave', leave);
    window.addEventListener('dragover', over);
    window.addEventListener('drop', drop);
    return () => {
      window.removeEventListener('dragenter', enter);
      window.removeEventListener('dragleave', leave);
      window.removeEventListener('dragover', over);
      window.removeEventListener('drop', drop);
    };
  }, []);
  return dragging;
}
