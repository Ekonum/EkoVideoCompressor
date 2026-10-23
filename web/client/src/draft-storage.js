/** Copies privées au navigateur, séparées par compte et par onglet. */
export function packFile(file) {
  return { blob: file.remote ? null : file, name: file.name, type: file.type,
    lastModified: file.lastModified, size: file.size, remote: file.remote,
    audioParts: file.audioParts, draftState: file.draftState ? { ...file.draftState,
      dossier: file.draftState.dossier ? { ...file.draftState.dossier, auto: false } : null } : undefined,
    parts: file.mergedParts?.map(packFile) };
}
export function unpackFile(saved) {
  const file = saved.remote ? { name: saved.name, size: saved.size, type: saved.type,
    lastModified: saved.lastModified, remote: saved.remote }
    : new File([saved.blob], saved.name, { type: saved.type, lastModified: saved.lastModified });
  if (saved.parts) file.mergedParts = saved.parts.map(unpackFile);
  if (saved.audioParts) file.audioParts = saved.audioParts;
  if (saved.draftState) file.draftState = saved.draftState;
  return file;
}

export function browserDraftStore() {
  let opening;
  function db() {
    return opening ||= new Promise((resolve, reject) => {
      const request = indexedDB.open('transcript-drafts', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('drafts', { keyPath: 'key' });
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error('Stockage local occupé.'));
      request.onsuccess = () => { request.result.onversionchange = () => request.result.close(); resolve(request.result); };
    });
  }
  async function transaction(mode, action) {
    const connection = await db();
    return new Promise((resolve, reject) => {
      const tx = connection.transaction('drafts', mode);
      const request = action(tx.objectStore('drafts'));
      tx.oncomplete = () => resolve(request?.result);
      tx.onabort = tx.onerror = () => reject(tx.error || new Error('Copie locale impossible.'));
    });
  }
  return {
    list: (owner) => transaction('readonly', (s) => s.getAll(IDBKeyRange.bound(`${owner}\0`, `${owner}\0\uffff`))),
    put: (value) => transaction('readwrite', (s) => s.put(value)),
    delete: (key) => transaction('readwrite', (s) => s.delete(key)),
  };
}

/** Une file ouverte ailleurs n'est jamais reprise ou écrasée par cet onglet. */
export function claimBrowserDraft(key) {
  if (!navigator.locks) return Promise.resolve(null);
  return new Promise((resolve) => {
    navigator.locks.request(`transcript-draft:${key}`, { ifAvailable: true }, (lock) => {
      if (!lock) { resolve(null); return undefined; }
      return new Promise((release) => {
        window.addEventListener('pagehide', release, { once: true });
        resolve(release);
      });
    }).catch(() => resolve(null));
  });
}

/** Les écritures successives ne peuvent pas ressusciter une ancienne file. */
export function createDraftSession({ store, claim, session, uuid = () => crypto.randomUUID() }) {
  let key, release, chain = Promise.resolve();
  return {
    async open(owner) {
      const prefix = `${owner}\0`;
      const own = session.getItem(`transcript-draft:${owner}`);
      const records = await store.list(owner);
      const candidates = [...new Set([own, ...records.sort((a, b) => b.updatedAt - a.updatedAt).map((r) => r.key)].filter(Boolean))];
      for (const candidate of candidates) {
        if (!candidate.startsWith(prefix)) continue;
        const lock = await claim(candidate);
        if (!lock) continue;
        key = candidate; release = lock;
        session.setItem(`transcript-draft:${owner}`, key);
        return records.find((r) => r.key === key)?.value || null;
      }
      key = `${prefix}${uuid()}`; release = await claim(key);
      if (!release) throw new Error('La sauvegarde locale est indisponible.');
      session.setItem(`transcript-draft:${owner}`, key);
      return null;
    },
    save(value) {
      if (!key || !release) return Promise.reject(new Error('Sauvegarde indisponible.'));
      const snapshot = { key, value, updatedAt: Date.now() };
      chain = chain.catch(() => {}).then(async () => {
        try {
          if (!value.entries.length) await store.delete(key);
          else await store.put(snapshot);
        } catch (error) {
          // Une ancienne sélection ne doit pas revenir après un retrait raté.
          await store.delete(key).catch(() => {});
          throw error;
        }
      });
      return chain;
    },
    close() { release?.(); release = null; },
  };
}
