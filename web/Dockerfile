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
COPY --from=client /client/dist ./web/client/dist

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
