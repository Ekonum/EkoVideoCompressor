import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { Bouton, Champ, DateHeure, Erreur } from './Communs.jsx';
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
  const [surlignee, setSurlignee] = useState(null);

  /** Amène la transcription à la réplique qui couvre cet instant. */
  const allerA = (secondes) => {
    const segments = fiche?.segments || [];
    if (!segments.length || secondes == null) return;
    let rang = 0;
    segments.forEach((seg, i) => { if (seg.start_second <= secondes) rang = i; });
    document.getElementById(`segment-${rang}`)
      ?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    setSurlignee(rang);
    setTimeout(() => setSurlignee((r) => (r === rang ? null : r)), 2500);
  };

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
      <DateReunion
        jobId={jobId}
        valeur={fiche.meeting_date || fiche.created_at}
        deduite={!fiche.meeting_date}
        surMaj={recharger}
        surErreur={setErreur}
      />

      <Erreur>{erreur}</Erreur>
      {note ? <p className="mt-4 text-[0.875rem] text-turquoise-sombre">{note}</p> : null}

      <div className="mt-8 grid gap-10 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div>
          <div className="flex items-center justify-between gap-3">
            <h2 className="titre text-[1.0625rem] font-medium">Transcription</h2>
            <div className="flex flex-wrap gap-2">
              <Relecture fiche={fiche} jobId={jobId} surMaj={recharger} surNote={setNote} surErreur={setErreur} />
              <Copier texte={fiche.transcript} />
            </div>
          </div>
          <Video jobId={jobId} video={fiche.video} surMaj={recharger} />
          <div className="verre mt-3 max-h-[34rem] overflow-y-auto rounded-xl">
            {fiche.segments.length === 0 ? (
              <p className="px-4 py-6 text-fonce/50">Pas encore de segment.</p>
            ) : (
              <ol>
                {fiche.segments.map((s, rang) => (
                  <li
                    key={rang}
                    id={`segment-${rang}`}
                    className={`flex gap-4 px-4 py-2 transition-colors duration-700 ${
                      surlignee === rang ? 'bg-turquoise/25' : ''
                    }`}
                  >
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
          <AVerifier fiche={fiche} surAller={allerA} />
          <Fenetres jobId={jobId} surNote={setNote} surErreur={setErreur} />
          <Odoo fiche={fiche} jobId={jobId} surMaj={recharger} surNote={setNote} surErreur={setErreur} />
          <Versions versions={fiche.previous_versions} />
        </aside>
      </div>
    </section>
  );
}

/** La date de la réunion — celle où elle a eu lieu, pas celle du dépôt.
 *  Corrigeable sur place : c'est elle qui trie la bibliothèque. */
function DateReunion({ jobId, valeur, deduite, surMaj, surErreur }) {
  const [edition, setEdition] = useState(false);
  const [saisie, setSaisie] = useState('');
  const date = valeur ? new Date(valeur.replace(' ', 'T')) : null;
  const lisible = date && !Number.isNaN(date.getTime())
    ? date.toLocaleString('fr-FR', { dateStyle: 'full', timeStyle: 'short' })
    : 'date inconnue';

  if (!edition) {
    return (
      <p className="mt-1 text-[0.875rem] text-fonce/70">
        Réunion du {lisible}
        {deduite ? <span className="text-fonce/45"> (date du dépôt)</span> : null}
        <button
          type="button"
          onClick={() => {
            const d = date && !Number.isNaN(date.getTime()) ? date : new Date();
            const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
            setSaisie(local.toISOString().slice(0, 16));
            setEdition(true);
          }}
          className="ml-2 text-[0.8125rem] text-turquoise-sombre underline-offset-2 hover:underline"
        >
          modifier
        </button>
      </p>
    );
  }
  return (
    <form
      className="mt-1 flex flex-wrap items-center gap-2 text-[0.875rem]"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await api.patch(jobId, { meeting_date: new Date(saisie).toISOString() });
          setEdition(false);
          surMaj();
        } catch (erreur) { surErreur(erreur.message); }
      }}
    >
      <DateHeure valeur={saisie} surChange={setSaisie} />
      <Bouton type="submit">Enregistrer</Bouton>
      <button type="button" onClick={() => setEdition(false)}
              className="text-[0.8125rem] text-fonce/55 hover:text-fonce">
        Annuler
      </button>
    </form>
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
function Copier({ texte, libelle = 'Copier la transcription' }) {
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
          : libelle}
    </button>
  );
}

/** « 17:29 » ou « 1:02:03 » → secondes ; null si illisible. */
function lireHorodatage(texte) {
  const parties = String(texte || '').trim().split(':').map(Number);
  if (!parties.length || parties.some((p) => Number.isNaN(p))) return null;
  return parties.reduce((total, p) => total * 60 + p, 0);
}

/** Ce dont le modèle n'était pas sûr.
 *
 *  L'app macOS écrivait ça dans un fichier « à vérifier » ; c'est la
 *  liste de ce qu'il faut réécouter, et elle ne vaut que si on la voit.
 */
