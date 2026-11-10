"""Écrans de Louis pour l'argent (PRD C1, C7, D1 à D4) : factures et paiements au cellulaire.

Tout passe par les méthodes de facturation.models, qui gardent les règles
(numéro à l'émission, facture émise figée, pas de trop-perçu). Les actions sont
des POST suivis d'une redirection, avec un message de confirmation.
"""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from clients.models import Client
from core import telephone
from core.acces import ecriture_requise, membre_requis, peut_ecrire, peut_modifier_clients
from facturation.models import Facture, LigneFacture, Paiement, Service

ZERO = Decimal("0.00")


class MontantField(forms.DecimalField):
    """Accepte « 158,69 », « 158.69 », « 1 200 $ »."""

    def to_python(self, value):
        if isinstance(value, str):
            value = value.replace("$", "").replace(" ", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
        return super().to_python(value)


class LigneForm(forms.Form):
    service = forms.IntegerField(required=False, widget=forms.HiddenInput)
    description = forms.CharField(max_length=200, error_messages={"required": "Écrire ce qui est facturé."})
    quantite = MontantField(max_digits=8, decimal_places=2, min_value=Decimal("0.01"), initial=1)
    prix = MontantField(max_digits=10, decimal_places=2, min_value=ZERO, error_messages={"required": "Indiquer le prix."})


class PaiementForm(forms.Form):
    mode = forms.ChoiceField(choices=Paiement.MODES_RECUS, error_messages={"required": "Choisir le mode de paiement."})
    montant = MontantField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    reference = forms.CharField(max_length=100, required=False)
    date = forms.DateField(required=False)
    recu = forms.BooleanField(required=False)
    surplus = forms.BooleanField(required=False)


def _facture(request, pk):
    return get_object_or_404(Facture.objects.select_related("client", "adresse", "contrat__saison"), pk=pk, entreprise=request.entreprise)


def _services(request):
    return Service.objects.filter(entreprise=request.entreprise, actif=True)


def _ajouter_ligne(facture, form, entreprise):
    d = form.cleaned_data
    service = Service.objects.filter(pk=d.get("service"), entreprise=entreprise).first() if d.get("service") else None
    facture.lignes.create(service=service, description=d["description"], quantite=d["quantite"], prix_unitaire=d["prix"],
                          taxable=service.taxable if service else True, ordre=facture.lignes.count())
    facture.recalculer()


@membre_requis
def nouvelle_facture(request, client_pk):
    client = get_object_or_404(Client, pk=client_pk, entreprise=request.entreprise)
    form = LigneForm(request.POST or None)
    if request.method == "POST":
        if not peut_ecrire(request):
            return render(request, "terrain/refuse.html", {"message": "Ton compte est en lecture seule : tu peux consulter, pas modifier."}, status=403)
        if form.is_valid():
            with transaction.atomic():
                f = Facture.objects.create(entreprise=request.entreprise, client=client,
                                           adresse=client.adresses.filter(active=True).first())
                _ajouter_ligne(f, form, request.entreprise)
            return redirect("terrain:facture", pk=f.pk)
    return render(request, "terrain/argent/nouvelle_facture.html", {"client": client, "form": form, "services": _services(request)})


@membre_requis
def facture(request, pk):
    f = _facture(request, pk)
    contexte = {
        "f": f, "client": f.client, "lignes": f.lignes.all(), "paiements": f.paiements.order_by("date", "pk"),
        "ecriture": peut_ecrire(request), "services": _services(request),
        "form_ligne": LigneForm(), "form_paiement": PaiementForm(initial={"montant": f.solde}),
        "modes": Paiement.MODES_RECUS, "aujourdhui": timezone.localdate(),
        "envois": f.messages.order_by("-cree_le")[:5],
        "cellulaire": telephone.afficher(f.client.cellulaire),
        "cheques": _cheques_en_main_pour(f),
    }
    return render(request, "terrain/argent/facture.html", contexte)


def _cheques_en_main_pour(f):
    from facturation.cheques import en_main_pour

    return en_main_pour(f)


def _brouillon_ou_erreur(request, f):
    if not f.modifiable:
        messages.error(request, "Cette facture est déjà émise : elle ne change plus.")
        return False
    return True


@require_POST
@ecriture_requise
def ajouter_ligne(request, pk):
    f = _facture(request, pk)
    if _brouillon_ou_erreur(request, f):
        form = LigneForm(request.POST)
        if form.is_valid():
            _ajouter_ligne(f, form, request.entreprise)
            messages.success(request, "Ligne ajoutée.")
        else:
            messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
    return redirect("terrain:facture", pk=f.pk)


@require_POST
@ecriture_requise
def retirer_ligne(request, pk, ligne_pk):
    f = _facture(request, pk)
    if _brouillon_ou_erreur(request, f):
        LigneFacture.objects.filter(pk=ligne_pk, facture=f).delete()
        f.recalculer()
        messages.success(request, "Ligne retirée.")
    return redirect("terrain:facture", pk=f.pk)


@require_POST
@ecriture_requise
def emettre(request, pk):
    f = _facture(request, pk)
    try:
        f.emettre()
        messages.success(request, f"Facture n° {f.numero} émise." if f.numero else "Solde émis.")
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    return redirect("terrain:facture", pk=f.pk)


@require_POST
@ecriture_requise
def supprimer_brouillon(request, pk):
    f = _facture(request, pk)
    client = f.client
    if _brouillon_ou_erreur(request, f):
        f.delete()
        messages.success(request, "Brouillon supprimé.")
        return redirect("terrain:fiche", pk=client.pk)
    return redirect("terrain:facture", pk=f.pk)


@require_POST
@ecriture_requise
def annuler(request, pk):
    f = _facture(request, pk)
    try:
        f.annuler(request.POST.get("raison", ""))
        messages.success(request, f"Facture n° {f.numero} annulée.")
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    return redirect("terrain:facture", pk=f.pk)


@require_POST
@ecriture_requise
def paiement(request, pk):
    f = _facture(request, pk)
    form = PaiementForm(request.POST)
    if not form.is_valid():
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
        return redirect("terrain:facture", pk=f.pk)
    d = form.cleaned_data
    # Double tape (réseau lent, gants) : le même paiement il y a moins d'une minute n'est pas enregistré deux fois
    if f.paiements.filter(montant=d["montant"], mode=d["mode"], cree_le__gte=timezone.now() - timedelta(minutes=1)).exists():
        messages.info(request, "Ce paiement est déjà enregistré.")
        return redirect("terrain:facture", pk=f.pk)
    from facturation import credits

    try:
        p, credit = credits.encaisser(f, d["montant"], d["mode"], d["reference"], d["date"], surplus_permis=d.get("surplus"))
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
        return redirect("terrain:facture", pk=f.pk)
    from facturation.templatetags.argent import argent
    reste = f.solde
    messages.success(request, f"{dict(Paiement.Mode.choices)[d['mode']]} de {argent(d['montant'])} enregistré. "
                              + ("Facture payée au complet." if reste <= 0 else f"Reste {argent(reste)}.")
                              + (f" Surplus de {argent(credit.montant)} gardé en crédit au compte"
                                 + (f" (reste {argent(credit.restant)} pour les prochaines factures)." if credit.restant > 0 else ", appliqué aux autres factures dues.")
                                 if credit else ""))
    recu_parti = _annoncer_recu(request, [p]) if d.get("recu") and p else False
    # Confirmation verte plein écran 2 secondes, puis la fiche du client avec son nouveau solde (audit UX)
    request.session["confirmation_paiement"] = {
        "titre": "Payée" if reste <= 0 else f"Reçu {argent(d['montant'])}",
        "detail": f"{dict(Paiement.Mode.choices)[d['mode']]}" + (" · reçu envoyé" if recu_parti else "")
                  + ("" if reste <= 0 else f" · reste {argent(reste)}"),
    }
    return redirect("terrain:fiche", pk=f.client_id)


def _annoncer_recu(request, paiements):
    """Envoie le reçu (C13) et dit à Louis s'il est parti. Renvoie vrai s'il est parti."""
    from communications.recus import envoyer_recu

    envoyes = envoyer_recu(paiements)
    partis = [m.destinataire for m in envoyes if m.statut == m.Statut.EN_FILE]
    if partis:
        messages.info(request, "Reçu en route : " + ", ".join(partis) + ".")
    elif envoyes:
        messages.info(request, f"Reçu pas envoyé : {envoyes[0].erreur}")
    return bool(partis)


@membre_requis
def factures(request):
    """Brouillons à émettre et factures émises récentes."""
    qs = Facture.objects.filter(entreprise=request.entreprise).select_related("client").avec_solde()
    return render(request, "terrain/argent/factures.html", {
        "brouillons": qs.filter(statut=Facture.Statut.BROUILLON).order_by("date_facture", "pk"),
        "versements_prets": _versements_prets(request.entreprise).count(),
        "recentes": qs.exclude(statut=Facture.Statut.BROUILLON).order_by("-date_facture", "-pk")[:50],
    })


@membre_requis
def comptes(request):
    """Comptes à recevoir (C7, J4) : qui doit quoi, depuis quand. Tri par montant ou par ancienneté."""
    aujourdhui = timezone.localdate()
    dues = Facture.objects.filter(entreprise=request.entreprise).a_recevoir()
    par_client = {}
    for f in dues.select_related("client").order_by("date_facture"):
        c = par_client.setdefault(f.client_id, {"client": f.client, "du": ZERO, "factures": 0, "depuis": f.date_facture})
        c["du"] += f.solde_du
        c["factures"] += 1
    lignes = list(par_client.values())
    from communications.relances import dernieres

    relances = dernieres(par_client.keys())
    for l in lignes:
        l["jours"] = max((aujourdhui - l["depuis"]).days, 0)
        l["relance"] = relances.get(l["client"].pk)
    tri = request.GET.get("tri", "anciennete")
    lignes.sort(key=(lambda l: -l["du"]) if tri == "montant" else (lambda l: l["depuis"]))
    from facturation import credits

    encaisse_30j = credits.encaisse(request.entreprise, date__gt=aujourdhui - timedelta(days=30))
    return render(request, "terrain/argent/comptes.html", {
        "saison": _bilan_saison(request.entreprise),
        "lignes": lignes, "tri": tri, "total": sum((l["du"] for l in lignes), ZERO),
        "plus_de_60": sum((l["du"] for l in lignes if l["jours"] > 60), ZERO),
        "encaisse_30j": encaisse_30j,
        "brouillons": Facture.objects.filter(entreprise=request.entreprise, statut=Facture.Statut.BROUILLON).count(),
        "modifier_clients": peut_modifier_clients(request),
        "relances_pretes": _relances_pretes(request.entreprise),
        "versements_prets": _versements_prets(request.entreprise).count(),
        "cheques": _cheques(request.entreprise),
    })


def _cheques(entreprise):
    from facturation import cheques

    return cheques.resume(entreprise)


def _relances_pretes(entreprise):
    if not entreprise.relances_proposees:
        return None
    from communications.relances_proposees import proposees

    return len(proposees(entreprise))


def resume_client(client):
    """Pour la fiche client : solde dû et dernières factures."""
    from communications import relances
    from communications.models import Message

    qs = client.factures.avec_solde().order_by("-date_facture", "-pk")
    dues = relances.factures_dues(client)
    from facturation.credits import credit_restant

    from facturation.models import ChequePostdate

    resume = {"du": sum((f.solde_du for f in dues), ZERO), "factures_client": qs[:10], "credit": credit_restant(client),
              "cheques_client": client.cheques.filter(statut=ChequePostdate.Statut.EN_MAIN)
              .select_related("facture", "versement__contrat__saison").order_by("date_cheque"),
              "contrats": client.contrats.filter(actif=True).select_related("saison").prefetch_related("versements").order_by("-saison__debut")[:2]}
    if dues:
        resume.update({"nb_dues": len(dues), "plus_vieille": dues[0],
                       "jours_plus_vieille": (timezone.localdate() - dues[0].date_facture).days})
        niveau = relances.niveau_suivant(client, dues)
        resume["relance"] = {
            "niveau": niveau, "niveaux": [(n, g.label) for n, g in enumerate(relances.RELANCES, start=1)],
            "canaux": " et ".join(dict(Message.Canal.choices)[c].lower() for c in relances.canaux(client)),
            "historique": Message.objects.filter(client=client, genre__in=relances.RELANCES).order_by("-cree_le")[:5],
        }
    return resume


@require_POST
@ecriture_requise
def envoyer_facture(request, pk):
    """Envoi de la facture au client (C4) : par courriel, PDF joint, ou par texto, avec le lien de la facture (L1).
    Le worker envoie; le statut paraît sur la facture."""
    from communications.factures import envoyer_facture as envoyer
    from communications.models import Message

    f = _facture(request, pk)
    canal = Message.Canal.TEXTO if request.POST.get("canal") == "texto" else Message.Canal.COURRIEL
    try:
        m = envoyer(f, canal)
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
        return redirect("terrain:facture", pk=f.pk)
    if m.statut == m.Statut.EN_FILE:
        messages.success(request, f"Facture en route vers {m.destinataire}.")
    else:
        messages.error(request, f"{m.get_statut_display()} : {m.erreur}")
    return redirect("terrain:facture", pk=f.pk)


@require_POST
@ecriture_requise
def relancer(request, client_pk):
    """Relance du client (C8) : tout ce qu'il doit, au niveau proposé ou choisi, par son canal préféré."""
    from communications import relances

    client = get_object_or_404(Client, pk=client_pk, entreprise=request.entreprise)
    niveau = request.POST.get("niveau", "")
    try:
        envoyes = relances.relancer(client, int(niveau) if niveau.isdigit() else None)
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
        return redirect("terrain:fiche", pk=client.pk)
    partis = [m for m in envoyes if m.statut == m.Statut.EN_FILE]
    if partis:
        messages.success(request, f"{envoyes[0].get_genre_display()} en route : " + ", ".join(m.destinataire for m in partis) + ".")
    for m in envoyes:
        if m not in partis:
            messages.error(request, f"{m.get_canal_display()} pas envoyé : {m.erreur}")
    return redirect("terrain:fiche", pk=client.pk)


@membre_requis
def relances_a_envoyer(request):
    """C9 : les relances dues aujourd'hui, toutes cochées; le déneigeur décoche ce qu'il ne veut pas et envoie."""
    from communications.relances_proposees import proposees

    return render(request, "terrain/argent/relances.html", {
        "propositions": proposees(request.entreprise), "actif": request.entreprise.relances_proposees,
        "ecriture": peut_ecrire(request),
    })


@require_POST
@ecriture_requise
def envoyer_relances(request):
    """Envoie les relances cochées. La liste est recalculée : un client qui a payé entre-temps est sauté."""
    from communications import relances
    from communications.relances_proposees import proposees

    cochees = set(request.POST.getlist("client"))
    partis, problemes = 0, []
    for p in proposees(request.entreprise):
        if str(p["client"].pk) not in cochees:
            continue
        try:
            envoyes = relances.relancer(p["client"], p["niveau"])
        except ValidationError as e:
            problemes.append(f"{p['client'].nom_affiche} : {' '.join(e.messages)}")
            continue
        if any(m.statut == m.Statut.EN_FILE for m in envoyes):
            partis += 1
        problemes += [f"{p['client'].nom_affiche}, {m.get_canal_display().lower()} : {m.erreur}"
                      for m in envoyes if m.statut != m.Statut.EN_FILE]
    if partis:
        messages.success(request, f"{partis} relance{'s' if partis > 1 else ''} en route.")
    for t in problemes:
        messages.error(request, t)
    if not partis and not problemes:
        messages.info(request, "Aucune relance envoyée.")
    return redirect("terrain:relances_a_envoyer")


@require_POST
@ecriture_requise
def reporter_relance(request, client_pk):
    """« Pas cette semaine » : le client sort de la liste pour REPORT_JOURS jours."""
    from communications.relances_proposees import REPORT_JOURS

    client = get_object_or_404(Client, pk=client_pk, entreprise=request.entreprise)
    client.relance_reportee_au = timezone.localdate() + timedelta(days=REPORT_JOURS)
    client.save(update_fields=["relance_reportee_au", "modifie_le"])
    messages.success(request, f"{client.nom_affiche} : relance reportée au {client.relance_reportee_au:%d/%m}.")
    return redirect("terrain:relances_a_envoyer")


@membre_requis
def virements(request):
    """Virements Interac reçus (D5) : à confirmer d'une tape, facture proposée par l'app."""
    from facturation.models import VirementInterac

    qs = VirementInterac.objects.filter(entreprise=request.entreprise).select_related("client", "facture", "courriel")
    a_confirmer = list(qs.filter(statut=VirementInterac.Statut.A_TRAITER).order_by("recu_le"))
    dues = list(Facture.objects.filter(entreprise=request.entreprise).a_recevoir().select_related("client")
                .order_by("client__nom", "date_facture"))
    return render(request, "terrain/argent/virements.html", {
        "a_confirmer": a_confirmer, "dues": dues, "ecriture": peut_ecrire(request),
        "traites": qs.exclude(statut=VirementInterac.Statut.A_TRAITER).prefetch_related("paiements__facture")[:20],
    })


@require_POST
@ecriture_requise
def virement(request, pk):
    from facturation import interac
    from facturation.models import VirementInterac
    from facturation.templatetags.argent import argent

    v = get_object_or_404(VirementInterac, pk=pk, entreprise=request.entreprise)
    if request.POST.get("action") == "ignorer":
        if v.statut == VirementInterac.Statut.A_TRAITER:
            v.statut = VirementInterac.Statut.IGNORE
            v.save(update_fields=["statut", "modifie_le"])
            messages.info(request, f"Virement de {argent(v.montant)} ignoré.")
        return redirect("terrain:virements")
    f = get_object_or_404(Facture, pk=request.POST.get("facture") or 0, entreprise=request.entreprise)
    try:
        faits = interac.enregistrer(v, f)
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
        return redirect("terrain:virements")
    detail = ", ".join(f"{argent(p.montant)} sur {p.facture}" for p in faits)
    messages.success(request, f"Virement de {argent(v.montant)} enregistré pour {f.client.nom_affiche} : {detail}.")
    if request.POST.get("recu"):
        _annoncer_recu(request, faits)
    return redirect("terrain:virements")


def _bilan_saison(entreprise):
    """J1 : la saison en un coup d'œil (facturé, encaissé, clients, opérations), de son début à aujourd'hui."""
    from clients.importation import saison_en_cours
    from facturation import credits
    from tournee.models import Operation, Passage

    saison = saison_en_cours(entreprise)
    periode = {"date__gte": saison.debut, "date__lte": saison.fin}
    factures = Facture.objects.filter(entreprise=entreprise, genre=Facture.Genre.FACTURE, statut=Facture.Statut.EMISE,
                                      date_facture__gte=saison.debut, date_facture__lte=saison.fin)
    return {
        "nom": saison.nom, "debut": saison.debut, "fin": saison.fin,
        "facture": factures.aggregate(s=Sum("total"))["s"] or ZERO,
        "taxes": factures.aggregate(s=Sum("tps"))["s"] or ZERO, "tvq": factures.aggregate(s=Sum("tvq"))["s"] or ZERO,
        "encaisse": credits.encaisse(entreprise, **periode),
        "clients": Client.objects.filter(entreprise=entreprise, statut__in=[Client.Statut.ACTIF, Client.Statut.RECOUVREMENT]).count(),
        "operations": Operation.objects.filter(entreprise=entreprise, debut__date__gte=saison.debut, debut__date__lte=saison.fin).count(),
        "passages": Passage.objects.filter(entreprise=entreprise, statut=Passage.Statut.FAIT,
                                           heure__date__gte=saison.debut, heure__date__lte=saison.fin).count(),
    }


@require_POST
@ecriture_requise
def envoyer_contrat(request, pk):
    """Contrat au client (B6) : courriel (PDF joint) ou texto (lien)."""
    from communications.contrats import envoyer_contrat as envoyer
    from communications.models import Message
    from facturation.models import Contrat

    c = get_object_or_404(Contrat, pk=pk, entreprise=request.entreprise)
    canal = Message.Canal.TEXTO if request.POST.get("canal") == "texto" else Message.Canal.COURRIEL
    try:
        m = envoyer(c, canal)
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    else:
        if m.statut == m.Statut.EN_FILE:
            messages.success(request, f"Contrat en route vers {m.destinataire}.")
        else:
            messages.error(request, f"{m.get_statut_display()} : {m.erreur}")
    return redirect("terrain:fiche", pk=c.client_id)


def _versements_prets(entreprise):
    return (Facture.objects.filter(entreprise=entreprise, statut=Facture.Statut.BROUILLON, versement__isnull=False)
            .select_related("client", "versement__contrat__saison").order_by("date_echeance", "client__nom", "pk"))


@membre_requis
def versements_a_envoyer(request):
    """C5 : factures de versement préparées d'avance (brouillons), toutes cochées; une tape les émet et les envoie
    au client par son canal préféré (courriel : PDF joint; texto : lien)."""
    from communications.relances import canaux

    lignes = []
    for f in _versements_prets(request.entreprise):
        c = canaux(f.client)
        lignes.append({"f": f, "canaux": " et ".join(x.label.lower() for x in c) if c else "", "cheques": _cheques_en_main_pour(f)})
    return render(request, "terrain/argent/versements.html", {"lignes": lignes, "ecriture": peut_ecrire(request)})


@require_POST
@ecriture_requise
def envoyer_versements(request):
    """Émet et envoie les factures de versement cochées. Sans coordonnées : émise quand même, à remettre en main propre."""
    from communications.factures import envoyer_facture as envoyer
    from communications.relances import canaux

    cochees = set(request.POST.getlist("facture"))
    emises, parties, problemes = 0, 0, []
    for f in _versements_prets(request.entreprise):
        if str(f.pk) not in cochees:
            continue
        try:
            f.emettre()
        except ValidationError as e:
            problemes.append(f"{f.client.nom_affiche} : {' '.join(e.messages)}")
            continue
        emises += 1
        choix = canaux(f.client)
        if not choix:
            problemes.append(f"{f.client.nom_affiche} : facture n° {f.numero} émise, mais pas de courriel ni de cellulaire (à remettre en main propre).")
        envoyee = False
        for canal in choix:
            try:
                m = envoyer(f, canal)
            except ValidationError as e:
                problemes.append(f"{f.client.nom_affiche} : {' '.join(e.messages)}")
                continue
            if m.statut == m.Statut.EN_FILE:
                envoyee = True
            else:
                problemes.append(f"{f.client.nom_affiche}, {m.get_canal_display().lower()} pas envoyé : {m.erreur or m.get_statut_display().lower()}")
        parties += envoyee
    if emises:
        s = "s" if emises > 1 else ""
        envoi = (f"{parties} en route vers {'les clients' if parties > 1 else 'le client'}" if parties
                 else "aucune envoyée (voir ci-dessous)")
        messages.success(request, f"{emises} facture{s} émise{s}, {envoi}.")
    for p in problemes:
        messages.error(request, p)
    if not emises and not problemes:
        messages.info(request, "Aucune facture choisie.")
    return redirect("terrain:versements_a_envoyer")
