import { useEffect, useRef, useState } from 'react';
import { Bouton, Erreur } from './Communs.jsx';
import { dropGroup, dropPart, fileKey, groupsFor, isAudioFile, moveItem, removeRecording, splitGroup } from '../organizer.js';
import { mergeAudioFiles } from '../merge-audio.js';
import { fileSize } from '../format.js';

const sameSource = (a, b) => a?.groupId === b?.groupId && a?.partKey === b?.partKey;

function OrderHandle({ source, label, disabled, controller, onMove, picked }) {
  return <button type="button" className="ekn-button ekn-button--subtle shrink-0 touch-none cursor-grab px-2"
    aria-label={`Déplacer ${label}`} aria-pressed={sameSource(source, picked)}
    title="Glisser pour déplacer ou retirer · flèches ↑ et ↓ au clavier · Suppr pour retirer"
    disabled={disabled} onKeyDown={(event) => {
      if (['ArrowUp', 'ArrowDown', 'Delete', 'Backspace', 'Escape'].includes(event.key)) {
        event.preventDefault();
        if (event.key === 'Escape') controller.cancel();
        else if (['Delete', 'Backspace'].includes(event.key)) controller.remove(source);
        else onMove(event.key === 'ArrowUp' ? -1 : 1);
      }
    }} onPointerDown={(event) => { if (event.button === 0) controller.start(source, event); }}
    onPointerMove={controller.move} onPointerUp={controller.end} onPointerCancel={controller.cancel}
    onLostPointerCapture={controller.cancel}
    onClick={(event) => { if (event.detail === 0) controller.pick(source); }}>
    <span aria-hidden="true">⠿</span>
  </button>;
}

