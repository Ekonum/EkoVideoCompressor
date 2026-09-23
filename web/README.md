# EkoVideo — serveur web

Jalon **M1** du plan de migration vers une webapp. Le socle : FastAPI +
SQLite, authentification Cloudflare Access, clé Gemini via le broker, et
l'API jobs/fenêtres qui réutilise `cloud_transcription.py` tel quel.

## Le point non négociable

**Le serveur ne voit jamais le média.** Le VPS partagé n'a ni le stockage
pour des sources de plusieurs Go ni le CPU pour les encoder. Le navigateur
découpe et encode ; le serveur ne reçoit que des fenêtres audio Opus de
quelques Mo (mesuré en M0 : 4,9 Mo pour une réunion de 3 h 34, soit vingt
fois sous le plafond de 100 Mo du tunnel Cloudflare), les relaie à Gemini,
et ne conserve que des transcriptions.

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
le même mécanisme qui servira au panneau « relancer certaines fenêtres ».

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
