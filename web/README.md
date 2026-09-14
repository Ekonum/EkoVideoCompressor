# EkoVideo — serveur web

Jalon **M1** du plan de migration vers une webapp. Le socle : FastAPI +
SQLite, authentification Cloudflare Access, clé Gemini via le broker, et
l'API jobs/fenêtres qui réutilise `cloud_transcription.py` tel quel.

## Le point non négociable

**Le serveur ne voit jamais le média.** Le VPS partagé n'a ni le stockage
pour des sources de plusieurs Go ni le CPU pour les encoder. Le navigateur
découpe et encode ; le serveur ne reçoit que des fenêtres audio de
quelques Mo — ~14 Mo pour une fenêtre de 30 min en MP3 64 kbps, sept fois
sous le plafond de 100 Mo du tunnel Cloudflare — les relaie à Gemini, et
ne conserve que des transcriptions.

## Pourquoi ici et pas dans son propre dépôt

Les deux applications consomment le **même** `cloud_transcription.py` —
catalogue des modèles, tarification, découpage, prompts, fusion. Pendant
la phase de parité, une copie divergente serait la première chose à
casser. Le découplage se fera en M6, quand l'app macOS sera retirée.

## Le contrat

| Route | Rôle |
|---|---|
| `POST /api/jobs` | Garde-fou budget, puis renvoie le **plan de découpage** et le profil audio à produire |
| `PUT /api/jobs/{id}/chunks/{i}` | Reçoit une fenêtre, répond **202 immédiatement**, transcrit en tâche de fond |
| `GET /api/jobs/{id}` | État, avancement, et **fenêtres manquantes** |
| `POST /api/jobs/{id}/finalize` | Fusionne, persiste transcript, segments, interlocuteurs et termes |

Trois décisions s'y lisent :

**Le plan de découpage est autoritatif côté serveur.** Le navigateur
exécute un plan qu'il reçoit, il ne le calcule pas — une seule source de
vérité (`plan_audio_chunks` + `chunk_seconds_for_model`).

**L'envoi est asynchrone.** Cloudflare coupe les requêtes vers 100 s, or
transcrire 30 minutes d'audio prend souvent plus : d'où le 202 et le
suivi par `GET`.

**La reprise est gratuite.** `missing_chunks` dit exactement ce que le
navigateur doit réencoder après un onglet fermé ou un réseau coupé. C'est
le même mécanisme qui sert au panneau « relancer certaines fenêtres ».

### Bibliothèque

| Route | Rôle |
|---|---|
| `GET /api/jobs` | La table — un traitement par ligne |
| `GET /api/jobs/{id}/detail` | Transcription, segments, interlocuteurs, termes, versions précédentes |
| `PATCH /api/jobs/{id}` | Édition **partielle** du titre, des interlocuteurs ou des termes |
| `POST /api/jobs/{id}/terms/replace` | Corrige un terme mal entendu partout à la fois |
| `POST /api/jobs/{id}/chunks/{i}/reset` | Redemande **une seule** fenêtre |
| `GET /api/search?q=` | Recherche plein texte dans ses propres transcriptions |

Quatre choix s'y lisent :

**L'édition est partielle.** Un champ absent est laissé tel quel : un
formulaire qui n'affiche pas les termes ne doit pas les effacer.

**Relancer une fenêtre ne repaie pas les autres.** `reset` remet la
fenêtre à l'état attendu et `missing_chunks` y renvoie le navigateur —
sur huit fenêtres dont trois ont échoué, les cinq bonnes sont gardées.

**Une relance archive la version en place** (`previous_versions_json`,
dix versions gardées) : rattraper une fenêtre ne doit pas détruire une
transcription déjà relue.

**La recherche est cloisonnée et vraiment plein texte** — FTS5, index
réécrit dans la même transaction que les segments, pour qu'une recherche
ne ramène jamais une phrase effacée. La requête est découpée et chaque
terme cité, sans quoi « l'équipe » partirait en erreur de syntaxe.

## Lancer en local

```bash
python3 -m venv .venv && .venv/bin/pip install -r web/requirements-dev.txt
EKOVIDEO_WEB_DEV_MODE=1 GEMINI_API_KEY=… \
  .venv/bin/uvicorn app.main:create_app --factory --app-dir web --port 8080
```

