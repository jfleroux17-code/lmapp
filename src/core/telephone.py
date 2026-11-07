"""Numéros de téléphone nord-américains, normalisés au format E.164 (+1XXXXXXXXXX).

Twilio envoie le numéro de l'expéditeur d'un texto en E.164; en stockant tous
les numéros des clients sous la même forme, on retrouve le client d'un texto
reçu par simple égalité (PRD E4).
"""
import re

from django.core.exceptions import ValidationError


def normaliser(numero):
    """Retourne le numéro au format +1XXXXXXXXXX, ou '' si vide.

    Accepte les formes courantes : 450-555-1234, (450) 555-1234,
    1 450 555 1234, +1 450.555.1234, 4505551234 poste 12 (le poste est rejeté).
    Lève ValidationError si le numéro n'est pas un numéro nord-américain valide.
    """
    if numero is None:
        return ""
    texte = str(numero).strip()
    if not texte:
        return ""
    if re.search(r"(poste|ext|#|x\s*\d)", texte, re.IGNORECASE):
        raise ValidationError("Pas de numéro de poste dans un numéro de cellulaire : %(n)s", params={"n": texte})
    chiffres = re.sub(r"\D", "", texte)
    if len(chiffres) == 11 and chiffres.startswith("1"):
        chiffres = chiffres[1:]
    if len(chiffres) != 10:
        raise ValidationError("Numéro invalide (10 chiffres attendus) : %(n)s", params={"n": texte})
    # Plan de numérotation nord-américain : indicatif et central ne commencent ni par 0 ni par 1
    if chiffres[0] in "01" or chiffres[3] in "01":
        raise ValidationError("Numéro invalide : %(n)s", params={"n": texte})
    return "+1" + chiffres


def afficher(numero_e164):
    """+14505551234 -> 450 555-1234 (affichage québécois)."""
    if not numero_e164:
        return ""
    c = numero_e164[-10:]
    return f"{c[0:3]} {c[3:6]}-{c[6:10]}"
