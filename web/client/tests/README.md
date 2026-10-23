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
- Sélectionner les deux premiers fichiers, les réunir, déplacer un morceau
  puis la réunion avec les poignées et avec les flèches du clavier.
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
