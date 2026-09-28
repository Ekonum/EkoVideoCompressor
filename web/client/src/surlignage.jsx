/** Surligner un terme dans un texte, sans tenir compte des accents ni
 *  de la casse : « controle » retrouve « Contrôle ». */

/** Minuscules sans accents, caractère par caractère — la longueur est
 *  gardée, pour que les positions trouvées valent dans le texte d'origine. */
export function plier(texte) {
  return [...String(texte || '')]
    .map((c) => c.normalize('NFD').replace(/\p{Mn}/gu, '').toLowerCase().slice(0, 1) || c)
    .join('');
}

/** Le texte, le terme cherché marqué partout où il apparaît.
 *
 *  `actif` désigne l'occurrence courante d'une recherche (les autres
 *  restent pâles) ; sans lui, toutes sont marquées franchement. */
export function surligner(texte, terme, actif) {
  const plie = plier(texte);
  const cible = plier(terme.trim());
  if (!cible) return texte;
  const morceaux = [];
  let depuis = 0;
  let k = 0;
  let trouve = plie.indexOf(cible);
  while (trouve >= 0) {
    morceaux.push(texte.slice(depuis, trouve));
    const franc = actif === undefined || actif === k;
    morceaux.push(
      <mark
        key={trouve}
        className={`rounded px-0.5 text-fonce ${
          franc ? 'bg-turquoise/60 ring-1 ring-turquoise-sombre' : 'bg-turquoise/20'
        }`}
      >
        {texte.slice(trouve, trouve + cible.length)}
      </mark>,
    );
    depuis = trouve + cible.length;
    trouve = plie.indexOf(cible, depuis);
    k += 1;
  }
  morceaux.push(texte.slice(depuis));
  return morceaux;
}

/** Chaque mot d'une requête marqué là où il apparaît — la recherche de
 *  la bibliothèque cherche les mots, pas la phrase. Les plages qui se
 *  chevauchent sont fusionnées. */
export function surlignerMots(texte, requete) {
  const plie = plier(texte);
  const mots = String(requete || '').trim().split(/\s+/)
    .map((m) => plier(m.replace(/[*"]/g, ''))).filter((m) => m.length >= 2);
  const plages = [];
  for (const mot of mots) {
    let trouve = plie.indexOf(mot);
    while (trouve >= 0) {
      plages.push([trouve, trouve + mot.length]);
      trouve = plie.indexOf(mot, trouve + mot.length);
    }
  }
  if (!plages.length) return texte;
  plages.sort((x, y) => x[0] - y[0]);
  const fusion = [plages[0]];
  for (const [debut, fin] of plages.slice(1)) {
    const derniere = fusion[fusion.length - 1];
    if (debut <= derniere[1]) derniere[1] = Math.max(derniere[1], fin);
    else fusion.push([debut, fin]);
  }
  const morceaux = [];
  let depuis = 0;
  for (const [debut, fin] of fusion) {
    morceaux.push(texte.slice(depuis, debut));
    morceaux.push(
      <mark key={debut} className="rounded bg-turquoise/45 px-0.5 text-fonce">
        {texte.slice(debut, fin)}
      </mark>,
    );
    depuis = fin;
  }
  morceaux.push(texte.slice(depuis));
  return morceaux;
}