export function FileOrganizer({ files, onConfirm, onCancel, partsOnly = false }) {
  const dialog = useRef(null), abort = useRef(null), gesture = useRef(null);
  const [groups, setGroups] = useState(() => groupsFor(files));
  const [drag, setDrag] = useState(null), [picked, setPicked] = useState(null);
  const [undo, setUndo] = useState(null), [announcement, setAnnouncement] = useState('');
  const [progress, setProgress] = useState(null), [error, setError] = useState('');
  const busy = progress !== null;
  const canJoin = (a, b) => [a, b].every((id) => groups.find((g) => g.id === id)?.files.every((f) => isAudioFile(f) && !f.remote));
  function focusGroup(id) {
    requestAnimationFrame(() => dialog.current?.querySelector(`[data-group-id="${id}"] button`)?.focus({ preventScroll: true }));
  }
  function change(next, message, groupId) {
    setUndo(null); setGroups(next); setAnnouncement(message);
    if (groupId) focusGroup(groupId);
  }
  function remove(source) {
    setUndo(groups); setGroups((current) => removeRecording(current, source)); setPicked(null);
    setAnnouncement('Enregistrement retiré de la sélection. Le fichier original reste sur ton poste.');
    requestAnimationFrame(() => dialog.current?.querySelector('[data-organizer-undo]')?.focus({ preventScroll: true }));
  }
  function finish(source, target) {
    if (!target) return;
    if (target.zone === 'trash') return remove(source);
    if (source.partKey) change((current) => dropPart(current, source.groupId, source.partKey, target.partKey, target.zone), 'Ordre des morceaux modifié. La file des réunions reste inchangée.', source.groupId);
    else change((current) => dropGroup(current, source.groupId, target.groupId, target.zone), target.zone === 'join'
      ? 'Audios réunis. Tu peux régler l’ordre des morceaux ou les séparer.' : 'Ordre des réunions modifié.', target.groupId);
  }
  const controller = {
    remove,
    cancel() { gesture.current = null; setDrag(null); setPicked(null); },
    pick(source) {
      if (!picked || sameSource(source, picked)) { setPicked(sameSource(source, picked) ? null : source); return; }
      if (picked.partKey && source.groupId === picked.groupId && source.partKey) {
        const group = groups.find((g) => g.id === source.groupId);
        const from = group.files.findIndex((f) => fileKey(f) === picked.partKey);
        const to = group.files.findIndex((f) => fileKey(f) === source.partKey);
        finish(picked, { ...source, zone: from < to ? 'after' : 'before' }); setPicked(null);
      } else if (!picked.partKey && !source.partKey && canJoin(picked.groupId, source.groupId)) {
        finish(picked, { ...source, zone: 'join' }); setPicked(null);
      }
    },
    start(source, event) {
      gesture.current = { source, x: event.clientX, y: event.clientY, active: false };
      setPicked(null); setDrag({ source, active: false });
      event.currentTarget.setPointerCapture(event.pointerId);
    },
    move(event) {
      const current = gesture.current;
      if (!current) return;
      if (!current.active && Math.hypot(event.clientX - current.x, event.clientY - current.y) < 6) return;
      current.active = true;
      const element = document.elementFromPoint(event.clientX, event.clientY);
      let target = null;
      if (element?.closest('[data-organizer-trash]')) target = { zone: 'trash' };
      else if (current.source.partKey) {
        const row = element?.closest('[data-part-key]');
        if (row?.dataset.groupId === current.source.groupId && row.dataset.partKey !== current.source.partKey) {
          const rect = row.getBoundingClientRect();
          target = { groupId: current.source.groupId, partKey: row.dataset.partKey, zone: event.clientY < rect.top + rect.height / 2 ? 'before' : 'after' };
        }
      } else {
        const row = element?.closest('[data-meeting]');
        if (row && row.dataset.groupId !== current.source.groupId) {
          const rect = row.getBoundingClientRect(), ratio = (event.clientY - rect.top) / rect.height;
          target = { groupId: row.dataset.groupId, zone: canJoin(current.source.groupId, row.dataset.groupId) && ratio > .24 && ratio < .76 ? 'join' : ratio < .5 ? 'before' : 'after' };
        }
      }
      current.target = target;
      setDrag({ ...current, x: event.clientX, y: event.clientY });
      const box = dialog.current.getBoundingClientRect();
      if (event.clientY < box.top + 60) dialog.current.scrollTop -= 12;
      if (event.clientY > box.bottom - 60 && target?.zone !== 'trash') dialog.current.scrollTop += 12;
    },
    end(event) {
      const current = gesture.current;
      if (current?.active) finish(current.source, current.target);
      gesture.current = null; setDrag(null);
      if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    },
  };
  useEffect(() => {
    dialog.current.showModal();
    return () => abort.current?.abort();
  }, []);

  async function confirm() {
    abort.current = new AbortController(); setProgress('Préparation…'); setError('');
    try {
      const prepared = [];
      for (let index = 0; index < groups.length; index++) {
        const group = groups[index];
        if (group.materialized) prepared.push(group.materialized);
        else if (group.files.length === 1) prepared.push(group.files[0]);
        else {
          const merged = await mergeAudioFiles(group.files, { signal: abort.current.signal,
            onProgress: ({ ratio }) => setProgress(`Assemblage de la réunion ${index + 1} sur ce poste — ${Math.round(ratio * 100)} %`),
          });
          setGroups((current) => current.map((g) => g.id === group.id ? { ...g, materialized: merged } : g));
          prepared.push(merged);
        }
      }
      onConfirm(prepared);
    } catch (failure) { if (failure.name !== 'AbortError') setError(failure.message); }
    finally { setProgress(null); }
  }
  const target = drag?.target;
  return <dialog ref={dialog} className="ekn-dialog ekn-dialog--wide" aria-labelledby="organizer-title"
    onCancel={(event) => {
      if (drag || picked) { event.preventDefault(); controller.cancel(); }
      else if (busy) { event.preventDefault(); abort.current?.abort(); }
    }} onClose={() => { if (!busy) onCancel(); }}>
    <h2 id="organizer-title">{partsOnly ? 'Morceaux de cette réunion' : 'Organiser les enregistrements'}</h2>
    <p>{partsOnly ? 'Déplace les morceaux dans l’ordre voulu. Les autres réunions gardent leur place dans la file.'
      : 'Avec la poignée, dépose un audio au centre d’un autre pour les réunir, ou entre deux réunions pour régler l’ordre.'}</p>
    <p className="text-ekn-sm">{groups.length} réunion{groups.length > 1 ? 's' : ''} · {groups.reduce((n, g) => n + g.files.length, 0)} fichier{groups.reduce((n, g) => n + g.files.length, 0) > 1 ? 's' : ''}</p>
    <p className="text-ekn-sm" role="status">{announcement || (partsOnly ? 'Flèches : déplacer · Entrée sur deux poignées : intervertir · Suppr : retirer · Échap : annuler le geste' : 'Flèches : déplacer · Entrée sur deux poignées : réunir ou intervertir · Suppr : retirer · Échap : annuler le geste')}</p>
    {undo && <button type="button" data-organizer-undo className="ekn-button ekn-button--subtle ekn-button--compact mb-3"
      onClick={() => { setGroups(undo); setUndo(null); setAnnouncement('Retrait annulé.'); }}>Annuler le retrait</button>}
    {!groups.length && <p>Aucun enregistrement dans la sélection.</p>}
    <ol className="space-y-3" aria-label="Ordre des réunions">
      {groups.map((group, index) => {
        const joined = group.files.length > 1;
        const source = { groupId: group.id };
        const groupTarget = !target?.partKey && target?.groupId === group.id;
        return <li key={group.id} data-meeting data-group-id={group.id}
          data-picked={picked && !picked.partKey && picked.groupId === group.id || undefined}
          data-dragging={drag && !drag.source.partKey && drag.source.groupId === group.id || undefined}
          data-drop={groupTarget ? target.zone : undefined}
          className="organizer-meeting rounded-lg border border-bord p-3">
          <div className="flex items-center gap-2">
            {!partsOnly && <OrderHandle source={source} label={`la réunion ${index + 1}`} controller={controller} picked={picked} disabled={busy}
              onMove={(delta) => change((current) => moveItem(current, index, index + delta), 'Ordre des réunions modifié.')} />}
            <strong className="min-w-0 flex-1 break-words text-ekn-sm">{index + 1}. {joined ? `Une réunion · ${group.files.length} morceaux` : group.files[0].name}</strong>
            {joined && !partsOnly && <button type="button" className="ekn-button ekn-button--subtle ekn-button--compact" disabled={busy}
              onClick={() => change((current) => splitGroup(current, group.id), 'Morceaux séparés en réunions indépendantes.')}>Séparer</button>}
            {!joined && !partsOnly && <span className="text-ekn-xs text-ekn-text-muted">{fileSize(group.files[0].size)}</span>}
          </div>
          {groupTarget && target.zone === 'join' && <span className="organizer-drop-label" aria-hidden="true">Relâche pour ajouter à cette réunion</span>}
          {(joined || partsOnly) && <ol className="mt-2 space-y-1 border-l border-bord pl-2" aria-label={`Morceaux de la réunion ${index + 1}`}>
            {group.files.map((file, part) => {
              const partKey = fileKey(file), source = { groupId: group.id, partKey };
              return <li key={partKey} data-part-key={partKey} data-group-id={group.id}
                data-drop={target?.partKey === partKey && target.groupId === group.id ? target.zone : undefined}
                data-picked={picked && sameSource(picked, source) || undefined}
                data-dragging={drag && sameSource(drag.source, source) || undefined}
                className="organizer-part flex min-w-0 items-center gap-2">
                <OrderHandle source={source} label={`le morceau ${part + 1}`} controller={controller} picked={picked} disabled={busy}
                  onMove={(delta) => change((current) => current.map((g) => g.id === group.id
                    ? { ...g, files: moveItem(g.files, part, part + delta), materialized: null } : g), 'Ordre des morceaux modifié.')} />
                <span className="min-w-0 break-words text-ekn-sm">{part + 1}. {file.name}</span>
              </li>;
            })}
          </ol>}
        </li>;
      })}
    </ol>
    {(drag || picked) && <button type="button" data-organizer-trash
      data-hovered={target?.zone === 'trash' || undefined} className="organizer-trash"
      aria-label="Retirer l’enregistrement de la sélection"
      onClick={() => { if (picked) remove(picked); }}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7" /></svg>
      <span>{target?.zone === 'trash' ? 'Relâche pour retirer' : 'Retirer de la sélection'}</span>
    </button>}
    {drag?.active && <div className="organizer-ghost" aria-hidden="true" style={{ left: Math.min(drag.x + 12, window.innerWidth - 220), top: Math.min(drag.y + 14, window.innerHeight - 70) }}>
      {target?.zone === 'trash' ? 'Retirer l’enregistrement' : target?.zone === 'join' ? '＋ Réunir les audios' : drag.source.partKey ? '⠿ Déplacer le morceau' : '⠿ Déplacer la réunion'}
    </div>}
    <p className="mt-4 text-ekn-sm">Retirer un enregistrement ne supprime jamais son fichier original.</p>
    <Erreur>{error}</Erreur>
    {busy && <p role="status">{progress}</p>}
    <div className="ekn-dialog__actions">
      <Bouton variante="discret" onClick={() => busy ? abort.current?.abort() : onCancel()}>{busy ? 'Interrompre l’assemblage' : 'Annuler'}</Bouton>
      <Bouton disabled={busy} onClick={confirm}>{!groups.length ? 'Valider les retraits' : partsOnly ? 'Appliquer l’ordre des morceaux' : `Continuer avec ${groups.length} réunion${groups.length > 1 ? 's' : ''}`}</Bouton>
    </div>
  </dialog>;
}
