import { useState } from 'react';
import { Entete } from './components/Marque.jsx';
import { Bibliotheque } from './components/Bibliotheque.jsx';
import { Nouveau } from './components/Nouveau.jsx';
import { Detail } from './components/Detail.jsx';
import { Compte } from './components/Compte.jsx';
import { Enroler } from './components/Enroler.jsx';
import { Aide } from './components/Aide.jsx';
import { useRaccourcis } from './raccourcis.js';

export default function App() {
  const [vue, setVue] = useState('bibliotheque');
  const [ouvert, setOuvert] = useState(null);
  // Le mot cherché dans la bibliothèque suit la réunion ouverte : on la
  // découvre déjà surlignée là où il apparaît.
  const [cherche, setCherche] = useState('');
  const [aide, setAide] = useState(false);
  // Un seul chemin d'URL dans toute l'application : celui qu'un appareil
  // affiche pour se faire autoriser. Le reste n'a pas de raison d'être
  // adressable — on ne partage pas un lien vers « Nouvelle transcription ».
  const [enrolement, setEnrolement] = useState(
    () => new URLSearchParams(window.location.search).get('code') || null,
  );

  useRaccourcis({
    n: () => { setOuvert(null); setVue('nouveau'); },
    '?': () => setAide((a) => !a),
  }, !enrolement);

  const ouvrir = (id, terme = '') => { setCherche(terme); setOuvert(id); };

  const quitterEnrolement = () => {
    setEnrolement(null);
    window.history.replaceState({}, '', '/');
  };

  // Pas de fond sur ce conteneur : le dégradé vit sur `html`, et un aplat
  // posé par-dessus le masquerait — le verre n'aurait alors plus rien à
  // laisser voir.
  return (
    <div className="min-h-screen">
      <Entete
        vue={vue}
        surVue={(cible) => { setOuvert(null); setVue(cible); }}
        surAide={() => setAide(true)}
      />
      <main>
        {enrolement ? (
          <Enroler code={enrolement} surFini={quitterEnrolement} />
        ) : ouvert !== null ? (
          <Detail key={ouvert} jobId={ouvert} recherche={cherche} surRetour={() => setOuvert(null)} />
        ) : vue === 'compte' ? (
          <Compte />
        ) : vue === 'nouveau' ? (
          <Nouveau
            surTermine={(id) => { setVue('bibliotheque'); ouvrir(id); }}
            surBibliotheque={() => setVue('bibliotheque')}
          />
        ) : (
          <Bibliotheque surOuvrir={ouvrir} />
        )}
      </main>
      {aide ? <Aide surFermer={() => setAide(false)} /> : null}
    </div>
  );
}
