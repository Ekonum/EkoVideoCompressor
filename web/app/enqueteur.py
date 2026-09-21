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

# Assez de tours pour chercher plusieurs pistes et en vérifier une ;
# assez peu pour qu'une boucle folle reste sans conséquence. Le dernier
# tour est réservé à la conclusion, quoi qu'il arrive.
TOURS_MAX = 10

SYSTEME = """Tu retrouves, dans Odoo, le dossier dont une réunion parle.

Tu disposes d'outils : cherche, lis, recoupe. Ne conclus pas sur un nom
qui ressemble — vérifie que le contenu du dossier correspond à ce qui a
été dit.

Méthode : cherche chaque société entendue ; si plusieurs dossiers
sortent, lis-les avant de choisir ; si rien ne sort, essaie les autres
orthographes, puis les personnes. Un dossier récemment actif est plus
probable qu'un dossier dormant, mais ce n'est qu'un indice.

Ne cherche pas de mots génériques — « facture », « commande », « projet »
sortent dans tous les dossiers et n'en désignent aucun.

À pertinence égale, préfère l'opportunité : c'est là que l'équipe suit
un client. Et cite toujours dans `autres` les dossiers que tu as
sérieusement envisagés — c'est ce qui permet de te corriger d'un clic
sans relancer une enquête.

Tes tours sont comptés : on te dit combien il t'en reste. Conclus avec
`conclure` avant la fin — sans certitude, conclus sans dossier, la
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
            "Rend le dossier retenu, ou aucun si le doute subsiste. "
            "`autres` porte les dossiers sérieusement envisagés."
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


def _tour_du_modele(payload: dict) -> dict:
    """Le tour du modèle, **tel quel**.

    Gemini 3 signe ses raisonnements (`thoughtSignature`) et refuse le
    tour suivant si la signature ne lui revient pas. Reconstruire les
    parties à partir des seuls appels de fonction, c'est perdre la
    signature — et se faire refuser en HTTP 400.
    """
    candidats = payload.get("candidates") or []
    if not candidats:
        return {"role": "model", "parts": []}
    contenu = dict(candidats[0].get("content") or {})
    contenu.setdefault("role", "model")
    return contenu


def _appels(payload: dict) -> list[dict]:
    parts = _tour_du_modele(payload).get("parts") or []
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
    memoire: dict[str, Any] = {}
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
        # Le dernier tour ne propose plus que `conclure` : un modèle qui
        # enquête encore à la fin rendrait la main sans rien dire, alors
        # qu'il a déjà tout lu.
        dernier = tour == tours_max - 1
        outils = [o for o in OUTILS if o["name"] == "conclure"] if dernier else OUTILS
        if dernier:
            contents.append({
                "role": "user",
                "parts": [{"text": "Dernier tour : conclus maintenant, avec ce "
                                   "que tu as. Sans certitude, conclus sans dossier."}],
            })
        reponse = client.generate_with_tools(
            model_id=model_id, contents=contents, tools=outils, system=SYSTEME
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

        contents.append(_tour_du_modele(reponse))
        reponses: list[dict] = []
        for appel in appels:
            nom = appel.get("name") or ""
            args = appel.get("args") or {}
            if nom == "conclure":
                return _conclure(args, lire, journal, usage)
            resultat, ligne = _executer(nom, args, chercher, lire, memoire)
            journal.append(ligne)
            reponses.append(
                {"functionResponse": {"name": nom, "response": {"resultat": resultat}}}
            )
        # Rôle « user » : côté Gemini, une réponse d'outil vient de
        # l'appelant, pas du modèle.
        restants = tours_max - tour - 1
        reponses.append({"text": f"Il te reste {restants} tour(s) avant de devoir conclure."})
        # Rôle « user » : côté Gemini, une réponse d'outil vient de
        # l'appelant, pas du modèle.
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
    memoire: dict[str, Any] | None = None,
) -> tuple[Any, str]:
    """Exécute un outil. Une panne Odoo se raconte au modèle au lieu de
    remonter : il peut alors changer de piste plutôt que tout perdre."""
    cache = memoire if memoire is not None else {}
    try:
        if nom == "chercher":
            terme = str(args.get("terme") or "").strip()
            cle = f"chercher:{terme.lower()}:{','.join(args.get('modeles') or [])}"
            if cle in cache:
                # Répéter une recherche coûte un tour et n'apprend rien :
                # on rend le résultat connu en le disant.
                return (
                    {"deja_cherche": True, "resultat": cache[cle]},
                    f"« {terme} » déjà cherché",
                )
            lignes = chercher(terme, args.get("modeles"))
            cache[cle] = lignes
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
    limite_autres: int = 3,
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
    # Les alternatives sont relues pour être affichables : une
    # proposition qu'on ne peut corriger qu'en relançant une enquête
    # n'est pas vraiment corrigeable.
    autres: list[dict[str, Any]] = []
    for autre in (args.get("autres") or [])[:limite_autres]:
        if not isinstance(autre, dict):
            continue
        try:
            fiche = lire(str(autre.get("modele") or ""), int(autre.get("record_id") or 0))
        except Exception as exc:  # noqa: BLE001
            journal.append(f"alternative illisible : {exc}")
            continue
        if dossier and fiche.get("id") == dossier.get("id") \
                and fiche.get("model") == dossier.get("model"):
            continue
        autres.append({**fiche, "reason": str(autre.get("raison") or "")})

    journal.append(f"conclusion {confiance} — {args.get('raison') or ''}")
    return Conclusion(
        dossier=dossier,
        confiance=confiance if dossier else "aucune",
        raison=str(args.get("raison") or ""),
        autres=autres,
        journal=journal,
        usage=usage,
    )


def json_compact(valeur: Any, limite: int = 4000) -> str:
    """Utilitaire de journalisation : ce qu'on a envoyé, borné."""
    texte = json.dumps(valeur, ensure_ascii=False)
    return texte if len(texte) <= limite else texte[:limite] + "…"
