/** Repères relatifs au fichier réellement écouté / archivé, rognage compris. */
export function clipAudioParts(parts, start = 0, end = Infinity) {
  if (!Array.isArray(parts) || !Number.isFinite(start) || start < 0 || !(end > start)) return [];
  let previous = 0;
  const result = [];
  for (const part of parts) {
    if (!part || !Number.isFinite(part.start) || !Number.isFinite(part.end) ||
      part.start < previous || part.end <= part.start || typeof part.name !== 'string') return [];
    previous = part.end;
    const left = Math.max(start, part.start), right = Math.min(end, part.end);
    if (right > left) result.push({ name: part.name, start: left - start, end: right - start });
  }
  return result;
}
