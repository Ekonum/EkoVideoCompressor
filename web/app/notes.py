"""Les transcriptions collées dans Odoo.

Avant transcript, la transcription d'une réunion finissait souvent en note
sur l'opportunité : un accordéon « Transcription complète (cliquer pour
dérouler) », collé à la main depuis l'app macOS, Gemini ou ailleurs. Le
texte existe, la réunion aussi, mais transcript n'en sait rien.

Ce module lit ces notes, les découpe en répliques, et les reconnaît par
leur texte : une transcription déjà dans la bibliothèque — même retouchée,
même transcrite par un autre moteur — ne revient pas une seconde fois.
"""

from __future__ import annotations

import html
import re
import unicodedata
import zlib
from typing import Any

# Ce que porte l'accordéon de toute transcription collée, qu'elle vienne
# de l'app macOS, d'un collage à la main ou de transcript lui-même.
NOTE_MARK = "cliquer pour dérouler"
GENERIC_TITLE = "transcription complète"

# Deux textes sont la même réunion quand l'un reprend au moins ce
# fragment de l'autre. Mesuré sur la base : deux transcriptions d'une même
# réunion par deux moteurs se recouvrent à 30 % et plus, deux réunions
# distinctes à moins de 15 %.
SAME_MEETING = 0.25

_LINE_TAGS = re.compile(r"<(?:br|p|div|li|h\d|tr)\b", re.IGNORECASE)
_TIME = r"\d{1,2}:\d{2}(?::\d{2})?"
# Un nom d'interlocuteur : quelques mots, le premier en capitale, et
# peut-être sa société entre parenthèses — « Robin (Ekonum) ». Un retour à
# la ligne peut séparer les deux : les transcriptions de Gemini sont
# souvent collées avec des lignes de quatre-vingts caractères.
_NAME = r"[A-ZÀ-ÖØ-Þ0-9][\w'’\-]*(?:[ \t][\w'’\-]+){0,3}(?:\s\((?!\d{1,2}:)[^()\n]{1,30}\))?"
# Ce qui précède une réplique : le début d'une ligne, ou la fin d'une
# phrase quand plusieurs répliques partagent une ligne.
_BEFORE = r"(?:^|(?<=[.!?…»\"”)\]*])\s|(?<=[.!?…»\"”)\]*])(?=\s))\s*"


def _mark(name: str) -> re.Pattern[str]:
    """« 00:31 – Robin (Ekonum) : », « [Robin] (00:01:02) »,
    « **Robin** : », « Robin (00:10 - 01:00) : », « Robin [00:31] » seul sur
    sa ligne : les façons d'annoncer une réplique d'un collage à l'autre."""
    return re.compile(
        rf"{_BEFORE}(?:[\[(]?(?P<t1>{_TIME})[\])]?\s*[–-]?\s*)?(?:\*\*)?"
        rf"(?:\[(?P<s1>{name})\]|(?P<s2>{name}))(?:\*\*)?[ \t]*"
        rf"(?:[\[(](?P<t2>{_TIME})(?:\s*[–-]\s*{_TIME})?[\])])?[ \t]*"
        # Le deux-points, ou rien quand un crochet ou un horodatage a
        # déjà annoncé la réplique.
        r"(?::(?=\s|$)|(?(t2)(?=\s|$)|(?(s1)(?=\s|$)|(?!))))",
        re.MULTILINE,
    )


_ANY_MARK = _mark(_NAME)

