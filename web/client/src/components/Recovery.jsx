import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api.js';
import { envoyerMorceaux } from '../archivage.js';
import { choixDossier, decrire, lireSelection, MAX_FICHIERS, parcourirDossier } from '../dossierMac.js';
import { Erreur } from './Communs.jsx';
import { duree, fileSize, jour } from '../format.js';

/** Récupérer son historique.
 *
 *  Avant transcript, les réunions finissaient dans le Drive, dans Odoo ou
 *  sur le Mac. Cet écran en fait l'inventaire et les range ici, à leur
 *  date. Rien ne bouge sans être coché : le Drive mêle réunions,
 *  tutoriels et voix off, et c'est à la personne de trier.
 */

const CONNECTION_MESSAGES = {
  connected: ['ok', 'Google Drive connecté.'],
  refused: ['erreur', 'Connexion annulée : rien n’a été partagé avec transcript.'],
  expired: ['erreur', 'La connexion a pris trop de temps. Recommence.'],
  wrong_account: ['erreur', 'Ce n’était pas ton compte Google Ekonum : connecte celui de ton adresse transcript.'],
  failed: ['erreur', 'Google n’a pas pu finaliser la connexion. Réessaie dans un instant.'],
};

const KIND_FILTERS = [
  ['meeting', 'Réunions probables'],
  ['unsure', 'À trier'],
  ['other', 'Probablement pas des réunions'],
  ['done', 'Déjà dans transcript'],
];

// Le Drive partagé et la fiche Odoo se disent par leur nom.
const LOCATION_LABELS = {
  my_drive: 'Mon Drive',
  shared_with_me: 'Partagé avec moi',
};

const plural = (n, singulier, pluriel) => `${n.toLocaleString('fr-FR')} ${n > 1 ? pluriel : singulier}`;

// Ce qu'on montre d'un enregistrement : sa durée et son poids.
const FILE_COLUMNS = [
  { label: 'Durée', cell: (item) => (item.duration_seconds ? duree(item.duration_seconds) : '—') },
  { label: 'Taille', right: true, cell: (item) => fileSize(item.size) },
];

const FILE_STATUS = {
  recovered: (item) => (item.recovered_by ? `déjà récupéré${item.job_id ? '' : ` par ${item.recovered_by}`}` : 'déjà récupéré'),
  duplicate: () => 'copie d’un autre fichier de la liste',
  in_library: (item) => (item.job_id
    ? 'déjà transcrite : sera rangée avec la réunion existante'
    : 'semble déjà transcrite par un collègue'),
};

/** Ce qui distingue une source dans l'inventaire : comment récupérer un
 *  élément, comment le ranger avec sa réunion, ce que devient l'original,
 *  et comment le dire. */
const DRIVE = {
  name: 'Drive',
  item: 'Fichier',
  dateLabel: 'date du Drive',
  needsStorage: true,
  columns: FILE_COLUMNS,
  status: FILE_STATUS,
  selection: (chosen) => `${plural(chosen.length, 'fichier', 'fichiers')} · ${fileSize(chosen.reduce((sum, i) => sum + (i.size || 0), 0))}`,
  recovered: (n) => `${plural(n, 'fichier rangé', 'fichiers rangés')} à leur date dans ta bibliothèque`,
  prompt: 'Coche les fichiers à récupérer',
  empty: 'Aucun fichier audio ou vidéo dans ce Drive.',
  trash: 'Mettre les originaux à la corbeille du Drive une fois copiés (30 jours pour se raviser)',
  import: (item, trash) => api.driveImport(item.id, trash),
  attach: (item, trash) => api.driveAttach(item.id, item.job_id, trash),
};

