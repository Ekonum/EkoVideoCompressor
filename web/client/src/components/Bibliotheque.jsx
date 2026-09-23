import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api.js';
import { Bouton, Champ, Etat, Erreur, Vide } from './Communs.jsx';
import { duree, usd, jour, horodatage } from '../format.js';

/** La bibliothèque : une table, pas une grille de cartes.
 *
 *  Ce sont des lignes comparables qu'on trie et qu'on balaie ; les
 *  encadrer une à une ajouterait des contenants sans rien clarifier.
 */
export function Bibliotheque({ surOuvrir }) {
  const [jobs, setJobs] = useState(null);
  const [erreur, setErreur] = useState('');
  const [tri, setTri] = useState({ champ: 'created_at', sens: 'desc' });
  const [recherche, setRecherche] = useState('');
  const [resultats, setResultats] = useState(null);
  const [etat, setEtat] = useState('actif');
  const [retention, setRetention] = useState(30);

  const recharger = useCallback(() => {
    api.listJobs(etat).then(setJobs).catch((e) => setErreur(e.message));
  }, [etat]);

  useEffect(() => { setJobs(null); recharger(); }, [recharger]);

  useEffect(() => {
    api.settings()
      .then((r) => setRetention(r.corbeille?.retention_jours ?? 30))
      .catch(() => {});
  }, []);

  // La recherche plein texte vit côté serveur (FTS5) : on ne filtre pas
  // la table en local, sinon elle ne verrait que la page chargée.
  useEffect(() => {
    const terme = recherche.trim();
    if (terme.length < 2) { setResultats(null); return undefined; }
    const attente = setTimeout(() => {
      api.search(terme).then(setResultats).catch((e) => setErreur(e.message));
    }, 250);
    return () => clearTimeout(attente);
  }, [recherche]);

  const triees = useMemo(() => {
    if (!jobs) return [];
    const copie = [...jobs];
    copie.sort((a, b) => {
      const ga = a[tri.champ] ?? '';
      const gb = b[tri.champ] ?? '';
      const comparaison = typeof ga === 'number' ? ga - gb : String(ga).localeCompare(String(gb), 'fr');
      return tri.sens === 'asc' ? comparaison : -comparaison;
    });
    return copie;
  }, [jobs, tri]);

  const colonne = (champ, libelle, classe = '') => (
    <th className={`px-4 py-2 text-left text-[0.8125rem] font-medium text-fonce/60 ${classe}`}>
      <button
        onClick={() => setTri((t) => ({ champ, sens: t.champ === champ && t.sens === 'desc' ? 'asc' : 'desc' }))}
        className="hover:text-fonce"
      >
        {libelle}
        {tri.champ === champ ? <span aria-hidden> {tri.sens === 'desc' ? '↓' : '↑'}</span> : null}
      </button>
    </th>
  );

  return (
    <section className="mx-auto max-w-6xl px-6 py-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h1 className="titre text-[1.5rem] font-semibold">Bibliothèque</h1>
        <div className="w-full sm:w-80">
          <Champ
            label="Rechercher dans les transcriptions"
            placeholder="un mot, un nom, une décision…"
            value={recherche}
            onChange={(e) => setRecherche(e.target.value)}
          />
        </div>
      </div>

      <div className="mt-4 flex gap-1 text-[0.875rem]">
        {[
          ['actif', 'Bibliothèque'],
          ['archive', 'Archives'],
          ['corbeille', 'Corbeille'],
        ].map(([cle, libelle]) => (
          <button
            key={cle}
            type="button"
            onClick={() => setEtat(cle)}
            className={`rounded-md px-3 py-1.5 transition-colors ${
              etat === cle ? 'bg-white/60 font-medium' : 'text-fonce/55 hover:bg-white/35'
            }`}
          >
            {libelle}
          </button>
        ))}
      </div>
      {etat === 'corbeille' ? (
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <p className="text-[0.8125rem] text-fonce/50">
            Les réunions jetées disparaissent définitivement au bout de{' '}
            {retention} jours.
          </p>
          {jobs?.length ? (
            <button
              type="button"
              onClick={async () => {
                // Ici, et seulement ici, on confirme : c'est le seul
                // geste de la bibliothèque qui ne se défait pas.
                if (!window.confirm(
                  `Supprimer définitivement ${jobs.length} réunion(s) ? `
                  + 'Cette fois, rien ne sera récupérable.',
                )) return;
                try { await api.viderCorbeille(); recharger(); }
                catch (e) { setErreur(e.message); }
              }}
              className="rounded-md px-3 py-1.5 text-[0.8125rem] text-violet ring-1 ring-violet/35 hover:bg-white/50"
            >
              Vider la corbeille
            </button>
          ) : null}
        </div>
      ) : null}

      <Erreur>{erreur}</Erreur>

      {resultats ? (
        <Resultats resultats={resultats} surOuvrir={surOuvrir} />
      ) : jobs === null ? (
        <p className="py-16 text-center text-fonce/50">Chargement…</p>
      ) : jobs.length === 0 ? (
        etat === 'corbeille' ? (
          <Vide titre="Corbeille vide">Rien à récupérer.</Vide>
        ) : etat === 'archive' ? (
          <Vide titre="Aucune archive">
            Archiver sort une réunion de la bibliothèque sans la perdre : elle
            reste trouvable par la recherche.
          </Vide>
        ) : (
          <Vide titre="Aucune transcription pour l'instant">
            Lance-en une depuis l'onglet « Nouvelle transcription ». Ton fichier
            restera sur ton poste.
          </Vide>
        )
      ) : (
        <div className="verre mt-6 overflow-x-auto rounded-xl">
          <table className="w-full min-w-[46rem] border-collapse">
            <thead className="border-b border-bord">
              <tr>
                {colonne('title', 'Réunion')}
                {colonne('created_at', 'Date')}
                {colonne('duration_seconds', 'Durée')}
                {colonne('status', 'État')}
                {colonne('cost_usd', 'Coût', 'text-right')}
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {triees.map((job) => (
                <tr
                  key={job.job_id}
                  onClick={() => surOuvrir(job.job_id)}
                  className="cursor-pointer border-b border-bord/50 last:border-0 transition-colors hover:bg-white/45"
                >
                  <td className="px-4 py-3">
                    <span className="titre font-medium">{job.title || job.filename}</span>
                    {job.has_versions ? (
                      <span className="ml-2 rounded px-1.5 py-0.5 text-[0.75rem] font-medium text-violet ring-1 ring-violet/35">
                        version antérieure
                      </span>
                    ) : null}
                    {job.title ? (
                      <span className="block text-[0.8125rem] text-fonce/45">{job.filename}</span>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 text-fonce/70">{jour(job.created_at)}</td>
                  <td className="px-4 py-3 tabular-nums text-fonce/70">{duree(job.duration_seconds)}</td>
                  <td className="px-4 py-3"><Etat valeur={job.status} /></td>
                  <td className="px-4 py-3 text-right tabular-nums text-fonce/70">{usd(job.cost_usd)}</td>
                  <td
                    className="whitespace-nowrap px-4 py-3 text-right"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Actions
                      job={job}
                      etat={etat}
                      surFait={recharger}
                      surErreur={setErreur}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** Jeter, archiver, restaurer — sans quitter la liste.
 *
 *  Pas de confirmation avant de jeter : la corbeille *est* la
 *  confirmation, et elle se défait d'un clic. Demander deux fois pour un
 *  geste réversible ne protège de rien et use l'attention. La
 *  suppression définitive, elle, se confirme : elle ne se défait pas.
 */
function Actions({ job, etat, surFait, surErreur }) {
  const [occupe, setOccupe] = useState(false);

  const agir = async (action) => {
    setOccupe(true);
    try { await action(job.job_id); surFait(); }
    catch (e) { surErreur(e.message); }
    finally { setOccupe(false); }
  };

  const bouton = (libelle, action, titre) => (
    <button
      type="button"
      title={titre}
      disabled={occupe}
      onClick={() => agir(action)}
      className="rounded px-2 py-1 text-[0.8125rem] text-fonce/55 transition-colors hover:bg-white/60 hover:text-fonce disabled:opacity-40"
    >
      {libelle}
    </button>
  );

  if (etat === 'actif') {
    return (
      <>
        {bouton('Archiver', api.archiver, 'Sortir de la bibliothèque, sans perdre')}
        {bouton('Jeter', api.jeter, 'Mettre à la corbeille')}
      </>
    );
  }
  if (etat === 'corbeille') {
    return (
      <>
        {bouton('Restaurer', api.restaurer, 'Remettre dans la bibliothèque')}
        {bouton('Supprimer', async (id) => {
          if (!window.confirm('Supprimer définitivement cette réunion ?')) {
            throw new Error('Suppression annulée.');
          }
          return api.supprimerDefinitivement(id);
        }, 'Supprimer définitivement — irréversible')}
      </>
    );
  }
  return bouton('Restaurer', api.restaurer, 'Remettre dans la bibliothèque');
}

function Resultats({ resultats, surOuvrir }) {
  if (resultats.length === 0) {
    return <Vide titre="Rien trouvé">Aucun passage ne contient ces mots.</Vide>;
  }
  return (
    <ul className="verre mt-6 divide-y divide-bord/60 rounded-xl">
      {resultats.map((hit, rang) => (
        <li key={`${hit.job_id}-${rang}`}>
          <button
            onClick={() => surOuvrir(hit.job_id)}
            className="block w-full px-4 py-3 text-left transition-colors hover:bg-white/45"
          >
            <span className="text-[0.8125rem] text-fonce/50">
              {hit.title || hit.filename} · {horodatage(hit.start_second)}
              {hit.speaker ? ` · ${hit.speaker}` : ''}
            </span>
            <span className="mt-0.5 block">{hit.text}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
