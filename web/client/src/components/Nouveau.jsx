import { useEffect, useState } from 'react';
import { Bouton, Champ, Erreur } from './Communs.jsx';
import { sonderDuree } from '../sonde.js';
import { api } from '../api.js';
import { useCompression } from '../useCompression.js';
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
export function Nouveau({ surTermine }) {
  const [fichier, setFichier] = useState(null);
  const [secondes, setSecondes] = useState(0);
  const [lecture, setLecture] = useState('');
  const [client, setClient] = useState('');
  const [participants, setParticipants] = useState('');
  const [glossaire, setGlossaire] = useState('');
  const [contexteOdoo, setContexteOdoo] = useState('');
  const [mode, setMode] = useState('transcrire');
  const pipeline = usePipeline();
  const compression = useCompression();

  const capacites = typeof AudioEncoder !== 'undefined' && window.isSecureContext;

  useEffect(() => {
    if (pipeline.etat === 'termine' && pipeline.resultat) surTermine?.(pipeline.jobId);
  }, [pipeline.etat, pipeline.resultat, pipeline.jobId, surTermine]);

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
      setLecture(`${mo(charge.size)} · ${duree(total)} (rodage)`);
    })().catch((e) => setLecture(`Rodage impossible : ${e.message}`));
  }, []);

  async function choisir(event) {
    const choisi = event.target.files[0] || null;
    setFichier(null);
    setSecondes(0);
    if (!choisi) return setLecture('');
    setLecture('Lecture des métadonnées…');
    try {
      const total = await sonderDuree(choisi);
      setFichier(choisi);
      setSecondes(total);
      setLecture(`${mo(choisi.size)} · ${duree(total)}`);
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
          {mode !== 'transcrire' ? (
            <p className="mt-2 text-[0.8125rem] text-fonce/55">
              La version compressée est écrite directement sur ton disque —
              720p, HEVC, environ 92 % plus légère. Elle n'est jamais envoyée
              au serveur.
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
          <Reunions
            surChoix={({ client: societe, termes, resume }) => {
              if (societe) setClient(societe);
              if (termes?.length) {
                setGlossaire((actuel) =>
                  [...new Set([...liste(actuel), ...termes])].join(', '),
                );
              }
              setContexteOdoo(resume || '');
            }}
          />
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
              if (mode !== 'transcrire') compression.compresser(fichier);
              if (mode === 'compresser') return;
              pipeline.lancer({
                fichier,
                duree: secondes,
                modele: MODELE,
                contexte: {
                  client_company: client.trim(),
                  expected_speaker_names: liste(participants),
                  glossary_terms: liste(glossaire),
                  odoo_context: contexteOdoo,
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
        <Compression compression={compression} />

        {pipeline.fenetres.length > 0 ? (
          <Avancement fenetres={pipeline.fenetres} message={pipeline.message} />
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
        En choisir une remplit la partie prenante et le vocabulaire depuis la fiche.
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