// Odoo n'a pas de corbeille, et l'enregistrement fait partie du dossier :
// l'original reste sur sa fiche.
const ODOO = {
  ...DRIVE,
  name: 'Odoo',
  title: 'Odoo',
  dateLabel: 'date d’Odoo',
  intro: 'Les enregistrements joints à tes fiches et à tes discussions. Une réunion récupérée depuis une fiche y reste liée, et l’original ne quitte pas Odoo.',
  noKey: 'Les enregistrements joints à tes fiches et à tes discussions. Il faut d’abord ta clé Odoo personnelle : transcript ne voit que ce que tu vois dans Odoo.',
  start: 'Faire l’inventaire d’Odoo',
  loading: 'Inventaire d’Odoo…',
  inventory: () => api.odooInventory(),
  empty: 'Aucun enregistrement audio ou vidéo joint à tes fiches Odoo.',
  trash: '',
  note: 'Les originaux restent sur leur fiche Odoo.',
  left: (linked) => (linked ? 'liée à sa fiche Odoo, où l’original reste' : 'original laissé dans Odoo'),
  import: (item) => api.odooImport(item.id),
  attach: (item) => api.odooAttach(item.id, item.job_id),
};

// Le texte d'une réunion, collé dans une note avant transcript. Rien à
// stocker : la réunion arrive transcrite, liée à sa fiche, et la note
// compte comme son dépôt — transcript ne la redéposera pas.
const ODOO_NOTES = {
  ...ODOO,
  title: 'Transcriptions collées dans Odoo',
  item: 'Transcription',
  dateLabel: 'date de la note',
  needsStorage: false,
  intro: 'Les transcriptions déposées en note sur tes fiches, « Transcription complète (cliquer pour dérouler) ». Celles déjà dans transcript sont reconnues à leur texte, même transcrites par un autre outil.',
  noKey: 'Les transcriptions déposées en note sur tes fiches. Il faut d’abord ta clé Odoo personnelle : transcript ne voit que ce que tu vois dans Odoo.',
  start: 'Retrouver les transcriptions d’Odoo',
  loading: 'Lecture des notes d’Odoo…',
  inventory: () => api.odooNotes(),
  columns: [
    { label: 'Longueur', right: true, cell: (item) => plural(item.words, 'mot', 'mots') },
    { label: 'Collée par', cell: (item) => item.author || '—' },
  ],
  status: {
    recovered: (item) => (item.job_id || !item.recovered_by ? 'déjà récupérée' : `déjà récupérée par ${item.recovered_by}`),
    published: () => 'déposée par transcript',
    colleague: (item) => `déjà dans la bibliothèque de ${item.recovered_by}`,
    duplicate: () => 'la même transcription qu’une autre note de la liste',
    in_library: () => 'déjà dans ta bibliothèque : la réunion sera liée à cette note',
  },
  selection: (chosen) => `${plural(chosen.length, 'transcription', 'transcriptions')} · ${plural(chosen.reduce((sum, i) => sum + (i.words || 0), 0), 'mot', 'mots')}`,
  recovered: (n) => `${plural(n, 'transcription rangée', 'transcriptions rangées')} à leur date dans ta bibliothèque`,
  prompt: 'Coche les transcriptions à récupérer',
  empty: 'Aucune transcription collée dans tes fiches Odoo.',
  note: 'Les notes restent sur leur fiche Odoo.',
  left: (linked) => (linked ? 'liée à sa fiche Odoo, où la note reste' : 'la note reste dans Odoo'),
  import: (item) => api.odooNoteImport(item.id),
  attach: (item) => api.odooNoteAttach(item.id, item.job_id),
};

// Le Mac : le navigateur a parcouru le dossier, il envoie lui-même chaque
// fichier coché, et l'original reste où il est. Une réunion n'est comptée
// récupérée qu'une fois son enregistrement arrivé en entier.
const MAC = {
  ...DRIVE,
  name: 'Mac',
  dateLabel: 'date du fichier',
  dateTitle: 'Date de dernière modification du fichier : la réunion peut être un peu plus ancienne.',
  trash: '',
  note: 'Les originaux restent sur ton Mac. Garde cette page ouverte pendant l’envoi.',
  empty: 'Aucun enregistrement audio ou vidéo dans ce dossier.',
  uploads: true,
};

