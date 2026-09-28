import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api.js';
import { Bouton, Champ, Etat, Erreur, Vide } from './Communs.jsx';
import { duree, usd, jour, horodatage } from '../format.js';
import { ALT, MOD, useRaccourcis } from '../raccourcis.js';

/** La bibliothèque : une table, pas une grille de cartes.
 *
 *  Ce sont des lignes comparables qu'on trie et qu'on balaie ; les
 *  encadrer une à une ajouterait des contenants sans rien clarifier.
 */
export function Bibliotheque({ surOuvrir }) {
  const [jobs, setJobs] = useState(null);
  const [erreur, setErreur] = useState('');
  const [tri, setTri] = useState({ champ: 'quand', sens: 'desc' });
  const [recherche, setRecherche] = useState('');
  const [resultats, setResultats] = useState(null);
  const [etat, setEtat] = useState('actif');
  const [retention, setRetention] = useState(30);
  const champRecherche = useRef(null);

  // Sélection multiple : ⌥-clic (ou ⌘/Ctrl-clic) ajoute ou retire une
  // ligne, Maj-clic prend toute la plage depuis la dernière touchée. Tant
  // qu'il y a une sélection, un simple clic la complète au lieu d'ouvrir.
  const [choisis, setChoisis] = useState(() => new Set());
  const ancre = useRef(null);

  const chercher = () => { champRecherche.current?.focus(); champRecherche.current?.select(); };
  const vider = () => { setChoisis(new Set()); ancre.current = null; };

  const recharger = useCallback(() => {
    api.listJobs(etat).then(setJobs).catch((e) => setErreur(e.message));
  }, [etat]);

  useEffect(() => { setJobs(null); recharger(); }, [recharger]);

  // Tant qu'une réunion tourne, la liste se rafraîchit seule : on doit
  // pouvoir lancer une deuxième transcription et regarder la première
  // avancer d'ici.
  const tourne = (jobs || []).some((j) => j.progress && j.status !== 'erreur');
  useEffect(() => {
    if (!tourne) return undefined;
    const minuteur = setInterval(recharger, 4000);
    return () => clearInterval(minuteur);
  }, [tourne, recharger]);

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

  useEffect(() => { vider(); }, [etat]);
  // Une réunion sortie de la liste (jetée, archivée) sort de la sélection.
  useEffect(() => {
    if (!jobs) return;
    setChoisis((c) => {
      const presents = new Set(jobs.map((j) => j.job_id));
      const reste = new Set([...c].filter((id) => presents.has(id)));
      return reste.size === c.size ? c : reste;
    });
  }, [jobs]);

  const triees = useMemo(() => {
    if (!jobs) return [];
    // La date qui compte est celle de la réunion ; à défaut, celle du dépôt.
    const copie = jobs.map((j) => ({ ...j, quand: j.meeting_date || j.created_at }));
    copie.sort((a, b) => {
      const ga = a[tri.champ] ?? '';
      const gb = b[tri.champ] ?? '';
      const comparaison = typeof ga === 'number' ? ga - gb : String(ga).localeCompare(String(gb), 'fr');
      return tri.sens === 'asc' ? comparaison : -comparaison;
    });
    return copie;
  }, [jobs, tri]);

  useRaccourcis({
    'mod+f': chercher,
    '/': chercher,
    'mod+a': (e) => {
      // Dans un champ, ⌘A sélectionne le texte, comme partout.
      if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return false;
      if (resultats || !triees.length) return false;
      setChoisis(new Set(triees.map((j) => j.job_id)));
      return undefined;
    },
    escape: () => (choisis.size ? vider() : false),
  });

  const cliquerLigne = (evenement, id) => {
    const ordre = triees.map((j) => j.job_id);
    if (evenement.shiftKey) {
      const depart = ordre.indexOf(ancre.current);
      const arrivee = ordre.indexOf(id);
      const [de, a] = depart < 0 ? [arrivee, arrivee] : [Math.min(depart, arrivee), Math.max(depart, arrivee)];
      setChoisis((c) => new Set([...c, ...ordre.slice(de, a + 1)]));
      if (depart < 0) ancre.current = id;
      return;
    }
    if (evenement.altKey || evenement.metaKey || evenement.ctrlKey || choisis.size) {
      setChoisis((c) => {
        const suite = new Set(c);
        if (suite.has(id)) suite.delete(id); else suite.add(id);
        return suite;
      });
      ancre.current = id;
      return;
    }
    surOuvrir(id);
  };

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
            ref={champRecherche}
            label={`Rechercher dans les transcriptions · ${MOD} F`}
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
        <Resultats resultats={resultats} surOuvrir={(id) => surOuvrir(id, recherche.trim())} />
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
        <>
        <p className="mt-6 h-4 text-right text-[0.75rem] text-fonce/40">
          {jobs.length > 1 && !choisis.size
            ? `${ALT}-clic pour sélectionner plusieurs réunions · Maj-clic pour une plage`
            : ''}
        </p>
        <div className="verre mt-1 overflow-x-auto rounded-xl">
          <table className="w-full min-w-[46rem] border-collapse">
            <thead className="border-b border-bord">
              <tr>
                {colonne('title', 'Réunion')}
                {colonne('quand', 'Date')}
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
                  onClick={(e) => cliquerLigne(e, job.job_id)}
                  // Maj-clic et ⌥-clic sélectionneraient aussi du texte.
                  onMouseDown={(e) => { if (e.shiftKey || e.altKey) e.preventDefault(); }}
                  aria-selected={choisis.has(job.job_id)}
                  className={`cursor-pointer border-b border-bord/50 last:border-0 transition-colors ${
                    choisis.has(job.job_id)
                      ? 'bg-turquoise/25 shadow-[inset_3px_0_0_#14A87B] hover:bg-turquoise/30'
                      : 'hover:bg-white/45'
                  }`}
                >
                  <td className="px-4 py-3">
                    <span className="titre font-medium">{job.title || job.filename}</span>
                    {job.has_versions ? (
                      <span className="ml-2 inline-block whitespace-nowrap rounded px-1.5 py-0.5 text-[0.75rem] font-medium text-violet ring-1 ring-violet/35">
                        version antérieure
                      </span>
                    ) : null}
                    {job.title ? (
                      <span className="block text-[0.8125rem] text-fonce/45">{job.filename}</span>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 text-fonce/70">{jour(job.quand)}</td>
                  <td className="px-4 py-3 tabular-nums text-fonce/70">{duree(job.duration_seconds)}</td>
                  <td className="px-4 py-3">
                    <Etat valeur={job.status} />
                    {job.progress && job.status !== 'erreur' && job.progress.total ? (
                      <span className="mt-1 block w-24">
                        <span className="block h-1 overflow-hidden rounded-full bg-bord">
                          <span
                            className="block h-full bg-turquoise transition-[width]"
                            style={{ width: `${(job.progress.done / job.progress.total) * 100}%` }}
                          />
                        </span>
                        <span className="text-[0.75rem] tabular-nums text-fonce/45">
                          {job.progress.done}/{job.progress.total} fenêtres
                        </span>
                      </span>
                    ) : null}
                  </td>
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
        </>
      )}
      {choisis.size && !resultats ? (
        <Selection
          jobs={triees.filter((j) => choisis.has(j.job_id))}
          etat={etat}
          total={triees.length}
          surTout={() => setChoisis(new Set(triees.map((j) => j.job_id)))}
          surVider={vider}
          surFait={recharger}
          surErreur={setErreur}
        />
      ) : null}
    </section>
  );
}