function AVerifier({ fiche, surAller }) {
  const passages = fiche.uncertain || [];
  if (!passages.length) return null;
  return (
    <div>
      <h2 className="titre text-[1.0625rem] font-medium">À vérifier</h2>
      <p className="mt-1 text-[0.8125rem] text-fonce/55">
        {passages.length} passage{passages.length > 1 ? 's' : ''} dont le modèle
        doute — un clic amène la transcription au bon endroit.
      </p>
      <ul className="mt-2 space-y-2">
        {passages.map((p, i) => {
          const t = lireHorodatage(p.timestamp);
          return (
            <li key={i}>
              <button
                type="button"
                disabled={t === null}
                onClick={() => surAller(t)}
                className="w-full rounded-lg bg-papier p-2.5 text-left transition-colors hover:bg-turquoise/15 disabled:cursor-default disabled:hover:bg-papier"
              >
                <span className="block text-[0.75rem] tabular-nums text-turquoise-sombre">
                  {p.timestamp || '—'}
                </span>
                <span className="block text-[0.875rem]">{p.text}</span>
                {p.reason ? (
                  <span className="block text-[0.8125rem] text-fonce/55">{p.reason}</span>
                ) : null}
              </button>
            </li>
          );
        })}
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
    <button
      type="button"
      disabled={occupe}
      title="Relit le texte déjà transcrit pour refaire le titre, les noms et les corrections métier — sans retranscrire, pour moins d'un centime."
      onClick={async () => {
        setOccupe(true);
        try {
          const vue = await api.reenrichir(jobId);
          surNote(`Relu pour ${usd(vue.cost_usd)} — ${vue.title}`);
          surMaj();
        } catch (e) { surErreur(e.message); }
        finally { setOccupe(false); }
      }}
      className="rounded-md px-3 py-1.5 text-[0.8125rem] text-fonce/70 ring-1 ring-bord transition-colors hover:bg-white/60 hover:text-fonce disabled:opacity-50"
    >
      {occupe ? 'Relecture…' : 'Refaire titre et noms'}
    </button>
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

      <h3 className="titre mt-5 text-[0.9375rem] font-medium">Corriger un mot mal entendu</h3>
      {/* Une phrase à compléter plutôt que deux champs empilés : le sens
          du remplacement se lit, il ne se devine pas. */}
      <div className="mt-2 grid grid-cols-[1fr_auto_1fr] items-end gap-2">
        <Champ
          label="Mot transcrit (faux)"
          placeholder="Acritek"
          value={ancien}
          onChange={(e) => setAncien(e.target.value)}
        />
        <span aria-hidden className="pb-2 text-fonce/40">→</span>
        <Champ
          label="Bonne orthographe"
          placeholder="Acritec"
          value={nouveau}
          onChange={(e) => setNouveau(e.target.value)}
        />
      </div>
      <p className="mt-2 text-[0.8125rem] text-fonce/55">
        {ancien.trim() && nouveau.trim()
          ? <>« {ancien.trim()} » deviendra « {nouveau.trim()} » partout : transcription, segments et vocabulaire.</>
          : 'Le remplacement s’applique à toute la réunion, et le bon mot rejoint le vocabulaire de l’équipe.'}
      </p>
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
        Remplacer partout
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

/** Les versions précédentes, lisibles.
 *
 *  Une relance ou une relecture empile la version d'avant plutôt que de
 *  l'écraser. Encore faut-il pouvoir la lire : chacune se déplie sur son
 *  texte complet, qu'on peut copier pour reprendre un passage.
 */
function Versions({ versions }) {
  if (!versions?.length) return null;
  return (
    <div>
      <h2 className="titre text-[1.0625rem] font-medium">Versions précédentes</h2>
      <p className="mt-1 text-[0.8125rem] text-fonce/55">
        Gardées à chaque relance ou relecture : rien n'est perdu.
      </p>
      <ul className="mt-3 space-y-2">
        {versions.map((v, rang) => (
          <li key={rang}>
            <details className="verre group rounded-lg px-3 py-2">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-2">
                <span className="min-w-0">
                  <span className="block text-[0.75rem] text-fonce/50">
                    {jour(v.archived_at)}
                  </span>
                  <span className="block truncate text-[0.875rem]">{v.title || 'Sans titre'}</span>
                </span>
                <span className="shrink-0 text-[0.75rem] text-violet group-open:hidden">lire</span>
                <span className="hidden shrink-0 text-[0.75rem] text-fonce/50 group-open:inline">replier</span>
              </summary>
              <div className="mt-2 max-h-72 overflow-y-auto whitespace-pre-wrap rounded-md bg-white/70 p-2 text-[0.8125rem] leading-relaxed text-fonce/80">
                {v.transcript || 'Texte non conservé pour cette version.'}
              </div>
              <div className="mt-2 flex justify-end">
                <Copier texte={v.transcript} libelle="Copier cette version" />
              </div>
            </details>
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
  // Relire puis déposer prend une vingtaine de secondes : sans étape
  // affichée, l'écran paraissait figé alors que tout se passait bien.
  const [etape, setEtape] = useState('');
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

      {etape ? (
        <p className="mt-2 flex items-center gap-2 text-[0.8125rem] text-turquoise-sombre">
          <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-turquoise border-t-transparent" />
          {etape}
        </p>
      ) : null}

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
                    setEtape(`Lecture du dossier « ${c.name} » et relecture du texte…`);
                    const relu = await api
                      .reenrichir(jobId, { model: c.model, record_id: c.id })
                      .catch(() => null);
                    setEtape('Dépôt dans le chatter…');
                    await api.odooPublish(jobId, { model: c.model, record_id: c.id });
                    surNote(relu
                      ? `Relue puis déposée dans « ${c.name} ».`
                      : `Déposée dans « ${c.name} ».`);
                    surMaj();
                  } catch (e) { surErreur(e.message); }
                  finally { setEnvoi(false); setEtape(''); }
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
