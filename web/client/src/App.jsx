import { useState } from 'react';
import { Entete } from './components/Marque.jsx';
import { Bibliotheque } from './components/Bibliotheque.jsx';
import { Nouveau } from './components/Nouveau.jsx';
import { Detail } from './components/Detail.jsx';
import { Compte } from './components/Compte.jsx';

export default function App() {
  const [vue, setVue] = useState('bibliotheque');
  const [ouvert, setOuvert] = useState(null);

  // Pas de fond sur ce conteneur : le dégradé vit sur `html`, et un aplat
  // posé par-dessus le masquerait — le verre n'aurait alors plus rien à
  // laisser voir.
  return (
    <div className="min-h-screen">
      <Entete
        vue={vue}
        surVue={(cible) => { setOuvert(null); setVue(cible); }}
      />
      <main>
        {ouvert !== null ? (
          <Detail jobId={ouvert} surRetour={() => setOuvert(null)} />
        ) : vue === 'compte' ? (
          <Compte />
        ) : vue === 'nouveau' ? (
          <Nouveau surTermine={(id) => { setVue('bibliotheque'); setOuvert(id); }} />
        ) : (
          <Bibliotheque surOuvrir={setOuvert} />
        )}
      </main>
    </div>
  );
}
