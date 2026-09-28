import { useEffect, useRef } from 'react';

/** Raccourcis clavier.
 *
 *  « mod » vaut ⌘ sur Mac et Ctrl ailleurs : chacun garde le réflexe de
 *  son système. Une touche seule (« / », « n », « ? ») ne se déclenche
 *  jamais pendant une saisie — taper un « n » dans un champ ne doit pas
 *  ouvrir une nouvelle transcription.
 */

export const MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.userAgent);
export const MOD = MAC ? '⌘' : 'Ctrl';
export const ALT = MAC ? '⌥' : 'Alt';

function enSaisie(cible) {
  if (!cible) return false;
  const balise = cible.tagName;
  return balise === 'INPUT' || balise === 'TEXTAREA' || balise === 'SELECT' || cible.isContentEditable;
}

function correspond(evenement, combinaison) {
  const parties = combinaison.toLowerCase().split('+');
  const touche = parties.pop();
  const mod = parties.includes('mod');
  const maj = parties.includes('shift');
  if ((MAC ? evenement.metaKey : evenement.ctrlKey) !== mod) return false;
  if (evenement.altKey) return false;
  // « ? » s'obtient avec Maj sur la plupart des claviers : pour une touche
  // imprimable, on compare le caractère produit, pas l'état de Maj.
  if (touche.length === 1 && !/[a-z]/.test(touche)) return evenement.key === touche;
  if (evenement.shiftKey !== maj) return false;
  return evenement.key.toLowerCase() === touche;
}

/** `table` : { 'mod+f': action, '/': action, … }. Une action qui rend
 *  `false` laisse le navigateur faire son geste habituel. */
export function useRaccourcis(table, actif = true) {
  const courante = useRef(table);
  courante.current = table;

  useEffect(() => {
    if (!actif) return undefined;
    const ecoute = (evenement) => {
      for (const [combinaison, action] of Object.entries(courante.current)) {
        if (!action || !correspond(evenement, combinaison)) continue;
        const simple = !combinaison.includes('mod') && combinaison.toLowerCase() !== 'escape';
        if (simple && enSaisie(evenement.target)) continue;
        if (action(evenement) === false) return;
        evenement.preventDefault();
        return;
      }
    };
    window.addEventListener('keydown', ecoute);
    return () => window.removeEventListener('keydown', ecoute);
  }, [actif]);
}
