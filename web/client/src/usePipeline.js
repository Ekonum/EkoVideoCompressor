import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api.js';

/** Pilote une transcription : création, encodage, envoi, suivi.
 *
 *  Tout le média reste ici et dans le worker. Le composant qui utilise
 *  ce hook ne manipule que des états — il n'a aucune raison de savoir
 *  qu'un encodeur existe.
 */
export function usePipeline() {
  const [jobId, setJobId] = useState(null);
  const [fenetres, setFenetres] = useState([]);
  const [etat, setEtat] = useState('repos');
  const [message, setMessage] = useState('');
  const [erreur, setErreur] = useState('');
  const [estimation, setEstimation] = useState(null);
  const [resultat, setResultat] = useState(null);
  const workerRef = useRef(null);

  // Le worker est coûteux à créer et détient l'encodeur : on le libère
  // quand le composant part, sinon un onglet laissé ouvert garde un fil
  // et sa mémoire.
  useEffect(() => () => workerRef.current?.terminate(), []);

  const majFenetre = useCallback((index, champs) => {
    setFenetres((actuelles) =>
      actuelles.map((f) => (f.index === index ? { ...f, ...champs } : f)),
    );
  }, []);

  const lancer = useCallback(async ({ fichier, duree, contexte, modele }) => {
    setErreur('');
    setResultat(null);
    setEtat('creation');
    setMessage('Création du traitement…');

    let job;
    try {
      job = await api.createJob({
        filename: fichier.name,
        duration_seconds: duree,
        model: modele,
        language: 'fr',
        context: contexte,
      });
    } catch (e) {
      // Le garde-fou budget répond ici, avant le premier octet envoyé.
      setErreur(e.message);
      setEtat('repos');
      return;
    }

    setJobId(job.job_id);
    setEstimation(job.estimated_cost_usd);
    setFenetres(job.chunks.map((c) => ({ ...c, etat: 'attendue', octets: 0 })));

    // Reprise : le serveur dit ce qui manque, on ne réencode que cela.
    const restant = (await api.job(job.job_id)).missing_chunks;

    const worker = new Worker(new URL('./media-worker.js', import.meta.url), {
      type: 'module',
    });
    workerRef.current = worker;
    worker.onmessage = ({ data }) => {
      if (data.kind === 'encoding') {
        majFenetre(data.index, { etat: 'encodage', progression: data.ratio });
      } else if (data.kind === 'encoded') {
        majFenetre(data.index, { etat: 'envoi', octets: data.bytes });
      } else if (data.kind === 'uploaded') {
        majFenetre(data.index, { etat: 'transcription' });
      } else if (data.kind === 'done') {
        setMessage('Fenêtres envoyées. La transcription se termine côté serveur.');
      } else if (data.kind === 'error') {
        setErreur(data.message);
      }
    };
    worker.postMessage({
      file: fichier,
      jobId: job.job_id,
      chunks: job.chunks,
      audio: job.audio,
      pending: restant,
    });

    setEtat('traitement');
    setMessage('Encodage sur ce poste…');
  }, [majFenetre]);

  // Suivi. L'envoi répond 202 : l'avancement réel se lit ici.
  useEffect(() => {
    if (etat !== 'traitement' || !jobId) return undefined;
    let vivant = true;

    const tour = async () => {
      try {
        const vue = await api.job(jobId);
        if (!vivant) return;
        setFenetres((actuelles) =>
          actuelles.map((f) => {
            const distante = vue.chunks.find((c) => c.index === f.index);
            if (!distante) return f;
            if (distante.status === 'termine') return { ...f, etat: 'terminee' };
            if (distante.status === 'erreur') return { ...f, etat: 'erreur', erreur: distante.error };
            return f;
          }),
        );
        if (vue.status === 'erreur') {
          setErreur(vue.error || 'La transcription a échoué.');
          setEtat('repos');
        } else if (vue.status === 'a_finaliser') {
          setMessage('Fusion des fenêtres…');
          const final = await api.finalize(jobId);
          if (!vivant) return;
          setResultat(final);
          setEtat('termine');
          setMessage('');
        }
      } catch (e) {
        if (vivant) setErreur(e.message);
      }
    };

    const minuteur = setInterval(tour, 3000);
    return () => { vivant = false; clearInterval(minuteur); };
  }, [etat, jobId]);

  return { jobId, fenetres, etat, message, erreur, estimation, resultat, lancer };
}
