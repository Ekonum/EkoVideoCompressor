# Client EkoVideo

React + Vite + Tailwind 4. Construit avec la charte Ekonum : palette
officielle, Chillax pour les titres, Synonym pour le texte, fontes et
logos servis par le conteneur — pas par un CDN, l'app vivant derrière
Cloudflare Access.

## Développer

```bash
npm install
npm run dev          # client sur 5173, /api relayé vers uvicorn:8080
```

En face, le serveur :

```bash
EKOVIDEO_WEB_DEV_MODE=1 uvicorn app.main:create_app --factory --app-dir web --port 8080
```

## Construire

```bash
npm run build        # → dist/, servi tel quel par FastAPI
```

## Ce qui structure le code

**Tout le média vit dans `media-worker.js`.** Découpage, encodage et
envoi s'y font, et même la sonde de durée : la garder sur le fil
principal y aurait fait entrer Mediabunny, soit 320 Ko de plus que toute
l'interface réunie. Le worker n'est chargé qu'au moment où un fichier est
choisi.

**`usePipeline`** enchaîne création, encodage, envoi et suivi. Les
composants ne manipulent que des états — ils n'ont pas à savoir qu'un
encodeur existe.

**La recherche est côté serveur** (FTS5) et non un filtre local, qui ne
verrait que les lignes déjà chargées.

## Parti pris visuel

Un seul grand aplat sombre, l'en-tête : la charte demande de les réserver
aux moments de contraste utiles, et une succession de sections sombres
donnerait le ton froid qu'Ekonum ne veut pas. Le turquoise porte les
actions et l'avancement ; le violet reste un accent rare — il ne signale
qu'une chose, l'existence d'une version antérieure.

Les cartes sont réservées aux objets autonomes : un traitement, une
fenêtre, une version. La bibliothèque est une table, parce que ce sont
des lignes comparables qu'on balaie, et les encadrer une à une
ajouterait des contenants sans rien clarifier.

## Rodage sans intervention

`?source=/chemin` charge un fichier servi par le serveur au lieu de
passer par le sélecteur : la chaîne complète est vérifiable sans humain.
Même origine, derrière Access comme le reste.
