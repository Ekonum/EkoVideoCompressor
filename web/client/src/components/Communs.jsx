import { useEffect, useId, useRef } from 'react';

/** Le peu de vocabulaire visuel partagé.
 *
 *  Volontairement maigre : la charte met en garde contre la carte
 *  réflexe. Ici une carte ne sert qu'à un objet autonome — un
 *  traitement, une fenêtre, une version. Le reste tient à
 *  l'alignement et à l'espacement.
 */

/** Les classes viennent d'ekonum-ui : le bouton principal prend la couleur
 *  la plus contrastée avec son fond (vert foncé sur clair, turquoise dans
 *  une zone foncée). L'ancienne variante « accent » turquoise sur fond clair
 *  s'y range : le design system l'a écartée, trop proche d'un point d'état. */
export function Bouton({ variante = 'primaire', className = '', ...props }) {
  const variantes = {
    primaire: 'ekn-button',
    accent: 'ekn-button',
    discret: 'ekn-button ekn-button--subtle',
    danger: 'ekn-button ekn-button--danger',
  };
  return <button {...props} className={`${variantes[variante]} ${className}`} />;
}

/** Le champ dans son libellé, comme le veut ekonum-ui : un clic sur le
 *  libellé y mène, sans id à tenir. L'aide reste dehors, liée par
 *  aria-describedby, pour ne pas allonger le nom du champ. */
export function Champ({ label, aide, id, ...props }) {
  const auto = useId();
  const cle = id || auto;
  return (
    <div className="flex flex-col gap-1">
      <label className="ekn-label">
        {label}
        <input {...props} id={cle} aria-describedby={aide ? `${cle}-aide` : undefined} className="ekn-input" />
      </label>
      {aide ? <span id={`${cle}-aide`} className="ekn-help">{aide}</span> : null}
    </div>
  );
}

/** États d'un traitement : un point et un libellé, jamais la couleur seule.
 *  « En cours » et « Fusion… » gardent le ton du succès sous forme d'anneau ;
 *  « À finaliser » demande un geste, d'où l'attention. */
const ETATS = {
  en_attente: ['En attente', ''],
  en_cours: ['En cours', 'ekn-status--running'],
  a_finaliser: ['À finaliser', 'ekn-status--warning'],
  finalisation: ['Fusion…', 'ekn-status--running'],
  termine: ['Terminé', 'ekn-status--success'],
  erreur: ['Erreur', 'ekn-status--error'],
  recovered: ['Récupérée', ''],
  cancelled: ['Interrompue', ''],
};

export function Etat({ valeur }) {
  const [libelle, ton] = ETATS[valeur] || [valeur, ''];
  return <span className={`ekn-status ${ton}`}>{libelle}</span>;
}

export function Erreur({ children }) {
  if (!children) return null;
  return <p role="alert" className="ekn-alert ekn-alert--error">{children}</p>;
}

export function Vide({ titre, children }) {
  return (
    <div className="ekn-empty">
      <strong>{titre}</strong>
      <p>{children}</p>
    </div>
  );
}

/** Date et heure d'une réunion : le <ekn-date-picker> d'ekonum-ui autour
 *  d'un champ datetime-local, dont il garde le format de valeur.
 *
 *  Le calendrier écrit dans le champ puis émet `input` et `change` natifs,
 *  que React ne voit pas : il croit la valeur déjà à jour. On écoute donc
 *  `change` sur le champ lui-même ; onChange ne sert qu'à la saisie au
 *  clavier. Sur écran tactile, c'est le calendrier du téléphone. Le
 *  bouton du calendrier suit seul l'état désactivé du champ. */
export function DateHeure({ valeur, surChange, disabled = false, id, label }) {
  const champ = useRef(null);
  const rappel = useRef(surChange);
  rappel.current = surChange;

  useEffect(() => {
    const el = champ.current;
    const suivre = () => rappel.current(el.value);
    el.addEventListener('change', suivre);
    return () => el.removeEventListener('change', suivre);
  }, []);

  return (
    <ekn-date-picker>
      <input
        ref={champ}
        id={id}
        aria-label={label}
        type="datetime-local"
        className="ekn-input"
        value={valeur || ''}
        onChange={(e) => surChange(e.target.value)}
        disabled={disabled}
      />
    </ekn-date-picker>
  );
}
