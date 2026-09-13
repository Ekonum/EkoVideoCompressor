# Spike M0 — pipeline média navigateur

Jalon M0 du plan de migration vers une webapp (`~/.claude/plans/temporal-wiggling-lovelace.md`).

**Question tranchée par ce spike** : peut-on, *dans un navigateur*, extraire l'audio et compresser
un enregistrement de plusieurs Go — pour n'uploader que de petits segments audio, le serveur
n'ayant ni le stockage ni le CPU pour faire ce travail ?

## Lancer

Un contexte sécurisé est requis (WebCodecs + écriture disque), donc `localhost`, pas `file://` :

```bash
cd spike/browser-media && python3 -m http.server 8747
```

Puis ouvrir <http://localhost:8747/> dans **Chrome** (le navigateur utilisé par l'équipe), choisir
un vrai fichier lourd, lancer les deux tests, et copier le rapport. Safari n'est pas testé : personne
ne l'utilise ici. La webapp affichera une barrière explicite si `AudioEncoder` / `VideoEncoder`
manquent, plutôt que de viser une compatibilité dont on n'a pas besoin.

Fichier de test conseillé (le plus exigeant disponible) :
`~/EkoVideo Compressor/…/Enregistrement de l'écran 2026-07-03 à 14.40.48.mov` — 4,4 Go.
Sa version compressée x265 existe à côté (288 Mo), ce qui donne une **référence directe** pour
juger la compression navigateur sur la même source.

## Ce qui est mesuré

- **Test A — audio pour transcription** : découpe en fenêtres (miroir de `plan_audio_chunks`)
  puis encodage Opus ou MP3 mono 16 kHz. On veut la taille du plus gros segment (doit rester
  très en dessous des 100 Mo du tunnel Cloudflare), le débit en Mo/heure, et le temps.
- **Test B — compression** : 720p/12 fps comme le profil actuel, en H.264 / HEVC / AV1 / VP9.
  La sortie est écrite **directement sur le disque** (`showSaveFilePicker`), jamais uploadée.
  Le débit vidéo et le profil audio sont réglables, parce que la référence à battre est très basse
  (voir ci-dessous) : à débit égal la question du codec ne se pose presque plus.

## Résultats de validation (clip de synthèse, 10 s, Chromium 152 sur Apple Silicon)

Validation des appels API, pas une mesure de performance représentative :

| Sortie | Taille | Temps |
|---|---|---|
| Opus mono 16 kHz @24 kbps | 35 Ko (≈ 12,8 Mo/h) | 142 ms |
| H.264 720p 12 fps @800 kbps | 432 Ko | 1 281 ms |
| HEVC 720p 12 fps @800 kbps | 354 Ko | 574 ms |

Deux enseignements qui **corrigent le plan** :

1. **Le HEVC est disponible** (`VIDEO_CODECS` de Mediabunny contient `hevc`, et
   `VideoEncoder.isConfigSupported` le confirme sur Mac). Le plan partait du principe qu'il
   était impossible en navigateur et retenait H.264 par défaut. Ici il est *plus petit et plus
   rapide* — la décision doit se reprendre sur mesure réelle.
2. **Le MP3 est disponible** aussi (`AUDIO_CODECS`), alors que WebCodecs ne propose qu'Opus et
   AAC : Mediabunny embarque son propre encodeur. On pourrait donc garder le format d'upload
   actuel à l'identique. L'Opus reste préférable (≈12,8 Mo/h contre 28 Mo/h en MP3 64 kbps),
   mais c'est désormais un choix, plus une contrainte.

## Régénérer le clip de synthèse

```bash
./bin/ffmpeg -y -f lavfi -i "testsrc=size=1280x720:rate=30" \
  -f lavfi -i "sine=frequency=440:sample_rate=48000" \
  -t 30 -c:v libx264 -preset ultrafast -c:a aac -shortest \
  spike/browser-media/_probe.mp4
```

## Mesures sur le vrai fichier (Chrome 152, `…2026-07-03 à 14.40.48.mov`, 4466 Mo, 3 h 34)

| Test | Résultat |
|---|---|
| A — Opus mono 16 kHz @24 kbps | 8 segments, 38,4 Mo au total, **plus gros segment 4,9 Mo** (10,7 Mo/h), 128 s soit **100× temps réel**, pic mémoire 119 Mo |
| B — H.264 720p/12 fps @800 kbps + AAC 128k stéréo | 843,8 Mo (−81,1 %), 1 436 s soit 9× temps réel, pic mémoire 215 Mo |

**Test A tranche la contrainte dure du plan** : le plus gros segment est 20× sous le plafond de
100 Mo du tunnel Cloudflare, et le serveur ne reçoit jamais que ~5 Mo à la fois.

**Test B était mal réglé, pas mal codé.** La sortie x265 de l'app sur la *même* source fait 288 Mo,
et `ffprobe` en donne la composition : **54 kbps de vidéo**, 128 kbps d'audio AAC stéréo 96 kHz —
autrement dit 206 des 288 Mo sont de l'audio. Cet enregistrement d'écran est quasi statique, donc
x265 en CRF 28 ne dépense presque rien. Viser 800 kbps en débit fixe, c'est demander ~15× la
référence : l'écart observé mesure mon réglage, pas le navigateur. D'où les deux réglages ajoutés
(débit vidéo par défaut ramené à 150 kbps, profil audio choisissable) avant de reprendre la mesure.
