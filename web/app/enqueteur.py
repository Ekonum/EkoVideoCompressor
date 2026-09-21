"""L'enquêteur : quel dossier Odoo cette réunion concerne-t-elle ?

La sonde entend des noms ; elle ne sait pas encore à quoi ils
correspondent. L'enquêteur, lui, a le droit de chercher dans Odoo, de
lire une fiche, de se raviser et de chercher autrement — jusqu'à
pouvoir répondre ou renoncer.

**Pourquoi une boucle plutôt qu'un seul appel.** Une réunion « Acritec »
peut concerner une opportunité, un chantier en cours ou un devis signé,
et le bon dossier ne se reconnaît qu'en regardant ce qu'il contient. Se
tromper dépose la transcription chez quelqu'un d'autre, sous les yeux de
toute l'équipe : mieux vaut trois recherches de plus qu'une erreur.

**Renoncer est une réponse.** Sans certitude, l'enquêteur conclut sans
dossier et la personne choisit à la main. C'est le comportement
attendu, pas un échec.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from cloud_transcription import (
    CloudTranscriptionError,
    CloudUsage,
    GeminiClient,
    canonical_cloud_model_id,
    compute_cost_usd,
)

log = logging.getLogger("ekovideo.web")

# Le modèle qui raisonne n'est pas celui qui écoute : ici on paie pour
# du jugement, pas pour de la transcription. Lier au mauvais dossier
# coûte bien plus cher que quelques milliers de jetons.
MODELE_ENQUETE = "gemini-3.8-flash"

# Assez de tours pour chercher deux ou trois pistes et en vérifier une ;
# assez peu pour qu'une boucle folle reste sans conséquence.
TOURS_MAX = 8

SYSTEME = """Tu retrouves, dans Odoo, le dossier dont une réunion parle.

Tu disposes d'outils : cherche, lis, recoupe. Ne conclus pas sur un nom
qui ressemble — vérifie que le contenu du dossier correspond à ce qui a
été dit.

Méthode : cherche chaque société entendue ; si plusieurs dossiers
sortent, lis-les avant de choisir ; si rien ne sort, cherche les
personnes, puis les mots du sujet. Un dossier récemment actif est plus
probable qu'un dossier dormant, mais ce n'est qu'un indice.

Conclus avec `conclure`. Sans certitude, conclus sans dossier : la
personne choisira. Une erreur de liaison dépose la transcription chez
un autre client, c'est le pire résultat possible."""

OUTILS = [
    {
        "name": "chercher",
        "description": (
            "Cherche dans Odoo par nom de dossier ou nom de client. "
            "Modèles : crm.lead (opportunité), sale.order (devis), "
            "project.project (projet), project.task (tâche)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "terme": {"type": "string"},
                "modeles": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["terme"],
        },
    },
    {
        "name": "lire",
        "description": (
            "Lit un dossier : son nom, son client et ses trois derniers "
            "messages de chatter. Sert à vérifier avant de conclure."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "modele": {"type": "string"},
                "record_id": {"type": "integer"},
            },
            "required": ["modele", "record_id"],
        },
    },
    {
        "name": "conclure",
        "description": (
            "Rend le dossier retenu, ou aucun si le doute subsiste."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "modele": {"type": "string"},
                "record_id": {"type": "integer"},
                "confiance": {
                    "type": "string",
                    "enum": ["certaine", "probable", "incertaine", "aucune"],
                },
                "raison": {"type": "string"},
                "autres": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "modele": {"type": "string"},
                            "record_id": {"type": "integer"},
                            "raison": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["confiance", "raison"],
        },
    },
]


@dataclass(slots=True)
class Conclusion:
    """Ce que l'enquêteur a retenu, et comment il y est arrivé."""

    dossier: dict[str, Any] | None = None
    confiance: str = "aucune"
    raison: str = ""
    autres: list[dict[str, Any]] = field(default_factory=list)
    journal: list[str] = field(default_factory=list)
    usage: CloudUsage = field(default_factory=CloudUsage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record": self.dossier,
            "confidence": self.confiance,
            "reason": self.raison,
            "others": self.autres,
            # Le journal se montre : une proposition qu'on ne peut pas
            # contredire est une proposition qu'on ne peut pas refuser.
            "trace": self.journal,
        }


def _appels(payload: dict) -> list[dict]:
    candidats = payload.get("candidates") or []
    if not candidats:
        return []
    parts = (candidats[0].get("content") or {}).get("parts") or []
    return [p["functionCall"] for p in parts if isinstance(p.get("functionCall"), dict)]


def _texte(payload: dict) -> str:
    candidats = payload.get("candidates") or []
    if not candidats:
        return ""
    parts = (candidats[0].get("content") or {}).get("parts") or []
    return " ".join(str(p.get("text") or "") for p in parts).strip()


def _cumuler(usage: CloudUsage, payload: dict, model_id: str) -> None:
    meta = payload.get("usageMetadata") or {}
    entree = int(meta.get("promptTokenCount") or 0)
    sortie = int(meta.get("candidatesTokenCount") or 0) + int(
        meta.get("thoughtsTokenCount") or 0
    )
    usage.add(
        CloudUsage(
            model=canonical_cloud_model_id(model_id),
            input_tokens=entree,
            output_tokens=sortie,
            cost_usd=compute_cost_usd(model_id, entree, sortie),
        )
    )


