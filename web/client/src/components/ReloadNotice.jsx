import { useDraftSaving, useQueuePersistence } from '../fileQueue.js';
import { useArchiving } from '../archivage.js';
import { encodeEncore, useTranscriptions } from '../usePipeline.js';
import { Bouton } from './Communs.jsx';

export function ReloadNotice({ error, compressing = false }) {
  useTranscriptions();
  const archiving = useArchiving();
  const saving = useDraftSaving();
  const persistenceError = useQueuePersistence();
  if (!error) return null;
  const busy = encodeEncore() || archiving || compressing || saving;
  return <div className="ekn-alert ekn-alert--warning mt-3" role="alert">
    <strong>Le module audio doit être rechargé</strong>
    <p>{error.message}</p>
    <p>{persistenceError ? 'La file n’a pas pu être sauvegardée. Redépose ses fichiers après rechargement.' : 'La file sauvegardée sur ce navigateur et les réunions déjà enregistrées sont conservées.'}</p>
    {busy && <p>Attends la fin des envois, compressions et archivages en cours avant de recharger.</p>}
    <Bouton variante="discret" disabled={busy} onClick={() => window.location.reload()}>Recharger la page</Bouton>
  </div>;
}
