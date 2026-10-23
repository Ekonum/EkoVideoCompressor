import { useArchiving } from '../archivage.js';
import { encodeEncore, useTranscriptions } from '../usePipeline.js';
import { Bouton } from './Communs.jsx';

export function ReloadNotice({ error, compressing = false }) {
  useTranscriptions();
  const archiving = useArchiving();
  if (!error) return null;
  const busy = encodeEncore() || archiving || compressing;
  return <div className="ekn-alert ekn-alert--warning mt-3" role="alert">
    <strong>Le module audio doit être rechargé</strong>
    <p>{error.message}</p>
    <p>Après rechargement, redépose les fichiers de cet onglet. Les réunions déjà enregistrées sont conservées.</p>
    {busy && <p>Attends la fin des envois, compressions et archivages en cours avant de recharger.</p>}
    <Bouton variante="discret" disabled={busy} onClick={() => window.location.reload()}>Recharger la page</Bouton>
  </div>;
}