`EKOVIDEO_WEB_DEV_MODE` court-circuite Access et le broker. Il est
**refusé dès qu'une configuration Access est présente** : un déploiement
ne doit pas pouvoir démarrer ouvert par accident, et l'application refuse
de démarrer si ni l'un ni l'autre n'est configuré.

## Le client

`web/static/` — pas de build. Le module qui compte est
`media-worker.js` : il découpe et encode les fenêtres hors du fil
principal, puis les envoie lui-même (repasser des ArrayBuffers de
plusieurs Mo au fil principal juste pour les poster n'ajouterait que des
copies). Il est indépendant de tout framework et survivra à l'UI.

Pas de Vite ni de React pour l'instant : la chaîne média doit rester
lisible directement dans le navigateur. La question du socle frontend se
pose maintenant que la bibliothèque a son API, et elle sera tranchée avec
l'UI — pas avant, et surtout pas en retardant une API vérifiable.

**Format d'upload : MP3 64 kbps mono 16 kHz**, soit exactement ce que
produit `build_cloud_audio_cmd`. Gemini documente wav, mp3, aiff, aac,
ogg et flac ; l'Opus n'y figure pas, et le vérifier demande une vraie
clé. À format identique, la transcription issue du navigateur se compare
par ailleurs trait pour trait à celle de l'app macOS — c'est la
vérification du jalon. L'Opus reste l'optimisation visée (~10,7 Mo/h
contre ~28) : le jour où il est validé, seule `AUDIO_PROFILE` change.

### Rodage sans intervention

`?source=/chemin` charge un fichier servi par le serveur au lieu de
passer par le sélecteur, ce qui rend la chaîne vérifiable de bout en
bout sans humain. Même origine, derrière Access comme le reste.

```bash
./bin/ffmpeg -f lavfi -i "sine=frequency=220:sample_rate=48000" \
  -f lavfi -i "testsrc=size=320x240:rate=5" -t 720 \
  -c:v libx264 -preset ultrafast -c:a aac -shortest web/static/_rodage.mp4
# puis http://127.0.0.1:8080/?source=/_rodage.mp4
```

## Configuration

| Variable | Rôle |
|---|---|
| `EKOVIDEO_WEB_STATE` | Racine de la base et des fenêtres en transit (défaut `./state`) |
| `EKOVIDEO_ACCESS_TEAM_DOMAIN` / `EKOVIDEO_ACCESS_AUD` | Vérification du jeton Access |
| `EKONUM_TOKEN` | Jeton du broker de secrets |
| `EKONUM_BROKER_ITEM` / `EKONUM_BROKER_FIELD` | Élément du coffre à lire (défaut « Ekonum - API Google Gemini » / « Clé API ») |
| `EKOVIDEO_MONTHLY_BUDGET_USD` | Plafond d'équipe (défaut 50) |

## Authentification

On vérifie le **jeton** (`Cf-Access-Jwt-Assertion`) contre les clés
publiques de l'équipe, en contrôlant l'audience — jamais l'en-tête
`Cf-Access-Authenticated-User-Email` seule, qui se forge dès qu'on
atteint le conteneur directement. C'est le modèle de sync-hub.

## Clé Gemini

Une clé d'équipe partagée, lue **une fois** au démarrage via le broker et
gardée en cache (relecture seulement sur 401) : le broker est contingenté
à 30 requêtes/min et ~12 secrets distincts par quart d'heure. Il faut un
`User-Agent` réel, sans quoi Cloudflare renvoie 1010, et le conteneur doit
avoir rejoint le réseau Docker externe `ekonum-broker`.

Pas de clé par utilisateur : le broker est en lecture seule côté
application. L'attribution des coûts reste fine malgré la clé partagée,
via `api_usage` joint à `jobs.owner_id`.

## Tests

```bash
.venv/bin/python -m unittest discover -t web -s web/tests
```

Le fournisseur est remplacé par un double : ce qui est vérifié, c'est le
contrat — plan autoritatif, garde-fou budget **avant** le premier octet,
202 immédiat, reprise par fenêtres manquantes, effacement des fenêtres
après usage, et cloisonnement entre utilisateurs (le job d'un collègue
renvoie 404, pas 403, qui révélerait son existence).
