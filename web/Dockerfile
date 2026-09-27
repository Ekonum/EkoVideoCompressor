# syntax=docker/dockerfile:1

# ---- Client -----------------------------------------------------------
# Vite construit l'interface ici : l'image finale n'embarque ni Node ni
# node_modules, seulement le dossier `dist`.
FROM node:22-alpine AS client
WORKDIR /client
COPY web/client/package.json web/client/package-lock.json ./
RUN npm ci
COPY web/client/ ./
RUN npm run build

# ---- Manifeste --------------------------------------------------------
# Le manifeste du portail Ekonum, converti en JSON et complété ici des
# champs de build — jamais écrits à la main, ce qui le rend non
# falsifiable par inadvertance. PyYAML ne sert qu'à cette étape : le
# serveur, lui, ne fait que servir le fichier obtenu.
FROM python:3.12-slim AS manifeste
ARG VERSION=0.0.0-dev
ARG GIT_SHA=0000000
ARG BUILT_AT=1970-01-01T00:00:00Z
RUN pip install --no-cache-dir pyyaml==6.0.2
COPY web/ekonum.yaml /m/ekonum.yaml
RUN python -c "import json, os, yaml; \
d = yaml.safe_load(open('/m/ekonum.yaml', encoding='utf-8')); \
d.update(version=os.environ['VERSION'], git_sha=os.environ['GIT_SHA'], built_at=os.environ['BUILT_AT']); \
json.dump(d, open('/m/ekonum-app.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)"

# ---- Serveur ----------------------------------------------------------
FROM python:3.12-slim AS serveur
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EKOVIDEO_WEB_STATE=/data

WORKDIR /app

COPY web/requirements.txt ./web/requirements.txt
RUN pip install --no-cache-dir -r web/requirements.txt

# Le moteur partagé vit à la racine du dépôt : cloud_transcription.py et
# odoo_client.py sont en stdlib pur et sont repris tels quels, sans copie
# divergente. C'est toute la raison d'être du dépôt unique pendant la
# phase de parité.
COPY cloud_transcription.py odoo_client.py ./
COPY web/app ./web/app
# Les outils d'opérateur : fabrication d'un jeton d'amorçage, reprise de la
# bibliothèque macOS. Ils n'ont d'intérêt que lancés *dans* le conteneur,
# là où vivent la base et la configuration.
COPY web/bin ./web/bin
COPY --from=client /client/dist ./web/client/dist
COPY --from=manifeste /m/ekonum-app.json ./web/ekonum-app.json

# Utilisateur non privilégié : rien ici n'a besoin de root.
RUN useradd --system --uid 10001 ekovideo \
 && mkdir -p /data && chown -R ekovideo:ekovideo /data /app
USER ekovideo

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).status == 200 else 1)"

# Une seule instance : les appels sont du réseau, pas du CPU, et le
# conteneur est plafonné à 256 Mo.
CMD ["uvicorn", "web.app.main:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
