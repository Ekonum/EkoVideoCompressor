# Banc automatisable

`index.html` demande un fichier au sélecteur et une destination au `showSaveFilePicker` : très bien
pour une mesure ponctuelle, impraticable dès qu'on veut balayer des réglages — chaque essai réclame
un humain devant l'écran.

Ce banc-ci fait la même chose sans intervention. `serve.py` sert la source **en Range** (Mediabunny
lit en streaming, donc un fichier de plusieurs Go ne pose pas de problème) et récupère les sorties en
`PUT` ; `bench.html` lit ses paramètres dans l'URL et enchaîne les encodages.

```bash
python3 serve.py "/chemin/vers/source.mov" bench.html ./out &
open "http://127.0.0.1:8748/bench?start=2700&span=180&h=720&runs=hevc:150,hevc:250"
```

| Paramètre | Rôle |
|---|---|
| `start` / `span` | fenêtre encodée, en secondes |
| `h` | hauteur de sortie (720, 1080…) |
| `runs` | liste `codec:kbps` séparée par des virgules |

La page écrit une ligne `RUN <fichier> bytes=… kbps=… ms=…` par encodage, puis `DONE`. Les fichiers
atterrissent dans le dossier de sortie, prêts pour `ffprobe` ou une extraction d'images.

**Pourquoi le navigateur et pas ffmpeg** : `hevc_videotoolbox` refuse de descendre sous ~300 kbps sur
ce contenu, là où l'encodeur de Chrome tient les 150 demandés. Les deux passent pourtant par
VideoToolbox — le pilotage du débit diffère. Une mesure en ligne de commande ne remplace donc pas le
navigateur ; elle le contredit.
