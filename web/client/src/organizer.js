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

export function combineGroups(groups, selected) {
  const chosen = groups.filter((group) => selected.has(group.id));
  if (chosen.length < 2 || chosen.some((group) => group.files.some((file) => !isAudioFile(file) || file.remote))) return groups;
  const joined = { id: chosen[0].id, files: chosen.flatMap((group) => group.files) };
  return groups.flatMap((group) => group === chosen[0] ? [joined] : selected.has(group.id) ? [] : [group]);
}

export function splitGroup(groups, id) {
  return groups.flatMap((group) => group.id !== id ? [group] : group.files.map((file, index) => ({
    id: `${id}-part-${index}`, files: [file], materialized: file,
  })));
}