def split_note(body: str) -> tuple[str, str, str]:
    """En-tête lisible, titre de l'accordéon, et son contenu HTML.

    Le texte d'avant l'accordéon — « Appel du 2 décembre »,
    « Interlocuteurs : … » — dit souvent de quoi il s'agit : il est gardé
    à part, pas mêlé aux répliques."""
    debut = body.find("<details")
    if debut < 0:
        return "", "", ""
    entete = html_text(body[:debut])
    reste = body[debut:]
    titre = ""
    resume = re.search(r"<summary[^>]*>(.*?)</summary>", reste, re.S | re.IGNORECASE)
    if resume:
        titre = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", resume.group(1))).split())
        titre = re.sub(r"\s*\(cliquer pour dérouler\)\s*$", "", titre, flags=re.IGNORECASE)
        reste = reste[resume.end():]
    fin = reste.rfind("</details>")
    contenu = reste[:fin] if fin >= 0 else reste
    # Le cadre de l'accordéon : un <div> en pre-wrap autour du texte.
    cadre = re.match(r"\s*<div[^>]*>(.*)</div>\s*$", contenu, re.S | re.IGNORECASE)
    return entete, titre, cadre.group(1) if cadre else contenu


def html_text(fragment: str) -> str:
    """Le texte d'un fragment de note, une ligne par ligne affichée.

    Deux façons de coller coexistent : du HTML (paragraphes, <br>), où les
    retours à la ligne du source ne comptent pas, et du texte brut dans un
    cadre pre-wrap — celui que transcript dépose — où ils sont les seuls
    séparateurs. Un <pre> garde toujours les siens."""
    morceaux = re.split(r"(<pre\b[^>]*>.*?</pre>)", fragment, flags=re.S | re.IGNORECASE)
    balise = any(_LINE_TAGS.search(m) for m in morceaux if not m.lower().startswith("<pre"))
    sortie = []
    for morceau in morceaux:
        if morceau.lower().startswith("<pre"):
            sortie.append("\n" + re.sub(r"<[^>]+>", "", morceau) + "\n")
            continue
        if balise:
            morceau = re.sub(r"\s*\n\s*", " ", morceau)
        morceau = re.sub(r"<br\s*/?>", "\n", morceau, flags=re.IGNORECASE)
        morceau = re.sub(r"</(?:p|div|li|h\d|tr)>", "\n", morceau, flags=re.IGNORECASE)
        sortie.append(re.sub(r"<[^>]+>", "", morceau))
    texte = html.unescape("".join(sortie)).replace("\xa0", " ").replace("​", "")
    lignes = (" ".join(ligne.split()) for ligne in texte.split("\n"))
    return "\n".join(ligne for ligne in lignes if ligne)


def _seconds(moment: str | None) -> float | None:
    if not moment:
        return None
    parts = [int(p) for p in moment.split(":")]
    total = 0
    for part in parts:
        total = total * 60 + part
    return float(total)


def segments(text: str) -> list[dict[str, Any]]:
    """Les répliques d'une transcription collée.

    Un nom n'est retenu comme interlocuteur que s'il revient — sinon
    « Feedback : » ou « Objet : » deviendrait quelqu'un. Une réplique court
    jusqu'à la suivante, retours à la ligne compris : c'est ce qui défait
    les lignes coupées à quatre-vingts caractères. Ce qui précède la
    première réplique — « Voici la transcription de l'appel… » — reste en
    lignes à part.

    Sans horodatage, toutes les répliques sont à zéro : l'ordre est celui
    du texte."""
    comptes: dict[str, int] = {}
    for trouve in _ANY_MARK.finditer(text):
        nom = " ".join((trouve.group("s1") or trouve.group("s2")).split())
        comptes[nom] = comptes.get(nom, 0) + 1
    valides = sorted(
        (nom for nom, n in comptes.items() if n >= 2 and len(nom.split()) <= 6),
        key=len, reverse=True,
    )
    reperes = []
    if valides:
        motif = "|".join(r"\s+".join(map(re.escape, nom.split())) for nom in valides)
        reperes = list(_mark(f"(?:{motif})").finditer(text))

    repliques: list[dict[str, Any]] = []
    entree = text[:reperes[0].start()] if reperes else text
    suite = False
    for ligne in entree.split("\n"):
        ligne = " ".join(ligne.split())
        if not ligne:
            continue
        if suite:
            repliques[-1]["text"] += " " + ligne
        else:
            repliques.append({"start": 0.0, "end": 0.0, "speaker": "", "text": ligne})
        # Une ligne qui ne finit pas sa phrase est une ligne coupée.
        suite = not re.search(r"[.!?:…»\")]$", ligne)
    dernier = 0.0
    for repere, suivant in zip(reperes, reperes[1:] + [None]):
        instant = _seconds(repere.group("t1") or repere.group("t2"))
        if instant is not None:
            dernier = instant
        dit = text[repere.end():suivant.start() if suivant else len(text)]
        repliques.append({
            "start": dernier, "end": dernier,
            "speaker": " ".join((repere.group("s1") or repere.group("s2")).split()),
            "text": " ".join(dit.replace("**", "").split()),
        })
    repliques = [r for r in repliques if r["text"]]
    for courante, suivante in zip(repliques, repliques[1:]):
        courante["end"] = max(courante["start"], suivante["start"])
    return repliques

