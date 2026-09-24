import { useEffect, useRef, useState } from 'react';
import { Bouton, Champ, Erreur } from './Communs.jsx';
import { sonderDuree, identifier } from '../sonde.js';
import { api } from '../api.js';
import { useCompression } from '../useCompression.js';
import { archiver, useArchivage } from '../archivage.js';
import { Apercu } from './Apercu.jsx';
import { usePipeline } from '../usePipeline.js';
import { duree, mo, usd, horodatage, liste } from '../format.js';

const MODELE = 'gemini-3.8-flash';

/** Assistant de lancement.
 *
 *  L'intention : rendre lisible et rassurant un traitement long. D'où
 *  une seule colonne, trois moments — le fichier, le contexte, puis
 *  l'avancement — et une phrase qui dit franchement que le média ne
 *  quitte pas le poste. C'est la promesse centrale de l'outil ; elle
 *  mérite d'être écrite, pas déduite.
 */
/** « 2026-09-21T18:34 » pour un champ datetime-local, à l'heure locale. */
function versChampLocal(date) {
  const decale = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return decale.toISOString().slice(0, 16);
}

export function Nouveau({ surTermine, surBibliotheque }) {
  const [fichier, setFichier] = useState(null);
  const [secondes, setSecondes] = useState(0);
  const [lecture, setLecture] = useState('');
  const [client, setClient] = useState('');
  const [participants, setParticipants] = useState('');
  const [glossaire, setGlossaire] = useState('');
  const [contexteOdoo, setContexteOdoo] = useState('');
  const [mode, setMode] = useState('transcrire');
  const [videoDisponible, setVideoDisponible] = useState(false);
  // Quand la réunion a eu lieu. Proposée d'après le fichier — daté de la
  // fin de l'enregistrement, d'où la durée retranchée — et corrigeable :
  // un fichier recopié ou renommé porte une date qui ment.
  const [dateReunion, setDateReunion] = useState('');
  // L'archivage démarre avant que le traitement existe : la compression
  // n'attend pas la création du job, l'envoi si.
  const cibleRef = useRef(null);
  const archivage = useArchivage(cibleRef.current?.cle);
  const [sonde, setSonde] = useState(null);
  const [dossier, setDossier] = useState(null);
  const [debut, setDebut] = useState(0);
  const [fin, setFin] = useState(0);
  const pipeline = usePipeline();
  const compression = useCompression();

  const capacites = typeof AudioEncoder !== 'undefined' && window.isSecureContext;

  useEffect(() => {
    if (pipeline.etat === 'termine' && pipeline.resultat) surTermine?.(pipeline.jobId);
  }, [pipeline.etat, pipeline.resultat, pipeline.jobId, surTermine]);

  useEffect(() => {
    api.settings().then((r) => setVideoDisponible(Boolean(r.video?.disponible))).catch(() => {});
  }, []);

  useEffect(() => {
    const cible = cibleRef.current;
    if (!cible) return;
    if (pipeline.jobId != null) cible.jobId = pipeline.jobId;
    if (pipeline.etat === 'erreur') cible.abandon = true;
  }, [pipeline.jobId, pipeline.etat]);

  // Entrée de rodage : « ?source=/chemin » charge un fichier servi par le
  // serveur au lieu de passer par le sélecteur, ce qui rend la chaîne
  // vérifiable de bout en bout sans intervention. Même origine, derrière
  // Access comme le reste — rien n'est contourné.
  useEffect(() => {
    const source = new URLSearchParams(window.location.search).get('source');
    if (!source) return;
    (async () => {
      setLecture(`Chargement de ${source}…`);
      const blob = await (await fetch(source)).blob();
      const charge = new File([blob], source.split('/').pop(), { type: blob.type });
      const total = await sonderDuree(charge);
      setFichier(charge);
      setSecondes(total);
      setDebut(0);
      setFin(total);
      setLecture(`${mo(charge.size)} · ${duree(total)} (rodage)`);
    })().catch((e) => setLecture(`Rodage impossible : ${e.message}`));
  }, []);

  /** Écoute le début du fichier pour proposer un dossier Odoo.
   *
   *  Lancée d'office : elle coûte une fraction de centime, et sans elle
   *  il faut savoir soi-même quel dossier chercher. Son échec ne se
   *  remonte pas comme une erreur — on retombe simplement sur la
   *  saisie à la main.
   */
  async function ecouter(choisi, total, instant = '') {
    setSonde({ enCours: true });
    try {
      const reglages = await api.settings();
      const vue = await identifier(choisi, {
        audio: reglages.audio,
        fenetre: reglages.probe?.window_seconds || 300,
        duree: total,
        moment: instant,
      });
      setSonde({ ...vue, enCours: false });
      const retenu = vue.investigation?.record;
      if (retenu) {
        setDossier({ ...retenu, auto: Boolean(vue.investigation.auto) });
        appliquerDossier(retenu);
      }
    } catch {
      setSonde(null);
    }
  }

  async function choisir(event) {
    const choisi = event.target.files[0] || null;
    setFichier(null);
    setSecondes(0);
    setSonde(null);
    setDossier(null);
    if (!choisi) return setLecture('');
    setLecture('Lecture des métadonnées…');
    try {
      const total = await sonderDuree(choisi);
      setFichier(choisi);
      setSecondes(total);
      setDebut(0);
      setFin(total);
      setLecture(`${mo(choisi.size)} · ${duree(total)}`);
      const debutReunion = new Date((choisi.lastModified || Date.now()) - total * 1000);
      setDateReunion(versChampLocal(debutReunion));
      if (mode !== 'compresser') ecouter(choisi, total, debutReunion.toISOString());
    } catch (e) {
      setFichier(null);
      setLecture(`Fichier illisible : ${e.message}`);
    }
  }

  if (!capacites) {
    return (
      <section className="mx-auto max-w-2xl px-6 py-16">
        <h1 className="titre text-[1.5rem] font-semibold">Navigateur non supporté</h1>
        <p className="mt-3 text-fonce/70">
          Le découpage se fait sur ton poste, ce qui demande WebCodecs et une
          connexion sécurisée. Chrome, Edge ou Safari 26 et plus conviennent.
        </p>
      </section>
    );
  }

  const enCours = pipeline.etat === 'traitement' || pipeline.etat === 'creation';

  /** Verse dans le formulaire ce qu'Odoo vient d'apprendre.
   *
   *  Même geste pour une réunion d'agenda et pour un dossier proposé
   *  par la sonde : ce qui est déjà saisi n'est jamais écrasé, seulement
   *  complété.
   */
  /** Charge le contexte Odoo d'un dossier retenu. */
  async function appliquerDossier(choisi) {
    try {
      const pack = await api.odooContext(choisi.model, choisi.id);
      appliquerContexte({
        client: pack.client_company,
        termes: pack.terms,
        resume: pack.summary,
      });
    } catch {
      // Le contexte est un bonus : son échec ne doit pas empêcher de
      // retenir le dossier.
    }
  }

  function appliquerContexte({ client: societe, termes, resume, invites }) {
    if (societe) setClient((actuel) => actuel || societe);
    if (invites?.length) {
      setParticipants((actuel) =>
        [...new Set([...liste(actuel), ...invites])].join(', '),
      );
    }
    if (termes?.length) {
      setGlossaire((actuel) =>
        [...new Set([...liste(actuel), ...termes])].join(', '),
      );
    }
    if (resume) setContexteOdoo(resume);
  }

  return (
    <section className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="titre text-[1.5rem] font-semibold">Nouvelle transcription</h1>
      <p className="mt-2 max-w-xl text-fonce/70">
        Le découpage et l'encodage se font sur ce poste. Seules des fenêtres
        audio de quelques mégaoctets partent au serveur — ta vidéo, elle, ne
        quitte pas ta machine.
      </p>

      <div className="mt-8 space-y-8">
        <div>
          <h2 className="titre text-[1.0625rem] font-medium">1. Le fichier</h2>
          <input
            type="file"
            accept="video/*,audio/*"
            onChange={choisir}
            disabled={enCours}
            className="verre mt-3 block w-full cursor-pointer rounded-xl border-dashed px-4 py-6 text-fonce/70 file:mr-4 file:rounded-md file:border-0 file:bg-fonce file:px-3 file:py-1.5 file:text-clair"
          />
          {lecture ? <p className="mt-2 text-[0.875rem] text-fonce/60">{lecture}</p> : null}
          {fichier ? (
            <label className="mt-3 flex flex-wrap items-center gap-3 text-[0.875rem]">
              <span className="text-fonce/70">Date de la réunion</span>
              <input
                type="datetime-local"
                value={dateReunion}
                onChange={(e) => setDateReunion(e.target.value)}
                disabled={enCours}
                className="rounded-md border border-bord bg-white px-2 py-1 tabular-nums"
              />
              <span className="text-[0.8125rem] text-fonce/45">
                déduite du fichier — corrige-la s'il a été recopié
              </span>
            </label>
          ) : null}
          <Apercu
            fichier={fichier}
            duree={secondes}
            debut={debut}
            fin={fin || secondes}
            surDebut={setDebut}
            surFin={setFin}
            actif={enCours}
          />
        </div>

        <div>
          <h2 className="titre text-[1.0625rem] font-medium">2. Que faire de ce fichier</h2>
          <div className="mt-3 flex flex-wrap gap-2">
            {[
              ['transcrire', 'Transcrire'],
              ['compresser', 'Compresser'],
              ['les-deux', 'Les deux'],
            ].map(([cle, libelle]) => (
              <button
                key={cle}
                type="button"
                onClick={() => setMode(cle)}
                aria-pressed={mode === cle}
                className={`titre rounded-lg px-3 py-1.5 text-[0.9375rem] font-medium transition-colors ${
                  mode === cle
                    ? 'bg-fonce text-clair'
                    : 'border border-bord bg-white hover:border-fonce/40'
                }`}
              >
                {libelle}
              </button>
            ))}
          </div>
          {mode === 'les-deux' && videoDisponible ? (
            <p className="mt-2 text-[0.8125rem] text-fonce/55">
              La vidéo est compressée sur ce poste — 720p, HEVC, environ 92 %
              plus légère — puis archivée en stockage froid avec la réunion.
              Ton fichier d'origine ne quitte pas ta machine.
            </p>
          ) : mode !== 'transcrire' ? (
            <p className="mt-2 text-[0.8125rem] text-fonce/55">
              La version compressée est enregistrée sur ton disque — 720p,
              HEVC, environ 92 % plus légère.
              {mode === 'compresser' && videoDisponible
                ? ' Pour l’archiver avec la réunion, choisis « Les deux ».'
                : ''}
              {!compression.supportee
                ? " Ce navigateur ne sait pas écrire un fichier sur le disque : utilise Chrome ou Edge."
                : ''}
            </p>
          ) : null}
        </div>

        <div className={mode === 'compresser' ? 'hidden' : undefined}>
          <h2 className="titre text-[1.0625rem] font-medium">3. Le contexte</h2>
          <p className="mt-1 text-[0.875rem] text-fonce/60">
            Facultatif, mais c'est ce qui fait la différence entre « Réunion du
            3 juillet » et un titre utile.
          </p>
          <Sonde
            etat={sonde}
            retenu={dossier}
            surChoix={(choisi) => {
              // Choisi à la main : on lie, mais on ne dépose pas sans
              // demander — la personne vient justement de corriger.
              setDossier({ ...choisi, auto: false });
              appliquerDossier(choisi);
            }}
          />
          <Reunions surChoix={appliquerContexte} />
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Champ
              label="Partie prenante"
              aide="Préfixe du titre : « Acritec - Sujet »"
              placeholder="Acritec"
              value={client}
              onChange={(e) => setClient(e.target.value)}
              disabled={enCours}
            />
            <Champ
              label="Participants attendus"
              aide="Séparés par des virgules"
              placeholder="Robin, Lùka"
              value={participants}
              onChange={(e) => setParticipants(e.target.value)}
              disabled={enCours}
            />
          </div>
          <div className="mt-4">
            <Champ
              label="Vocabulaire métier"
              aide="Les termes que le modèle risque d'écorcher"
              placeholder="Odoo, Wedophone, EDOF"
              value={glossaire}
              onChange={(e) => setGlossaire(e.target.value)}
              disabled={enCours}
            />
            <Suggestions
              choisis={[...liste(glossaire), client.trim()].filter(Boolean)}
              surAjout={(terme) =>
                setGlossaire((actuel) => (actuel.trim() ? `${actuel}, ${terme}` : terme))
              }
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-4">
          <Bouton
            variante="accent"
            disabled={!fichier || enCours || (mode === 'compresser' && !compression.supportee)}
            onClick={() => {
              const borne = debut > 0 || (fin && fin < secondes)
                ? { start: debut, end: fin || secondes }
                : null;
              if (mode === 'les-deux' && videoDisponible) {
                const cible = { cle: `nouveau-${Date.now()}`, jobId: null };
                cibleRef.current = cible;
                archiver({ fichier, trim: borne, cible });
              } else if (mode !== 'transcrire') {
                compression.compresser(fichier, borne);
              }
              if (mode === 'compresser') return;
              pipeline.lancer({
                meetingDate: dateReunion ? new Date(dateReunion).toISOString() : null,
                fichier,
                // Seule la partie retenue est transcrite — donc payée.
                duree: (fin || secondes) - debut,
                offset: debut,
                modele: MODELE,
                contexte: {
                  client_company: client.trim(),
                  expected_speaker_names: liste(participants),
                  glossary_terms: liste(glossaire),
                  odoo_context: contexteOdoo,
                  // Décidé avant de partir : à la fin, le dépôt n'aura
                  // plus rien à demander.
                  ...(dossier
                    ? {
                        odoo_record: { model: dossier.model, record_id: dossier.id },
                        odoo_auto: dossier.auto,
                      }
                    : {}),
                },
              });
            }}
          >
            {enCours
              ? 'Traitement en cours…'
              : mode === 'compresser'
                ? 'Compresser'
                : mode === 'les-deux'
                  ? 'Compresser et transcrire'
                  : 'Lancer la transcription'}
          </Bouton>
          {pipeline.estimation !== null ? (
            <span className="text-[0.875rem] text-fonce/60">
              Coût estimé {usd(pipeline.estimation)}
            </span>
          ) : null}
        </div>

        <Erreur>{pipeline.erreur}</Erreur>
        <Erreur>{compression.erreur}</Erreur>
        {archivage ? <AvancementArchivage tache={archivage} /> : null}
        <Compression compression={compression} />

        {pipeline.fenetres.length > 0 ? (
          <Avancement fenetres={pipeline.fenetres} message={pipeline.message} />
        ) : null}

        {pipeline.etat === 'traitement' ? (
          <div className="verre rounded-xl p-4">
            <p className="text-[0.875rem] text-fonce/75">
              {pipeline.envoiTermine
                ? 'Tout est envoyé : le serveur termine seul. Tu peux fermer cet onglet.'
                : 'Tu peux faire autre chose pendant ce temps — garde seulement cet onglet ouvert tant que l’envoi n’est pas fini.'}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Bouton onClick={() => { pipeline.detacher(); surBibliotheque?.(); }}>
                Revenir à la bibliothèque
              </Bouton>
              <button
                type="button"
                onClick={() => {
                  // La transcription en cours continue ; on repart d'un
                  // formulaire vierge pour la suivante.
                  pipeline.detacher();
                  setFichier(null); setSecondes(0); setLecture(''); setSonde(null);
                  setDossier(null); setClient(''); setParticipants(''); setGlossaire('');
                  setContexteOdoo(''); setDateReunion(''); setDebut(0); setFin(0);
                  cibleRef.current = null;
                }}
                className="rounded-md px-3 py-1.5 text-[0.875rem] text-fonce/70 ring-1 ring-bord hover:bg-white/60"
              >
                Lancer une autre transcription
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}

const LIBELLES = {
  attendue: 'en attente',
  encodage: 'encodage sur ce poste',
  envoi: 'envoi',
  transcription: 'transcription',
  terminee: 'terminée',
  erreur: 'erreur',
};

/** Avancement par fenêtre.
 *
 *  Une ligne par fenêtre plutôt qu'une barre unique : sur une réunion de
 *  trois heures, savoir *laquelle* patine est la seule information qui
 *  aide — c'est aussi elle qu'on pourra relancer seule.
 */
function Avancement({ fenetres, message }) {
  const finies = fenetres.filter((f) => f.etat === 'terminee').length;
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <h2 className="titre text-[1.0625rem] font-medium">3. Avancement</h2>
        <span className="text-[0.875rem] text-fonce/60">
          {finies} / {fenetres.length} fenêtres
        </span>
      </div>

      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-fonce/10">
        <div
          className="h-full rounded-full bg-turquoise transition-[width] duration-500"
          style={{ width: `${(finies / fenetres.length) * 100}%` }}
        />
      </div>
      {message ? <p className="mt-2 text-[0.875rem] text-fonce/60">{message}</p> : null}

      <ul className="verre mt-4 divide-y divide-bord/60 rounded-xl">
        {fenetres.map((f) => (
          <li key={f.index} className="flex items-center gap-4 px-4 py-2.5">
            <span className="w-16 shrink-0 text-[0.875rem] tabular-nums text-fonce/55">
              {horodatage(f.start)}
            </span>
            <span className={`flex-1 text-[0.9375rem] ${f.etat === 'erreur' ? 'text-[#8c1d18]' : ''}`}>
              {f.etat === 'erreur' ? f.erreur : LIBELLES[f.etat]}
              {f.etat === 'encodage' && f.progression
                ? ` ${Math.round(f.progression * 100)} %`
                : ''}
            </span>
            <span className="shrink-0 text-[0.875rem] tabular-nums text-fonce/45">
              {f.octets ? mo(f.octets) : ''}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Vocabulaire déjà connu de l'équipe.
 *
 *  Trié par affinité avec ce qui est déjà saisi, pas par fréquence :
 *  saisir « Acritec » doit faire remonter les termes de ce client, et
 *  non les cinq mêmes mots présents dans toutes les réunions.
 */
function Suggestions({ choisis, surAjout }) {
  const [termes, setTermes] = useState([]);
  const cle = choisis.join(',');

  useEffect(() => {
    let vivant = true;
    const attente = setTimeout(() => {
      api.vocabulary(choisis)
        .then((v) => vivant && setTermes(v.slice(0, 12)))
        .catch(() => {});
    }, 200);
    return () => { vivant = false; clearTimeout(attente); };
  }, [cle]);

  if (termes.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      <span className="text-[0.8125rem] text-fonce/50">Déjà utilisés :</span>
      {termes.map((t) => (
        <button
          key={t.term}
          type="button"
          onClick={() => surAjout(t.term)}
          className="rounded-md border border-bord bg-white px-2 py-0.5 text-[0.8125rem] hover:border-turquoise-sombre hover:text-turquoise-sombre"
        >
          {t.term}
        </button>
      ))}
    </div>
  );
}

/** Ce que la sonde a entendu, et les dossiers que ça désigne.
 *
 *  Un seul point d'arrêt dans le flux, et il est ici : lier une
 *  transcription au mauvais dossier la dépose chez un autre client,
 *  visible par toute l'équipe. Le reste peut tourner seul ; ce choix-là
 *  se valide d'un clic.
 */
function Sonde({ etat, retenu, surChoix }) {
  if (!etat) return null;
  if (etat.enCours) {
    return (
      <p className="mt-4 text-[0.875rem] text-fonce/55">
        Écoute des premières minutes pour reconnaître le sujet…
      </p>
    );
  }

  const indices = etat.clues || {};
  const enquete = etat.investigation || {};
  const entendu = [...(indices.organisations || []), ...(indices.personnes || [])];
  if (!entendu.length && !(etat.candidates || []).length) return null;

  const CERTITUDE = {
    certaine: 'Liaison certaine',
    probable: 'Liaison probable',
    incertaine: 'Liaison incertaine',
  };

  return (
    <div className="verre mt-4 rounded-xl p-4">
      <p className="titre text-[0.9375rem] font-medium">Ce qu'on a entendu</p>
      {indices.resume ? (
        <p className="mt-1 text-[0.8125rem] text-fonce/70">{indices.resume}</p>
      ) : null}
      {entendu.length ? (
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {entendu.map((terme) => (
            <li key={terme}
                className="rounded-full bg-papier px-2 py-0.5 text-[0.75rem] text-fonce/70">
              {terme}
            </li>
          ))}
        </ul>
      ) : null}

      {enquete.reason && !enquete.record ? (
        <p className="mt-3 text-[0.8125rem] text-fonce/55">
          Aucun dossier proposé : {enquete.reason}
        </p>
      ) : null}

      {(etat.candidates || []).length ? (
        // Un bloc à part, sur fond clair : c'est une décision à prendre,
        // pas une information de plus. Chaque dossier est une carte avec
        // son bouton, et celui qui sera utilisé se voit d'un coup d'œil.
        <div className="mt-4 rounded-lg border border-turquoise/40 bg-white/80 p-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="titre text-[0.9375rem] font-medium">Dossier Odoo de cette réunion</p>
            {enquete.record ? (
              <span className="rounded-full bg-turquoise/20 px-2 py-0.5 text-[0.75rem] font-medium text-turquoise-sombre">
                {CERTITUDE[enquete.confidence] || 'Proposé'}
              </span>
            ) : null}
          </div>
          <p className="mt-1 text-[0.8125rem] text-fonce/60">
            {enquete.record
              ? enquete.reason
              : 'Aucun n’est certain : choisis celui qui convient, son contexte guidera la transcription.'}
          </p>
          <ul className="mt-3 space-y-2">
            {etat.candidates.map((dossier) => {
              const choisi = retenu && retenu.id === dossier.id && retenu.model === dossier.model;
              return (
                <li
                  key={`${dossier.model}-${dossier.id}`}
                  className={`flex items-center gap-3 rounded-lg border p-2.5 ${
                    choisi ? 'border-turquoise-sombre bg-turquoise/10' : 'border-bord bg-white'
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-[0.875rem]">
                      <span className="titre font-medium">{dossier.name}</span>
                      {dossier.partner ? <span className="text-fonce/55"> · {dossier.partner}</span> : null}
                    </p>
                    <p className="text-[0.75rem] text-fonce/50">
                      {[dossier.kind, dossier.reason,
                        dossier.matched ? `trouvé sur « ${dossier.matched} »` : '',
                        dossier.updated ? `modifié le ${dossier.updated}` : '']
                        .filter(Boolean).join(' · ')}
                    </p>
                  </div>
                  {choisi ? (
                    <span className="shrink-0 text-[0.8125rem] font-medium text-turquoise-sombre">
                      ✓ utilisé
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => surChoix(dossier)}
                      className="shrink-0 rounded-md bg-fonce px-3 py-1.5 text-[0.8125rem] text-clair hover:bg-fonce-doux"
                    >
                      Utiliser
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
          {retenu ? (
            <p className="mt-2 text-[0.8125rem] text-turquoise-sombre">
              {retenu.auto
                ? 'La transcription y sera déposée automatiquement, sans te redemander.'
                : 'La transcription attendra ton clic pour y être déposée.'}
            </p>
          ) : null}
        </div>
      ) : null}

      {(enquete.trace || []).length ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-[0.75rem] text-fonce/45">
            Comment on est arrivé là
          </summary>
          <ol className="mt-1 space-y-0.5 text-[0.75rem] text-fonce/55">
            {enquete.trace.map((ligne, i) => (
              <li key={i}>· {ligne}</li>
            ))}
          </ol>
        </details>
      ) : null}
    </div>
  );
}

/** Réunions Odoo du moment.
 *
 *  Odoo enrichit, il ne conditionne pas : s'il est absent ou en panne,
 *  ce bloc disparaît simplement. Rien n'empêche de transcrire.
 */
function Reunions({ surChoix }) {
  const [etat, setEtat] = useState(null);
  const [choisie, setChoisie] = useState(null);
  const [chargement, setChargement] = useState(false);

  useEffect(() => {
    api.odooMeetings().then(setEtat).catch(() => setEtat({ available: false, meetings: [] }));
  }, []);

  if (!etat?.available || etat.meetings.length === 0) return null;

  return (
    <div className="verre mt-4 rounded-xl p-4">
      <p className="titre text-[0.9375rem] font-medium">Réunions Odoo du moment</p>
      <p className="mt-0.5 text-[0.8125rem] text-fonce/55">
        En choisir une remplit les participants, la partie prenante et le
        vocabulaire depuis Odoo.
      </p>
      <ul className="mt-3 space-y-1">
        {etat.meetings.map((r) => (
          <li key={r.id}>
            <button
              type="button"
              disabled={chargement}
              onClick={async () => {
                setChoisie(r.id);
                setChargement(true);
                try {
                  const pack = r.resource_model
                    ? await api.odooContext(r.resource_model, r.resource_id)
                    : {};
                  surChoix({
                    client: pack.client_company,
                    termes: pack.terms,
                    resume: pack.summary,
                    // Les invités valent même sans fiche liée : c'est le
                    // cas le plus fréquent, et savoir qui parle change
                    // l'attribution des répliques.
                    invites: r.attendees,
                  });
                } catch {
                  // Le contexte est un bonus : son échec ne doit pas
                  // empêcher de retenir la réunion choisie.
                } finally {
                  setChargement(false);
                }
              }}
              className={`w-full rounded-md px-2 py-1.5 text-left text-[0.875rem] hover:bg-papier ${
                choisie === r.id ? 'ring-1 ring-turquoise-sombre' : ''
              }`}
            >
              <span className="titre font-medium">{r.name}</span>
              {r.attendees.length ? (
                <span className="block text-[0.8125rem] text-fonce/55">
                  {r.attendees.join(', ')}
                </span>
              ) : null}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Où en est l'archivage de la vidéo, tant qu'on est sur cet écran.
 *  La fiche de la réunion prend le relais une fois qu'on l'a ouverte. */
export function AvancementArchivage({ tache }) {
  const libelle = {
    compression: 'Compression sur ce poste',
    envoi: 'Envoi vers le stockage froid',
    termine: 'Vidéo archivée',
    erreur: 'Archivage interrompu',
  }[tache.etape] || 'Archivage';
  return (
    <div className="mt-2">
      <p className="text-[0.875rem] text-fonce/70">
        {libelle}
        {tache.etape === 'compression' || tache.etape === 'envoi'
          ? ` — ${Math.round((tache.progression || 0) * 100)} %. Tu peux continuer à travailler, mais garde cet onglet ouvert.`
          : ''}
      </p>
      {tache.etape === 'compression' || tache.etape === 'envoi' ? (
        <div className="mt-1 h-1.5 w-full max-w-md overflow-hidden rounded-full bg-bord">
          <div
            className="h-full bg-turquoise transition-[width]"
            style={{ width: `${(tache.progression || 0) * 100}%` }}
          />
        </div>
      ) : null}
      {tache.erreur ? <p className="mt-1 text-[0.8125rem] text-violet">{tache.erreur}</p> : null}
    </div>
  );
}

/** Avancement de la compression.
 *
 *  Séparé de la transcription parce que les deux avancent en parallèle
 *  et à des rythmes très différents : l'audio part en quelques minutes,
 *  la vidéo prend des heures sur une longue réunion.
 */
function Compression({ compression }) {
  if (compression.etat === 'repos' && !compression.resultat) return null;
  const { resultat } = compression;
  return (
    <div>
      <h2 className="titre text-[1.0625rem] font-medium">Compression</h2>
      {resultat ? (
        <p className="mt-2 text-[0.9375rem]">
          {mo(resultat.source)} → <strong>{mo(resultat.bytes)}</strong>{' '}
          <span className="text-fonce/55">
            ({Math.round((1 - resultat.bytes / resultat.source) * 100)} % de moins,
            en {Math.round(resultat.ms / 60000)} min) — enregistré sur ton disque.
          </span>
        </p>
      ) : (
        <>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-fonce/10">
            <div
              className="h-full rounded-full bg-turquoise transition-[width] duration-500"
              style={{ width: `${compression.progression * 100}%` }}
            />
          </div>
          <p className="mt-2 text-[0.875rem] text-fonce/60">
            Encodage sur ce poste — {Math.round(compression.progression * 100)} %.
            Garde cet onglet ouvert.
          </p>
        </>
      )}
    </div>
  );
}
