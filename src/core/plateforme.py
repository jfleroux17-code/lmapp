"""Tableau de bord de la plateforme (JF) : l'usage de chaque entreprise de déneigement, mois par mois.

Sert à suivre la plateforme et à facturer les entreprises (frais de base annuels, plus l'usage des
courriels et des textos, tarifs à venir). Compte ce qui est vraiment parti ou arrivé :
  - courriels envoyés par l'app (statut Envoyé, identifiant du serveur), reçus (boîte lue par l'app);
  - textos envoyés et leurs segments (ce que Twilio facture), reçus;
  - factures émises (nombre et montant), factures envoyées par courriel, relances;
  - paiements enregistrés, virements Interac détectés;
  - clients servis, opérations, passages, utilisateurs, dernière connexion;
  - espace : boîte courriel (quota) et archives dans la base.
"""
from datetime import date

from django.db.models import Count, Max, Q, Sum

from clients.models import Client
from communications.models import RELANCES, ArchiveCourriel, EtatBoite, Genre, Message
from core.models import Entreprise, Membre
from facturation.models import ZERO, Facture, Paiement, VirementInterac
from tournee.models import Operation, Passage

COLONNES = [
    ("courriels_envoyes", "Courriels envoyés"), ("courriels_recus", "Courriels reçus"),
    ("textos_envoyes", "Textos envoyés"), ("segments", "Segments de textos"), ("textos_recus", "Textos reçus"),
    ("echecs", "Envois en échec"),
    ("factures_emises", "Factures émises"), ("montant_facture", "Montant facturé ($)"),
    ("factures_envoyees", "Factures envoyées par courriel"), ("relances", "Relances envoyées"),
    ("paiements", "Paiements enregistrés"), ("montant_encaisse", "Montant encaissé ($)"), ("virements", "Virements Interac lus"),
    ("operations", "Opérations"), ("passages", "Passages"),
    ("clients_servis", "Clients servis (aujourd'hui)"), ("utilisateurs", "Utilisateurs"), ("derniere_connexion", "Dernière connexion"),
    ("boite_utilisee_mo", "Boîte courriel utilisée (Mo)"), ("boite_permise_mo", "Boîte permise (Mo)"), ("archives_mo", "Archives (Mo)"),
]


def mois(annee, numero):
    debut = date(annee, numero, 1)
    fin = date(annee + (numero == 12), numero % 12 + 1, 1)
    return debut, fin


def _par_entreprise(qs, **agregats):
    return {r["entreprise"]: r for r in qs.values("entreprise").annotate(**agregats)}


def statistiques(debut, fin):
    """Une ligne par entreprise pour la période [debut, fin[ (dates locales), plus la ligne des totaux."""
    periode = Q(cree_le__date__gte=debut, cree_le__date__lt=fin)
    parti = Q(statut=Message.Statut.ENVOYE)
    m = _par_entreprise(
        Message.objects.filter(periode),
        courriels_envoyes=Count("pk", filter=Q(canal="courriel", sens="sortant") & parti & ~Q(fournisseur_id="")),
        courriels_recus=Count("pk", filter=Q(canal="courriel", sens="entrant")),
        textos_envoyes=Count("pk", filter=Q(canal="texto", sens="sortant") & parti),
        segments=Sum("segments", filter=Q(canal="texto", sens="sortant") & parti),
        textos_recus=Count("pk", filter=Q(canal="texto", sens="entrant")),
        echecs=Count("pk", filter=Q(statut=Message.Statut.ECHEC)),
        factures_envoyees=Count("pk", filter=Q(genre=Genre.FACTURE) & parti),
        relances=Count("pk", filter=Q(genre__in=RELANCES) & parti),
    )
    f = _par_entreprise(Facture.objects.filter(emise_le__date__gte=debut, emise_le__date__lt=fin, genre=Facture.Genre.FACTURE),
                        factures_emises=Count("pk"), montant_facture=Sum("total"))
    p = _par_entreprise(Paiement.objects.filter(date__gte=debut, date__lt=fin), paiements=Count("pk"), montant_encaisse=Sum("montant"))
    v = _par_entreprise(VirementInterac.objects.filter(recu_le__date__gte=debut, recu_le__date__lt=fin), virements=Count("pk"))
    o = _par_entreprise(Operation.objects.filter(debut__date__gte=debut, debut__date__lt=fin), operations=Count("pk"))
    pa = _par_entreprise(Passage.objects.filter(heure__date__gte=debut, heure__date__lt=fin), passages=Count("pk"))
    c = _par_entreprise(Client.objects.filter(statut__in=[Client.Statut.ACTIF, Client.Statut.RECOUVREMENT]), clients_servis=Count("pk"))
    u = _par_entreprise(Membre.objects.all(), utilisateurs=Count("pk"), derniere_connexion=Max("utilisateur__last_login"))
    a = _par_entreprise(ArchiveCourriel.objects.all(), archives=Sum("taille"))
    b = {e.entreprise_id: e for e in EtatBoite.objects.filter(dossier="INBOX")}

    lignes = []
    for ent in Entreprise.objects.order_by("nom"):
        ligne = {"entreprise": ent}
        for source in (m, f, p, v, o, pa, c, u):
            ligne.update({k: val for k, val in source.get(ent.pk, {}).items() if k != "entreprise"})
        boite = b.get(ent.pk)
        ligne["boite_utilisee_mo"] = round(boite.quota_utilise_ko / 1024, 1) if boite and boite.quota_utilise_ko is not None else None
        ligne["boite_permise_mo"] = round(boite.quota_max_ko / 1024) if boite and boite.quota_max_ko else None
        ligne["boite_pourcent"] = (round(100 * boite.quota_utilise_ko / boite.quota_max_ko) if boite and boite.quota_max_ko
                                   and boite.quota_utilise_ko is not None else None)
        ligne["archives_mo"] = round((a.get(ent.pk, {}).get("archives") or 0) / 1024 / 1024, 1)
        for k, _ in COLONNES:
            if ligne.get(k) is None and k not in ("derniere_connexion", "boite_utilisee_mo", "boite_permise_mo"):
                ligne[k] = ZERO if k.startswith("montant") else 0
        lignes.append(ligne)
    total = {"entreprise": None}
    for k, _ in COLONNES:
        valeurs = [l[k] for l in lignes if isinstance(l.get(k), (int, float, type(ZERO))) and not isinstance(l.get(k), bool)]
        total[k] = sum(valeurs) if valeurs and k not in ("derniere_connexion", "boite_permise_mo") else None
    return lignes, total
