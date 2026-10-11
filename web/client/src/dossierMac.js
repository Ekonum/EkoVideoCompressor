/** Parcourir un dossier du Mac depuis le navigateur.
 *
 *  Rien ne quitte le poste à ce stade : on liste les enregistrements, on
 *  calcule une empreinte de chacun, et seule cette liste part au serveur
 *  pour l'inventaire. Un fichier n'est envoyé qu'une fois coché.
 */

const MEDIA = new Set([
  'mp4', 'm4v', 'mov', 'mkv', 'webm', 'avi', 'm4a', 'mp3', 'wav', 'aac', 'flac',
  'ogg', 'opus', 'amr', 'caf', 'aiff', 'aif', 'qta', '3gp',
]);
// Les paquets de macOS sont des dossiers : on n'y entre pas, la
// photothèque et les projets iMovie ont leurs propres outils.
const PAQUETS = /\.(app|photoslibrary|imovielibrary|fcpbundle|logicx|band|bundle|framework|plugin|tvlibrary|musiclibrary)$/i;
const IGNORES = new Set(['Library', 'node_modules', 'Applications']);
// En dessous, ce n'est pas une réunion : un son système, une notification.
const TAILLE_MIN = 50 * 1024;
// Ce que l'empreinte lit au début et à la fin de chaque fichier.
const BOUT = 256 * 1024;
export const MAX_FICHIERS = 5000;

/** Le dossier peut-il être choisi en entier, ou seulement fichier par
 *  fichier (Safari, Firefox) ? */
export const choixDossier = () => typeof window.showDirectoryPicker === 'function';

const extension = (nom) => nom.slice(nom.lastIndexOf('.') + 1).toLowerCase();
const retenu = (fichier) => MEDIA.has(extension(fichier.name)) && fichier.size >= TAILLE_MIN;
const ignore = (nom) => nom.startsWith('.') || IGNORES.has(nom) || PAQUETS.test(nom);

/** Les enregistrements d'un dossier choisi avec showDirectoryPicker. */
export async function parcourirDossier(dossier, surAvancee) {
  const trouves = [];
  let vus = 0;
  async function visiter(poignee, chemin) {
    for await (const entree of poignee.values()) {
      if (ignore(entree.name)) continue;
      const ici = chemin ? `${chemin}/${entree.name}` : entree.name;
      if (entree.kind === 'directory') {
        await visiter(entree, ici);
      } else {
        vus += 1;
        if (vus % 200 === 0) surAvancee({ vus, trouves: trouves.length });
        if (!MEDIA.has(extension(entree.name))) continue;
        const fichier = await entree.getFile().catch(() => null);
        if (fichier && retenu(fichier)) trouves.push({ chemin: ici, fichier });
      }
    }
  }
  await visiter(dossier, dossier.name);
  return trouves;
}

/** Les enregistrements d'un <input webkitdirectory>, quand le navigateur
 *  ne sait pas ouvrir un dossier autrement. */
export function lireSelection(fichiers) {
  return Array.from(fichiers)
    .filter((f) => !f.webkitRelativePath.split('/').slice(0, -1).some(ignore))
    .filter((f) => !ignore(f.name) && retenu(f))
    .map((f) => ({ chemin: f.webkitRelativePath || f.name, fichier: f }));
}

/** L'empreinte d'un fichier : sa taille, son début et sa fin. Lire
 *  quelques centaines de Go de vidéos en entier prendrait des heures ;
 *  deux enregistrements distincts qui partagent taille, premier et dernier
 *  quart de Mo, cela n'arrive pas. */
export async function empreinte(fichier) {
  const parts = fichier.size > 2 * BOUT
    ? [fichier.slice(0, BOUT), fichier.slice(fichier.size - BOUT)]
    : [fichier];
  const tout = await new Blob([String(fichier.size), ':', ...parts]).arrayBuffer();
  const condense = await crypto.subtle.digest('SHA-256', tout);
  return Array.from(new Uint8Array(condense), (o) => o.toString(16).padStart(2, '0')).join('');
}

/** Ce que le serveur reçoit d'un fichier, sans son contenu. */
export async function decrire(trouves, surAvancee) {
  const fichiers = [];
  for (const [n, { chemin, fichier }] of trouves.entries()) {
    surAvancee({ empreintes: n, total: trouves.length });
    fichiers.push({
      id: chemin,
      checksum: await empreinte(fichier),
      name: fichier.name,
      size: fichier.size,
      modified: fichier.lastModified || 0,
      mime_type: fichier.type || '',
    });
  }
  return fichiers;
}
