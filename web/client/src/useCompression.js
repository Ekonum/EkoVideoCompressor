import { useCallback, useRef, useState } from 'react';

/** Profil arrêté au jalon M0 : HEVC 720p, 12 i/s, ~150 kbps.
 *
 *  Mesuré sur une réunion de 3 h 34 : 4 466 Mo deviennent 335 Mo, soit
 *  92,5 % de réduction, en 5,4× le temps réel — une parité de vitesse
 *  avec le libx265 de l'app macOS, pas un gain.
 */
export const PROFIL = {
  codec: 'hevc',
  height: 720,
  frameRate: 12,
  videoBitrate: 150_000,
  audioBitrate: 64_000,
};

export function useCompression() {
  const [etat, setEtat] = useState('repos');
  const [progression, setProgression] = useState(0);
  const [resultat, setResultat] = useState(null);
  const [erreur, setErreur] = useState('');
  const workerRef = useRef(null);

  const supportee = typeof window !== 'undefined' && 'showSaveFilePicker' in window;

  const compresser = useCallback(async (fichier) => {
    setErreur('');
    setResultat(null);

    // Le sélecteur d'enregistrement exige un geste de l'utilisateur et le
    // fil principal ; la poignée obtenue, elle, se transfère au worker.
    let handle;
    try {
      handle = await window.showSaveFilePicker({
        suggestedName: fichier.name.replace(/\.[^.]+$/, '') + '_compresse.mp4',
        types: [{ description: 'MP4', accept: { 'video/mp4': ['.mp4'] } }],
      });
    } catch {
      return; // l'utilisateur a renoncé : ce n'est pas une erreur
    }

    setEtat('compression');
    setProgression(0);
    const worker = new Worker(new URL('./media-worker.js', import.meta.url), {
      type: 'module',
    });
    workerRef.current = worker;
    worker.onmessage = ({ data }) => {
      if (data.kind === 'compress-progress') setProgression(data.ratio);
      else if (data.kind === 'compressed') {
        setResultat({ bytes: data.bytes, ms: data.ms, source: fichier.size });
        setEtat('termine');
        worker.terminate();
      } else if (data.kind === 'compress-error') {
        setErreur(data.message);
        setEtat('repos');
        worker.terminate();
      }
    };
    worker.postMessage({ kind: 'compress', file: fichier, handle, profile: PROFIL });
  }, []);

  return { supportee, etat, progression, resultat, erreur, compresser };
}
