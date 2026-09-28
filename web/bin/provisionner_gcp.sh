#!/usr/bin/env bash
# Met en place, côté Google, le stockage vidéo de transcript — sans clé de
# compte de service. Idempotent : relancé, il ne recrée rien et remet le
# JWKS du fournisseur à jour (c'est aussi le geste de rotation).
#
#   gcloud auth login --enable-gdrive-access      # une fois, par un humain
#   ssh server-casaos "sudo docker exec transcript python -m web.app.identite" > jwks.json
#   web/bin/provisionner_gcp.sh <projet-gcp> jwks.json
#
# Ce que ça crée, et rien d'autre :
#   - les API IAM, IAM Credentials, STS et Drive dans le projet ;
#   - le compte de service transcript-stockage, sans aucune clé ;
#   - le pool « transcript » et son fournisseur OIDC « serveur », qui ne croit
#     que les jetons signés par la clé du serveur (JWKS déposé ici, jamais
#     récupéré sur le réseau) et dont le sujet vaut « transcript » ;
#   - le droit, pour ce seul sujet, d'emprunter ce seul compte ;
#   - le Drive partagé « transcript — stockage », le compte en Gestionnaire.
#
# Retirer les humains du Drive partagé (ce qui le rend invisible) reste un
# geste à part, volontaire : --retirer-humains.
set -euo pipefail

PROJET="${1:?projet GCP attendu}"
JWKS="${2:?fichier JWKS attendu (python -m web.app.identite)}"
RETIRER_HUMAINS="${3:-}"

EMETTEUR="https://transcript.ekonum.fr"
SUJET="transcript"
POOL="transcript"
FOURNISSEUR="serveur"
COMPTE_NOM="transcript-stockage"
COMPTE="${COMPTE_NOM}@${PROJET}.iam.gserviceaccount.com"
DRIVE_NOM="transcript — stockage"

g() { gcloud --project "$PROJET" --quiet "$@"; }
etape() { printf '\n→ %s\n' "$*"; }

python3 -c 'import json,sys; k=json.load(open(sys.argv[1]))["keys"]; assert k and all("d" not in c for c in k)' "$JWKS" \
  || { echo "JWKS illisible, ou contenant une partie privée : refus." >&2; exit 1; }

NUMERO="$(g projects describe "$PROJET" --format='value(projectNumber)')"
RESSOURCE="projects/${NUMERO}/locations/global/workloadIdentityPools/${POOL}/providers/${FOURNISSEUR}"

etape "API"
g services enable iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com drive.googleapis.com

etape "Compte de service ${COMPTE}"
g iam service-accounts describe "$COMPTE" >/dev/null 2>&1 \
  || g iam service-accounts create "$COMPTE_NOM" \
       --display-name="transcript — stockage vidéo" \
       --description="Écrit et lit les vidéos de transcript.ekonum.fr. Sans clé : emprunté par fédération d'identité."
# Une clé gérée par l'utilisateur n'a rien à faire ici : on le vérifie.
if [ -n "$(g iam service-accounts keys list --iam-account="$COMPTE" --managed-by=user --format='value(name)')" ]; then
  echo "Attention : ce compte porte une clé utilisateur. À supprimer." >&2
fi

etape "Pool ${POOL}"
g iam workload-identity-pools describe "$POOL" --location=global >/dev/null 2>&1 \
  || g iam workload-identity-pools create "$POOL" --location=global \
       --display-name="transcript" --description="Le serveur de transcript.ekonum.fr"

etape "Fournisseur ${FOURNISSEUR} (JWKS déposé)"
if g iam workload-identity-pools providers describe "$FOURNISSEUR" \
     --workload-identity-pool="$POOL" --location=global >/dev/null 2>&1; then
  g iam workload-identity-pools providers update-oidc "$FOURNISSEUR" \
    --workload-identity-pool="$POOL" --location=global --jwk-json-path="$JWKS"
else
  g iam workload-identity-pools providers create-oidc "$FOURNISSEUR" \
    --workload-identity-pool="$POOL" --location=global \
    --issuer-uri="$EMETTEUR" \
    --allowed-audiences="//iam.googleapis.com/${RESSOURCE}" \
    --attribute-mapping="google.subject=assertion.sub" \
    --attribute-condition="assertion.sub == '${SUJET}'" \
    --jwk-json-path="$JWKS"
fi

etape "Emprunt du compte, pour le seul sujet « ${SUJET} »"
g iam service-accounts add-iam-policy-binding "$COMPTE" \
  --role=roles/iam.workloadIdentityUser \
  --member="principal://iam.googleapis.com/projects/${NUMERO}/locations/global/workloadIdentityPools/${POOL}/subject/${SUJET}" \
  --format=none

etape "Drive partagé « ${DRIVE_NOM} »"
JETON="$(gcloud auth print-access-token)"
if ! curl -fsS --data-urlencode "access_token=${JETON}" https://oauth2.googleapis.com/tokeninfo | grep -q 'auth/drive'; then
  echo "La session gcloud n'a pas l'accès Drive. Relancer :" >&2
  echo "  gcloud auth login --enable-gdrive-access --force" >&2
  exit 1
fi
drive() { curl -fsS -H "Authorization: Bearer ${JETON}" -H "Content-Type: application/json" "$@"; }
DRIVE_ID="$(drive "https://www.googleapis.com/drive/v3/drives?pageSize=100&fields=drives(id,name)" \
  | python3 -c 'import json,sys; n=sys.argv[1]; print(next((d["id"] for d in json.load(sys.stdin).get("drives",[]) if d["name"]==n),""))' "$DRIVE_NOM")"
if [ -z "$DRIVE_ID" ]; then
  DRIVE_ID="$(drive -X POST "https://www.googleapis.com/drive/v3/drives?requestId=$(uuidgen)" \
    -d "$(python3 -c 'import json,sys; print(json.dumps({"name": sys.argv[1]}))' "$DRIVE_NOM")" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
fi
MEMBRES="$(drive "https://www.googleapis.com/drive/v3/files/${DRIVE_ID}/permissions?supportsAllDrives=true&fields=permissions(id,emailAddress,role)")"
if ! grep -q "$COMPTE" <<<"$MEMBRES"; then
  drive -X POST "https://www.googleapis.com/drive/v3/files/${DRIVE_ID}/permissions?supportsAllDrives=true&sendNotificationEmail=false" \
    -d "{\"type\":\"user\",\"role\":\"organizer\",\"emailAddress\":\"${COMPTE}\"}" >/dev/null
fi

if [ "$RETIRER_HUMAINS" = "--retirer-humains" ]; then
  etape "Retrait des humains du Drive partagé"
  python3 -c '
import json, sys
compte = sys.argv[1]
for p in json.loads(sys.argv[2]).get("permissions", []):
    if p.get("emailAddress") != compte:
        print(p["id"])' "$COMPTE" "$MEMBRES" | while read -r id; do
    drive -X DELETE "https://www.googleapis.com/drive/v3/files/${DRIVE_ID}/permissions/${id}?supportsAllDrives=true"
  done
fi

cat <<FIN

Variables du stack (rien de secret) :
  EKOVIDEO_GCP_FOURNISSEUR=${RESSOURCE}
  EKOVIDEO_GCP_COMPTE=${COMPTE}
  EKOVIDEO_VIDEO_DOSSIER=${DRIVE_ID}
FIN
