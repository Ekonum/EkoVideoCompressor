import { useEffect, useState } from 'react';
import { api } from './api.js';
import { identifier, sonderDuree } from './sonde.js';
import { fileKey, uniqueFiles } from './organizer.js';

export async function snapshotFile(file) {
  if (file.remote || file.size > 400 * 1024 * 1024) return file;
  const stable = new File([await file.arrayBuffer()], file.name, { type: file.type, lastModified: file.lastModified });
  if (file.mergedParts) stable.mergedParts = file.mergedParts;
  if (file.audioParts) stable.audioParts = file.audioParts;
  return stable;
}

export function meetingMoment(file, duration) {
  const recorded = file.remote?.meetingDate;
  const date = recorded ? new Date(recorded.replace(' ', 'T')) : null;
  return date && Number.isFinite(date.getTime()) ? date.toISOString()
    : new Date((file.lastModified || Date.now()) - duration * 1000).toISOString();
}

/** Une seule recherche par fichier, partagée entre l'écran et la file.
 *  Une recherche d'avance à la fois ; aucune transcription ni publication.
 *  Les copies média sont libérées après la sonde, seul le contexte reste. */
export function createPreparer({ snapshot, durationOf, identify, settings, momentOf = meetingMoment }) {
  const entries = new Map();
  const listeners = new Set();
  let waiting = [];
  let running = false;
  const notify = () => listeners.forEach((callback) => callback());
  function prepare(file, options = {}) {
    const key = fileKey(file);
    const existing = entries.get(key);
    if (existing && (!options.moment || !existing.moment || options.moment === existing.moment) &&
        !(options.retry && existing.status === 'error')) return existing.promise;
    const entry = { status: 'running', phase: 'extrait', duration: options.duration, moment: options.moment };
    entries.set(key, entry);
    entry.promise = (async () => {
      try {
        const stable = await snapshot(file);
        entry.duration ??= await durationOf(stable);
        entry.moment ||= momentOf(file, entry.duration);
        const config = await settings();
        entry.result = await identify(stable, { audio: config.audio,
          fenetre: config.probe?.window_seconds || 300, duree: entry.duration, moment: entry.moment,
          surPhase: (phase) => { entry.phase = phase; notify(); },
        });
        entry.status = 'ready';
        return { ...entry.result, moment: entry.moment, duration: entry.duration };
      } catch (error) {
        entry.status = 'error';
        entry.error = error.message || 'Recherche indisponible.';
        throw error;
      } finally { notify(); }
    })();
    notify();
    return entry.promise;
  }
  async function pump() {
    if (running) return;
    running = true;
    try {
      while (waiting.length) {
        const next = waiting.shift();
        if (!entries.has(fileKey(next))) await prepare(next).catch(() => {});
      }
    } finally { running = false; }
  }
  return {
    prepare,
    schedule(files) { waiting = uniqueFiles(files).filter((file) => !file.remote); void pump(); },
    get(file) { return file ? entries.get(fileKey(file)) : null; },
    subscribe(callback) { listeners.add(callback); return () => listeners.delete(callback); },
  };
}

export const preparation = createPreparer({ snapshot: snapshotFile, durationOf: sonderDuree,
  identify: identifier, settings: api.settings });

export function usePreparation(file) {
  const [, refresh] = useState(0);
  useEffect(() => preparation.subscribe(() => refresh((n) => n + 1)), []);
  return preparation.get(file);
}

export function preparationLabel(state) {
  return !state ? 'Contexte à préparer' : state.status === 'ready' ? 'Contexte prêt'
    : state.status === 'error' ? 'Contexte indisponible — saisie manuelle possible'
      : state.phase === 'extrait' ? 'Préparation du contexte…' : 'Recherche du contexte…';
}
