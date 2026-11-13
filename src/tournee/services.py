"""Règles de la tournée : marquer un passage, et la facturation au passage (F11)."""
from django.db import models, transaction
from django.utils import timezone
from django.utils.formats import date_format

from facturation.models import Contrat, Facture
from tournee.models import Passage


def contrat_au_passage(adresse, quand):
    """Le contrat « au passage » actif qui couvre cette adresse à cette date, s'il y en a un."""
    jour = timezone.localdate(quand)
    qs = Contrat.objects.filter(entreprise_id=adresse.entreprise_id, client_id=adresse.client_id, actif=True,
                                type=Contrat.Type.AU_PASSAGE, saison__debut__lte=jour, saison__fin__gte=jour)
    return qs.filter(adresse=adresse).first() or qs.filter(adresse=None).first()


def _facturer(passage):
    """Une facture par passage (décision de JF, 12 novembre 2026), en brouillon, payable sur réception (délai réglable :
    Entreprise.jours_paiement_passage). À la fin de l'opération, l'écran « Factures des passages » les émet et les
    envoie d'une tape."""
    from datetime import timedelta

    contrat = contrat_au_passage(passage.adresse, passage.heure)
    if contrat is None:
        return
    ent = contrat.entreprise
    jour = timezone.localdate(passage.heure)
    aujourdhui = timezone.localdate()
    f = Facture.objects.create(entreprise_id=contrat.entreprise_id, client_id=contrat.client_id, adresse=passage.adresse, contrat=contrat, a_valider=True,
                               date_facture=min(jour, aujourdhui), date_echeance=min(jour, aujourdhui) + timedelta(days=ent.jours_paiement_passage))
    heure = timezone.localtime(passage.heure)
    desc = f"Déneigement du {date_format(heure, 'j F')} ({passage.operation.get_type_display().lower()}), {passage.adresse.ligne1}"
    passage.ligne_facture = f.lignes.create(description=desc, quantite=1, prix_unitaire=contrat.prix)
    f.recalculer()


def _retirer_de_la_facture(passage):
    """Fait corrigé en Sauté : la facture du passage (encore en brouillon) disparaît."""
    ligne = passage.ligne_facture
    if ligne is not None and ligne.facture.modifiable:
        f = ligne.facture
        passage.ligne_facture = None
        passage.save(update_fields=["ligne_facture"])
        ligne.delete()
        if not f.lignes.exists():
            f.delete()
        else:
            f.recalculer()


def factures_des_passages(entreprise):
    """Brouillons créés par les passages (contrats au passage), à valider après l'opération : entrée bien faite?"""
    return (Facture.objects.filter(entreprise=entreprise, statut=Facture.Statut.BROUILLON, a_valider=True, lignes__passage__isnull=False)
            .distinct().select_related("client", "adresse").order_by("date_facture", "client__nom", "pk"))


def marquer(operation, adresse, statut, raison="", note="", position=None, quand=None):
    """Fait ou sauté. Retaper corrige le passage déjà noté pour cette opération."""
    with transaction.atomic():
        p, cree = Passage.objects.select_for_update().get_or_create(
            operation=operation, adresse=adresse,
            defaults={"entreprise_id": operation.entreprise_id, "statut": statut, "raison": raison, "note": note,
                      "position": position, "heure": quand or timezone.now()})
        if not cree:
            ancien = p.statut
            p.statut, p.raison = statut, (raison if statut == Passage.Statut.SAUTE else "")
            if note:
                p.note = note
            if position is not None:
                p.position = position
            if quand:
                p.heure = quand
            if ancien == Passage.Statut.FAIT and statut != Passage.Statut.FAIT:
                _retirer_de_la_facture(p)
        if statut != Passage.Statut.SAUTE:
            p.raison = ""
        p.full_clean()
        if p.statut == Passage.Statut.FAIT and p.ligne_facture_id is None:
            _facturer(p)
        p.save()
    from communications.avis import aviser_passage_fait

    aviser_passage_fait(p)  # G5, si l'entreprise l'a activé (une fois par opération)
    return p


def factures_en_attente(entreprise, client=None):
    """Factures prêtes, gardées pour un envoi plus tard (passages validés « En attente », jobs à la pièce), hors factures de
    la saison (elles ont leur section) : l'écran central « Factures à envoyer » et la fiche du client."""
    qs = Facture.objects.filter(entreprise=entreprise, statut=Facture.Statut.BROUILLON, a_valider=False, versements__isnull=True)
    qs = qs.filter(models.Q(lignes__passage__isnull=False) | models.Q(jobs__isnull=False))
    if client is not None:
        qs = qs.filter(client=client)
    return qs.distinct().select_related("client", "adresse").order_by("date_facture", "client__nom", "pk")
