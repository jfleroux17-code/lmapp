"""Abonnement des entreprises à la plateforme (PRD Q2; prix de JF, 11 novembre 2026).

Prix (réglages PLATEFORME_PRIX_*), taxes en sus :
  - abonnement : 99 $ par mois, le logiciel complet, un utilisateur compris (administrateur et opérateur);
  - 25 $ par mois par utilisateur de plus (administrateur ou opérateur actif); lecture seule gratuite;
  - 0,03 $ par texto, envoyé ou reçu (un texto reçu compte pour un, quelle que soit sa longueur); courriels gratuits.

Textos comptés : envoyés par l'app (statut Envoyé : un texto préparé, bloqué ou en échec n'est pas parti) et reçus.
Le 1er du mois, une facture brouillon du mois passé est préparée pour chaque entreprise dont l'abonnement est
facturé (`Entreprise.abonnement_facture`). JF la relit (lignes modifiables : rabais, premier mois), l'émet et
l'envoie depuis l'administration. Rien ne part sans lui.
"""
from datetime import date, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from facturation.calculs import arrondir, taxes

ZERO = arrondir(0)


def debut_du_mois(jour):
    return jour.replace(day=1)


def mois_suivant(premier):
    return date(premier.year + (premier.month == 12), premier.month % 12 + 1, 1)


def mois_precedent(premier):
    return date(premier.year - (premier.month == 1), (premier.month - 2) % 12 + 1, 1)


def utilisateurs_facturables(entreprise):
    """Administrateurs et opérateurs dont le compte est actif (la lecture seule est gratuite)."""
    from core.models import Membre

    return (Membre.objects.filter(entreprise=entreprise, utilisateur__is_active=True)
            .exclude(role=Membre.Role.LECTURE).count())


def usage(entreprise, premier):
    """Ce qui compte pour la facture du mois qui commence le `premier` (dates locales)."""
    from communications.models import Message
    from core.models import Membre

    fin = mois_suivant(premier)
    qs = Message.objects.filter(entreprise=entreprise, cree_le__date__gte=premier, cree_le__date__lt=fin)
    r = qs.aggregate(
        textos_envoyes=Count("pk", filter=Q(canal="texto", sens="sortant", statut=Message.Statut.ENVOYE)),
        textos_recus=Count("pk", filter=Q(canal="texto", sens="entrant")),
        courriels_envoyes=Count("pk", filter=Q(canal="courriel", sens="sortant", statut=Message.Statut.ENVOYE)),
        courriels_recus=Count("pk", filter=Q(canal="courriel", sens="entrant")),
    )
    r["textos"] = r["textos_envoyes"] + r["textos_recus"]
    r["utilisateurs"] = utilisateurs_facturables(entreprise)
    r["lecture_seule"] = Membre.objects.filter(entreprise=entreprise, role=Membre.Role.LECTURE, utilisateur__is_active=True).count()
    return r


def lignes(u, premier):
    """[(description, quantité, prix unitaire)] pour un usage."""
    from core.templatetags.dates_qc import date_texte

    nom_mois = date_texte(premier, "F Y")
    sortie = [(f"Abonnement Le Déneigeur, {nom_mois} (un utilisateur compris)", 1, settings.PLATEFORME_PRIX_ABONNEMENT)]
    de_plus = max(0, u["utilisateurs"] - 1)
    if de_plus:
        sortie.append((f"Utilisateur{'s' if de_plus > 1 else ''} de plus (administrateur ou opérateur)", de_plus,
                       settings.PLATEFORME_PRIX_UTILISATEUR))
    if u["textos"]:
        sortie.append((f"Textos : {u['textos_envoyes']} envoyé{'s' if u['textos_envoyes'] > 1 else ''}, "
                       f"{u['textos_recus']} reçu{'s' if u['textos_recus'] > 1 else ''}", u["textos"], settings.PLATEFORME_PRIX_TEXTO))
    return sortie


