"""Nombre de segments d'un texto (ce que Twilio facture).

GSM-7 : 160 caractères pour un segment, 153 par segment au-delà; les caractères de l'extension
(€, [, ], {, }, etc.) comptent double. Un seul caractère hors GSM-7 (ê, â, î, ô, û, ë, œ, emoji...)
fait passer tout le texto en UCS-2 : 70 caractères, 67 par segment au-delà.
"""
import math

GSM7 = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§"
           "¿abcdefghijklmnopqrstuvwxyzäöñüà")
GSM7_EXTENSION = set("^{}\\[~]|€\f")


def compter(texte):
    if not texte:
        return 0
    if all(c in GSM7 or c in GSM7_EXTENSION for c in texte):
        longueur = sum(2 if c in GSM7_EXTENSION else 1 for c in texte)
        return 1 if longueur <= 160 else math.ceil(longueur / 153)
    unites = len(texte.encode("utf-16-le")) // 2
    return 1 if unites <= 70 else math.ceil(unites / 67)


# Longueur permise d'un texto (décision de JF, 11 novembre 2026) : 201 caractères, signature et liens compris,
# soit 3 segments au plus même avec les accents (UCS-2 : 67 x 3). Les accents sont toujours gardés.
LIMITE = 201


def longueur(texte):
    """Caractères comptés comme Twilio (et comme `.length` en JavaScript) : un emoji en vaut deux."""
    return len((texte or "").encode("utf-16-le")) // 2


def trop_long(texte):
    return longueur(texte) > LIMITE


def raison_trop_long(texte):
    return f"Texto trop long : {longueur(texte)} caractères, signature comprise ({LIMITE} au plus)."


def premier_qui_entre(*versions):
    """La première version qui tient dans la limite, sinon la dernière (l'envoi la gardera « Préparé »)."""
    for v in versions:
        if not trop_long(v):
            return v
    return versions[-1]
