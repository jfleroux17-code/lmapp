"""Chèques postdatés (PRD D9) : reçus d'avance, comptés comme reçus seulement au dépôt, jamais avant leur date.

Règles :
  - en main : ni paiement ni crédit (l'argent n'est pas encore là); visible dans la fiche et dans /cheques/;
  - déposé (une tape de Louis, à partir de la date du chèque) : paie la facture visée si elle est émise et due
    (surplus en crédit), sinon devient un crédit au compte (mode chèque), appliqué tout de suite à ce qui est dû,
    ou à la prochaine facture émise; compté comme reçu à la date du dépôt;
  - retourné par la banque : le paiement, le crédit et ses applications sont retirés (au journal), la facture
    redevient due;
  - rendu au client : seulement s'il est encore en main.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from facturation import credits
from facturation.models import ZERO, ChequePostdate, Credit, Facture, Paiement

S = ChequePostdate.Statut


def en_main(entreprise):
    return ChequePostdate.objects.filter(entreprise=entreprise, statut=S.EN_MAIN)


def a_deposer(entreprise, jour=None):
    return en_main(entreprise).filter(date_cheque__lte=jour or timezone.localdate())


def en_main_pour(facture):
    """Chèques en main qui paieront cette facture (visée directement, ou par son versement)."""
    from django.db.models import Q

    q = Q(facture=facture) | Q(versement__facture=facture)
    return list(ChequePostdate.objects.filter(q, statut=S.EN_MAIN).order_by("date_cheque"))


def resume(entreprise, jour=None):
    """(nombre à déposer, montant à déposer, nombre en main, montant en main) pour les bandeaux."""
    jour = jour or timezone.localdate()
    tous = en_main(entreprise)
    dus = tous.filter(date_cheque__lte=jour)
    somme = lambda qs: qs.aggregate(s=Sum("montant"))["s"] or ZERO  # noqa: E731
    return {"a_deposer": dus.count(), "a_deposer_montant": somme(dus), "en_main": tous.count(), "en_main_montant": somme(tous)}


def _reference(cheque):
    return f"Chèque n° {cheque.numero}" if cheque.numero else "Chèque postdaté"


def deposer(cheque, jour=None):
    """Le chèque est déposé : il devient de l'argent reçu. Retourne (paiement ou None, crédit ou None)."""
    jour = jour or timezone.localdate()
    with transaction.atomic():
        c = ChequePostdate.objects.select_for_update(of=("self",)).select_related("facture", "versement__facture").get(pk=cheque.pk)
        if c.statut != S.EN_MAIN:
            raise ValidationError(f"Ce chèque est déjà {c.get_statut_display().lower()}.")
        if c.date_cheque > jour:
            raise ValidationError(f"Ce chèque est daté du {c.date_cheque:%d/%m/%Y} : pas déposable avant.")
        f = c.facture_visee
        p = credit = None
        if f is not None and f.statut == Facture.Statut.EMISE and f.solde > 0:
            p, credit = credits.encaisser(f, c.montant, Paiement.Mode.CHEQUE, _reference(c), jour, surplus_permis=True)
        else:
            credit = Credit.objects.create(entreprise=c.entreprise, client=c.client, montant=c.montant, date=jour,
                                           mode=Paiement.Mode.CHEQUE, reference=_reference(c)[:100],
                                           note=f"{_reference(c)} daté du {c.date_cheque:%d/%m/%Y}")
            credits.appliquer(c.client)
        c.statut, c.depose_le, c.paiement, c.credit = S.DEPOSE, jour, p, credit
        c.save(update_fields=["statut", "depose_le", "paiement", "credit", "modifie_le"])
    cheque.refresh_from_db()
    return p, credit


def retourner(cheque, raison=""):
    """Chèque retourné par la banque (sans provision, arrêt de paiement) : l'argent n'est jamais arrivé."""
    with transaction.atomic():
        c = ChequePostdate.objects.select_for_update().get(pk=cheque.pk)
        if c.statut != S.DEPOSE:
            raise ValidationError("Seul un chèque déposé peut être retourné.")
        if c.credit_id:
            Paiement.objects.filter(credit_id=c.credit_id).delete()  # le crédit avait payé d'autres factures
            Credit.objects.filter(pk=c.credit_id).delete()
        if c.paiement_id:
            Paiement.objects.filter(pk=c.paiement_id).delete()
        c.statut, c.paiement, c.credit = S.RETOURNE, None, None
        c.note = (f"Retourné : {raison}" if raison else "Retourné par la banque")[:200]
        c.save(update_fields=["statut", "paiement", "credit", "note", "modifie_le"])
    cheque.refresh_from_db()


def rendre(cheque):
    with transaction.atomic():
        c = ChequePostdate.objects.select_for_update().get(pk=cheque.pk)
        if c.statut != S.EN_MAIN:
            raise ValidationError("Seul un chèque encore en main peut être rendu.")
        c.statut = S.RENDU
        c.save(update_fields=["statut", "modifie_le"])
    cheque.refresh_from_db()


def cibles(client):
    """Ce qu'un nouveau chèque peut payer : versements pas encore payés des contrats actifs (montant taxes
    comprises proposé), factures émises dues. [(valeur, libellé, montant proposé, date proposée)]."""
    from facturation.calculs import taxes

    ent = client.entreprise
    choix = []
    deja = set(ChequePostdate.objects.filter(client=client, statut__in=[S.EN_MAIN, S.DEPOSE]).values_list("versement_id", flat=True))
    listees = set()
    for contrat in client.contrats.filter(actif=True).select_related("saison").prefetch_related("versements__facture"):
        vs = list(contrat.versements.all())
        # Facture de la saison émise : montant de chaque versement taxes comprises, et ce qui est déjà payé
        etat = {}
        for v in vs:
            if v.facture_id and v.facture.statut == Facture.Statut.EMISE and not etat:
                etat = {vv.pk: (m, paye) for vv, m, paye in v.facture.echeancier()}
        for v in vs:
            if v.pk in deja or (v.pk in etat and etat[v.pk][1]):
                continue
            if v.pk in etat:
                total = etat[v.pk][0]
            else:
                total = v.montant + (sum(taxes(v.montant, ent.taux_tps, ent.taux_tvq)) if ent.inscrit_taxes else ZERO)
            listees.add(v.facture_id)
            choix.append((f"v{v.pk}", f"Versement {v.rang} de {len(vs)} ({v.date_prevue:%d/%m/%Y})",
                          total, v.date_prevue))
    for f in Facture.objects.filter(client=client, statut=Facture.Statut.EMISE).a_recevoir().order_by("date_facture"):
        if f.pk in listees:
            continue  # déjà proposée comme versement
        nom = "Solde antérieur" if f.genre == Facture.Genre.SOLDE_OUVERTURE else f"Facture n° {f.numero}"
        choix.append((f"f{f.pk}", f"{nom} ({f.date_facture:%d/%m/%Y}), reste à payer", f.solde_du, timezone.localdate()))
    choix.append(("compte", "Au compte (sans facture précise)", None, None))
    return choix
