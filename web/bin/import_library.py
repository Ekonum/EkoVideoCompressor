#!/usr/bin/env python3
"""Importe la bibliothèque de l'app macOS dans la base du serveur.

Reprise unique, au moment de la bascule. Le script est **idempotent** :
relancé, il ne crée pas de doublon — la reprise d'une bibliothèque de
plusieurs années ne réussit jamais du premier coup, et il faut pouvoir
recommencer sans tout casser.

La base source est ouverte en **lecture seule** : rien ne doit pouvoir
abîmer la bibliothèque de l'utilisateur pendant une migration.

    python3 web/bin/import_library.py \\
        --source ~/Library/Application\\ Support/EkoVideo\\ Compressor/library.db \\
        --destination ./state/ekovideo.db \\
        --owner robin@ekonum.fr
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Database  # noqa: E402


def _ouvrir_source(chemin: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _transcription(job: sqlite3.Row) -> str:
    """Le texte le plus abouti disponible sur le disque.

    Attention à l'ordre : `review_path` n'est **pas** une transcription
    mais la liste des passages à vérifier — quelques centaines
    d'octets là où le transcript en fait des dizaines de milliers. Le
    prendre en premier importerait 82 réunions vidées de leur contenu,
    et le défaut ne se verrait qu'à la lecture.

    Un fichier disparu n'est pas une erreur : la migration doit passer
    même si l'utilisateur a fait le ménage.
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


def importer(source: Path, destination: Path, owner: str) -> dict[str, int]:
    db = Database(destination)
    proprietaire = db.user_id_for_email(owner)
    src = _ouvrir_source(source)

    # Le couple (nom de fichier, date de création) identifie une réunion
    # de façon stable : la base source n'a pas d'identifiant qu'on
    # puisse transposer sans risque de collision avec les jobs créés
    # depuis la webapp.
    with db.connect() as conn:
        deja = {
            (r["filename"], r["created_at"])
            for r in conn.execute("SELECT filename, created_at FROM jobs")
        }

    importes = ignores = segments_total = 0
    for job in src.execute("SELECT * FROM jobs ORDER BY id"):
        nom = Path(job["source_path"] or "").name or f"job-{job['id']}"
        cle = (nom, job["created_at"])
        if cle in deja:
            ignores += 1
            continue

        segments = [
            dict(r)
            for r in src.execute(
                "SELECT * FROM transcription_segments WHERE job_id = ? "
                "ORDER BY start_time",
                (job["id"],),
            )
        ]
        duree = max((float(s["end_time"] or 0) for s in segments), default=0.0)

        with db.connect() as conn:
            curseur = conn.execute(
                "INSERT INTO jobs (owner_id, filename, duration_seconds, model, "
                "language, status, chunk_count, context_json, title, transcript, "
                "speaker_map_json, technical_terms_json, cloud_cost_usd, "
                "previous_versions_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'fr', 'termine', 1, '{}', ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    proprietaire,
                    nom,
                    duree,
                    job["cloud_model"] or job["transcription_model"] or "",
                    job["custom_title"] or "",
                    _transcription(job),
                    job["speaker_map_json"],
                    job["technical_terms_json"],
                    float(job["cloud_cost_usd"] or 0.0),
                    job["previous_versions_json"],
                    job["created_at"],
                    job["updated_at"],
                ),
            )
            nouveau = int(curseur.lastrowid)

        if segments:
            db.replace_segments(
                nouveau,
                [
                    {
                        "start": s["start_time"],
                        "end": s["end_time"],
                        "speaker": s["speaker"],
                        "text": s["text"],
                    }
                    for s in segments
                ],
            )
            segments_total += len(segments)

        # Le vocabulaire de chaque réunion nourrit le glossaire d'équipe :
        # c'est ce qui fait qu'à la bascule les suggestions ne partent pas
        # de zéro.
        try:
            termes = json.loads(job["technical_terms_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            termes = []
        if termes:
            db.record_vocabulary([str(t) for t in termes])

        importes += 1

    src.close()
    return {"importes": importes, "ignores": ignores, "segments": segments_total}


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--source", required=True, type=Path)
    parseur.add_argument("--destination", required=True, type=Path)
    parseur.add_argument("--owner", required=True)
    args = parseur.parse_args()

    if not args.source.exists():
        print(f"Bibliothèque introuvable : {args.source}", file=sys.stderr)
        return 1

    bilan = importer(args.source, args.destination, args.owner)
    print(
        f"{bilan['importes']} réunion(s) importée(s), "
        f"{bilan['ignores']} déjà présente(s), "
        f"{bilan['segments']} segment(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
