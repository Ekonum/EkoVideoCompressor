import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { Bouton, Champ, Erreur } from './Communs.jsx';
import { horodatage, usd, jour, mo } from '../format.js';
import { useArchivage } from '../archivage.js';
import { AvancementArchivage } from './Nouveau.jsx';

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
          <div className="flex items-center justify-between gap-3">
            <h2 className="titre text-[1.0625rem] font-medium">Transcription</h2>
            <Copier texte={fiche.transcript} />
          </div>
          <Video jobId={jobId} video={fiche.video} surMaj={recharger} />
          <div className="verre mt-3 max-h-[34rem] overflow-y-auto rounded-xl">
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
          <AVerifier fiche={fiche} />
          <Relecture fiche={fiche} jobId={jobId} surMaj={recharger} surNote={setNote} surErreur={setErreur} />
          <Fenetres jobId={jobId} surNote={setNote} surErreur={setErreur} />
          <Odoo fiche={fiche} jobId={jobId} surMaj={recharger} surNote={setNote} surErreur={setErreur} />
          <Versions versions={fiche.previous_versions} />
        </aside>
      </div>
    </section>
  );
}

/** La vidéo de la réunion, en stockage froid.
 *
 *  Le stockage froid se paie à l'envers de l'intuition : garder une
 *  vidéo ne coûte presque rien, la relire coûte davantage. On prend
 *  l'habitude dès maintenant, avant que GCS ne rende ce coût réel — d'où
 *  une question avant chaque lecture, et rien qui se charge tout seul.
 */
function Video({ jobId, video, surMaj }) {
  const tache = useArchivage(jobId);
  const [etape, setEtape] = useState('repos'); // repos → question → lecture

  useEffect(() => {
    if (tache?.etape === 'termine') surMaj();
  }, [tache?.etape]);

  if (tache && tache.etape !== 'termine') {
    return <div className="mt-3"><AvancementArchivage tache={tache} /></div>;
  }
  if (!video?.presente) {
    return video?.en_cours ? (
      <p className="mt-3 text-[0.8125rem] text-fonce/55">
        L'envoi de la vidéo a été interrompu (onglet fermé ?). La transcription,
        elle, est complète.
      </p>
    ) : null;
  }

  if (etape === 'lecture') {
    return (
      <video
        className="mt-3 w-full rounded-xl bg-fonce"
        src={`/api/jobs/${jobId}/video`}
        controls
        autoPlay
        preload="metadata"
      />
    );
  }

  return (
    <div className="verre mt-3 rounded-xl p-4">
      {etape === 'question' ? (
        <>
          <p className="titre text-[0.9375rem] font-medium">Relire la vidéo ?</p>
          <p className="mt-1 text-[0.875rem] text-fonce/70">
            Elle est en <strong>stockage froid</strong> : la conserver ne coûte
            presque rien, la relire coûte davantage. On ne la charge que si tu
            en as besoin.
          </p>
          <div className="mt-3 flex gap-2">
            <Bouton onClick={() => setEtape('lecture')}>Lire la vidéo</Bouton>
            <button
              type="button"
              onClick={() => setEtape('repos')}
              className="rounded-md px-3 py-1.5 text-[0.875rem] text-fonce/60 hover:text-fonce"
            >
              Pas maintenant
            </button>
          </div>
        </>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-[0.875rem] text-fonce/70">
            Vidéo archivée{video.octets ? ` — ${mo(video.octets)}` : ''}, en
            stockage froid.
          </p>
          <button
            type="button"
            onClick={() => setEtape('question')}
            className="rounded-md px-3 py-1.5 text-[0.8125rem] text-fonce/70 ring-1 ring-bord hover:bg-white/60 hover:text-fonce"
          >
            Regarder
          </button>
        </div>
      )}
    </div>
  );
}