def enqueter(
    indices: dict[str, Any],
    *,
    chercher: Callable[[str, list[str] | None], list[dict]],
    lire: Callable[[str, int], dict],
    api_key: str,
    model_id: str = MODELE_ENQUETE,
    tours_max: int = TOURS_MAX,
    opener: Callable[..., Any] | None = None,
) -> Conclusion:
    """Mène l'enquête et rend une conclusion.

    `chercher` et `lire` sont injectés : ils portent la clé Odoo *de la
    personne*, et l'enquêteur ne voit jamais rien qu'elle ne verrait
    pas elle-même.
    """
    client = GeminiClient(api_key, opener=opener)
    usage = CloudUsage()
    journal: list[str] = []
    contents: list[dict] = [
        {
            "role": "user",
            "parts": [
                {
                    "text": (
                        "Voici ce qu'on a entendu au début de la réunion :\n"
                        f"- sociétés : {', '.join(indices.get('organisations') or []) or '—'}\n"
                        f"- personnes : {', '.join(indices.get('personnes') or []) or '—'}\n"
                        f"- sujets : {', '.join(indices.get('sujets') or []) or '—'}\n"
                        f"- autres orthographes possibles : "
                        f"{', '.join(indices.get('variantes') or []) or '—'}\n"
                        f"- résumé : {indices.get('resume') or '—'}\n\n"
                        "Quel dossier Odoo ?"
                    )
                }
            ],
        }
    ]

    for tour in range(tours_max):
        reponse = client.generate_with_tools(
            model_id=model_id, contents=contents, tools=OUTILS, system=SYSTEME
        )
        _cumuler(usage, reponse, model_id)
        appels = _appels(reponse)
        if not appels:
            # Le modèle a répondu en prose : on prend ce qu'il dit comme
            # un renoncement motivé plutôt que d'insister.
            return Conclusion(
                raison=_texte(reponse) or "Aucun dossier proposé.",
                journal=journal,
                usage=usage,
            )

        contents.append({"role": "model", "parts": [{"functionCall": a} for a in appels]})
        reponses: list[dict] = []
        for appel in appels:
            nom = appel.get("name") or ""
            args = appel.get("args") or {}
            if nom == "conclure":
                return _conclure(args, lire, journal, usage)
            resultat, ligne = _executer(nom, args, chercher, lire)
            journal.append(ligne)
            reponses.append(
                {"functionResponse": {"name": nom, "response": {"resultat": resultat}}}
            )
        contents.append({"role": "user", "parts": reponses})

    journal.append(f"Arrêt après {tours_max} tours sans conclusion.")
    return Conclusion(
        raison="L'enquête n'a pas abouti dans le temps imparti.",
        journal=journal,
        usage=usage,
    )


def _executer(
    nom: str,
    args: dict,
    chercher: Callable[[str, list[str] | None], list[dict]],
    lire: Callable[[str, int], dict],
) -> tuple[Any, str]:
    """Exécute un outil. Une panne Odoo se raconte au modèle au lieu de
    remonter : il peut alors changer de piste plutôt que tout perdre."""
    try:
        if nom == "chercher":
            terme = str(args.get("terme") or "").strip()
            lignes = chercher(terme, args.get("modeles"))
            return lignes, f"cherché « {terme} » → {len(lignes)} dossier(s)"
        if nom == "lire":
            modele = str(args.get("modele") or "")
            record_id = int(args.get("record_id") or 0)
            fiche = lire(modele, record_id)
            return fiche, f"lu {modele} {record_id} — {fiche.get('name', '')}"
    except Exception as exc:  # noqa: BLE001 — raconté au modèle, pas avalé
        log.warning("outil %s en échec : %s", nom, exc)
        return {"erreur": str(exc)}, f"{nom} en échec : {exc}"
    return {"erreur": f"outil inconnu : {nom}"}, f"outil inconnu : {nom}"


def _conclure(
    args: dict,
    lire: Callable[[str, int], dict],
    journal: list[str],
    usage: CloudUsage,
) -> Conclusion:
    confiance = str(args.get("confiance") or "aucune")
    modele = str(args.get("modele") or "")
    record_id = int(args.get("record_id") or 0)
    dossier: dict[str, Any] | None = None
    if modele and record_id and confiance != "aucune":
        try:
            dossier = lire(modele, record_id)
        except Exception as exc:  # noqa: BLE001
            # Conclure sur un dossier illisible n'a pas de sens : mieux
            # vaut rendre la main.
            journal.append(f"dossier retenu illisible : {exc}")
            confiance = "aucune"
    journal.append(f"conclusion {confiance} — {args.get('raison') or ''}")
    return Conclusion(
        dossier=dossier,
        confiance=confiance if dossier else "aucune",
        raison=str(args.get("raison") or ""),
        autres=[a for a in (args.get("autres") or []) if isinstance(a, dict)],
        journal=journal,
        usage=usage,
    )


def json_compact(valeur: Any, limite: int = 4000) -> str:
    """Utilitaire de journalisation : ce qu'on a envoyé, borné."""
    texte = json.dumps(valeur, ensure_ascii=False)
    return texte if len(texte) <= limite else texte[:limite] + "…"
