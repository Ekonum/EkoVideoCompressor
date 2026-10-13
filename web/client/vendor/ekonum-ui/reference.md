# Couleurs et typographie — ekonum-ui 3.15.0

> Généré à partir des tokens de la version 3.15.0 : ne pas modifier à la main. Toujours à jour pour la dernière version 3.x : https://ui.ekonum.fr/3/reference.md

Dans le code, chaque token est une propriété CSS (`--ekn-dark-green`) et un utilitaire Tailwind (`bg-ekn-dark-green`). Le thème sombre s'applique à toute une page (`data-ekn-theme="dark"`) ou à une zone (`.ekn-dark`) ; « idem » : la même valeur dans les deux thèmes.

## Couleurs

### Palette officielle

Les quatre couleurs de la charte. Dans une interface, peindre avec les rôles plutôt qu'avec ces valeurs : les rôles changent avec le thème.

| Token | Clair | Sombre | Usage |
|---|---|---|---|
| `ekn-dark-green` | `#021A1A` | idem | encre de la marque : action principale sur clair, texte, en-têtes, zones sombres. |
| `ekn-off-white` | `#EAEAEA` | idem | base claire : fond de page, texte et libellé d'action sur vert foncé. |
| `ekn-turquoise` | `#2AD39F` | idem | signal : action et lien courant sur fond sombre, continuité ; jamais sous un texte clair. |
| `ekn-violet` | `#9645D6` | idem | accent ponctuel : marqueur et grande action de décision, avec du blanc pur ; un ou deux par écran. |

### Rôles

Ce avec quoi les composants peignent. Une maquette faite avec les rôles vaut pour les deux thèmes.

| Token | Clair | Sombre | Usage |
|---|---|---|---|
| `ekn-field` | `#FFFFFF` | `#021A1A` (`dark-green`) | intérieur d'un champ, rail d'un interrupteur. |
| `ekn-hover` | `#021A1A` à 12 % | `#EAEAEA` à 8 % | ligne, entrée de menu, bouton discret ou jour survolés. |
| `ekn-action` | `#021A1A` (`dark-green`) | `#2AD39F` (`turquoise`) | action principale, case cochée, jour choisi : la couleur la plus contrastée avec le fond. |
| `ekn-on-action` | `#EAEAEA` (`off-white`) | `#021A1A` (`dark-green`) | libellé et pictogramme sur la couleur d'action. |
| `ekn-action-hover` | `#0B3C34` (`hover-dark`) | `#27C695` | action principale survolée. |
| `ekn-focus` | `#021A1A` (`dark-green`) | `#2AD39F` (`turquoise`) | contour de focus, 2 px. |
| `ekn-danger` | `#BF3A2B` (`error-dark`) | `#D6584A` (`error`) | bouton d'action destructrice. |
| `ekn-on-danger` | `#FFFFFF` | `#021A1A` (`dark-green`) | libellé du bouton d'action destructrice. |
| `ekn-tone-success` | `#18785A` (`success-dark`) | `#2AD39F` (`success`) | état « réussite » sur le fond courant : pastille, liseré d'alerte. |
| `ekn-tone-warning` | `#89631B` (`warning-dark`) | `#D9A441` (`warning`) | état « attention » sur le fond courant. |
| `ekn-tone-error` | `#BF3A2B` (`error-dark`) | `#DE776B` (`error-light`) | état « erreur » sur le fond courant : pastille, message, bord d'un champ invalide. |
| `ekn-tone-unknown` | `#021A1A` à 50 % (`unknown-dark`) | `#EAEAEA` à 50 % (`unknown`) | état « inconnu » sur le fond courant. |
| `ekn-tile` | `#021A1A` (`dark-green`) | `#EAEAEA` (`off-white`) | plaque d'icône. |
| `ekn-on-tile` | `#2AD39F` (`turquoise`) | `#021A1A` (`dark-green`) | pictogramme sur la plaque d'icône. |
| `ekn-halo` | transparent | `#021A1A` (`dark-green`) | filet qui détache une marque fine d'une couleur vive qu'elle traverse. |
| `ekn-underline` | `#18785A` (`success-dark`) | `#2AD39F` (`turquoise`) | soulignement d'un lien, qui garde la couleur du texte. |
| `ekn-emphasis` | `#18785A` (`success-dark`) | `#2AD39F` (`turquoise`) | texte mis en valeur par la couleur de la marque : nom d'un interlocuteur, intitulé court ; jamais un état. |