/** Ce qu'on peut faire d'une sélection.
 *
 *  Une barre flottante, qui n'apparaît qu'avec la sélection : les mêmes
 *  gestes que sur une ligne, appliqués à toutes. Les réunions partent
 *  une à une, et l'avancement se voit.
 */
function Selection({ jobs, etat, total, surTout, surVider, surFait, surErreur }) {
  const [cours, setCours] = useState(null); // { libelle, fait, total }
  const [bilan, setBilan] = useState('');

  const appliquer = async (libelle, action, cibles = jobs) => {
    setBilan('');
    const echecs = [];
    setCours({ libelle, fait: 0, total: cibles.length });
    for (const [rang, job] of cibles.entries()) {
      try { await action(job.job_id); } catch (e) { echecs.push(e.message); }
      setCours({ libelle, fait: rang + 1, total: cibles.length });
    }
    setCours(null);
    if (echecs.length) surErreur(`${echecs.length} réunion(s) en échec : ${echecs[0]}`);
    surFait();
    return cibles.length - echecs.length;
  };

  const n = jobs.length;
  const pluriel = n > 1 ? 's' : '';
  const terminees = jobs.filter((j) => j.status === 'termine');

  const bouton = (libelle, surClic, titre, danger = false) => (
    <button
      type="button"
      title={titre}
      disabled={Boolean(cours)}
      onClick={surClic}
      className={`rounded-md px-2.5 py-1 text-[0.8125rem] transition-colors hover:bg-white/10 disabled:opacity-40 ${
        danger ? 'text-[#ffb4ab]' : 'text-clair'
      }`}
    >
      {libelle}
    </button>
  );

  return (
    <div
      role="toolbar"
      aria-label="Actions sur la sélection"
      className="fixed inset-x-0 bottom-6 z-40 mx-auto flex w-fit max-w-[calc(100vw-2rem)] flex-wrap items-center gap-1 rounded-xl bg-fonce px-3 py-2 text-clair shadow-2xl"
    >
      <span className="px-2 text-[0.8125rem] tabular-nums text-clair/70">
        {cours
          ? `${cours.libelle} ${cours.fait}/${cours.total}…`
          : bilan || `${n} sélectionnée${pluriel}`}
      </span>
      <span className="mx-1 h-4 w-px bg-clair/20" />
      {etat === 'actif' ? (
        <>
          {bouton('Archiver', () => appliquer('Archivage', api.archiver), 'Sortir de la bibliothèque, sans perdre')}
          {bouton('Jeter', () => appliquer('Mise à la corbeille', api.jeter), 'Mettre à la corbeille — récupérable')}
          {bouton(
            'Refaire titre et noms',
            async () => {
              const faites = await appliquer('Relecture', (id) => api.reenrichir(id), terminees);
              setBilan(`${faites} relue${faites > 1 ? 's' : ''}`);
            },
            terminees.length < n
              ? `Relit le texte déjà transcrit — seules les ${terminees.length} réunion(s) terminées sont concernées.`
              : 'Relit le texte déjà transcrit pour refaire titre, noms et corrections — moins d’un centime chacune.',
          )}
        </>
      ) : null}
      {etat === 'archive' ? (
        <>
          {bouton('Restaurer', () => appliquer('Restauration', api.restaurer), 'Remettre dans la bibliothèque')}
          {bouton('Jeter', () => appliquer('Mise à la corbeille', api.jeter), 'Mettre à la corbeille — récupérable')}
        </>
      ) : null}
      {etat === 'corbeille' ? (
        <>
          {bouton('Restaurer', () => appliquer('Restauration', api.restaurer), 'Remettre dans la bibliothèque')}
          {bouton(
            'Supprimer définitivement',
            () => {
              if (!window.confirm(`Supprimer définitivement ${n} réunion${pluriel} ? Rien ne sera récupérable.`)) return;
              appliquer('Suppression', api.supprimerDefinitivement);
            },
            'Irréversible',
            true,
          )}
        </>
      ) : null}
      <span className="mx-1 h-4 w-px bg-clair/20" />
      {n < total ? bouton(`Tout (${total})`, surTout, `Tout sélectionner (${MOD} A)`) : null}
      <button
        type="button"
        onClick={surVider}
        aria-label="Annuler la sélection"
        title="Annuler la sélection (Échap)"
        className="rounded-md px-2 text-[1.125rem] leading-none text-clair/60 hover:bg-white/10 hover:text-clair"
      >
        ×
      </button>
    </div>
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
