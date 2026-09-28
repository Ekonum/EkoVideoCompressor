import { useCallback, useEffect, useState } from 'react';
import { api } from './api.js';

/** Pilote les transcriptions : création, encodage, envoi, suivi.
 *
 *  Les tâches vivent **hors des composants**. Le navigateur n'a qu'un
 *  rôle — encoder les fenêtres et les envoyer — et il le tient même quand
 *  on a quitté l'écran « Nouvelle transcription ». Une fois les fenêtres
 *  parties, le serveur finit seul : on peut revenir à la bibliothèque,
 *  lancer une deuxième transcription, voire fermer l'onglet.
 */

const taches = new Map(); // cle → état d'une transcription
const abonnes = new Set();

function publier(cle, champs) {
  taches.set(cle, { ...(taches.get(cle) || {}), ...champs });
  abonnes.forEach((f) => f());
}

function majFenetre(cle, index, champs) {
  const tache = taches.get(cle);
  if (!tache) return;
  publier(cle, {
    fenetres: tache.fenetres.map((f) => (f.index === index ? { ...f, ...champs } : f)),
  });
}

/** Encode ou envoie encore depuis cet onglet : le fermer tuerait le travail. */
export function encodeEncore() {
  return [...taches.values()].some(
    (t) => t.etat === 'creation' || (t.etat === 'traitement' && !t.envoiTermine),
  );
}

if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', (evenement) => {
    if (encodeEncore()) {
      evenement.preventDefault();
      evenement.returnValue = '';
    }
  });
}

function suivre(cle, jobId) {
  const tour = async () => {
    try {
      const vue = await api.job(jobId);
      const tache = taches.get(cle);
      if (!tache) return;
      publier(cle, {
        fenetres: tache.fenetres.map((f) => {
          const distante = vue.chunks.find((c) => c.index === f.index);
          if (!distante) return f;
          if (distante.status === 'termine') return { ...f, etat: 'terminee' };
          if (distante.status === 'erreur') return { ...f, etat: 'erreur', erreur: distante.error };
          return f;
        }),
      });
      if (vue.status === 'erreur') {
        publier(cle, { etat: 'repos', erreur: vue.error || 'La transcription a échoué.' });
        return;
      }
      if (vue.status === 'termine') {
        publier(cle, { etat: 'termine', message: '', resultat: { job_id: jobId, title: vue.title } });
        return;
      }
      if (vue.status === 'finalisation') publier(cle, { message: 'Fusion des fenêtres…' });
    } catch (e) {
      publier(cle, { erreur: e.message });
    }
    setTimeout(tour, 3000);
  };
  setTimeout(tour, 3000);
}

async function demarrer(cle, { fichier, duree, contexte, modele, offset = 0, meetingDate }) {
  publier(cle, {
    etat: 'creation', message: 'Création du traitement…', erreur: '',
    fichier: fichier.name, fenetres: [], resultat: null, estimation: null, jobId: null,
  });
  let job;
  try {
    job = await api.createJob({
      filename: fichier.name,
      duration_seconds: duree,
      model: modele,
      language: 'fr',
      context: contexte,
      meeting_date: meetingDate || null,
    });
  } catch (e) {
    // Le garde-fou budget répond ici, avant le premier octet envoyé.
    publier(cle, { etat: 'repos', erreur: e.message });
    return;
  }

  publier(cle, {
    jobId: job.job_id,
    estimation: job.estimated_cost_usd,
    fenetres: job.chunks.map((c) => ({ ...c, etat: 'attendue', octets: 0 })),
    etat: 'traitement',
    message: 'Encodage sur ce poste…',
  });

  // Reprise : le serveur dit ce qui manque, on ne réencode que cela.
  const restant = (await api.job(job.job_id)).missing_chunks;
  const worker = new Worker(new URL('./media-worker.js', import.meta.url), { type: 'module' });
  worker.onmessage = ({ data }) => {
    if (data.kind === 'encoding') {
      majFenetre(cle, data.index, { etat: 'encodage', progression: data.ratio });
    } else if (data.kind === 'encoded') {
      majFenetre(cle, data.index, { etat: 'envoi', octets: data.bytes });
    } else if (data.kind === 'uploaded') {
      majFenetre(cle, data.index, { etat: 'transcription' });
    } else if (data.kind === 'done') {
      worker.terminate();
      publier(cle, {
        envoiTermine: true,
        message: 'Tout est envoyé : le serveur termine seul. Tu peux quitter cet écran.',
      });
    } else if (data.kind === 'error') {
      worker.terminate();
      publier(cle, { erreur: data.message });
    }
  };
  worker.postMessage({
    file: fichier, jobId: job.job_id, chunks: job.chunks, audio: job.audio,
    pending: restant, offset,
  });
  suivre(cle, job.job_id);
}

/** Toutes les transcriptions lancées depuis cet onglet. */
export function useTranscriptions() {
  const [, rafraichir] = useState(0);
  useEffect(() => {
    const f = () => rafraichir((n) => n + 1);
    abonnes.add(f);
    return () => abonnes.delete(f);
  }, []);
  return [...taches.values()];
}

/** L'écran de lancement ne suit qu'une transcription à la fois — la
 *  sienne. Les autres continuent, visibles dans la bibliothèque. */
export function usePipeline() {
  const [cle, setCle] = useState(null);
  const [, rafraichir] = useState(0);
  useEffect(() => {
    const f = () => rafraichir((n) => n + 1);
    abonnes.add(f);
    return () => abonnes.delete(f);
  }, []);

  const lancer = useCallback((options) => {
    const nouvelle = `t-${Date.now()}`;
    setCle(nouvelle);
    demarrer(nouvelle, options);
  }, []);

  /** Oublie la transcription suivie, sans l'arrêter : elle continue. */
  const detacher = useCallback(() => setCle(null), []);

  const tache = (cle && taches.get(cle)) || {};
  return {
    jobId: tache.jobId ?? null,
    fenetres: tache.fenetres || [],
    etat: tache.etat || 'repos',
    message: tache.message || '',
    erreur: tache.erreur || '',
    estimation: tache.estimation ?? null,
    resultat: tache.resultat || null,
    envoiTermine: Boolean(tache.envoiTermine),
    lancer,
    detacher,
  };
}