### Surfaces, textes et bords

Les nuances d'interface dérivées de la palette.

| Token | Clair | Sombre | Usage |
|---|---|---|---|
| `ekn-surface` | `#F4F4F2` | `#152B2B` | fond des cartes, menus et fenêtres. *À valider par la marque (sombre).* |
| `ekn-background` | `#EAEAEA` (`off-white`) | `#0B2222` | fond de page. *À valider par la marque (sombre).* |
| `ekn-border` | `#021A1A` à 12 % | `#EAEAEA` à 12 % | séparateurs fins, bord des cartes. |
| `ekn-border-strong` | `#021A1A` à 24 % | `#EAEAEA` à 32 % | contour d'un bouton discret, filet d'en-tête de tableau. |
| `ekn-hover-dark` | `#0B3C34` | idem | survol d'un bouton vert foncé. |
| `ekn-border-control` | `#021A1A` à 50 % | `#EAEAEA` à 50 % | bord d'un champ : au moins 3:1, il identifie le champ. |
| `ekn-text` | `#021A1A` (`dark-green`) | `#EAEAEA` (`off-white`) | texte courant. |
| `ekn-text-muted` | `#021A1A` à 64 % | `#EAEAEA` à 72 % | texte secondaire, aide, exemple dans un champ ; le seul gris de texte. |
| `ekn-text-inverse` | `#EAEAEA` (`off-white`) | idem | texte sur vert foncé. |
| `ekn-text-inverse-muted` | `#EAEAEA` à 70 % | idem | texte secondaire et liens de navigation sur vert foncé. |
| `ekn-border-inverse` | `#EAEAEA` à 32 % | idem | bord sur fond sombre. |
| `ekn-hover-inverse` | `#EAEAEA` à 8 % | idem | survol sur fond sombre. |
| `ekn-overlay` | `#021A1A` à 48 % | `#021A1A` à 72 % | voile derrière une fenêtre modale. |
| `ekn-highlight` | `#2AD39F` à 24 % | idem | passage surligné, ligne sélectionnée. |
| `ekn-mark` | `#2AD39F` à 45 % | `#2AD39F` à 75 % | mots surlignés (résultat de recherche) sous une encre vert foncé. |

### États

Réussite, attention, erreur, inconnu : validés par la marque le 24/09/2026. Sur fond clair, la nuance foncée pour le texte et les pastilles ; sur fond sombre, la teinte vive. Un libellé dit toujours l'état : la couleur ne le porte jamais seule.

| Token | Clair | Sombre | Usage |
|---|---|---|---|
| `ekn-success` | `#2AD39F` (`turquoise`) | idem | pastille « réussite » sur fond sombre. |
| `ekn-success-dark` | `#18785A` | idem | texte et pastille « réussite » sur fond clair. |
| `ekn-warning` | `#D9A441` | idem | pastille « attention » sur fond sombre. |
| `ekn-warning-dark` | `#89631B` | idem | texte et pastille « attention » sur fond clair. |
| `ekn-error` | `#D6584A` | idem | pastille « erreur » sur fond sombre. |
| `ekn-error-dark` | `#BF3A2B` | idem | texte et pastille « erreur » sur fond clair. |
| `ekn-error-light` | `#DE776B` | idem | texte d'erreur dans une carte du thème sombre. *À valider par la marque (sombre).* |
| `ekn-unknown` | `#EAEAEA` à 50 % | idem | pastille « inconnu » sur fond sombre. |
| `ekn-unknown-dark` | `#021A1A` à 50 % | idem | pastille « inconnu » sur fond clair. |

### Séries de graphique

Une couleur par catégorie, toujours dans cet ordre, jamais pour dire un état. Chacune atteint 3:1 sur les fonds des deux thèmes et reste distincte des autres avec les trois daltonismes. Une cinquième catégorie va dans « Autres ».

