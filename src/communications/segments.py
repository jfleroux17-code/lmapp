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
