import { preparationLabel, usePreparation } from '../preparation.js';

export function PreparationStatus({ file }) {
  const state = usePreparation(file);
  return <span className="block text-ekn-xs text-ekn-text-muted" role="status">{preparationLabel(state)}</span>;
}
