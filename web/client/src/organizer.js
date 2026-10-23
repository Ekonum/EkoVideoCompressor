/** Une liste de réunions, chacune composée d'un ou de plusieurs fichiers. */
export const fileKey = (file) => `${file.name}|${file.size}|${file.lastModified}`
  + (file.mergedParts ? `|parts:${file.mergedParts.map(fileKey).join('>')}` : '');
export const isAudioFile = (file) => Boolean(file) &&
  (file.type?.startsWith('audio/') || /\.(m4a|mp3|wav|aac|flac|ogg|opus|amr|caf|aiff?|weba)$/i.test(file.name || ''));

export function uniqueFiles(files) {
  const seen = new Set();
  return files.filter((file) => {
    const key = fileKey(file);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function groupsFor(files) {
  return uniqueFiles(files).map((file, index) => ({
    id: `meeting-${index}`, files: file.mergedParts || [file], materialized: file,
  }));
}

export function moveItem(items, from, to) {
  if (from < 0 || to < 0 || from >= items.length || to >= items.length) return items;
  const next = [...items];
  next.splice(to, 0, next.splice(from, 1)[0]);
  return next;
}

/** Le centre ajoute les morceaux à la fin de la réunion cible ; les
 * bords changent seulement la place dans la file. */
export function dropGroup(groups, sourceId, targetId, zone) {
  const source = groups.find((group) => group.id === sourceId);
  const target = groups.find((group) => group.id === targetId);
  if (!source || !target || source === target) return groups;
  if (zone === 'join') {
    if ([source, target].some((group) => group.files.some((file) => !isAudioFile(file) || file.remote))) return groups;
    return groups.filter((group) => group !== source).map((group) => group === target
      ? { id: target.id, files: [...target.files, ...source.files] } : group);
  }
  if (!['before', 'after'].includes(zone)) return groups;
  const next = groups.filter((group) => group !== source);
  next.splice(next.indexOf(target) + (zone === 'after' ? 1 : 0), 0, source);
  return next;
}

export function splitGroup(groups, id) {
  return groups.flatMap((group) => group.id !== id ? [group] : group.files.map((file, index) => ({
    id: `${id}-part-${index}`, files: [file], materialized: file,
  })));
}
