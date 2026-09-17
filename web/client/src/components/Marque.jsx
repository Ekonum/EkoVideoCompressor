import { useEffect, useState } from 'react';
import { api } from '../api.js';

/** En-tête de l'application.
 *
 *  Navigation flottante en verre : c'est l'un des usages que la charte
 *  cite explicitement, et le seul endroit où une surface vitrée est
 *  posée sur toute la largeur. Elle suit le défilement, donc le fond
 *  bouge derrière elle — c'est ce mouvement qui rend la matière lisible
 *  plutôt que décorative.
 */
export function Entete({ vue, surVue }) {
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

        <Compte moi={moi} surVue={surVue} actif={vue === 'compte'} />
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
function Compte({ moi, surVue, actif }) {
  if (!moi?.email) return <span className="ml-auto" />;
  const initiales = moi.email.slice(0, 2).toUpperCase();
  return (
    <button
      onClick={() => surVue('compte')}
      title={`Connecté via ${moi.via}`}
      aria-current={actif ? 'page' : undefined}
      className={`ml-auto flex items-center gap-2.5 rounded-full py-1 pl-3 pr-1 transition-colors ${
        actif ? 'bg-clair/15' : 'hover:bg-clair/10'
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
  );
}
