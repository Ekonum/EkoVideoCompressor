# Stockage vidéo

Les vidéos compressées vont dans le Drive partagé **« transcript — stockage »**, dont le seul
membre est le compte de service `transcript-stockage@transcript-509912.iam.gserviceaccount.com`.
Personne ne le voit dans son Drive ; transcript est la seule porte d'entrée. En service depuis
le 28/09/2026.

## Sans clé de compte de service

Le serveur prouve qui il est par la **fédération d'identité de charge de travail** — la voie
que Google recommande hors de Google Cloud :

1. il signe un jeton de 5 minutes avec sa propre clé, née dans le volume
   (`/data/identite-google.pem`, 0600) et qui n'en sort jamais ;
2. STS le vérifie contre la moitié publique, déposée dans le fournisseur `serveur` du pool
   `transcript` (projet `transcript-509912`), et n'accepte que le sujet `transcript` ;
3. IAM Credentials rend un jeton d'une heure du compte de service, que ce sujet — et lui
   seul — a le droit d'emprunter.

La contrainte `iam.disableServiceAccountKeyCreation` reste en place : aucune clé JSON n'existe.

## Configuration du stack (rien de secret)

| Variable | Valeur |
|---|---|
| `EKOVIDEO_GCP_FOURNISSEUR` | `projects/917294492697/locations/global/workloadIdentityPools/transcript/providers/serveur` |
| `EKOVIDEO_GCP_COMPTE` | `transcript-stockage@transcript-509912.iam.gserviceaccount.com` |
| `EKOVIDEO_VIDEO_DOSSIER` | `0AHJJzO0VawJuUk9PVA` (le Drive partagé) |

Sans l'une des trois, la fonction disparaît de l'interface — rien ne casse.

## Refaire, ou faire tourner la clé

Tout le côté Google tient dans `bin/provisionner_gcp.sh`, idempotent :

```bash
gcloud auth login --enable-gdrive-access --force          # un humain, une fois
ssh server-casaos "sudo docker exec transcript python -m web.app.identite" > jwks.json
web/bin/provisionner_gcp.sh transcript-509912 jwks.json
```

**Rotation** : supprimer `/data/identite-google.pem` dans le conteneur, puis les deux
dernières commandes — le script redépose le JWKS. Entre les deux, les envois échouent
proprement (« stockage indisponible », avec le motif de Google).

**Perte du volume** = nouvelle clé au premier besoin, refusée par Google tant que le JWKS n'a
pas été redéposé : même geste.

**Retrouver le Drive** : les humains en ont été retirés (`--retirer-humains`). Pour y revenir,
console d'administration Workspace → Drive partagés → « transcript — stockage ».
