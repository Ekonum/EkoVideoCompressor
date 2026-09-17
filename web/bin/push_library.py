#!/usr/bin/env python3
"""Pousse la bibliothèque macOS vers le serveur, par l'API.

L'autre voie serait d'aller écrire dans le volume du conteneur. Celle-ci
est meilleure : elle passe par le contrat public, elle est rejouable, et
elle laisse la base du serveur cohérente — segments indexés, vocabulaire
d'équipe alimenté.

La base locale est ouverte en **lecture seule** : une reprise ne doit
jamais pouvoir abîmer la bibliothèque d'origine.

    python3 web/bin/push_library.py \\
        --source ~/Library/Application\\ Support/EkoVideo\\ Compressor/library.db \\
        --serveur https://transcript.ekonum.fr \\
        --jeton-fichier ~/.transcript-token \\
        --entetes-fichier ~/.transcript-access.env
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

UA = "push-library/1.0"


def _artefact(job: sqlite3.Row) -> str:
    """Le texte le plus abouti présent sur le disque.

    L'ordre compte : `review_path` n'est pas une transcription mais la
    liste des passages à vérifier — quelques centaines d'octets là où le
    transcript en fait des dizaines de milliers.
    """
    for colonne in ("enhanced_transcript_path", "transcript_path"):
        brut = job[colonne] if colonne in job.keys() else None
        if not brut:
            continue
        chemin = Path(brut)
        if chemin.exists():
            try:
                return chemin.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return ""


def _poster(url: str, entetes: dict[str, str], charge: dict) -> dict:
    corps = json.dumps(charge, ensure_ascii=False).encode("utf-8")
    requete = urllib.request.Request(url, data=corps, method="POST")
    for cle, valeur in {**entetes, "Content-Type": "application/json",
                        "User-Agent": UA}.items():
        requete.add_header(cle, valeur)
    with urllib.request.urlopen(requete, timeout=120) as reponse:
        return json.loads(reponse.read().decode("utf-8") or "{}")


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--source", required=True, type=Path)
    parseur.add_argument("--serveur", required=True)
    parseur.add_argument("--jeton-fichier", required=True, type=Path,
                         help="fichier contenant le jeton d'API (jamais en argument)")
    parseur.add_argument("--entetes-fichier", type=Path,
                         help="fichier CF_ID=… / CF_SECRET=… pour Cloudflare Access")
    parseur.add_argument("--simulation", action="store_true",
                         help="ne pousse rien, compte seulement")
    args = parseur.parse_args()

    if not args.source.exists():
        print(f"Bibliothèque introuvable : {args.source}", file=sys.stderr)
        return 1

    entetes = {"Authorization": "Bearer " + args.jeton_fichier.read_text().strip()}
    if args.entetes_fichier and args.entetes_fichier.exists():
        for ligne in args.entetes_fichier.read_text().splitlines():
            if ligne.startswith("CF_ID="):
                entetes["CF-Access-Client-Id"] = ligne.split("=", 1)[1].strip()
            elif ligne.startswith("CF_SECRET="):
                entetes["CF-Access-Client-Secret"] = ligne.split("=", 1)[1].strip()

    src = sqlite3.connect(f"file:{args.source}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    url = args.serveur.rstrip("/") + "/api/jobs/import"

    pousses = deja = vides = 0
    for job in src.execute("SELECT * FROM jobs ORDER BY id"):
        transcript = _artefact(job)
        segments = [
            {"start": r["start_time"], "end": r["end_time"],
             "speaker": r["speaker"] or "", "text": r["text"] or ""}
            for r in src.execute(
                "SELECT * FROM transcription_segments WHERE job_id = ? ORDER BY start_time",
                (job["id"],),
            )
        ]
        if not transcript and not segments:
            # Un job de compression seule, ou dont les fichiers ont été
            # effacés : rien à reprendre, et une ligne vide dans la
            # bibliothèque serait pire que son absence.
            vides += 1
            continue

        charge = {
            "filename": Path(job["source_path"] or "").name or f"job-{job['id']}",
            "created_at": job["created_at"],
            "title": job["custom_title"] or "",
            "duration_seconds": max((float(s["end"] or 0) for s in segments), default=0.0),
            "model": job["cloud_model"] or job["transcription_model"] or "",
            "transcript": transcript,
            "speakers": json.loads(job["speaker_map_json"] or "{}"),
            "technical_terms": json.loads(job["technical_terms_json"] or "[]"),
            "cost_usd": float(job["cloud_cost_usd"] or 0),
            "segments": segments,
        }

        if args.simulation:
            pousses += 1
            continue

        for tentative in range(3):
            try:
                vue = _poster(url, entetes, charge)
                pousses += vue.get("imported", False)
                deja += not vue.get("imported", False)
                break
            except urllib.error.HTTPError as exc:
                print(f"  {charge['filename']} : HTTP {exc.code}", file=sys.stderr)
                break
            except urllib.error.URLError as exc:
                # Une reprise de 80 réunions traverse forcément un hoquet
                # réseau ; s'arrêter là obligerait à tout recommencer.
                if tentative == 2:
                    print(f"  {charge['filename']} : {exc.reason}", file=sys.stderr)
                time.sleep(2 * (tentative + 1))

    src.close()
    verbe = "à pousser" if args.simulation else "poussée(s)"
    print(f"{pousses} réunion(s) {verbe}, {deja} déjà présente(s), "
          f"{vides} sans transcription (ignorée(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