/** Copie la transcription telle qu'on la colle ailleurs — un courriel,
 *  un chatter, un document : « Interlocuteur : texte », ligne par ligne.
 *
 *  Le bouton dit lui-même que c'est fait, plutôt qu'une notice ailleurs
 *  dans la page qu'on ne regarde pas au moment de coller.
 */
function Copier({ texte }) {
  const [etat, setEtat] = useState('repos');
  if (!texte?.trim()) return null;
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(texte);
          setEtat('copie');
        } catch {
          setEtat('refus');
        }
        setTimeout(() => setEtat('repos'), 2000);
      }}
      className="rounded-md px-3 py-1.5 text-[0.8125rem] text-fonce/70 ring-1 ring-bord transition-colors hover:bg-white/60 hover:text-fonce"
    >
      {etat === 'copie'
        ? 'Copiée ✓'
        : etat === 'refus'
          ? 'Copie refusée par le navigateur'
          : 'Copier la transcription'}
    </button>
  );
}

/** Ce dont le modèle n'était pas sûr.
 *
 *  L'app macOS écrivait ça dans un fichier « à vérifier » ; c'est la
 *  liste de ce qu'il faut réécouter, et elle ne vaut que si on la voit.
 */
function AVerifier({ fiche }) {
  const passages = fiche.uncertain || [];
  if (!passages.length) return null;
  return (
    <div>
      <h2 className="titre text-[1.0625rem] font-medium">À vérifier</h2>
      <p className="mt-1 text-[0.8125rem] text-fonce/55">
        {passages.length} passage{passages.length > 1 ? 's' : ''} dont le modèle
        doute.
      </p>
      <ul className="mt-2 space-y-2">
        {passages.map((p, i) => (
          <li key={i} className="rounded-lg bg-papier p-2.5">
            <span className="block text-[0.75rem] tabular-nums text-fonce/45">
              {p.timestamp || '—'}
            </span>
            <span className="block text-[0.875rem]">{p.text}</span>
            {p.reason ? (
              <span className="block text-[0.8125rem] text-fonce/55">{p.reason}</span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Relire la transcription à la lumière du bon dossier.
 *
 *  Une liaison corrigée ne doit pas coûter une transcription : le texte
 *  existe déjà, seule sa lecture change. Titre, noms d'interlocuteurs et
 *  corrections métier sont refaits pour quelques centimes, et la version
 *  d'avant reste dans l'historique.
 */
function Relecture({ fiche, jobId, surMaj, surNote, surErreur }) {
  const [occupe, setOccupe] = useState(false);
  if (!fiche.transcript?.trim()) return null;
  return (
    <div>
      <h2 className="titre text-[1.0625rem] font-medium">Relecture</h2>
      <p className="mt-1 text-[0.8125rem] text-fonce/55">
        Refaire le titre, les noms et les corrections métier à partir du texte
        déjà transcrit — sans repayer la transcription.
      </p>
      <Bouton
        className="mt-2"
        disabled={occupe}
        onClick={async () => {
          setOccupe(true);
          try {
            const vue = await api.reenrichir(jobId);
            surNote(`Relu pour ${usd(vue.cost_usd)} — ${vue.title}`);
            surMaj();
          } catch (e) { surErreur(e.message); }
          finally { setOccupe(false); }
        }}
      >
        {occupe ? 'Relecture…' : 'Relire'}
      </Bouton>
    </div>
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
      <ul className="verre mt-3 divide-y divide-bord/60 rounded-xl">
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
          <li key={rang} className="verre rounded-lg border-violet/25 px-3 py-2">
            <span className="text-[0.8125rem] text-fonce/55">{jour(v.archived_at)}</span>
            <span className="block truncate text-[0.875rem]">{v.title || 'Sans titre'}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Dépôt dans le chatter Odoo.
 *
 *  Remplace la recopie manuelle qui a fini par gonfler des opportunités
 *  jusqu'à 300 000 caractères. La transcription part en accordéon : le
 *  texte intégral reste disponible sans noyer l'historique commercial.
 */
function Odoo({ fiche, jobId, surMaj, surNote, surErreur }) {
  const [requete, setRequete] = useState('');
  const [candidats, setCandidats] = useState(null);
  const [envoi, setEnvoi] = useState(false);
  const lien = fiche.odoo || {};

  useEffect(() => {
    const terme = requete.trim();
    if (terme.length < 2) { setCandidats(null); return undefined; }
    const attente = setTimeout(() => {
      api.odooRecords(terme).then((v) => setCandidats(v.records)).catch(() => setCandidats([]));
    }, 300);
    return () => clearTimeout(attente);
  }, [requete]);

  if (lien.message_id) {
    return (
      <div>
        <h2 className="titre text-[1.0625rem] font-medium">Odoo</h2>
        <p className="mt-2 text-[0.875rem] text-turquoise-sombre">
          Déposée dans le chatter le {jour(lien.published_at)}.
        </p>
        <p className="mt-0.5 text-[0.8125rem] text-fonce/50">
          {lien.model} #{lien.record_id}
        </p>
      </div>
    );
  }

  if (!fiche.transcript?.trim()) return null;

  return (
    <div>
      <h2 className="titre text-[1.0625rem] font-medium">Odoo</h2>
      {lien.record_id ? (
        <div className="mt-2 rounded-lg bg-papier p-3">
          <p className="text-[0.875rem]">
            Dossier retenu avant la transcription :{' '}
            <span className="titre font-medium">{lien.model} #{lien.record_id}</span>
          </p>
          <Bouton
            className="mt-2"
            disabled={envoi}
            onClick={async () => {
              setEnvoi(true);
              try {
                await api.odooPublish(jobId, {
                  model: lien.model, record_id: lien.record_id,
                });
                surNote('Déposée dans le dossier retenu.');
                surMaj();
              } catch (e) { surErreur(e.message); }
              finally { setEnvoi(false); }
            }}
          >
            Déposer ici
          </Bouton>
        </div>
      ) : null}
      <p className="mt-3 text-[0.8125rem] text-fonce/55">
        {lien.record_id
          ? 'Ou chercher un autre dossier.'
          : 'Déposer la transcription dans le chatter, repliée en accordéon.'}
      </p>
      <div className="mt-2">
        <Champ
          label="Chercher l'opportunité"
          placeholder="Acritec, Canolle…"
          value={requete}
          onChange={(e) => setRequete(e.target.value)}
        />
      </div>

      {candidats?.length === 0 ? (
        <p className="mt-2 text-[0.8125rem] text-fonce/50">Aucun dossier trouvé.</p>
      ) : null}

      {candidats?.length ? (
        <ul className="mt-2 space-y-1">
          {candidats.map((c) => (
            <li key={`${c.model}-${c.id}`}>
              <button
                type="button"
                disabled={envoi}
                onClick={async () => {
                  setEnvoi(true);
                  try {
                    // Relire d'abord : le dossier qu'on vient de choisir
                    // change le titre et les noms, et la note déposée
                    // doit porter la bonne version.
                    const relu = await api
                      .reenrichir(jobId, { model: c.model, record_id: c.id })
                      .catch(() => null);
                    await api.odooPublish(jobId, { model: c.model, record_id: c.id });
                    surNote(relu
                      ? `Relue puis déposée dans « ${c.name} ».`
                      : `Déposée dans « ${c.name} ».`);
                    surMaj();
                  } catch (e) { surErreur(e.message); }
                  finally { setEnvoi(false); }
                }}
                className="w-full rounded-md px-2 py-1.5 text-left text-[0.875rem] transition-colors hover:bg-white/60 disabled:opacity-40"
              >
                <span className="titre font-medium">{c.name}</span>
                <span className="block text-[0.8125rem] text-fonce/50">
                  {c.partner || c.model} · {c.updated}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
