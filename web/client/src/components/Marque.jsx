import { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';

/** En-tête de l'application.
 *
 *  Navigation flottante en verre : c'est l'un des usages que la charte
 *  cite explicitement, et le seul endroit où une surface vitrée est
 *  posée sur toute la largeur. Elle suit le défilement, donc le fond
 *  bouge derrière elle — c'est ce mouvement qui rend la matière lisible
 *  plutôt que décorative.
 */
export function Entete({ vue, surVue, surAide }) {
  const [moi, setMoi] = useState(null);

  useEffect(() => {
    api.me().then(setMoi).catch(() => {});
  }, []);

  const onglets = [
    ['bibliotheque', 'Bibliothèque'],
    ['nouveau', 'Nouvelle transcription'],
  ];

  return (
    <header className="verre-sombre sticky top-0 z-20 text-clair">
      <div className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-3">
        <img src="/marque/logo-sombre.svg" alt="Ekonum" className="h-7 w-auto shrink-0" />

        <nav className="flex gap-1">
          {onglets.map(([cle, libelle]) => (
            <button
              key={cle}
              onClick={() => surVue(cle)}
              aria-current={vue === cle ? 'page' : undefined}
              className={`titre rounded-lg px-3 py-1.5 text-[0.9375rem] font-medium transition-colors ${
                vue === cle
                  ? 'bg-turquoise text-fonce'
                  : 'text-clair/70 hover:bg-clair/10 hover:text-clair'
              }`}
            >
              {libelle}
            </button>
          ))}
        </nav>

        <Compte moi={moi} surVue={surVue} surAide={surAide} actif={vue === 'compte'} />
      </div>
    </header>
  );
}

/** Le compte connecté.
 *
 *  Savoir sous quelle identité on travaille est la première chose qu'on
 *  cherche sur un outil d'équipe — surtout un outil qui dépense de
 *  l'argent et où le vocabulaire est partagé.
 */
/** La session est celle de Cloudflare Access, pas de l'application : se
 *  déconnecter, c'est la clore là-bas. La visite suivante repasse par la
 *  page de connexion Google — c'est le « se connecter ». */
export const DECONNEXION = '/cdn-cgi/access/logout';

/** Le compte, et ce qui ne sert pas tous les jours : réglages,
 *  raccourcis, déconnexion — rangés derrière l'avatar plutôt qu'affichés
 *  en permanence. */
function Compte({ moi, surVue, surAide, actif }) {
  const [ouvert, setOuvert] = useState(false);
  const cadre = useRef(null);

  useEffect(() => {
    if (!ouvert) return undefined;
    const dehors = (e) => { if (!cadre.current?.contains(e.target)) setOuvert(false); };
    const echap = (e) => { if (e.key === 'Escape') setOuvert(false); };
    document.addEventListener('mousedown', dehors);
    window.addEventListener('keydown', echap);
    return () => {
      document.removeEventListener('mousedown', dehors);
      window.removeEventListener('keydown', echap);
    };
  }, [ouvert]);

  if (!moi?.email) return <span className="ml-auto" />;
  const initiales = moi.email.slice(0, 2).toUpperCase();
  const choisir = (action) => () => { setOuvert(false); action(); };
  const entree = 'block w-full rounded-md px-3 py-2 text-left text-[0.875rem] text-fonce/80 transition-colors hover:bg-papier hover:text-fonce';

  return (
    <div ref={cadre} className="relative ml-auto">
      <button
        type="button"
        onClick={() => setOuvert((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={ouvert}
        title={`Connecté via ${moi.via}`}
        className={`flex items-center gap-2.5 rounded-full py-1 pl-3 pr-1 transition-colors ${
          actif || ouvert ? 'bg-clair/15' : 'hover:bg-clair/10'
        }`}
      >
        <span className="hidden text-[0.875rem] text-clair/75 sm:inline">{moi.email}</span>
        <span
          aria-hidden
          className="titre grid h-8 w-8 place-items-center rounded-full bg-turquoise text-[0.8125rem] font-semibold text-fonce"
        >
          {initiales}
        </span>
      </button>
      {ouvert ? (
        <div
          role="menu"
          className="absolute right-0 top-full z-30 mt-2 w-60 rounded-xl bg-white p-1.5 text-fonce shadow-2xl ring-1 ring-bord"
        >
          <p className="truncate px-3 pb-1.5 pt-1 text-[0.75rem] text-fonce/45">{moi.email}</p>
          <button type="button" role="menuitem" onClick={choisir(() => surVue('compte'))} className={entree}>
            Réglages
          </button>
          <button type="button" role="menuitem" onClick={choisir(surAide)}
                  className={`${entree} flex items-center justify-between`}>
            Raccourcis clavier
            <kbd className="rounded border border-bord bg-papier px-1.5 text-[0.75rem] text-fonce/55">?</kbd>
          </button>
          <div className="my-1 h-px bg-bord/70" />
          <a role="menuitem" href={DECONNEXION} className={entree}>Se déconnecter</a>
        </div>
      ) : null}
    </div>
  );
}
