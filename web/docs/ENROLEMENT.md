# Enrôler un Mac sur transcript.ekonum.fr

État : **écrit, éteint**. `EKOVIDEO_ENROLEMENT` absente ou à `0`, les routes
d'enrôlement répondent 404 — tant que la fonction dort, elle n'existe pas.

## La question tranchée

Aujourd'hui Cloudflare Access protège **tout**, API comprise : aucune app macOS
ne peut joindre le serveur sans jeton de service Cloudflare. Ouvrir un chemin
retire une couche, et ça méritait une décision.

Elle est déjà prise ailleurs. `sync-hub`, qui résout le même problème — des
machines locales qui poussent vers un conteneur du serveur — l'écrit noir sur
blanc dans `docs/CONNEXION-CLOUDFLARE-ACCESS.md` :

> Ne pas protéger `/api/sync/push` ni `/api/sync/pull` par Access : les daemons
> s'y authentifient avec leur jeton d'appareil, pas avec un navigateur.

On suit le même motif plutôt que d'en inventer un second : **le navigateur
derrière Access, les chemins machine derrière nos jetons**. Ce n'est pas une
exception, c'est la convention maison.

## Ce qu'il faudra faire, le jour de l'activation

1. **Zero Trust → Access → Applications**, sur l'application « Transcriptions »,
   exclure ces chemins (ou leur donner une politique *Bypass*) :

   | Chemin | Qui l'appelle | Ce qui l'authentifie |
   |---|---|---|
   | `POST /api/enroll/device` | l'app, avant d'avoir un jeton | rien — ne donne rien d'exploitable |
   | `POST /api/enroll/token` | l'app, pour récupérer son jeton | le code appareil, à usage unique |
   | `POST /api/jobs/import` | l'app, pour pousser l'historique | `Authorization: Bearer ekt_…` |
   | `GET /api/me` | l'app, pour vérifier son jeton | idem |

   La validation (`GET /api/enroll/{code}` et `…/approve`) **reste derrière
   Access** : c'est un geste humain, dans un navigateur, et le serveur refuse
   d'ailleurs un jeton d'API sur ces routes.

2. Poser `EKOVIDEO_ENROLEMENT: "1"` dans le stack.

3. Côté app macOS (partie Swift, à écrire) : ouvrir la demande, afficher le code
   et le lien, attendre, puis **ranger le jeton dans le trousseau** — jamais
   dans un fichier ni en argument de commande, où l'historique du shell le
   garderait. C'est ce que fait `scripts/enroll.sh` de sync-hub.

## Le parcours

```
app macOS                     serveur                      navigateur
    │  POST /api/enroll/device    │                              │
    │────────────────────────────▶│  code appareil (secret)      │
    │◀────────────────────────────│  + code humain (ABCD-2345)   │
    │                             │                              │
    │  affiche « ABCD-2345 »      │       ouvre le lien ─────────▶│ Access
    │  et le lien                 │                              │ authentifie
    │                             │◀───── POST …/approve ────────│ valide
    │  POST /api/enroll/token     │                              │
    │────────────────────────────▶│                              │
    │◀──── jeton ekt_… (1 fois)   │                              │
    │                             │                              │
    │  POST /api/jobs/import …    │  pousse tout l'historique    │
```

## Ce qui est refusé, et pourquoi

- **Un jeton d'API ne peut pas approuver un enrôlement** (403). Sinon un jeton
  volé se multiplierait tout seul en appareils légitimes.
- **Un code appareil ne donne jamais deux jetons** : la demande est close à la
  première réclamation.
- **Une demande expire en quinze minutes**, et une demande expirée ne
  s'approuve plus.
- La page de validation affiche **quel** appareil demande et **quand** :
  valider à l'aveugle un code qu'on n'a pas provoqué est le seul risque réel du
  procédé.

Un jeton par machine : perdre un portable se règle en le révoquant depuis
« Mon compte », sans toucher aux autres.
