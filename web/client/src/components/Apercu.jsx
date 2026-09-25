import { useEffect, useRef, useState } from 'react';
import { horodatage } from '../format.js';

/** « 1:02:03 », « 12:30 » ou « 45 » → secondes ; null si illisible. */
function lireTemps(texte) {
  const parties = String(texte || '').trim().split(':').map((p) => p.trim());
  if (!parties.length || parties.some((p) => p === '' || Number.isNaN(Number(p)))) return null;
  return parties.reduce((total, p) => total * 60 + Number(p), 0);
}

/** Réécoute et rognage avant de lancer.
 *
 *  Deux besoins que l'app macOS couvrait : vérifier qu'on a le bon
 *  enregistrement, et couper le bavardage du début ou la demi-heure
 *  oubliée à la fin. Transcrire ce qu'on va jeter coûte de l'argent et
 *  pollue le transcript.
 *
 *  Le geste principal est la frise : la partie gardée est surlignée, et
 *  ses deux bords s'attrapent à la souris. Le lecteur reste petit — il
 *  sert à reconnaître un moment, pas à regarder la réunion. Il lit le
 *  fichier local par une URL d'objet : rien ne part au serveur.
 */
export function Apercu({ fichier, duree, debut, fin, surDebut, surFin, actif }) {
  const [url, setUrl] = useState('');
  const [position, setPosition] = useState(0);
  const [lisible, setLisible] = useState(true);
  const media = useRef(null);
  const frise = useRef(null);
  const [prise, setPrise] = useState(null); // 'debut' | 'fin' | null

  useEffect(() => {
    if (!fichier) return undefined;
    const objet = URL.createObjectURL(fichier);
    setUrl(objet);
    setLisible(true);
    // Sans révocation, chaque changement de fichier laisse le précédent
    // épinglé en mémoire par le navigateur.
    return () => URL.revokeObjectURL(objet);
  }, [fichier]);

  if (!fichier || !duree) return null;

  const rogne = debut > 0 || fin < duree;
  const pct = (t) => `${(Math.min(Math.max(t, 0), duree) / duree) * 100}%`;

  const tempsSous = (clientX) => {
    const cadre = frise.current.getBoundingClientRect();
    const ratio = Math.min(Math.max((clientX - cadre.left) / cadre.width, 0), 1);
    return ratio * duree;
  };

  const aller = (t) => {
    if (media.current) media.current.currentTime = t;
    setPosition(t);
  };

  const placer = (bord, t) => {
    // Une seconde d'écart au moins : une plage vide ne se transcrit pas.
    if (bord === 'debut') surDebut(Math.min(Math.max(t, 0), fin - 1));
    else surFin(Math.max(Math.min(t, duree), debut + 1));
  };

  const poignee = (bord, valeur) => (
    <button
      type="button"
      disabled={actif}
      aria-label={bord === 'debut' ? 'Début de la partie gardée' : 'Fin de la partie gardée'}
      onPointerDown={(e) => {
        e.stopPropagation();
        e.currentTarget.setPointerCapture(e.pointerId);
        setPrise(bord);
      }}
      onPointerMove={(e) => {
        if (prise !== bord) return;
        const t = tempsSous(e.clientX);
        placer(bord, t);
        aller(t);
      }}
      onPointerUp={() => setPrise(null)}
      onKeyDown={(e) => {
        const pas = e.shiftKey ? 10 : 1;
        if (e.key === 'ArrowLeft') placer(bord, valeur - pas);
        if (e.key === 'ArrowRight') placer(bord, valeur + pas);
      }}
      style={{ left: pct(valeur) }}
      className={`absolute top-1/2 z-10 h-7 w-4 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize rounded-md border-2 border-white bg-turquoise-sombre shadow focus:outline-none focus:ring-2 focus:ring-turquoise disabled:cursor-not-allowed ${
        prise === bord ? 'scale-110' : ''
      }`}
    />
  );

  const champTemps = (libelle, valeur, bord) => (
    <label className="flex items-center gap-2 text-[0.8125rem] text-fonce/60">
      {libelle}
      <input
        key={`${bord}-${Math.round(valeur)}`}
        defaultValue={horodatage(valeur)}
        disabled={actif}
        onBlur={(e) => {
          const t = lireTemps(e.target.value);
          if (t === null) e.target.value = horodatage(valeur);
          else placer(bord, t);
        }}
        onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); }}
        className="w-20 rounded-md border border-bord bg-white px-2 py-1 text-center tabular-nums text-fonce"
      />
      <button
        type="button"
        disabled={actif}
        onClick={() => placer(bord, position)}
        title="Prendre la position de lecture"
        className="rounded px-1.5 py-0.5 text-[0.75rem] text-turquoise-sombre hover:bg-turquoise/15 disabled:opacity-40"
      >
        ← lecture
      </button>
    </label>
  );

  return (
    <div className="verre mt-4 rounded-xl p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="titre text-[0.9375rem] font-medium">Écouter et rogner</p>
        {/* « tout reprendre » vit ici, dans l'en-tête : placé entre les
            champs, il faisait passer la ligne à la ligne et remonter la
            frise sous le curseur — au pire moment, en pleine prise. */}
        <p className="text-[0.8125rem] tabular-nums text-fonce/60">
          {rogne ? (
            <>
              <span className="text-turquoise-sombre">
                {horodatage(fin - debut)} gardées sur {horodatage(duree)}
              </span>
              <button
                type="button"
                disabled={actif}
                onClick={() => { surDebut(0); surFin(duree); }}
                className="ml-3 text-fonce/55 underline-offset-2 hover:text-fonce hover:underline"
              >
                tout reprendre
              </button>
            </>
          ) : `${horodatage(duree)} — tout est gardé`}
        </p>
      </div>

      <div className="mt-3 flex flex-col gap-4 sm:flex-row sm:items-center">
        {lisible ? (
          <video
            ref={media}
            src={url}
            controls
            onTimeUpdate={(e) => setPosition(e.currentTarget.currentTime)}
            onError={() => setLisible(false)}
            className="aspect-video w-full shrink-0 rounded-lg bg-fonce sm:w-56"
          />
        ) : (
          <p className="rounded-lg bg-fonce/5 px-3 py-2 text-[0.8125rem] text-fonce/70 sm:w-56">
            Format non lisible par ce navigateur : le rognage reste possible,
            à l'aveugle.
          </p>
        )}

        <div className="min-w-0 flex-1">
          {/* La frise : cliquer déplace la lecture, les poignées bornent
              la partie gardée. */}
          <div
            ref={frise}
            onPointerDown={(e) => aller(tempsSous(e.clientX))}
            className="relative h-10 cursor-pointer select-none"
          >
            <div className="absolute inset-x-0 top-1/2 h-2 -translate-y-1/2 rounded-full bg-fonce/10" />
            <div
              className="absolute top-1/2 h-2 -translate-y-1/2 rounded-full bg-turquoise"
              style={{ left: pct(debut), width: `calc(${pct(fin)} - ${pct(debut)})` }}
            />
            <div
              className="pointer-events-none absolute top-1 bottom-1 w-px bg-fonce/70"
              style={{ left: pct(position) }}
            />
            {poignee('debut', debut)}
            {poignee('fin', fin)}
          </div>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
            {champTemps('Début', debut, 'debut')}
            {champTemps('Fin', fin, 'fin')}
          </div>
        </div>
      </div>
      <p className="mt-2 text-[0.75rem] text-fonce/45">
        Seule la partie surlignée sera transcrite — et payée.
      </p>
    </div>
  );
}
