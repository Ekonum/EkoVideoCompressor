/** En-tête de l'application.
 *
 *  Un aplat vert foncé, le logo à sa taille lisible, la navigation à
 *  droite. C'est le seul grand aplat sombre de l'interface : la charte
 *  demande de les réserver aux moments de contraste utiles, et une
 *  succession de sections sombres donnerait le ton froid qu'Ekonum ne
 *  veut pas.
 */
export function Entete({ vue, surVue }) {
  const onglets = [
    ['bibliotheque', 'Bibliothèque'],
    ['nouveau', 'Nouvelle transcription'],
  ];
  return (
    <header className="bg-fonce text-clair">
      <div className="mx-auto flex max-w-6xl items-center gap-8 px-6 py-4">
        <img src="/marque/logo-sombre.svg" alt="Ekonum" className="h-7 w-auto" />
        <nav className="flex gap-1">
          {onglets.map(([cle, libelle]) => (
            <button
              key={cle}
              onClick={() => surVue(cle)}
              aria-current={vue === cle ? 'page' : undefined}
              className={`titre rounded-lg px-3 py-1.5 text-[0.9375rem] font-medium transition-colors ${
                vue === cle
                  ? 'bg-turquoise text-fonce'
                  : 'text-clair/70 hover:text-clair'
              }`}
            >
              {libelle}
            </button>
          ))}
        </nav>
      </div>
    </header>
  );
}
