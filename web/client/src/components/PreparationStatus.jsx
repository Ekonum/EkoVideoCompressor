import { preparation, preparationLabel, usePreparation } from '../preparation.js';

/** Le nom du fichier garde sa ligne ; le détail reste lisible au survol
 * et par les lecteurs d'écran. La file donne aussi un résumé visible. */
export function PreparationStatus({ file }) {
  const state = usePreparation(file);
  const status = state?.status || 'waiting';
  const label = preparationLabel(state);
  return <span className="context-indicator" data-state={status} role="status" title={label} aria-label={label}>
    {status === 'running' ? <span className="context-spinner" aria-hidden="true" /> :
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        {status === 'ready' ? <path d="m5 12 4 4L19 6" /> : status === 'error' ? <><circle cx="12" cy="12" r="9" /><path d="M12 7v6m0 3v1" /></> : <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>}
      </svg>}
  </span>;
}

export function PreparationSummary({ files }) {
  usePreparation(null);
  const states = files.map((file) => preparation.get(file)?.status || 'waiting');
  const ready = states.filter((s) => s === 'ready').length;
  const errors = states.filter((s) => s === 'error').length;
  const pending = states.length - ready - errors;
  const labels = [ready && `${ready} prêt${ready > 1 ? 's' : ''}`, pending && `${pending} en préparation`, errors && `${errors} indisponible${errors > 1 ? 's' : ''}`].filter(Boolean);
  return <span className="text-ekn-xs text-ekn-text-muted" role="status">Contextes : {labels.join(' · ')}</span>;
}