| Token | Clair | Sombre | Usage |
|---|---|---|---|
| `ekn-series-1` | `#0E8A73` | `#2AD39F` (`turquoise`) | première série. *À valider par la marque (clair).* |
| `ekn-series-2` | `#9645D6` (`violet`) | `#B98AE8` | deuxième série. *À valider par la marque (sombre).* |
| `ekn-series-3` | `#C2571A` | `#F08A4B` | troisième série. *À valider par la marque (les deux).* |
| `ekn-series-4` | `#0B3C34` (`hover-dark`) | `#EAEAEA` (`off-white`) | quatrième série : l'encre du thème. |
| `ekn-series-other` | `#525C5C` | `#7E9090` | le reste regroupé, « Autres ». *À valider par la marque (les deux).* |

## Typographie

Deux familles de la charte, jamais remplacées : les polices sont livrées à part et réservées à l'usage interne (licence FFL).

| Token | Familles | Usage |
|---|---|---|
| `ekn-font-heading` | Chillax, system-ui, sans-serif | titres, actions, libellés d'état et marqueurs. |
| `ekn-font-body` | Synonym, system-ui, sans-serif | texte courant, champs, tableaux. |

### Échelle

Resserrée par rapport à la charte (écart assumé) : une interface dense a besoin de 12, 14, 16 et 20 px. Les trois grands titres sont fluides : leur taille descend jusqu'au minimum sur un téléphone (375 px).

| Token | Ordinateur | Téléphone | Usage |
|---|---:|---:|---|
| `ekn-text-xs` | 12 px | idem | métadonnées, libellés. |
| `ekn-text-sm` | 14 px | idem | texte secondaire. |
| `ekn-text-md` | 16 px | idem | corps de texte, champs. |
| `ekn-text-lg` | 20 px | idem | titre de carte. |
| `ekn-text-xl` | 26 px | 22 px | titre de section. |
| `ekn-text-2xl` | 34 px | 28 px | titre de page. |
| `ekn-text-3xl` | 44 px | 32 px | grand titre d'accueil. |

### Graisses des titres

| Niveau | Graisse | Taille |
|---|---:|---|
| `h1` | 700 | `ekn-text-2xl` |
| `h2` | 600 | `ekn-text-xl` |
| `h3` | 600 | `ekn-text-lg` |
| `h4` | 600 | `ekn-text-md` |

Texte courant en Synonym 500. Chillax 700 seulement pour le titre de premier niveau. Jamais moins de 16 px dans un champ, sinon Safari iOS zoome. Chiffres en colonnes : chiffres tabulaires.

### Rythme

| Token | Valeur | Usage |
|---|---:|---|
| `ekn-tracking` | −0,01 em | interlettrage, partout : les -10 unités de la charte. |
| `ekn-leading-heading` | 1,15 | interligne des titres. |
| `ekn-leading-body` | 1,55 | interligne du texte courant. |

## Contrastes mesurés

Chaque paire utilisée par les composants est mesurée (WCAG) à chaque version ; une paire sous son seuil bloque la publication. Pour une association absente d'ici, la mesurer sur son fond réel (transparence, dégradé, survol, thème) avant de l'employer.

**Paires utilisées par les composants — contrôlées en CI.** Seuils WCAG : 4,5 pour le texte, 3 pour le grand texte et les éléments d'interface (bords de contrôle, contours de focus, pictogrammes). Une paire qui nomme un rôle (`text`, `surface`, `action`…) est mesurée dans les deux thèmes : clair, et sombre (zone `.ekn-dark` ou page en `data-ekn-theme`).

