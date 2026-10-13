/** Une seule barre pour tout le traitement.
 *
 *  Les étapes n'avancent ni au même rythme ni en même temps : la vidéo se
 *  compresse pendant que l'audio part et se transcrit. Chacune reçoit donc
 *  une part fixe de la barre, et la transcription — la seule qu'on attend
 *  vraiment — avance fenêtre par fenêtre, sur la durée estimée par le
 *  serveur d'après les précédentes. Rien n'atteint 100 % avant d'être
 *  réellement fini : une fenêtre en retard ralentit, elle ne déborde pas.
 */

const PART_COMPRESSION = 0.1;
const PART_ENVOI = 0.05;
// La fusion des fenêtres, et la fin de l'archivage vidéo : la barre ne
// dépasse pas 90 % tant qu'il reste l'un ou l'autre.
const PART_FIN = 0.1;

// Le pendant de ``capped`` dans ``app/avancement.py``.
const A_L_HEURE = 0.9;
const PLAFOND = 0.99;

export function plafonner(part) {
  if (part <= 0) return 0;
  if (part <= 1) return A_L_HEURE * part;
  return A_L_HEURE + (PLAFOND - A_L_HEURE) * (1 - Math.exp(-(part - 1)));
}

function envoiFenetre(f) {
  if (f.etat === 'attendue') return 0;
  if (f.etat === 'encodage') return 0.8 * (f.progression || 0);
  if (f.etat === 'envoi') return 0.8;
  return 1;
}

function transcriptionFenetre(f, maintenant) {
  if (f.etat === 'terminee') return 1;
  if (f.etat !== 'transcription' || f.ecoule == null || !f.prevu) return 0;
  const ecoule = f.ecoule + Math.max(0, maintenant - (f.mesureA || maintenant)) / 1000;
  return plafonner(ecoule / f.prevu);
}

function archivageFait(tache) {
  return tache.etape === 'termine' || tache.etape === 'erreur';
}

/** Part de la vidéo compressée, et part envoyée. Une erreur compte comme
 *  finie : elle s'affiche à part, la barre n'a pas à rester bloquée. */
function archivage(tache) {
  if (!tache) return null;
  if (archivageFait(tache) || tache.etape === 'envoi') {
    return {
      compression: 1,
      envoi: archivageFait(tache) ? 1 : tache.progression || 0,
    };
  }
  return { compression: tache.etape === 'compression' ? tache.progression || 0 : 0, envoi: 0 };
}

/** De 0 à 1, pour une transcription suivie et, s'il y en a un, l'archivage
 *  de sa vidéo. */
export function avancementGlobal({ fenetres, etat, finalisation, tache, maintenant = Date.now() }) {
  const video = archivage(tache);
  const partCompression = video ? PART_COMPRESSION : 0;
  const partTranscription = 1 - partCompression - PART_ENVOI - PART_FIN;
  const transcrite = etat === 'termine';

  let total = 0;
  if (video) total += partCompression * video.compression;

  const envoiAudio = transcrite || !fenetres.length
    ? (transcrite ? 1 : 0)
    : fenetres.reduce((s, f) => s + envoiFenetre(f), 0) / fenetres.length;
  total += PART_ENVOI * (video ? (envoiAudio + video.envoi) / 2 : envoiAudio);

  const duree = fenetres.reduce((s, f) => s + (f.end - f.start), 0);
  const faite = transcrite
    ? 1
    : duree > 0
      ? fenetres.reduce((s, f) => s + transcriptionFenetre(f, maintenant) * (f.end - f.start), 0) / duree
      : 0;
  total += partTranscription * faite;

  // La fin : moitié pendant la fusion, le reste quand tout est vraiment fait.
  const videoFinie = !video || archivageFait(tache);
  if (transcrite && videoFinie) total += PART_FIN;
  else if (transcrite || finalisation) total += PART_FIN / 2;

  return Math.min(1, total);
}
