import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { Bouton, Champ, Erreur } from './Communs.jsx';
import { horodatage, usd, jour } from '../format.js';

/** Fiche d'une transcription : la lire, la corriger, la relancer.
 *
 *  Les éditeurs sont posés à côté du transcript plutôt que dans une
 *  fenêtre modale : corriger un nom d'interlocuteur se fait en le
 *  lisant, pas de mémoire.
 */
export function Detail({ jobId, surRetour }) {
  const [fiche, setFiche] = useState(null);
  const [erreur, setErreur] = useState('');
  const [note, setNote] = useState('');

  const recharger = () => api.detail(jobId).then(setFiche).catch((e) => setErreur(e.message));
  useEffect(() => { recharger(); }, [jobId]);

  if (erreur && !fiche) return <div className="mx-auto max-w-4xl px-6 py-10"><Erreur>{erreur}</Erreur></div>;
  if (!fiche) return <p className="py-16 text-center text-fonce/50">Chargement…</p>;

  return (
    <section className="mx-auto max-w-6xl px-6 py-10">
      <button onClick={surRetour} className="text-[0.875rem] text-fonce/55 hover:text-fonce">
        ← Bibliothèque
      </button>

      <h1 className="titre mt-3 text-[1.5rem] font-semibold">{fiche.title || fiche.filename}</h1>
      <p className="mt-1 text-[0.875rem] text-fonce/55">
        {fiche.filename} · {fiche.model} · {usd(fiche.cost_usd)}
      </p>

      <Erreur>{erreur}</Erreur>
      {note ? <p className="mt-4 text-[0.875rem] text-turquoise-sombre">{note}</p> : null}

      <div className="mt-8 grid gap-10 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div>
          <h2 className="titre text-[1.0625rem] font-medium">Transcription</h2>
          <div className="mt-3 max-h-[34rem] overflow-y-auto rounded-lg border border-bord bg-white">
            {fiche.segments.length === 0 ? (
              <p className="px-4 py-6 text-fonce/50">Pas encore de segment.</p>
            ) : (
              <ol>
                {fiche.segments.map((s, rang) => (
                  <li key={rang} className="flex gap-4 px-4 py-2">
                    <span className="w-12 shrink-0 pt-0.5 text-[0.8125rem] tabular-nums text-fonce/40">
                      {horodatage(s.start_second)}
                    </span>
                    <span>
                      {s.speaker ? (
                        <span className="titre mr-2 font-medium text-turquoise-sombre">{s.speaker}</span>
                      ) : null}
                      {s.text}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </div>

        <aside className="space-y-8">
          <Interlocuteurs fiche={fiche} jobId={jobId} surMaj={recharger} surNote={setNote} surErreur={setErreur} />
          <Termes fiche={fiche} jobId={jobId} surMaj={recharger} surNote={setNote} surErreur={setErreur} />
          <Fenetres jobId={jobId} surNote={setNote} surErreur={setErreur} />
          <Versions versions={fiche.previous_versions} />
        </aside>
      </div>
    </section>
  );
}

function Interlocuteurs({ fiche, jobId, surMaj, surNote, surErreur }) {
  const [carte, setCarte] = useState(fiche.speakers);
  useEffect(() => setCarte(fiche.speakers), [fiche.speakers]);
  const entrees = Object.entries(carte);
  if (entrees.length === 0) return null;

  return (
    <div>
      <h2 className="titre text-[1.0625rem] font-medium">Interlocuteurs</h2>
      <div className="mt-3 space-y-2">
        {entrees.map(([etiquette, nom]) => (
          <Champ
            key={etiquette}
            label={etiquette}
            value={nom}
            placeholder="Qui est-ce ?"
            onChange={(e) => setCarte({ ...carte, [etiquette]: e.target.value })}
          />
        ))}
      </div>
      <Bouton
        variante="discret"
        className="mt-3 w-full"
        onClick={async () => {
          try {
            await api.patch(jobId, { speakers: carte });
            surNote('Interlocuteurs enregistrés.');
            surMaj();
          } catch (e) { surErreur(e.message); }
        }}
      >
        Enregistrer
      </Bouton>
    </div>
  );
}

function Termes({ fiche, jobId, surMaj, surNote, surErreur }) {
  const [ancien, setAncien] = useState('');
  const [nouveau, setNouveau] = useState('');

  return (
    <div>
      <h2 className="titre text-[1.0625rem] font-medium">Vocabulaire</h2>
      {fiche.technical_terms.length ? (
        <p className="mt-2 text-[0.875rem] leading-relaxed text-fonce/70">
          {fiche.technical_terms.join(' · ')}
        </p>
      ) : (
        <p className="mt-2 text-[0.875rem] text-fonce/50">Aucun terme relevé.</p>
      )}

      <p className="mt-4 text-[0.8125rem] text-fonce/55">
        Corriger un terme mal entendu le remplace dans toute la transcription,
        les segments et le glossaire.
      </p>
      <div className="mt-2 space-y-2">
        <Champ label="Écrit" placeholder="Acritek" value={ancien} onChange={(e) => setAncien(e.target.value)} />
        <Champ label="À la place" placeholder="Acritec" value={nouveau} onChange={(e) => setNouveau(e.target.value)} />
      </div>
      <Bouton
        variante="discret"
        className="mt-3 w-full"
        disabled={!ancien.trim() || !nouveau.trim()}
        onClick={async () => {
          try {
            const vue = await api.replaceTerm(jobId, ancien, nouveau);
            surNote(
              vue.occurrences
                ? `${vue.occurrences} occurrence${vue.occurrences > 1 ? 's' : ''} corrigée${vue.occurrences > 1 ? 's' : ''}.`
                : 'Aucune occurrence trouvée.',
            );
            setAncien(''); setNouveau('');
            surMaj();
          } catch (e) { surErreur(e.message); }
        }}
      >
        Corriger partout
      </Bouton>
    </div>
  );
}

/** Relance ciblée.
 *
 *  Sur une réunion de huit fenêtres dont trois ont échoué, relancer les
 *  cinq bonnes serait les repayer pour rien.
 */
function Fenetres({ jobId, surNote, surErreur }) {
  const [vue, setVue] = useState(null);
  useEffect(() => { api.job(jobId).then(setVue).catch(() => {}); }, [jobId]);
  if (!vue || vue.chunks.length <= 1) return null;

  return (
    <div>
      <h2 className="titre text-[1.0625rem] font-medium">Fenêtres</h2>
      <ul className="mt-3 divide-y divide-bord rounded-lg border border-bord bg-white">
        {vue.chunks.map((c) => (
          <li key={c.index} className="flex items-center gap-3 px-3 py-2 text-[0.875rem]">
            <span className="w-12 shrink-0 tabular-nums text-fonce/45">{horodatage(c.start)}</span>
            <span className={`flex-1 ${c.status === 'erreur' ? 'text-[#8c1d18]' : 'text-fonce/70'}`}>
              {c.status === 'termine' ? 'terminée' : c.status === 'erreur' ? 'erreur' : c.status}
            </span>
            <button
              className="text-turquoise-sombre hover:underline"
              onClick={async () => {
                try {
                  await api.resetChunk(jobId, c.index);
                  surNote(`Fenêtre ${c.index + 1} à refaire — relance-la depuis l'onglet de transcription.`);
                  setVue(await api.job(jobId));
                } catch (e) { surErreur(e.message); }
              }}
            >
              relancer
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Versions({ versions }) {
  if (!versions?.length) return null;
  return (
    <div>
      <h2 className="titre text-[1.0625rem] font-medium">Versions précédentes</h2>
      <ul className="mt-3 space-y-2">
        {versions.map((v, rang) => (
          <li key={rang} className="rounded-lg border border-violet/25 bg-white px-3 py-2">
            <span className="text-[0.8125rem] text-fonce/55">{jour(v.archived_at)}</span>
            <span className="block truncate text-[0.875rem]">{v.title || 'Sans titre'}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
