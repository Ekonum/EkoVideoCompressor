/** Le peu de vocabulaire visuel partagé.
 *
 *  Volontairement maigre : la charte met en garde contre la carte
 *  réflexe. Ici une carte ne sert qu'à un objet autonome — un
 *  traitement, une fenêtre, une version. Le reste tient à
 *  l'alignement et à l'espacement.
 */

export function Bouton({ variante = 'primaire', className = '', ...props }) {
  const styles = {
    primaire: 'bg-fonce text-clair hover:bg-fonce-doux disabled:opacity-40',
    accent: 'bg-turquoise text-fonce hover:bg-turquoise-sombre hover:text-clair disabled:opacity-40',
    discret: 'border border-bord/80 bg-white/70 text-fonce hover:border-fonce/40 hover:bg-white disabled:opacity-40',
  }[variante];
  return (
    <button
      {...props}
      className={`titre rounded-lg px-4 py-2 text-[0.9375rem] font-medium transition-colors disabled:cursor-not-allowed ${styles} ${className}`}
    />
  );
}

export function Champ({ label, aide, ...props }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[0.8125rem] text-fonce/65">{label}</span>
      <input
        {...props}
        className="w-full rounded-lg border border-bord/80 bg-white/70 px-3 py-2 text-fonce transition-colors placeholder:text-fonce/35 focus:bg-white"
      />
      {aide ? <span className="mt-1 block text-[0.8125rem] text-fonce/50">{aide}</span> : null}
    </label>
  );
}

/** États d'un traitement. Le violet est un accent, pas un second
 *  turquoise : il ne sert qu'à signaler qu'une version antérieure
 *  existe — un repère rare, donc précieux. */
const ETATS = {
  en_attente: ['En attente', 'bg-fonce/8 text-fonce/70'],
  en_cours: ['En cours', 'bg-turquoise/20 text-turquoise-sombre'],
  a_finaliser: ['À finaliser', 'bg-turquoise/20 text-turquoise-sombre'],
  finalisation: ['Fusion…', 'bg-turquoise/20 text-turquoise-sombre'],
  termine: ['Terminé', 'bg-turquoise text-fonce'],
  erreur: ['Erreur', 'bg-[#b3261e]/12 text-[#8c1d18]'],
};

export function Etat({ valeur }) {
  const [libelle, style] = ETATS[valeur] || [valeur, 'bg-fonce/8 text-fonce/70'];
  return (
    <span className={`inline-block rounded-md px-2 py-0.5 text-[0.8125rem] font-medium ${style}`}>
      {libelle}
    </span>
  );
}

export function Erreur({ children }) {
  if (!children) return null;
  return (
    <p className="rounded-lg border border-[#b3261e]/25 bg-[#b3261e]/6 px-3 py-2 text-[0.875rem] text-[#8c1d18]">
      {children}
    </p>
  );
}

export function Vide({ titre, children }) {
  return (
    <div className="py-16 text-center">
      <p className="titre text-[1.0625rem] font-medium text-fonce">{titre}</p>
      <p className="mx-auto mt-2 max-w-md text-fonce/60">{children}</p>
    </div>
  );
}
