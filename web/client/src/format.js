export const mo = (bytes) => `${(bytes / 1048576).toFixed(1)} Mo`;

/** Mo sous le gigaoctet, Go au-delà : un inventaire de Drive parle vite en Go. */
export const fileSize = (bytes) =>
  bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} Go` : `${Math.max(1, Math.round(bytes / 1048576))} Mo`;

export const duree = (secondes) => {
  const t = Math.round(secondes || 0);
  const h = Math.floor(t / 3600);
  const m = String(Math.floor((t % 3600) / 60)).padStart(2, '0');
  const s = String(t % 60).padStart(2, '0');
  return h ? `${h} h ${m}` : `${m}:${s}`;
};

export const horodatage = (secondes) => {
  const t = Math.round(secondes || 0);
  return `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`;
};

export const usd = (montant) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(montant || 0);

export const jour = (iso) => {
  if (!iso) return '';
  const date = new Date(iso.replace(' ', 'T'));
  return Number.isNaN(date.getTime())
    ? ''
    : new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' }).format(date);
};

export const liste = (valeur) =>
  valeur.split(',').map((part) => part.trim()).filter(Boolean);
