# Recette du dépôt de plusieurs fichiers

`npm test` vérifie les regroupements, leur ordre, la déduplication et le
partage des recherches entre la file et le formulaire, y compris après
un échec réseau ou un changement d'ordre.

Pour la recette navigateur, depuis `web/client` :

```sh
python3 tests/make-fixtures.py
npm run dev -- --host 127.0.0.1
```

Ouvrir `/tests/browser.html`. Cette page charge les vrais composants, avec
une API simulée et des sons synthétiques locaux. Elle n'appelle aucun
service distant, ne lance aucune transcription et ne publie rien dans Odoo.

- Ouvrir « Nouvelle transcription », puis « Déposer 3 enregistrements de test ».
- Avec la poignée, déposer le deuxième audio au centre du premier : deux
  réunions doivent rester. Ajouter le troisième au groupe, puis séparer.
- Déposer au bord d’une autre réunion : seul l’ordre change. Vérifier aussi
  un relâchement hors cible, Échap, le tactile et les flèches du clavier.
- Au clavier, Entrée sur la poignée choisit la réunion ; Entrée sur une
  autre poignée les réunit. Échap annule le choix.
- Vérifier « Séparer », puis « Annuler » : la file existante doit rester intacte.
- Valider un regroupement : la première réunion s'ouvre, le contexte de la
  suivante se prépare. Lancer la suivante depuis « À lancer » doit afficher
  le contexte prêt sans augmenter le compteur de recherches.
- « Contrôler l'assemblage audio » vérifie la durée et la fréquence du son
  avant et après la jonction, puis recommence dans l'ordre inverse. Le
  remplissage de l'encodeur AAC est toléré jusqu'à 150 ms sur ces deux sons.
- Refaire la recette à 375 px et 1280 px, dans les thèmes clair et sombre.

Les fichiers générés sont ignorés par Git. Cette page de recette n'est pas
une entrée du build de production.

### Module absent après déploiement

`/tests/browser.html?missing-worker=1` renvoie volontairement le worker de
lecture vers un module inexistant. Déposer un son valide doit afficher une
consigne et le bouton « Recharger la page », jamais « Fichier illisible ».
L'action est explicite et annonce la nécessité de redéposer la file.

`/tests/browser.html?reload-only=1&busy=1` vérifie le bouton désactivé pendant
une compression ; sans `busy`, le bouton doit être disponible.

### Recette parlée du 23 octobre 2026

Deux M4A parlés synthétiques (AAC mono 16 kHz et stéréo 44,1 kHz) ont
été réunis par le module réel. Le résultat de 28,331 s a suivi le
parcours de production existant : recherche de contexte, transcription
Gemini terminée, puis archivage. Les repères « tournesol » et
« montgolfière » apparaissent dans cet ordre, sur quatre segments.
La relecture complète du stockage retrouve les 236 690 octets et le
SHA-256 du fichier assemblé :
`83b89247b441b00680be36adccf537366442597e9fc7951c037c554ecc84286c`.
Aucun dossier Odoo n'a été retenu ni destinataire notifié. La nouvelle
interface a été vérifiée séparément sur la même paire, avec un autre
fichier laissé dans la file et son contexte préparé en parallèle.

Le bouton « Exporter l’assemblage de recette » permet de vérifier le
fichier produit hors de la page. `?spoken=1` utilise les fichiers locaux
`_fixtures/recette-partie-1.m4a` et `_fixtures/recette-partie-2.m4a` à la
place des deux sons ; les fixtures restent ignorées par Git.

### Retrait, ordre interne et repères d’écoute

- La corbeille est absente au repos, visible dès la saisie d’une poignée,
  et change d’état au survol. Relâcher y retire seulement l’élément saisi.
- Retirer un morceau puis « Annuler le retrait » ; vérifier aussi un groupe
  entier, Suppr au clavier et la validation d’une sélection devenue vide.
- Intervertir les morceaux avec leur propre poignée ; les réunions voisines
  conservent leur ordre. « Modifier les morceaux » ne montre que la réunion
  courante ; la file reste identique après validation.
- Vérifier les marqueurs aux jonctions dans le lecteur, et les liens des
  morceaux qui déplacent la tête de lecture sans démarrer le son.
- `?player-only=1` ouvre le lecteur de réécoute avec un assemblage synthétique.
  « Contrôler l’assemblage audio » vérifie aussi les repères réellement encodés
  et leur conservation lors de la copie du fichier avant transcription.
- Refaire le retrait au tactile à 375 px ; vérifier la file dans les deux
  écrans, sans débordement horizontal, et le lecteur sombre à mouvement réduit.

Les repères après rognage et leur restitution par l’API sont couverts par les
tests automatisés. Les nouvelles données sont facultatives dans le contexte
JSON existant ; aucune migration de base n’est requise.