function macSource(fichiers) {
  // Envoyer le fichier quand le serveur l'attend, puis lui faire constater
  // qu'il est arrivé en entier.
  const envoyer = async (vue, item, surProgression) => {
    if (!vue.upload) return vue;
    const { description, fichier } = fichiers.get(item.id);
    await envoyerMorceaux(vue.job_id, fichier, vue.morceau, surProgression);
    return api.macDone(description, vue.job_id);
  };
  return {
    ...MAC,
    import: async (item, _trash, surProgression) => {
      const { description } = fichiers.get(item.id);
      const vue = await api.macImport(description);
      try {
        return await envoyer(vue, item, surProgression);
      } catch (e) {
        // Pas de réunion vide dans la bibliothèque : un nouvel essai
        // repartira de zéro.
        await api.macAbandon(description, vue.job_id).catch(() => {});
        throw e;
      }
    },
    attach: async (item, _trash, surProgression) => {
      const vue = await api.macAttach(fichiers.get(item.id).description, item.job_id);
      return envoyer(vue, item, surProgression);
    },
  };
}

export function Recovery({ connection, onOpen, onAccount }) {
  const [state, setState] = useState(null);
  const [error, setError] = useState('');
  const message = CONNECTION_MESSAGES[connection];

  useEffect(() => {
    api.recoveryState().then(setState).catch((e) => setError(e.message));
  }, []);

  return (
    <section className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="titre text-[1.5rem] font-semibold">Récupérer ton historique</h1>
      <p className="mt-2 max-w-2xl text-ekn-text/70">
        Les réunions enregistrées avant transcript dorment peut-être dans ton
        Drive, sur tes fiches Odoo ou sur ton Mac. On les retrouve, tu choisis lesquelles
        ranger ici — à la date où elles ont eu lieu. Rien n’est transcrit
        d’office : tu lances la transcription d’une réunion quand tu en as
        besoin.
      </p>
      {message ? (
        <p className={`mt-4 text-ekn-sm ${message[0] === 'ok' ? 'text-ekn-tone-success' : 'text-ekn-tone-error'}`}>
          {message[1]}
        </p>
      ) : null}
      <Erreur>{error}</Erreur>

      <div className="mt-8 space-y-6">
        {state ? (
          <DriveSource
            google={state.google}
            storage={state.storage}
            onGoogle={(google) => setState({ ...state, google })}
            onOpen={onOpen}
          />
        ) : (
          <p className="text-ekn-text-muted">Chargement…</p>
        )}
        {state ? (
          <OdooSource source={ODOO} configured={state.odoo} storage={state.storage} onOpen={onOpen} onAccount={onAccount} />
        ) : null}
        {state ? (
          <OdooSource source={ODOO_NOTES} configured={state.odoo} storage={state.storage} onOpen={onOpen} onAccount={onAccount} />
        ) : null}
        {state ? <MacSource storage={state.storage} onOpen={onOpen} /> : null}
      </div>
    </section>
  );
}