def kind(repliques: list[dict[str, Any]], text: str) -> str:
    """« meeting » quand on lit un dialogue ou un long compte rendu,
    « unsure » sinon : une note peut aussi porter un courriel, une
    synthèse, un questionnaire."""
    if not text.strip():
        return "other"
    if re.match(r"(?:from|de|à|to)\s*:", text, re.IGNORECASE):
        return "other"
    voix = {r["speaker"] for r in repliques if r["speaker"]}
    dites = sum(1 for r in repliques if r["speaker"])
    # Un compte rendu dicté seul au sortir d'un rendez-vous compte aussi.
    return "meeting" if (len(voix) >= 2 and dites >= 3) or dites >= 10 else "unsure"


def words(text: str) -> list[str]:
    plie = unicodedata.normalize("NFKD", text.lower())
    plie = "".join(c for c in plie if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", plie)


def fingerprint(text: str, n: int = 6) -> frozenset[int]:
    """L'empreinte d'un texte : ses suites de six mots, un quart d'entre
    elles. Insensible aux horodatages, aux noms d'interlocuteurs reformatés
    et à la mise en page ; un quart suffit à reconnaître une réunion et
    tient la bibliothèque entière en mémoire."""
    mots = words(text)
    empreinte = set()
    for i in range(max(len(mots) - n + 1, 0)):
        valeur = zlib.crc32(" ".join(mots[i:i + n]).encode())
        if valeur % 4 == 0:
            empreinte.add(valeur)
    return frozenset(empreinte)


def overlap(a: frozenset[int], b: frozenset[int]) -> float:
    """La part du plus court des deux textes que l'autre reprend."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def best_match(empreinte: frozenset[int], library: list[dict[str, Any]]) -> dict[str, Any] | None:
    meilleur, score = None, 0.0
    for job in library:
        s = overlap(empreinte, job["fingerprint"])
        if s > score:
            meilleur, score = job, s
    return meilleur if score >= SAME_MEETING else None


def read_note(message: dict[str, Any]) -> dict[str, Any]:
    """Une note d'Odoo, lue : titre, en-tête, texte et répliques."""
    entete, titre, contenu = split_note(str(message.get("body") or ""))
    texte = html_text(contenu)
    repliques = segments(texte)
    fiche = str(message.get("record_name") or "")
    if not titre or titre.lower() == GENERIC_TITLE:
        titre = fiche or "Transcription collée dans Odoo"
    return {
        "title": titre,
        "header": entete,
        "text": texte,
        "segments": repliques,
        "kind": kind(repliques, texte),
        # Les répliques, pas le texte brut : les horodatages couperaient
        # les suites de mots que la bibliothèque, elle, n'a pas.
        "fingerprint": fingerprint("\n".join(f"{r['speaker']} {r['text']}" for r in repliques)),
    }


def author_name(message: dict[str, Any]) -> str:
    """« SAS Ekonum, Robin » → « Robin » : la société ne dit rien ici."""
    auteur = message.get("author_id")
    nom = auteur[1] if isinstance(auteur, list) and len(auteur) > 1 else ""
    return str(nom).split(", ")[-1]
