# Dépendances vendorisées

Servies par le conteneur plutôt que depuis un CDN : l'application vit
derrière Cloudflare Access, et dépendre de jsdelivr à l'exécution
ajouterait une panne possible et une fuite de trafic pour rien.

| Fichier | Paquet | Licence |
|---|---|---|
| `mediabunny.mjs` | `mediabunny@1.56.0` | MPL-2.0 |
| `mediabunny-mp3-encoder.mjs` | `@mediabunny/mp3-encoder@1.56.2` | MPL-2.0 |

## Une modification à reporter en cas de mise à jour

`mediabunny-mp3-encoder.mjs` importe `"mediabunny"` en spécificateur nu.
Une carte d'import résoudrait cela dans la page — mais **Chrome ne les
applique pas aux workers de module**, et c'est précisément dans le worker
que l'extension est chargée. L'import est donc réécrit en
`"./mediabunny.mjs"`, une ligne à refaire à chaque montée de version :

```bash
sed -i '' 's|from "mediabunny";|from "./mediabunny.mjs";|' mediabunny-mp3-encoder.mjs
```

## Pourquoi une extension pour le MP3

WebCodecs n'encode nativement que l'Opus et l'AAC. Le MP3 vient de ce
paquet séparé — le cœur de Mediabunny liste bien `mp3` dans ses codecs
audio, mais échoue à l'exécution sans l'extension, avec un message
explicite.
