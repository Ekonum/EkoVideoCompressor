import { useEffect, useRef, useState } from 'react';
import { Bouton, Erreur } from './Communs.jsx';
import { dropGroup, fileKey, groupsFor, isAudioFile, moveItem, splitGroup } from '../organizer.js';
import { mergeAudioFiles } from '../merge-audio.js';
import { fileSize } from '../format.js';

/** Le même geste pour déplacer une réunion ou ses morceaux. Le clavier
 *  et le tactile restent utilisables sans glisser-déposer HTML natif. */
function OrderHandle({ index, count, scope, onMove, label, disabled, groupDrag, onPick, picked }) {
  const dragging = useRef(false);
  return <button type="button" className="ekn-button ekn-button--subtle shrink-0 touch-none cursor-grab px-2"
    aria-label={`Déplacer ${label}`} aria-pressed={groupDrag ? Boolean(picked) : undefined}
    title={groupDrag ? "Glisser au centre pour réunir, au bord pour déplacer · Entrée pour choisir, puis Entrée sur la cible" : "Glisser pour déplacer · flèches ↑ et ↓ au clavier"}
    disabled={disabled} onKeyDown={(event) => {
      if (groupDrag && event.key === 'Escape') { event.preventDefault(); onPick(true); return; }
      if (!['ArrowUp', 'ArrowDown'].includes(event.key)) return;
      event.preventDefault();
      const target = index + (event.key === 'ArrowUp' ? -1 : 1);
      if (target >= 0 && target < count) onMove(target);
    }} onPointerDown={(event) => {
      if (event.button !== 0) return;
      if (groupDrag) { groupDrag.start(event); return; }
      dragging.current = true;
      event.currentTarget.setPointerCapture(event.pointerId);
    }} onPointerMove={(event) => {
      if (groupDrag) { groupDrag.move(event); return; }
      if (!dragging.current) return;
      let target = document.elementFromPoint(event.clientX, event.clientY);
      while (target && target.dataset?.reorderScope !== scope) target = target.parentElement;
      if (target && Number(target.dataset.reorderIndex) !== index) onMove(Number(target.dataset.reorderIndex));
    }} onPointerUp={(event) => { if (groupDrag) groupDrag.end(event); dragging.current = false; }}
    onPointerCancel={() => { groupDrag?.cancel(); dragging.current = false; }}
    onClick={(event) => { if (groupDrag && event.detail === 0) onPick(false); }}>
    <span aria-hidden="true">⠿</span>
  </button>;
}

