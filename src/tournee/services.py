"""Règles de la tournée : marquer un passage, et la facturation au passage (F11)."""
from django.db import transaction
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
    """Ajoute le passage à la facture brouillon du contrat (une facture qui s'allonge pendant le mois)."""
    contrat = contrat_au_passage(passage.adresse, passage.heure)
    if contrat is None:
        return
    f = (Facture.objects.filter(entreprise_id=contrat.entreprise_id, contrat=contrat, statut=Facture.Statut.BROUILLON).first()
         or Facture.objects.create(entreprise_id=contrat.entreprise_id, client_id=contrat.client_id, adresse=passage.adresse, contrat=contrat))
    heure = timezone.localtime(passage.heure)
    desc = f"Passage du {date_format(heure, 'j F')} ({passage.operation.get_type_display().lower()})"
    passage.ligne_facture = f.lignes.create(description=desc, quantite=1, prix_unitaire=contrat.prix, ordre=f.lignes.count())
    f.recalculer()


def _retirer_de_la_facture(passage):
    ligne = passage.ligne_facture
    if ligne is not None and ligne.facture.modifiable:
        f = ligne.facture
        passage.ligne_facture = None
        ligne.delete()
        f.recalculer()


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