function MacSource({ storage, onOpen }) {
  const [inventory, setInventory] = useState(null); // { folder, items, source }
  const [progress, setProgress] = useState('');
  const [error, setError] = useState('');
  const input = useRef(null);

  const examine = async (folder, trouver) => {
    setError('');
    setProgress('Parcours du dossier…');
    try {
      const trouves = await trouver();
      if (trouves.length > MAX_FICHIERS) {
        throw new Error(`${plural(trouves.length, 'enregistrement', 'enregistrements')} dans ce dossier : choisis-en un plus petit.`);
      }
      const descriptions = await decrire(trouves, ({ empreintes, total }) => {
        setProgress(`Empreinte des fichiers… ${empreintes}/${total}`);
      });
      setProgress('Comparaison avec la bibliothèque…');
      const vue = await api.macInventory(descriptions);
      const fichiers = new Map(trouves.map((t, n) => [t.chemin, { fichier: t.fichier, description: descriptions[n] }]));
      setInventory({
        folder, items: vue.items, source: macSource(fichiers), key: Date.now(),
        reload: () => examine(folder, trouver),
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setProgress('');
    }
  };

  const choose = async () => {
    if (!choixDossier()) {
      input.current?.click();
      return;
    }
    let dossier;
    try {
      dossier = await window.showDirectoryPicker({ id: 'recuperation', mode: 'read', startIn: 'videos' });
    } catch (e) {
      if (e.name !== 'AbortError') setError('Chrome n’a pas pu ouvrir ce dossier. Choisis-en un autre, par exemple Films ou Documents.');
      return;
    }
    examine(dossier.name, () => parcourirDossier(dossier, ({ vus, trouves }) => {
      setProgress(`Parcours du dossier… ${plural(vus, 'fichier vu', 'fichiers vus')}, ${plural(trouves, 'enregistrement', 'enregistrements')}`);
    }));
  };

  return (
    <div className="verre rounded-xl p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="titre text-[1.0625rem] font-medium">Ton Mac</h2>
        {inventory && !progress ? (
          <span className="text-ekn-sm text-ekn-text-muted">
            {inventory.folder} ·{' '}
            <button type="button" className="underline-offset-2 hover:text-ekn-text hover:underline" onClick={choose}>
              changer de dossier
            </button>
          </span>
        ) : null}
      </div>
      <input
        ref={input}
        type="file"
        webkitdirectory=""
        multiple
        hidden
        onChange={(e) => {
          const fichiers = e.target.files;
          if (fichiers?.length) {
            const dossier = fichiers[0].webkitRelativePath.split('/')[0];
            examine(dossier, async () => lireSelection(fichiers));
          }
          e.target.value = '';
        }}
      />
      {progress ? (
        <p className="mt-3 text-ekn-sm tabular-nums text-ekn-text-muted">{progress}</p>
      ) : !inventory ? (
        <div className="mt-2">
          <p className="text-ekn-sm text-ekn-text/60">
            Les enregistrements restés sur ton poste. Choisis un dossier —
            Films, Documents, Bureau : ton navigateur le parcourt, et rien
            n’est envoyé avant que tu coches. Les originaux ne bougent pas.
          </p>
          <button type="button" className="ekn-button mt-3" onClick={choose}>
            Choisir un dossier
          </button>
        </div>
      ) : null}
      <Erreur>{error}</Erreur>
      {inventory && !progress ? (
        <Inventory
          key={inventory.key}
          items={inventory.items}
          source={inventory.source}
          storage={storage}
          onReload={inventory.reload}
          onOpen={onOpen}
        />
      ) : null}
    </div>
  );
}

function OdooSource({ source, configured, storage, onOpen, onAccount }) {
  const [items, setItems] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [open, setOpen] = useState(false);

  const load = () => {
    setOpen(true);
    setLoading(true);
    setError('');
    source.inventory()
      .then((vue) => setItems(vue.items))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  return (
    <div className="verre rounded-xl p-5">
      <h2 className="titre text-[1.0625rem] font-medium">{source.title}</h2>
      {!configured ? (
        <div className="mt-2">
          <p className="text-ekn-sm text-ekn-text/60">{source.noKey}</p>
          <button type="button" className="ekn-button ekn-button--subtle mt-3" onClick={onAccount}>
            Ajouter ma clé Odoo
          </button>
        </div>
      ) : !open ? (
        <div className="mt-2">
          <p className="text-ekn-sm text-ekn-text/60">{source.intro}</p>
          <button type="button" className="ekn-button mt-3" onClick={load}>
            {source.start}
          </button>
        </div>
      ) : loading && !items ? (
        <p className="mt-3 text-ekn-sm text-ekn-text-muted">{source.loading}</p>
      ) : (
        <>
          <Erreur>{error}</Erreur>
          {items ? (
            <Inventory items={items} source={source} storage={storage} onReload={load} onOpen={onOpen} />
          ) : null}
        </>
      )}
    </div>
  );
}

function DriveSource({ google, storage, onGoogle, onOpen }) {
  const [items, setItems] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = () => {
    setLoading(true);
    setError('');
    api.driveInventory()
      .then((vue) => setItems(vue.items))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { if (google.connected) load(); }, [google.connected]);

  return (
    <div className="verre rounded-xl p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="titre text-[1.0625rem] font-medium">Google Drive</h2>
        {google.connected ? (
          <span className="text-ekn-sm text-ekn-text-muted">
            {google.email} ·{' '}
            <button
              type="button"
              className="underline-offset-2 hover:text-ekn-text hover:underline"
              onClick={async () => {
                await api.googleDisconnect();
                setItems(null);
                onGoogle({ ...google, connected: false, email: '' });
              }}
            >
              déconnecter
            </button>
          </span>
        ) : null}
      </div>

      {!google.available ? (
        <p className="mt-2 text-ekn-sm text-ekn-text/60">
          La connexion à Google n’est pas encore configurée sur ce serveur.
        </p>
      ) : !google.connected ? (
        <div className="mt-2">
          <p className="text-ekn-sm text-ekn-text/60">
            Ton Drive, les Drive partagés dont tu es membre, et ce qu’on t’a
            partagé. transcript ne voit que ce que tu vois, et ne déplace un
            fichier qu’en ton nom, quand tu le demandes.
          </p>
          <a
            href="/api/google/connect"
            className="ekn-button mt-3"
          >
            Connecter mon Google Drive
          </a>
        </div>
      ) : loading && !items ? (
        <p className="mt-3 text-ekn-sm text-ekn-text-muted">Inventaire du Drive… cela peut prendre une minute.</p>
      ) : (
        <>
          <Erreur>{error}</Erreur>
          {items ? (
            <Inventory items={items} source={DRIVE} storage={storage} onReload={load} onOpen={onOpen} />
          ) : null}
        </>
      )}
    </div>
  );
}

function Inventory({ items, source, storage, onReload, onOpen }) {
  const [filter, setFilter] = useState('meeting');
  const [selected, setSelected] = useState(() => new Set([
    ...items.filter((i) => i.status === 'new' && i.kind === 'meeting').map((i) => i.id),
    ...plusLegerParReunion(items.filter(attachable)).map((i) => i.id),
  ]));
  const [trashOriginals, setTrashOriginals] = useState(true);
  const [results, setResults] = useState({}); // id → { state, message, jobId }
  const [running, setRunning] = useState(false);

  const done = (i) => i.status !== 'new' && i.status !== 'in_library';
  const groups = useMemo(() => ({
    meeting: items.filter((i) => !done(i) && i.kind === 'meeting'),
    unsure: items.filter((i) => !done(i) && i.kind === 'unsure'),
    other: items.filter((i) => !done(i) && i.kind === 'other'),
    done: items.filter(done),
  }), [items]);
  const visible = groups[filter];
  // Un échec reste coché : un second clic sur « Récupérer » le retente.
  const chosen = items.filter((i) => selected.has(i.id) && (!results[i.id] || results[i.id].state === 'error'));
  const ready = storage || !source.needsStorage;

  const toggle = (id) => setSelected((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  // Quitter la page couperait l'envoi en cours depuis le navigateur.
  useEffect(() => {
    if (!running || !source.uploads) return undefined;
    const retenir = (e) => { e.preventDefault(); e.returnValue = ''; };
    window.addEventListener('beforeunload', retenir);
    return () => window.removeEventListener('beforeunload', retenir);
  }, [running, source.uploads]);

  const recover = async () => {
    setRunning(true);
    for (const item of chosen) {
      setResults((r) => ({ ...r, [item.id]: { state: 'running' } }));
      const progress = (part) => setResults((r) => ({ ...r, [item.id]: { state: 'running', progress: part } }));
      try {
        // Déjà transcrite : le fichier rejoint sa réunion, il n'en crée pas
        // une seconde.
        const vue = attachable(item)
          ? await source.attach(item, trashOriginals, progress)
          : await source.import(item, trashOriginals, progress);
        setResults((r) => ({
          ...r,
          [item.id]: { state: 'done', jobId: vue.job_id, message: resultMessage(vue, source) },
        }));
      } catch (e) {
        setResults((r) => ({ ...r, [item.id]: { state: 'error', message: e.message } }));
      }
    }
    setRunning(false);
  };

  const recoveredCount = Object.values(results).filter((r) => r.state === 'done').length;

  if (!items.length) {
    return <p className="mt-3 text-ekn-sm text-ekn-text/60">{source.empty}</p>;
  }

  return (
    <div className="mt-4">
      <div className="flex flex-wrap gap-1 text-ekn-sm">
        {KIND_FILTERS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setFilter(key)}
            className={`rounded-md px-3 py-1.5 transition-colors ${
              filter === key ? 'bg-voile/70 font-medium' : 'text-ekn-text-muted hover:bg-voile/40'
            }`}
          >
            {label} <span className="tabular-nums text-ekn-text-muted">{groups[key].length}</span>
          </button>
        ))}
        <button type="button" onClick={onReload} className="ml-auto px-2 text-ekn-sm text-ekn-text-muted hover:text-ekn-text">
          Relancer l’inventaire
        </button>
      </div>

      {visible.length ? (
        <div className="mt-3 overflow-x-auto rounded-lg border border-bord/70 bg-voile/60">
          <table className="w-full min-w-[46rem] border-collapse text-ekn-sm">
            <thead className="border-b border-bord text-left text-ekn-sm text-ekn-text-muted">
              <tr>
                <th className="w-10 px-3 py-2" />
                <th className="px-3 py-2 font-medium">{source.item}</th>
                <th className="px-3 py-2 font-medium">Date</th>
                {source.columns.map((c) => (
                  <th key={c.label} className={`px-3 py-2 font-medium ${c.right ? 'text-right' : ''}`}>{c.label}</th>
                ))}
                <th className="px-3 py-2 font-medium">Emplacement</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((item) => (
                <Row
                  key={item.id}
                  item={item}
                  checked={selected.has(item.id)}
                  result={results[item.id]}
                  disabled={running || done(item)}
                  onToggle={() => toggle(item.id)}
                  onOpen={onOpen}
                  source={source}
                />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="mt-3 text-ekn-sm text-ekn-text-muted">Rien dans cette catégorie.</p>
      )}

      <div className="ekn-dark sticky bottom-4 mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl bg-fonce px-4 py-3 text-clair shadow-xl">
        <span className="text-ekn-sm tabular-nums">
          {running
            ? `Récupération… ${recoveredCount}/${recoveredCount + chosen.length}`
            : chosen.length
              ? source.selection(chosen)
              : recoveredCount
                ? source.recovered(recoveredCount)
                : source.prompt}
        </span>
        {source.trash ? (
          <label className="flex items-center gap-2 text-ekn-sm text-clair/80">
            <input
              type="checkbox"
              checked={trashOriginals}
              disabled={running}
              onChange={(e) => setTrashOriginals(e.target.checked)}
              className="h-4 w-4 accent-turquoise"
            />
            {source.trash}
          </label>
        ) : source.note ? (
          <span className="text-ekn-sm text-clair/70">{source.note}</span>
        ) : null}
        <button
          type="button"
          disabled={running || !chosen.length || !ready}
          onClick={recover}
          title={ready ? '' : 'Le stockage vidéo n’est pas configuré'}
          className="ml-auto rounded-lg bg-turquoise px-4 py-1.5 text-ekn-sm font-medium text-fonce hover:bg-turquoise/90 disabled:opacity-40"
        >
          Récupérer
        </button>
      </div>
    </div>
  );
}

// Un fichier qui enregistre une réunion déjà à soi dans transcript : on le
// range avec elle plutôt que d'en créer une seconde.
const attachable = (item) => item.status === 'in_library' && Boolean(item.job_id);

/** Plusieurs fichiers pour une même réunion (l'original, sa version
 *  compressée, une copie) : seul le plus léger est coché d'office — la
 *  réunion ne garde qu'une vidéo, la première envoyée. */
function plusLegerParReunion(items) {
  const retenus = new Map();
  for (const item of items) {
    const deja = retenus.get(item.job_id);
    if (!deja || Number(item.size) < Number(deja.size)) retenus.set(item.job_id, item);
  }
  return [...retenus.values()];
}

function resultMessage(vue, source) {
  const rangement = vue.video === 'attached'
    ? 'rangée avec la réunion existante, qui garde désormais son enregistrement'
    : vue.video === 'kept' ? 'rangée avec la réunion existante' : 'récupérée';
  const original = {
    trashed: 'original à la corbeille du Drive',
    kept: 'original gardé (droits insuffisants pour le retirer)',
    kept_different: 'original gardé : il diffère de l’enregistrement déjà conservé',
    left_in_odoo: source.left?.(vue.linked),
    left_on_mac: 'original laissé sur ton Mac',
  }[vue.original];
  return original ? `${rangement} · ${original}` : rangement;
}

function Row({ item, checked, result, disabled, onToggle, onOpen, source }) {
  const status = source.status[item.status]?.(item);

  return (
    <tr className="border-b border-bord/50 last:border-0">
      <td className="px-3 py-2 align-top">
        {result?.state === 'done' ? (
          <span className="text-ekn-tone-success">✓</span>
        ) : result?.state === 'running' ? (
          <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-ekn-text/20 border-t-fonce/70" />
        ) : (
          <input
            type="checkbox"
            checked={checked}
            disabled={disabled}
            onChange={onToggle}
            aria-label={`Récupérer ${item.name}`}
            className="mt-0.5 h-4 w-4 accent-turquoise-sombre disabled:opacity-30"
          />
        )}
      </td>
      <td className="px-3 py-2">
        {item.web_link ? (
          <a href={item.web_link} target="_blank" rel="noreferrer" className="ekn-link">
            {item.name}
          </a>
        ) : (
          <span className="break-all" title={item.id}>{item.name}</span>
        )}
        {item.excerpt ? (
          <span className="max-w-xl text-ekn-sm text-ekn-text/60 line-clamp-2">{item.excerpt}</span>
        ) : null}
        {result?.state === 'running' && result.progress !== undefined ? (
          <span className="block text-ekn-sm tabular-nums text-ekn-text-muted">
            envoi… {Math.round(result.progress * 100)} %
          </span>
        ) : status || result ? (
          <span className={`block text-ekn-sm ${result?.state === 'error' ? 'text-ekn-tone-error' : 'text-ekn-text-muted'}`}>
            {result?.message || status}
            {(result?.jobId || item.job_id) ? (
              <button
                type="button"
                onClick={() => onOpen(result?.jobId || item.job_id)}
                className="ml-2 ekn-link"
              >
                ouvrir
              </button>
            ) : null}
          </span>
        ) : null}
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-ekn-text/70">
        {jour(item.recorded_at)}
        {!item.recorded_at_from_name ? (
          <span className="block text-ekn-xs text-ekn-text-muted" title={source.dateTitle || `Date du dépôt dans ${source.name} : la réunion peut être un peu plus ancienne.`}>
            {source.dateLabel}
          </span>
        ) : null}
      </td>
      {source.columns.map((c) => (
        <td key={c.label} className={`whitespace-nowrap px-3 py-2 tabular-nums text-ekn-text/70 ${c.right ? 'text-right' : ''}`}>
          {c.cell(item)}
        </td>
      ))}
      <td className="px-3 py-2 text-ekn-text/60">
        {LOCATION_LABELS[item.location.kind] || item.location.name}
      </td>
    </tr>
  );
}