def estimation(entreprise, premier):
    """Pour l'écran du déneigeur : lignes, sous-total, taxes et total, comme la facture serait préparée."""
    u = usage(entreprise, premier)
    rangees = [{"description": d, "quantite": q, "prix": p, "montant": arrondir(q * p)} for d, q, p in lignes(u, premier)]
    sous_total = sum((r["montant"] for r in rangees), ZERO)
    tps, tvq = taxes(sous_total, settings.PLATEFORME_TAUX_TPS, settings.PLATEFORME_TAUX_TVQ)
    return {"usage": u, "lignes": rangees, "sous_total": sous_total, "tps": tps, "tvq": tvq, "total": sous_total + tps + tvq}


def recalculer(f):
    """Brouillon : sous-total, taxes (taux actuels de la plateforme) et total d'après les lignes."""
    f.sous_total = sum((l.montant for l in f.lignes.all()), ZERO)
    f.taux_tps, f.taux_tvq = settings.PLATEFORME_TAUX_TPS, settings.PLATEFORME_TAUX_TVQ
    f.tps, f.tvq = taxes(f.sous_total, f.taux_tps, f.taux_tvq)
    f.total = f.sous_total + f.tps + f.tvq
    f.save()
    return f


def preparer(entreprise, premier):
    """Brouillon du mois (une seule facture par entreprise et par mois, hors annulées). Retourne (facture, créée)."""
    from core.models import FacturePlateforme, LigneFacturePlateforme

    with transaction.atomic():
        existante = FacturePlateforme.objects.filter(entreprise=entreprise, mois=premier).exclude(
            statut=FacturePlateforme.Statut.ANNULEE).first()
        if existante:
            return existante, False
        u = usage(entreprise, premier)
        f = FacturePlateforme.objects.create(entreprise=entreprise, mois=premier, textos_envoyes=u["textos_envoyes"],
                                             textos_recus=u["textos_recus"], utilisateurs=u["utilisateurs"],
                                             courriels=u["courriels_envoyes"] + u["courriels_recus"])
        for i, (d, q, p) in enumerate(lignes(u, premier)):
            LigneFacturePlateforme.objects.create(facture=f, ordre=i, description=d, quantite=q, prix_unitaire=p)
        return recalculer(f), True


def preparer_mois_passe(aujourd_hui=None):
    """Le 1er du mois (tâche du worker) : brouillons du mois passé. Retourne les factures créées."""
    from core.models import Entreprise

    premier = mois_precedent(debut_du_mois(aujourd_hui or timezone.localdate()))
    return [f for ent in Entreprise.objects.filter(abonnement_facture=True)
            for f, cree in [preparer(ent, premier)] if cree]


def raison_pas_emettable(f):
    if not f.modifiable:
        return "Déjà émise."
    if not f.lignes.exists():
        return "Aucune ligne."
    if not (settings.PLATEFORME_NUMERO_TPS and settings.PLATEFORME_NUMERO_TVQ):
        return "Numéros de TPS et de TVQ de la plateforme manquants (PLATEFORME_NUMERO_TPS et PLATEFORME_NUMERO_TVQ dans .env)."
    return ""


def emettre(f, aujourd_hui=None):
    """Numéro suivant de la série de la plateforme, taxes figées, échéance. Ensuite plus rien ne change."""
    from django.core.exceptions import ValidationError

    from core.models import FacturePlateforme

    raison = raison_pas_emettable(f)
    if raison:
        raise ValidationError(raison)
    with transaction.atomic():
        FacturePlateforme.objects.select_for_update().filter(pk=f.pk).first()
        recalculer(f)
        dernier = FacturePlateforme.objects.aggregate(n=Max("numero"))["n"] or 0
        jour = aujourd_hui or timezone.localdate()
        f.numero, f.statut = dernier + 1, FacturePlateforme.Statut.EMISE
        f.date_facture, f.date_echeance = jour, jour + timedelta(days=settings.PLATEFORME_JOURS_PAIEMENT)
        f.numero_tps, f.numero_tvq = settings.PLATEFORME_NUMERO_TPS, settings.PLATEFORME_NUMERO_TVQ
        f.save()
    return f


def destinataire(f):
    ent = f.entreprise
    return (ent.courriel or ent.courriel_reponse or "").lower()