| Premier plan | Fond | Thème | Où | Ratio | Seuil | Verdict |
|---|---|---|---|---:|---:|---|
| `text` | `background` | clair | texte courant sous .ekn, touche .ekn-key | 14,98 | 4,5 | ✓ |
| `text` | `background` | sombre | texte courant sous .ekn, touche .ekn-key | 13,79 | 4,5 | ✓ |
| `text` | `surface` | clair | texte dans une carte, un menu, une fenêtre, le calendrier | 16,36 | 4,5 | ✓ |
| `text` | `surface` | sombre | texte dans une carte, un menu, une fenêtre, le calendrier | 12,36 | 4,5 | ✓ |
| `text` | `field` | clair | saisie dans un champ | 18,02 | 4,5 | ✓ |
| `text` | `field` | sombre | saisie dans un champ | 14,98 | 4,5 | ✓ |
| `text-muted` | `background` | clair | texte secondaire | 5,08 | 4,5 | ✓ |
| `text-muted` | `background` | sombre | texte secondaire | 7,70 | 4,5 | ✓ |
| `text-muted` | `surface` | clair | texte secondaire dans une carte ; .ekn-replace, .ekn-disclosure, lecteur audio | 5,26 | 4,5 | ✓ |
| `text-muted` | `surface` | sombre | texte secondaire dans une carte ; .ekn-replace, .ekn-disclosure, lecteur audio | 7,11 | 4,5 | ✓ |
| `text-muted` | `field` | clair | indication d'un champ (placeholder) | 5,46 | 4,5 | ✓ |
| `text-muted` | `field` | sombre | indication d'un champ (placeholder) | 8,16 | 4,5 | ✓ |
| `on-action` | `action` (principale) | clair | .ekn-button, jour choisi du calendrier | 14,98 | 4,5 | ✓ |
| `on-action` | `action` (principale) | sombre | .ekn-button, jour choisi du calendrier | 9,37 | 4,5 | ✓ |
| `on-action` | `action-hover` | clair | .ekn-button survolé | 10,21 | 4,5 | ✓ |
| `on-action` | `action-hover` | sombre | .ekn-button survolé | 8,24 | 4,5 | ✓ |
| `on-danger` | `danger` | clair | .ekn-button--danger | 5,45 | 4,5 | ✓ |
| `on-danger` | `danger` | sombre | .ekn-button--danger | 4,59 | 4,5 | ✓ |
| blanc pur `#fff` | `violet` (principale depuis le 24/09/2026) | les deux | .ekn-badge en 12 px, .ekn-button--brand | 5,10 | 4,5 | ✓ |
| `tone-success` | `background` | clair | texte d'état « conforme » | 4,51 | 4,5 | ✓ |
| `tone-success` | `background` | sombre | texte d'état « conforme » | 8,62 | 4,5 | ✓ |
| `tone-success` | `surface` | clair | texte d'état « conforme » dans une carte | 4,92 | 4,5 | ✓ |
| `tone-success` | `surface` | sombre | texte d'état « conforme » dans une carte | 7,73 | 4,5 | ✓ |
| `tone-warning` | `background` | clair | texte d'état « à vérifier » | 4,52 | 4,5 | ✓ |
| `tone-warning` | `background` | sombre | texte d'état « à vérifier » | 7,37 | 4,5 | ✓ |
| `tone-warning` | `surface` | clair | texte d'état « à vérifier » dans une carte | 4,93 | 4,5 | ✓ |
| `tone-warning` | `surface` | sombre | texte d'état « à vérifier » dans une carte | 6,61 | 4,5 | ✓ |
| `tone-error` | `background` | clair | message d'erreur .ekn-error | 4,53 | 4,5 | ✓ |
| `tone-error` | `background` | sombre | message d'erreur .ekn-error | 5,49 | 4,5 | ✓ |
| `tone-error` | `surface` | clair | message d'erreur .ekn-error dans une carte | 4,95 | 4,5 | ✓ |
| `tone-error` | `surface` | sombre | message d'erreur .ekn-error dans une carte | 4,93 | 4,5 | ✓ |
| `text` | `hover` sur `surface` | clair | élément de menu, jour du calendrier survolés | 12,78 | 4,5 | ✓ |
| `text` | `hover` sur `surface` | sombre | élément de menu, jour du calendrier survolés | 9,95 | 4,5 | ✓ |
| `text-muted` | `hover` sur `surface` | clair | texte secondaire d'une ligne de tableau survolée | 4,76 | 4,5 | ✓ |
| `text-muted` | `hover` sur `surface` | sombre | texte secondaire d'une ligne de tableau survolée | 6,01 | 4,5 | ✓ |
| `text` | `highlight` sur `background` | clair | passage surligné, ligne sélectionnée sur le fond | 13,11 | 4,5 | ✓ |
| `text` | `highlight` sur `background` | sombre | passage surligné, ligne sélectionnée sur le fond | 8,13 | 4,5 | ✓ |
| `text` | `highlight` sur `surface` | clair | passage surligné, ligne sélectionnée dans une carte | 14,07 | 4,5 | ✓ |
| `text` | `highlight` sur `surface` | sombre | passage surligné, ligne sélectionnée dans une carte | 7,33 | 4,5 | ✓ |
| `text-muted` | `highlight` sur `background` | clair | texte secondaire d'une ligne sélectionnée sur le fond | 4,78 | 4,5 | ✓ |
| `text-muted` | `highlight` sur `background` | sombre | texte secondaire d'une ligne sélectionnée sur le fond | 5,06 | 4,5 | ✓ |
| `text-muted` | `highlight` sur `surface` | clair | texte secondaire d'une ligne sélectionnée dans une carte | 4,92 | 4,5 | ✓ |
| `text-muted` | `highlight` sur `surface` | sombre | texte secondaire d'une ligne sélectionnée dans une carte | 4,66 | 4,5 | ✓ |
| `text-inverse` | `dark-green` (principale) | les deux | texte de l'en-tête, de .ekn-nav et des zones sombres | 14,98 | 4,5 | ✓ |
| `text-inverse-muted` | `dark-green` | les deux | liens de l'en-tête et de .ekn-nav | 7,77 | 4,5 | ✓ |
| `turquoise` | `dark-green` (principale) | les deux | lien courant de .ekn-nav, compte de .ekn-selection-bar | 9,37 | 4,5 | ✓ |
| `dark-green` | `turquoise` (principale) | les deux | lien courant de l'en-tête, initiales du compte, mot surligné courant .ekn-mark | 9,37 | 4,5 | ✓ |
| `dark-green` | `mark` sur `background` | clair | mot surligné .ekn-mark sur le fond | 11,77 | 4,5 | ✓ |
| `dark-green` | `mark` sur `background` | sombre | mot surligné .ekn-mark sur le fond | 5,91 | 4,5 | ✓ |
| `dark-green` | `mark` sur `surface` | clair | mot surligné .ekn-mark dans une carte | 12,41 | 4,5 | ✓ |
| `dark-green` | `mark` sur `surface` | sombre | mot surligné .ekn-mark dans une carte | 6,07 | 4,5 | ✓ |
| `emphasis` | `background` | clair | texte mis en valeur : nom d'un interlocuteur, intitulé court, sur le fond | 4,51 | 4,5 | ✓ |
| `emphasis` | `background` | sombre | texte mis en valeur : nom d'un interlocuteur, intitulé court, sur le fond | 8,62 | 4,5 | ✓ |
| `emphasis` | `surface` | clair | texte mis en valeur : nom d'un interlocuteur, intitulé court, dans une carte | 4,92 | 4,5 | ✓ |
| `emphasis` | `surface` | sombre | texte mis en valeur : nom d'un interlocuteur, intitulé court, dans une carte | 7,73 | 4,5 | ✓ |
| `underline` | `background` | clair | soulignement d'un lien, .ekn-link, sur le fond | 4,51 | 3 | ✓ |
| `underline` | `background` | sombre | soulignement d'un lien, .ekn-link, sur le fond | 8,62 | 3 | ✓ |
| `underline` | `surface` | clair | soulignement d'un lien, .ekn-link, dans une carte | 4,92 | 3 | ✓ |
| `underline` | `surface` | sombre | soulignement d'un lien, .ekn-link, dans une carte | 7,73 | 3 | ✓ |
| `border-control` | `field` | clair | bord d'un champ, contre son intérieur | 3,45 | 3 | ✓ |
| `border-control` | `field` | sombre | bord d'un champ, contre son intérieur | 4,54 | 3 | ✓ |
| `border-control` | `background` | clair | bord d'un champ posé sur le fond | 3,30 | 3 | ✓ |
| `border-control` | `background` | sombre | bord d'un champ posé sur le fond | 4,41 | 3 | ✓ |
| `border-control` | `surface` | clair | bord d'un champ posé dans une carte | 3,37 | 3 | ✓ |
| `border-control` | `surface` | sombre | bord d'un champ posé dans une carte | 4,21 | 3 | ✓ |
| `focus` | `field` | clair | focus d'un champ | 18,02 | 3 | ✓ |
| `focus` | `field` | sombre | focus d'un champ | 9,37 | 3 | ✓ |
| `focus` | `background` | clair | focus sur le fond | 14,98 | 3 | ✓ |
| `focus` | `background` | sombre | focus sur le fond | 8,62 | 3 | ✓ |
| `focus` | `surface` | clair | focus dans une carte, un menu, le calendrier | 16,36 | 3 | ✓ |
| `focus` | `surface` | sombre | focus dans une carte, un menu, le calendrier | 7,73 | 3 | ✓ |
| `focus` | `hover` sur `surface` | clair | focus d'un élément de menu survolé | 12,78 | 3 | ✓ |
| `focus` | `hover` sur `surface` | sombre | focus d'un élément de menu survolé | 6,22 | 3 | ✓ |
| `turquoise` | `dark-green` | les deux | focus dans l'en-tête | 9,37 | 3 | ✓ |
| `tone-error` | `field` | clair | bord d'un champ en erreur | 5,45 | 3 | ✓ |
| `tone-error` | `field` | sombre | bord d'un champ en erreur | 5,97 | 3 | ✓ |
| `action` | `background` | clair | .ekn-switch activée, case cochée sur le fond | 14,98 | 3 | ✓ |
| `action` | `background` | sombre | .ekn-switch activée, case cochée sur le fond | 8,62 | 3 | ✓ |
| `action` | `surface` | clair | case cochée, carte de choix cochée, soulignement du jour courant, curseur du lecteur audio | 16,36 | 3 | ✓ |
| `action` | `surface` | sombre | case cochée, carte de choix cochée, soulignement du jour courant, curseur du lecteur audio | 7,73 | 3 | ✓ |
| `on-action` | `action` | clair | curseur de .ekn-switch activée, pictogramme du bouton lecture | 14,98 | 3 | ✓ |
| `on-action` | `action` | sombre | curseur de .ekn-switch activée, pictogramme du bouton lecture | 9,37 | 3 | ✓ |
| `text-muted` | `field` | clair | curseur de .ekn-switch désactivée | 5,46 | 3 | ✓ |
| `text-muted` | `field` | sombre | curseur de .ekn-switch désactivée | 8,16 | 3 | ✓ |
| `on-tile` | `tile` | clair | pictogramme de .ekn-tile | 9,37 | 3 | ✓ |
| `on-tile` | `tile` | sombre | pictogramme de .ekn-tile | 14,98 | 3 | ✓ |
| `dark-green` | `off-white` | les deux | pictogramme de .ekn-tile--light | 14,98 | 3 | ✓ |
| `tile` | `surface` | clair | .ekn-tile posée dans une carte | 16,36 | 3 | ✓ |
| `tile` | `surface` | sombre | .ekn-tile posée dans une carte | 12,36 | 3 | ✓ |
| `tile` | `background` | clair | .ekn-tile posée sur le fond | 14,98 | 3 | ✓ |
| `tile` | `background` | sombre | .ekn-tile posée sur le fond | 13,79 | 3 | ✓ |
| `tone-success` | `background` | clair | pastille et liseré « conforme » sur le fond | 4,51 | 3 | ✓ |
| `tone-success` | `background` | sombre | pastille et liseré « conforme » sur le fond | 8,62 | 3 | ✓ |
| `tone-success` | `surface` | clair | pastille et liseré « conforme » dans une carte | 4,92 | 3 | ✓ |
| `tone-success` | `surface` | sombre | pastille et liseré « conforme » dans une carte | 7,73 | 3 | ✓ |
| `tone-warning` | `background` | clair | pastille et liseré « à vérifier » sur le fond | 4,52 | 3 | ✓ |
| `tone-warning` | `background` | sombre | pastille et liseré « à vérifier » sur le fond | 7,37 | 3 | ✓ |
| `tone-warning` | `surface` | clair | pastille et liseré « à vérifier » dans une carte | 4,93 | 3 | ✓ |
| `tone-warning` | `surface` | sombre | pastille et liseré « à vérifier » dans une carte | 6,61 | 3 | ✓ |
| `tone-error` | `background` | clair | pastille et liseré « en échec » sur le fond | 4,53 | 3 | ✓ |
| `tone-error` | `background` | sombre | pastille et liseré « en échec » sur le fond | 5,49 | 3 | ✓ |
| `tone-error` | `surface` | clair | pastille et liseré « en échec » dans une carte | 4,95 | 3 | ✓ |
| `tone-error` | `surface` | sombre | pastille et liseré « en échec » dans une carte | 4,93 | 3 | ✓ |
| `tone-unknown` | `background` | clair | pastille et liseré « inconnu » sur le fond | 3,30 | 3 | ✓ |
| `tone-unknown` | `background` | sombre | pastille et liseré « inconnu » sur le fond | 4,41 | 3 | ✓ |
| `tone-unknown` | `surface` | clair | pastille et liseré « inconnu » dans une carte | 3,37 | 3 | ✓ |
| `tone-unknown` | `surface` | sombre | pastille et liseré « inconnu » dans une carte | 4,21 | 3 | ✓ |
| `tone-success` | `surface` | clair | poignée du lecteur audio non touchée en dernier | 4,92 | 3 | ✓ |
| `tone-success` | `surface` | sombre | poignée du lecteur audio non touchée en dernier | 7,73 | 3 | ✓ |
| `text` | `surface` | clair | poignée touchée en dernier, tête de lecture du lecteur audio | 16,36 | 3 | ✓ |
| `text` | `surface` | sombre | poignée touchée en dernier, tête de lecture du lecteur audio | 12,36 | 3 | ✓ |
| `text` | `turquoise` | clair | tête de lecture sur la partie gardée | 9,37 | 3 | ✓ |
| `halo` | `turquoise` | sombre | liseré de la tête de lecture sur la partie gardée | 9,37 | 3 | ✓ |
| `series-1` | `background` | clair | première série d'un graphique, d'une légende, d'une barre de répartition sur le fond | 3,56 | 3 | ✓ |
| `series-1` | `background` | sombre | première série d'un graphique, d'une légende, d'une barre de répartition sur le fond | 8,62 | 3 | ✓ |
| `series-1` | `surface` | clair | première série d'un graphique, d'une légende, d'une barre de répartition dans une carte | 3,89 | 3 | ✓ |
| `series-1` | `surface` | sombre | première série d'un graphique, d'une légende, d'une barre de répartition dans une carte | 7,73 | 3 | ✓ |
| `series-2` | `background` | clair | deuxième série d'un graphique, d'une légende, d'une barre de répartition sur le fond | 4,24 | 3 | ✓ |
| `series-2` | `background` | sombre | deuxième série d'un graphique, d'une légende, d'une barre de répartition sur le fond | 6,21 | 3 | ✓ |
| `series-2` | `surface` | clair | deuxième série d'un graphique, d'une légende, d'une barre de répartition dans une carte | 4,63 | 3 | ✓ |
| `series-2` | `surface` | sombre | deuxième série d'un graphique, d'une légende, d'une barre de répartition dans une carte | 5,57 | 3 | ✓ |
| `series-3` | `background` | clair | troisième série d'un graphique, d'une légende, d'une barre de répartition sur le fond | 3,74 | 3 | ✓ |
| `series-3` | `background` | sombre | troisième série d'un graphique, d'une légende, d'une barre de répartition sur le fond | 6,67 | 3 | ✓ |
| `series-3` | `surface` | clair | troisième série d'un graphique, d'une légende, d'une barre de répartition dans une carte | 4,08 | 3 | ✓ |
| `series-3` | `surface` | sombre | troisième série d'un graphique, d'une légende, d'une barre de répartition dans une carte | 5,98 | 3 | ✓ |
| `series-4` | `background` | clair | quatrième série d'un graphique, d'une légende, d'une barre de répartition sur le fond | 10,21 | 3 | ✓ |
| `series-4` | `background` | sombre | quatrième série d'un graphique, d'une légende, d'une barre de répartition sur le fond | 13,79 | 3 | ✓ |
| `series-4` | `surface` | clair | quatrième série d'un graphique, d'une légende, d'une barre de répartition dans une carte | 11,15 | 3 | ✓ |
| `series-4` | `surface` | sombre | quatrième série d'un graphique, d'une légende, d'une barre de répartition dans une carte | 12,36 | 3 | ✓ |
| `series-other` | `background` | clair | série « Autres » d'un graphique, d'une légende, d'une barre de répartition sur le fond | 5,73 | 3 | ✓ |
| `series-other` | `background` | sombre | série « Autres » d'un graphique, d'une légende, d'une barre de répartition sur le fond | 4,96 | 3 | ✓ |
| `series-other` | `surface` | clair | série « Autres » d'un graphique, d'une légende, d'une barre de répartition dans une carte | 6,26 | 3 | ✓ |
| `series-other` | `surface` | sombre | série « Autres » d'un graphique, d'une légende, d'une barre de répartition dans une carte | 4,45 | 3 | ✓ |
| `tone-success` | `border` sur `surface` | clair | remplissage de la jauge .ekn-meter dans la zone favorable, contre son rail, dans une carte | 3,85 | 3 | ✓ |
| `tone-success` | `border` sur `surface` | sombre | remplissage de la jauge .ekn-meter dans la zone favorable, contre son rail, dans une carte | 5,53 | 3 | ✓ |
| `tone-success` | `border` sur `background` | clair | remplissage de la jauge .ekn-meter dans la zone favorable, contre son rail, sur le fond | 3,53 | 3 | ✓ |
| `tone-success` | `border` sur `background` | sombre | remplissage de la jauge .ekn-meter dans la zone favorable, contre son rail, sur le fond | 6,25 | 3 | ✓ |
| `tone-warning` | `border` sur `surface` | clair | remplissage de la jauge .ekn-meter dans la zone à surveiller, contre son rail, dans une carte | 3,85 | 3 | ✓ |
| `tone-warning` | `border` sur `surface` | sombre | remplissage de la jauge .ekn-meter dans la zone à surveiller, contre son rail, dans une carte | 4,73 | 3 | ✓ |
| `tone-warning` | `border` sur `background` | clair | remplissage de la jauge .ekn-meter dans la zone à surveiller, contre son rail, sur le fond | 3,54 | 3 | ✓ |
| `tone-warning` | `border` sur `background` | sombre | remplissage de la jauge .ekn-meter dans la zone à surveiller, contre son rail, sur le fond | 5,34 | 3 | ✓ |
| `tone-error` | `border` sur `surface` | clair | remplissage de la jauge .ekn-meter dans la zone défavorable, contre son rail, dans une carte | 3,86 | 3 | ✓ |
| `tone-error` | `border` sur `surface` | sombre | remplissage de la jauge .ekn-meter dans la zone défavorable, contre son rail, dans une carte | 3,52 | 3 | ✓ |
| `tone-error` | `border` sur `background` | clair | remplissage de la jauge .ekn-meter dans la zone défavorable, contre son rail, sur le fond | 3,55 | 3 | ✓ |
| `tone-error` | `border` sur `background` | sombre | remplissage de la jauge .ekn-meter dans la zone défavorable, contre son rail, sur le fond | 3,98 | 3 | ✓ |
| `action` | `border` sur `surface` | clair | remplissage de la jauge .ekn-meter sans seuils, contre son rail, dans une carte | 12,78 | 3 | ✓ |
| `action` | `border` sur `surface` | sombre | remplissage de la jauge .ekn-meter sans seuils, contre son rail, dans une carte | 5,53 | 3 | ✓ |
| `action` | `border` sur `background` | clair | remplissage de la jauge .ekn-meter sans seuils, contre son rail, sur le fond | 11,73 | 3 | ✓ |
| `action` | `border` sur `background` | sombre | remplissage de la jauge .ekn-meter sans seuils, contre son rail, sur le fond | 6,25 | 3 | ✓ |

**Paires de la charte non utilisées — mesurées, sans seuil.**

| Premier plan | Fond | Thème | Où | Ratio | Seuil | Verdict |
|---|---|---|---|---:|---:|---|
| `off-white` | `violet` (secondaire) | les deux | non utilisée | 4,24 | — | grand texte seulement |
| `violet` | `off-white` (secondaire) | les deux | non utilisée | 4,24 | — | grand texte seulement |
| blanc pur `#fff` | `turquoise` (secondaire) | les deux | interdite pour du texte à toute taille (marque, 24/09/2026) | 1,92 | — | **échec, même en grand** |
| `off-white` | `turquoise` (secondaire) | les deux | interdite pour du texte à toute taille (marque, 24/09/2026) | 1,60 | — | **échec, même en grand** |

