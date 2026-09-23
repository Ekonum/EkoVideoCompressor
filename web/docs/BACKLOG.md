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

## Importer les enregistrements Meet déjà dans Drive

Le Drive de l'équipe contient déjà des centaines de vidéos de réunions. Une
fois le stockage en place, elles pourraient être transcrites et rattachées à
leur dossier Odoo par la même sonde — mais seulement sur demande, réunion par
réunion : les transcrire toutes coûterait cher pour un intérêt incertain.