def pdf(f):
    from django.template.loader import render_to_string
    from weasyprint import HTML

    html = render_to_string("core/facture_plateforme_pdf.html", {
        "f": f, "ent": f.entreprise, "lignes": list(f.lignes.all()),
        "plateforme": {"nom": settings.PLATEFORME_NOM_LEGAL, "adresse": [l.strip() for l in settings.PLATEFORME_ADRESSE.split("|") if l.strip()],
                       "telephone": settings.PLATEFORME_TELEPHONE, "courriel": settings.PLATEFORME_COURRIEL,
                       "paiement": settings.PLATEFORME_PAIEMENT}})
    return HTML(string=html).write_pdf()


def demander_envoi(f):
    """Confie l'envoi au worker (l'app n'a pas Internet). Hors prod : seulement aux destinataires du test."""
    from django.core.exceptions import ValidationError

    from communications.envoi import destinataire_permis
    from core.models import FacturePlateforme

    if f.statut not in (FacturePlateforme.Statut.EMISE, FacturePlateforme.Statut.PAYEE):
        raise ValidationError("Seule une facture émise s'envoie.")
    dest = destinataire(f)
    if not dest:
        raise ValidationError("Pas de courriel dans la fiche de l'entreprise.")
    if not destinataire_permis(dest):
        raise ValidationError(f"Environnement de test : {dest} n'est pas un destinataire permis.")
    if not (settings.SMTP_HOTE and settings.PLATEFORME_IMAP_UTILISATEUR and settings.PLATEFORME_IMAP_MOT_DE_PASSE):
        raise ValidationError("Boîte de la plateforme pas configurée (PLATEFORME_IMAP_* dans .env).")
    from core.tasks import envoyer_facture_plateforme

    pk = f.pk
    transaction.on_commit(lambda: envoyer_facture_plateforme.defer(facture_id=pk))
    return dest


def courriel(f):
    from email.message import EmailMessage
    from email.utils import format_datetime, make_msgid

    from core.templatetags.dates_qc import date_texte
    from facturation.templatetags.argent import argent

    m = EmailMessage()
    m["From"] = f"Le Déneigeur <{settings.PLATEFORME_IMAP_UTILISATEUR}>"
    m["To"] = destinataire(f)
    m["Subject"] = f"Facture n° {f.numero} : Le Déneigeur, {date_texte(f.mois, 'F Y')}"
    m["Date"] = format_datetime(timezone.now())
    m["Message-ID"] = make_msgid(domain=settings.PLATEFORME_IMAP_UTILISATEUR.split("@")[-1] or None)
    corps = [f"Bonjour,", f"Voici la facture n° {f.numero} de votre abonnement à Le Déneigeur pour {date_texte(f.mois, 'F Y')} : "
             f"{argent(f.total)}, taxes comprises, à payer au plus tard le {date_texte(f.date_echeance)}.",
             "Le détail (abonnement, utilisateurs, textos) est dans la facture jointe."]
    if settings.PLATEFORME_PAIEMENT:
        corps.append(settings.PLATEFORME_PAIEMENT)
    corps += ["Merci!", f"{settings.PLATEFORME_NOM_LEGAL}\n{settings.PLATEFORME_TELEPHONE}"]
    m.set_content("\n\n".join(corps))
    m.add_attachment(pdf(f), maintype="application", subtype="pdf", filename=f"facture-le-deneigeur-{f.numero}.pdf")
    return m


def envoyer(f):
    """Dans le worker : envoie le courriel par la boîte de la plateforme. Retourne vrai si parti."""
    import smtplib
    import ssl

    from core.models import FacturePlateforme

    try:
        with smtplib.SMTP_SSL(settings.SMTP_HOTE, settings.SMTP_PORT, local_hostname=settings.COURRIEL_HELO,
                              context=ssl.create_default_context(), timeout=30) as s:
            s.login(settings.PLATEFORME_IMAP_UTILISATEUR, settings.PLATEFORME_IMAP_MOT_DE_PASSE)
            s.send_message(courriel(f))
    except (OSError, smtplib.SMTPException) as e:
        FacturePlateforme.objects.filter(pk=f.pk).update(erreur_envoi=str(e)[:300])
        return False
    FacturePlateforme.objects.filter(pk=f.pk).update(envoyee_le=timezone.now(), envoyee_a=destinataire(f), erreur_envoi="")
    return True