export function FileOrganizer({ files, onConfirm, onCancel }) {
  const dialog = useRef(null);
  const controller = useRef(null);
  const [groups, setGroups] = useState(() => groupsFor(files));
  const gesture = useRef(null);
  const [drag, setDrag] = useState(null);
  const [picked, setPicked] = useState(null);
  const [announcement, setAnnouncement] = useState('');
  function finishDrop(source, target, zone) {
    setGroups((current) => dropGroup(current, source, target, zone));
    requestAnimationFrame(() => dialog.current?.querySelector(`[data-group-id="${target}"] button`)?.focus({ preventScroll: true }));
    setAnnouncement(zone === 'join' ? 'Audios réunis. Tu peux régler l’ordre des morceaux ou les séparer.' : 'Ordre des réunions modifié.');
  }
  function pickGroup(id, cancel) {
    if (cancel || picked === id) { setPicked(null); setAnnouncement('Sélection annulée.'); return; }
    if (!picked) { setPicked(id); setAnnouncement('Choisis la poignée de la réunion à rejoindre puis appuie sur Entrée. Échap pour annuler.'); return; }
    const compatible = [picked, id].every((key) => groups.find((g) => g.id === key)?.files.every((f) => isAudioFile(f) && !f.remote));
    if (compatible) { finishDrop(picked, id, 'join'); setPicked(null); }
    else setAnnouncement('Seuls les audios locaux peuvent être réunis.');
  }
  function groupDrag(id) {
    return {
      start(event) {
        gesture.current = { id, x: event.clientX, y: event.clientY, active: false };
        setPicked(null);
        event.currentTarget.setPointerCapture(event.pointerId);
      },
      move(event) {
        const current = gesture.current;
        if (!current) return;
        if (!current.active && Math.hypot(event.clientX - current.x, event.clientY - current.y) < 6) return;
        current.active = true;
        let element = document.elementFromPoint(event.clientX, event.clientY);
        while (element && element.dataset?.reorderScope !== 'meetings') element = element.parentElement;
        let target = null, zone = null;
        if (element && element.dataset.groupId !== id) {
          target = element.dataset.groupId;
          const rect = element.getBoundingClientRect();
          const ratio = (event.clientY - rect.top) / rect.height;
          const compatible = [id, target].every((key) => groups.find((g) => g.id === key)?.files.every((f) => isAudioFile(f) && !f.remote));
          zone = compatible && ratio > .24 && ratio < .76 ? 'join' : ratio < .5 ? 'before' : 'after';
        }
        current.target = target; current.zone = zone;
        setDrag({ id, target, zone, x: event.clientX, y: event.clientY });
        const node = dialog.current, box = node.getBoundingClientRect();
        if (event.clientY < box.top + 60) node.scrollTop -= 12;
        if (event.clientY > box.bottom - 60) node.scrollTop += 12;
      },
      end(event) {
        const current = gesture.current;
        if (current?.active && current.target) finishDrop(id, current.target, current.zone);
        gesture.current = null; setDrag(null);
        if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
      },
      cancel() { gesture.current = null; setDrag(null); },
    };
  }
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState('');
  const busy = progress !== null;
  useEffect(() => {
    const node = dialog.current;
    if (!node.open) node.showModal();
    return () => controller.current?.abort();
  }, []);
  const moveGroup = (index, target) => { setGroups((current) => moveItem(current, index, target)); setAnnouncement('Ordre des réunions modifié.'); };
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

  return <dialog ref={dialog} className="ekn-dialog ekn-dialog--wide" aria-labelledby="organizer-title"
    onCancel={(event) => { if (drag || picked) { event.preventDefault(); gesture.current = null; setDrag(null); setPicked(null); } else if (busy) { event.preventDefault(); controller.current?.abort(); } }}
    onClose={() => { if (!busy) onCancel(); }}>
    <h2 id="organizer-title">Organiser les enregistrements</h2>
    <p>Avec la poignée, dépose un audio au centre d’un autre pour les réunir, ou entre deux réunions pour régler l’ordre.</p>
    <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
      <span className="text-ekn-sm text-ekn-text-muted" aria-live="polite">
        {groups.length} réunion{groups.length > 1 ? 's' : ''} · {groups.reduce((total, group) => total + group.files.length, 0)} fichiers
      </span>
    </div>
    <p className="text-ekn-sm text-ekn-text-muted" role="status">{announcement || 'Au clavier : les flèches déplacent ; Entrée choisit une réunion, puis Entrée sur une autre les réunit.'}</p>
    <ol className="space-y-3 mt-3" aria-label="Ordre des réunions">
      {groups.map((group, index) => {
        const joined = group.files.length > 1;
        const audio = group.files.every((file) => isAudioFile(file) && !file.remote);
        return <li key={group.id} data-reorder-index={index} data-reorder-scope="meetings"
          data-group-id={group.id}
          data-dragging={drag?.id === group.id || undefined}
          data-drop={drag?.target === group.id ? drag.zone : undefined}
          data-picked={picked === group.id || undefined}
          className="organizer-meeting rounded-lg border border-bord p-3">
          <div className="flex items-center gap-2">
            <OrderHandle index={index} count={groups.length} scope="meetings" label={`la réunion ${index + 1}`}
              disabled={busy} onMove={(target) => moveGroup(index, target)} groupDrag={groupDrag(group.id)}
              picked={picked === group.id} onPick={(cancel) => pickGroup(group.id, cancel)} />
            <div className="flex min-w-0 flex-1 items-center gap-3">
              <span className="min-w-0 break-words text-ekn-sm">
                <strong className="block">{index + 1}. {joined ? `Une réunion · ${group.files.length} morceaux` : group.files[0].name}</strong>
                {!joined && <span className="text-ekn-text-muted">{fileSize(group.files[0].size)}{!audio ? ' · séparé' : ''}</span>}
              </span>
            </div>
            {joined && <button className="ekn-button ekn-button--subtle ekn-button--compact" disabled={busy}
              onClick={() => { setGroups((current) => splitGroup(current, group.id)); setPicked(null); setAnnouncement('Morceaux séparés en réunions indépendantes.'); }}>Séparer</button>}
          </div>
          {drag?.target === group.id && drag.zone === 'join' && <p className="organizer-drop-label" aria-hidden="true">Relâche pour ajouter à cette réunion</p>}
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
    {drag && <div className="organizer-ghost" aria-hidden="true" style={{ left: Math.min(drag.x + 12, window.innerWidth - 220), top: drag.y + 14 }}>
      {drag.zone === 'join' ? '＋ Réunir les audios' : '⠿ Déplacer la réunion'}
    </div>}
    <p className="mt-4 text-ekn-sm">Les audios réunis donneront une seule transcription et un seul enregistrement. Les autres restent dans la file.</p>
    <Erreur>{error}</Erreur>
    {busy && <p role="status">{progress}</p>}
    <div className="ekn-dialog__actions">
      <Bouton variante="discret" onClick={() => busy ? controller.current?.abort() : onCancel()}>{busy ? 'Interrompre l’assemblage' : 'Annuler'}</Bouton>
      <Bouton disabled={busy || !groups.length} onClick={confirm}>Continuer avec {groups.length} réunion{groups.length > 1 ? 's' : ''}</Bouton>
    </div>
  </dialog>;
}
