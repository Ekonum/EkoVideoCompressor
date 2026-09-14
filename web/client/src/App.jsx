import { useState } from 'react';
import { Entete } from './components/Marque.jsx';
import { Bibliotheque } from './components/Bibliotheque.jsx';
import { Nouveau } from './components/Nouveau.jsx';
import { Detail } from './components/Detail.jsx';

export default function App() {
  const [vue, setVue] = useState('bibliotheque');
  const [ouvert, setOuvert] = useState(null);

  return (
    <div className="min-h-screen bg-papier">
      <Entete
        vue={vue}
        surVue={(cible) => { setOuvert(null); setVue(cible); }}
      />
      <main>
        {ouvert !== null ? (
          <Detail jobId={ouvert} surRetour={() => setOuvert(null)} />
        ) : vue === 'nouveau' ? (
          <Nouveau surTermine={(id) => { setVue('bibliotheque'); setOuvert(id); }} />
        ) : (
          <Bibliotheque surOuvrir={setOuvert} />
        )}
      </main>
    </div>
  );
}
