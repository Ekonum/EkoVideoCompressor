import { useEffect, useRef, useState } from 'react';
import { Bouton, Erreur } from './Communs.jsx';
import { combineGroups, fileKey, groupsFor, isAudioFile, moveItem, splitGroup } from '../organizer.js';
import { mergeAudioFiles } from '../merge-audio.js';
import { fileSize } from '../format.js';

/** Le même geste pour déplacer une réunion ou ses morceaux. Le clavier
 *  et le tactile restent utilisables sans glisser-déposer HTML natif. */
function OrderHandle({ index, count, scope, onMove, label, disabled }) {
  const dragging = useRef(false);
  return <button type="button" className="ekn-button ekn-button--subtle shrink-0 touch-none cursor-grab px-2"
    aria-label={`Déplacer ${label}`} title="Glisser pour déplacer · flèches ↑ et ↓ au clavier"
    disabled={disabled} onKeyDown={(event) => {
      if (!['ArrowUp', 'ArrowDown'].includes(event.key)) return;
      event.preventDefault();
      const target = index + (event.key === 'ArrowUp' ? -1 : 1);
      if (target >= 0 && target < count) onMove(target);
    }} onPointerDown={(event) => {
      if (event.button !== 0) return;
      dragging.current = true;
      event.currentTarget.setPointerCapture(event.pointerId);
    }} onPointerMove={(event) => {
      if (!dragging.current) return;
      let target = document.elementFromPoint(event.clientX, event.clientY);
      while (target && target.dataset?.reorderScope !== scope) target = target.parentElement;
      if (target && Number(target.dataset.reorderIndex) !== index) onMove(Number(target.dataset.reorderIndex));
    }} onPointerUp={() => { dragging.current = false; }} onPointerCancel={() => { dragging.current = false; }}>
    <span aria-hidden="true">⠿</span>
  </button>;
}

export function FileOrganizer({ files, onConfirm, onCancel }) {
  const dialog = useRef(null);
  const controller = useRef(null);
  const [groups, setGroups] = useState(() => groupsFor(files));
  const [selected, setSelected] = useState(new Set());
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState('');
  const busy = progress !== null;
  useEffect(() => {
    const node = dialog.current;
    if (!node.open) node.showModal();
    return () => controller.current?.abort();
  }, []);
  const moveGroup = (index, target) => setGroups((current) => moveItem(current, index, target));
  const movePart = (id, index, target) => setGroups((current) => current.map((group) => group.id === id
    ? { ...group, materialized: null, files: moveItem(group.files, index, target) } : group));

  async function confirm() {
    controller.current = new AbortController();
    setProgress('Préparation…');
    setError('');
    try {
      const prepared = [];
      for (let index = 0; index < groups.length; index++) {
        const group = groups[index];
        if (group.materialized) prepared.push(group.materialized);
        else if (group.files.length === 1) prepared.push(group.files[0]);
        else {
          const merged = await mergeAudioFiles(group.files, { signal: controller.current.signal,
            onProgress: ({ ratio }) => setProgress(`Assemblage de la réunion ${index + 1} sur ce poste — ${Math.round(ratio * 100)} %`),
          });
          // En cas d'échec d'un groupe suivant, ce résultat est réutilisé
          // au prochain essai ; la file existante reste intacte.
          setGroups((current) => current.map((g) => g.id === group.id ? { ...g, materialized: merged } : g));
          prepared.push(merged);
        }
      }
      onConfirm(prepared);
    } catch (failure) {
      if (failure.name !== 'AbortError') setError(failure.message);
    } finally { setProgress(null); }
  }

  const selectable = groups.filter((group) => group.files.every((file) => isAudioFile(file) && !file.remote));
  const canCombine = [...selected].length >= 2;
  return <dialog ref={dialog} className="ekn-dialog ekn-dialog--wide" aria-labelledby="organizer-title"
    onCancel={(event) => { if (busy) { event.preventDefault(); controller.current?.abort(); } }}
    onClose={() => { if (!busy) onCancel(); }}>
    <h2 id="organizer-title">Organiser les enregistrements</h2>
    <p>Un fichier par réunion, sauf ceux que tu choisis de réunir. Déplace les poignées pour régler l’ordre.</p>
    <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
      <span className="text-ekn-sm text-ekn-text-muted" aria-live="polite">
        {groups.length} réunion{groups.length > 1 ? 's' : ''} · {groups.reduce((total, group) => total + group.files.length, 0)} fichiers
      </span>
      {selectable.length > 1 && <Bouton variante="discret" disabled={!canCombine || busy}
        onClick={() => { setGroups((current) => combineGroups(current, selected)); setSelected(new Set()); }}>
        Réunir la sélection
      </Bouton>}
    </div>
    <ol className="space-y-3" aria-label="Ordre des réunions">
      {groups.map((group, index) => {
        const joined = group.files.length > 1;
        const audio = group.files.every((file) => isAudioFile(file) && !file.remote);
        return <li key={group.id} data-reorder-index={index} data-reorder-scope="meetings"
          className="rounded-lg border border-bord p-3">
          <div className="flex items-center gap-2">
            <OrderHandle index={index} count={groups.length} scope="meetings" label={`la réunion ${index + 1}`}
              disabled={busy} onMove={(target) => moveGroup(index, target)} />
            <label className="flex min-w-0 flex-1 items-center gap-3">
              <input type="checkbox" checked={selected.has(group.id)} disabled={!audio || busy}
                aria-label={`Sélectionner la réunion ${index + 1}`} onChange={(event) => setSelected((current) => {
                  const next = new Set(current);
                  if (event.target.checked) next.add(group.id); else next.delete(group.id);
                  return next;
                })} />
              <span className="min-w-0 break-words text-ekn-sm">
                <strong className="block">{index + 1}. {joined ? `Une réunion · ${group.files.length} morceaux` : group.files[0].name}</strong>
                {!joined && <span className="text-ekn-text-muted">{fileSize(group.files[0].size)}{!audio ? ' · séparé' : ''}</span>}
              </span>
            </label>
            {joined && <button className="ekn-button ekn-button--subtle ekn-button--compact" disabled={busy}
              onClick={() => { setGroups((current) => splitGroup(current, group.id)); setSelected(new Set()); }}>Séparer</button>}
          </div>
          {joined && <ol className="mt-2 space-y-1 border-l border-bord pl-2 sm:ml-10" aria-label={`Morceaux de la réunion ${index + 1}`}>
            {group.files.map((file, part) => <li key={fileKey(file)} className="flex min-w-0 items-center gap-2"
              data-reorder-index={part} data-reorder-scope={group.id}>
              <OrderHandle index={part} count={group.files.length} scope={group.id} label={`le morceau ${part + 1}`}
                disabled={busy} onMove={(target) => movePart(group.id, part, target)} />
              <span className="min-w-0 break-words text-ekn-sm">{part + 1}. {file.name}</span>
            </li>)}
          </ol>}
        </li>;
      })}
    </ol>
    <p className="mt-4 text-ekn-sm">Les audios réunis donneront une seule transcription et un seul enregistrement. Les autres restent dans la file.</p>
    <Erreur>{error}</Erreur>
    {busy && <p role="status">{progress}</p>}
    <div className="ekn-dialog__actions">
      <Bouton variante="discret" onClick={() => busy ? controller.current?.abort() : onCancel()}>{busy ? 'Interrompre l’assemblage' : 'Annuler'}</Bouton>
      <Bouton disabled={busy || !groups.length} onClick={confirm}>Continuer avec {groups.length} réunion{groups.length > 1 ? 's' : ''}</Bouton>
    </div>
  </dialog>;
}
