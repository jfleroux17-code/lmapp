"""Reçu au client après un paiement (PRD C13, D2) : par son canal préféré, PDF de la facture joint au courriel.

Un seul reçu pour un encaissement réparti sur plusieurs factures (virement Interac, par exemple).
Passe par les garde-fous habituels (interrupteur « envois réels », destinataires du test).
"""
from core.templatetags.dates_qc import date_texte
from django.utils import formats, timezone

from communications import envoi, relances, segments
from communications.models import Gabarit, Genre, Message
from facturation.models import ZERO, Facture
from facturation.templatetags.argent import argent


def envoyer_recu(paiements):
    """Retourne les messages créés (aucun si le client n'a ni cellulaire ni courriel)."""
    if not paiements:
        return []
    client = paiements[0].facture.client
    ent = client.entreprise
    from facturation.models import Credit

    # Ce que le client a remis : la part appliquée aux factures, plus le surplus gardé en crédit (D7)
    surplus = sum((c.montant for c in Credit.objects.filter(paiement__in=paiements)), ZERO)
    total = sum((p.montant for p in paiements), ZERO) + surplus
    mode = paiements[0].get_mode_display()
    mode = mode[:1].lower() + mode[1:]  # « virement Interac », pas « virement interac »
    factures = list(dict.fromkeys(p.facture for p in paiements))
    du = sum((f.solde_du for f in Facture.objects.filter(client=client).a_recevoir()), ZERO)  # tout ce qui reste, versements à venir compris
    variables = {
        "client": client.nom_affiche, "montant": argent(total), "mode": mode,
        "date": date_texte(paiements[0].date),
        "factures": ", ".join(str(f).replace("Facture n°", "la facture n°").replace("Solde d'ouverture", "le solde antérieur").strip()
                              for f in factures),
        "solde": (f"Le surplus de {argent(surplus)} est porté en crédit à votre compte. " if surplus > 0 else "")
                 + (f"Solde restant à votre compte : {argent(du)}." if du > 0 else "Votre compte est payé au complet."),
    }
    gabarit = Gabarit.texte_pour(ent, Genre.RECU_PAIEMENT)
    signature = ent.signature_messages or ent.nom

    def remplir(**v):
        try:
            texte = gabarit.format(**v)
        except (KeyError, IndexError, ValueError):
            texte = gabarit
        return f"{texte.strip()}\n\n{signature}"

    texte = remplir(**variables)
    # Par texto (201 caractères au plus) : date sans l'année, solde en bref. S'il ne tient pas, le minimum avec le
    # solde (le surplus et ce qui reste dû comptent plus que la formule), puis le gabarit sans le solde, puis le minimum
    court = dict(variables, date=date_texte(paiements[0].date, "j F"),
                 solde=(f"Surplus de {argent(surplus)} gardé en crédit. " if surplus > 0 else "")
                       + (f"Solde restant : {argent(du)}." if du > 0 else "Compte payé au complet."))
    texto = segments.premier_qui_entre(remplir(**court),
                                       f"Paiement de {argent(total)} reçu le {court['date']}. {court['solde']} Merci!\n{signature}",
                                       remplir(**dict(court, solde="")),
                                       f"Paiement de {argent(total)} reçu le {court['date']}. Merci!\n{signature}")
    messages = []
    for canal in relances.canaux(client):
        courriel = canal == Message.Canal.COURRIEL
        m = Message.objects.create(entreprise=ent, client=client, genre=Genre.RECU_PAIEMENT, canal=canal,
                                   destinataire=client.courriel if courriel else client.cellulaire,
                                   sujet=f"Reçu : paiement de {argent(total)}, {ent.nom}" if courriel else "",
                                   contenu=texte if courriel else texto)
        if courriel:
            m.factures_jointes.set(factures)
        messages.append(envoi.envoyer(m))
    if any(m.statut == Message.Statut.EN_FILE for m in messages):
        for p in paiements:
            p.recu_envoye_le = timezone.now()
            p.save(update_fields=["recu_envoye_le"])
    return messages
