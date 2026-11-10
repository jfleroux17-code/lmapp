"""Reçu au client après un paiement (PRD C13, D2) : par son canal préféré, PDF de la facture joint au courriel.

Un seul reçu pour un encaissement réparti sur plusieurs factures (virement Interac, par exemple).
Passe par les garde-fous habituels (interrupteur « envois réels », destinataires du test).
"""
from core.templatetags.dates_qc import date_texte
from django.utils import formats, timezone

from communications import envoi, relances
from communications.models import Gabarit, Genre, Message
from facturation.models import ZERO
from facturation.templatetags.argent import argent


def envoyer_recu(paiements):
    """Retourne les messages créés (aucun si le client n'a ni cellulaire ni courriel)."""
    if not paiements:
        return []
    client = paiements[0].facture.client
    ent = client.entreprise
    total = sum((p.montant for p in paiements), ZERO)
    factures = list(dict.fromkeys(p.facture for p in paiements))
    du = sum((f.solde_du for f in relances.factures_dues(client)), ZERO)
    variables = {
        "client": client.nom_affiche, "montant": argent(total), "mode": paiements[0].get_mode_display().lower(),
        "date": date_texte(paiements[0].date),
        "factures": ", ".join(str(f).replace("Facture n°", "la facture n°").replace("Solde d'ouverture", "le solde antérieur").strip()
                              for f in factures),
        "solde": f"Solde restant à votre compte : {argent(du)}." if du > 0 else "Votre compte est payé au complet.",
    }
    gabarit = Gabarit.texte_pour(ent, Genre.RECU_PAIEMENT)
    try:
        texte = gabarit.format(**variables)
    except (KeyError, IndexError, ValueError):
        texte = gabarit
    texte = f"{texte.strip()}\n\n{ent.signature_messages or ent.nom}"
    messages = []
    for canal in relances.canaux(client):
        courriel = canal == Message.Canal.COURRIEL
        m = Message.objects.create(entreprise=ent, client=client, genre=Genre.RECU_PAIEMENT, canal=canal,
                                   destinataire=client.courriel if courriel else client.cellulaire,
                                   sujet=f"Reçu : paiement de {argent(total)}, {ent.nom}" if courriel else "", contenu=texte)
        if courriel:
            m.factures_jointes.set(factures)
        messages.append(envoi.envoyer(m))
    if any(m.statut == Message.Statut.EN_FILE for m in messages):
        for p in paiements:
            p.recu_envoye_le = timezone.now()
            p.save(update_fields=["recu_envoye_le"])
    return messages
