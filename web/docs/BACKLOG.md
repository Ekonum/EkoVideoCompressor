# Backlog transcript.ekonum.fr

Ce qui est décidé mais pas encore fait, et pourquoi ça attend.

## Stockage des vidéos : passer de Google Drive à GCS

**Pourquoi** : GCS est aujourd'hui le seul stockage objet qu'Odoo sait
utiliser pour ses pièces jointes. À terme, une vidéo de réunion devrait
pouvoir vivre à côté du dossier client, dans Odoo, sans copie.

**Pourquoi pas tout de suite** : on démarre sur un Drive partagé, qui ne
demande aucun compte de facturation GCP de plus. Le compte de service créé
pour Drive est **le même** que celui dont Odoo aura besoin pour GCS : le
travail d'identité est déjà fait.

**Ce que ça changera** : `web/app/stockage.py` expose une interface étroite
(ouvrir un envoi, envoyer un morceau, lire une plage, supprimer). GCS en sera
une seconde implémentation, avec deux gains :

- **URL signées** : le navigateur lira la vidéo directement dans GCS, sans
  passer par notre serveur ;
- **vraies classes de stockage** (Coldline, Archive) : le coût à la lecture,
  que l'interface annonce déjà, deviendra réel.

## Supprimer l'original en local après envoi

L'app macOS proposait « supprimer le fichier source après copie ». Un
navigateur ne peut effacer un fichier que si on lui en a donné le droit au
moment de le choisir (API File System Access, Chrome seulement). À faire en
choisissant le fichier par `showOpenFilePicker` avec accès en écriture,
jamais en silence.

## Un modèle de transcription moins cher, ou européen

Sans aucune régression de qualité : c'est la condition. Banc d'essai tout
trouvé — la bibliothèque, dont on connaît déjà les bonnes réponses, et la
réunion Acritec du 4 septembre transcrite deux fois. Pas de choix de modèle
exposé aux utilisateurs : ils ne connaissent pas ces noms, et ce n'est pas à
eux d'arbitrer.

## Mettre en service le stockage Drive — prévu le week-end du 26-27 septembre

Le code est prêt et dort (`EKOVIDEO_VIDEO_ITEM` / `EKOVIDEO_VIDEO_DOSSIER`
vides). Reste à créer, côté Google :

1. le compte de service « transcript-stockage » et sa clé JSON (API Drive
   activée ; lever `iam.disableServiceAccountKeyCreation` si elle bloque) ;
2. le Drive partagé « transcript — stockage », le compte de service en
   Gestionnaire, **puis retirer les humains** — c'est ce qui le rend invisible ;
3. l'élément de coffre « Ekonum - Google transcript (compte de service) »,
   champ « Clé JSON », lisible par l'application serveur « transcript ».

Puis : poser les deux variables dans le stack, et faire un premier vrai envoi
— le client Drive n'a été éprouvé que contre un Drive simulé.

## Migrer les vidéos existantes du Drive vers ce stockage

**Pourquoi** : le Drive de l'équipe déborde de vidéos de réunions (plus d'une
centaine rien que sur la première page de recherche de Robin). Les ranger dans
le stockage dédié fait le ménage, et les rattache à leur réunion dans
transcript.

**Comment, en deux temps** :

1. **Inventaire, sans rien toucher** : lister les vidéos (propriétaire, date,
   taille, dossier) et proposer pour chacune la réunion de la bibliothèque
   correspondante — par la date d'enregistrement et l'agenda, comme la sonde.
   Robin valide la liste avant tout déplacement.
2. **Déplacement** : une vidéo quitte le Drive de quelqu'un pour le Drive
   partagé — ce qui exige les droits de son propriétaire. Soit chacun lance la
   migration de ses propres fichiers depuis transcript, soit une délégation
   de domaine temporaire pour le compte de service. Les vidéos sans réunion
   correspondante restent où elles sont : le ménage ne doit rien perdre.

Les vidéos rattachées à une réunion déjà transcrite prennent sa place en
stockage froid ; les autres pourront être transcrites à la demande — jamais
en masse, pour ne pas payer des transcriptions sans intérêt.
