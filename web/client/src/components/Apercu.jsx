import { useEffect, useRef, useState } from 'react';
import { Bouton } from './Communs.jsx';
import { horodatage } from '../format.js';

/** Réécoute et rognage avant de lancer.
 *
 *  Deux besoins que l'app macOS couvrait : vérifier qu'on a le bon
 *  enregistrement, et couper les cinq minutes de bavardage du début ou
 *  la demi-heure oubliée à la fin. Transcrire ce qu'on va jeter coûte de
 *  l'argent et pollue le transcript.
 *
 *  On ne saisit pas des minuteries : on écoute, et on marque. Le lecteur
 *  lit le fichier local par une URL d'objet — rien n'est chargé en
 *  mémoire, rien ne part au serveur.
 */
export function Apercu({ fichier, duree, debut, fin, surDebut, surFin, actif }) {
  const [url, setUrl] = useState('');
  const [position, setPosition] = useState(0);
  const [lisible, setLisible] = useState(true);
  const media = useRef(null);

  useEffect(() => {
    if (!fichier) return undefined;
    const objet = URL.createObjectURL(fichier);
    setUrl(objet);
    setLisible(true);
    // Sans révocation, chaque changement de fichier laisse le précédent
    // épinglé en mémoire par le navigateur.
    return () => URL.revokeObjectURL(objet);
  }, [fichier]);

  if (!fichier) return null;

  const span = Math.max(fin - debut, 0);
  const rogne = debut > 0 || fin < duree;

  return (
    <div className="verre mt-4 rounded-xl p-4">
      <p className="titre text-[0.9375rem] font-medium">Écouter et rogner</p>
      <p className="mt-0.5 text-[0.8125rem] text-fonce/55">
        Place la lecture où tu veux couper, puis marque le début ou la fin.
        Seule la partie retenue sera transcrite — et payée.
      </p>

      {lisible ? (
        <video
          ref={media}
          src={url}
          controls
          onTimeUpdate={(e) => setPosition(e.currentTarget.currentTime)}
          onError={() => setLisible(false)}
          className="mt-3 max-h-64 w-full rounded-lg bg-fonce"
        />
      ) : (
        <p className="mt-3 rounded-lg bg-fonce/5 px-3 py-2 text-[0.875rem] text-fonce/70">
          Ce navigateur ne sait pas lire ce format directement. Le rognage reste
          possible, mais à l'aveugle — l'encodage, lui, fonctionnera.
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Bouton
          variante="discret"
          disabled={actif}
          onClick={() => surDebut(Math.min(position, fin - 1))}
        >
          Début ici
        </Bouton>
        <Bouton
          variante="discret"
          disabled={actif}
          onClick={() => surFin(Math.max(position, debut + 1))}
        >
          Fin ici
        </Bouton>
        {rogne ? (
          <Bouton
            variante="discret"
            disabled={actif}
            onClick={() => { surDebut(0); surFin(duree); }}
          >
            Tout reprendre
          </Bouton>
        ) : null}

        <span className="ml-auto text-[0.875rem] tabular-nums text-fonce/60">
          {rogne ? (
            <>
              <span className="text-turquoise-sombre">
                {horodatage(debut)} → {horodatage(fin)}
              </span>
              <span className="ml-2">({horodatage(span)} retenues)</span>
            </>
          ) : (
            `position ${horodatage(position)}`
          )}
        </span>
      </div>
    </div>
  );
}
