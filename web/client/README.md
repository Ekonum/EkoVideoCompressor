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

## Compression

Profil arrêté au jalon M0 : **HEVC 720p, 12 images par seconde, ~150 kbps,
audio AAC 64 kbps mono**. Mesuré sur une réunion de 3 h 34 : 4 466 Mo
deviennent 335 Mo, soit 92,5 % de réduction, à 5,4× le temps réel — une
parité de vitesse avec le libx265 de l'app macOS, pas un gain.

Le débit n'est pas un curseur : l'encodeur plafonne vers 133 kbps, et la
zone de texte d'une capture d'écran est *byte-identique* de 60 à
250 kbps. Les bits supplémentaires vont aux zones en mouvement. Monter la
résolution est le seul vrai levier, et le 1080p (490 Mo) n'a pas semblé
valoir les 155 Mo supplémentaires.

La sortie est écrite **directement sur le disque** via
`showSaveFilePicker` et un `StreamTarget` : une archive de plusieurs
centaines de mégaoctets ne tient pas en mémoire, et surtout elle n'est
jamais envoyée au serveur. En mode « Compresser » seul, le serveur n'est
pas sollicité du tout.

*Écart assumé* : l'app macOS ajoute `-movflags +faststart`, qui déplace
l'index en tête de fichier. Ce n'est pas faisable en écriture
continue — il faudrait réécrire le fichier entier après coup. L'archive
se lit parfaitement en local ; elle démarrera juste moins vite si un
jour on la sert en HTTP.
