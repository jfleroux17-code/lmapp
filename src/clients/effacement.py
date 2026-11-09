"""Effacement des renseignements d'un client à sa demande (Loi 25, PRD K5).

On ne détruit pas la fiche : les factures émises doivent être gardées six ans (lois fiscales),
avec le nom et l'adresse de facturation. On efface tout le reste :
  - coordonnées (cellulaire, autre téléphone, courriel), notes, consentement, autres personnes à joindre (A3);
  - particularités du terrain, photos de l'entrée et des passages, position et notes de passage de ses adresses (rendues inactives);
  - contenu de ses messages et copies intégrales des courriels archivés;
  - description des demandes;
  - anciennes valeurs gardées dans le journal des actions (K4).
Sans facture émise, le nom, l'organisation et les adresses (facturation et service) partent aussi.
Les brouillons de facture sont supprimés. Irréversible : fait depuis l'administration, après confirmation.
"""
from django.db import transaction
from django.utils import timezone

EFFACE = "[effacé à la demande du client]"


def effacer(client):
    from clients.models import PhotoAdresse
    from communications.models import ArchiveCourriel
    from facturation.models import Facture
    from tournee.models import Passage, PhotoPassage

    with transaction.atomic():
        garde = client.factures.exclude(statut=Facture.Statut.BROUILLON).exists()
        bilan = {"brouillons": 0, "messages": 0, "archives": 0, "demandes": 0, "adresses": 0, "factures_gardees": garde}
        for f in client.factures.filter(statut=Facture.Statut.BROUILLON):
            f.delete()
            bilan["brouillons"] += 1

        msgs = client.messages.all()
        bilan["archives"] = ArchiveCourriel.objects.filter(message__in=msgs).delete()[0]
        bilan["messages"] = msgs.update(contenu=EFFACE, sujet="", destinataire="", expediteur="", message_id_externe="")
        bilan["demandes"] = client.demandes.update(description=EFFACE, contact="", reglement="")

        bilan["contacts"] = client.contacts.all().delete()[0]
        adresses = client.adresses.all()
        bilan["photos"] = (PhotoAdresse.objects.filter(adresse__in=adresses).delete()[0]
                           + PhotoPassage.objects.filter(adresse__in=adresses).delete()[0])
        Passage.objects.filter(adresse__in=adresses).update(note="")
        champs = dict(active=False, ou_mettre_neige="", obstacles="", borne_fontaine=False, entree_en_pente=False, consignes="",
                      position=None, position_source="", geocodage_note="")
        if not garde:
            champs.update(ligne1="Adresse effacée", ligne2="", code_postal="")
        bilan["adresses"] = adresses.update(**champs, modifie_le=timezone.now())

        client.cellulaire = client.telephone_autre = client.courriel = client.notes = ""
        client.consentement_commercial, client.consentement_date, client.consentement_source = False, None, ""
        client.desabonne_le = None
        client.statut = client.Statut.INACTIF
        if not garde:
            client.prenom, client.nom, client.organisation = "", "Client effacé", ""
            client.facturation_ligne1 = client.facturation_ligne2 = client.facturation_ville = ""
            client.facturation_province = client.facturation_code_postal = ""
        client.efface_le = timezone.now()
        client.save()
        from core import journal

        journal.effacer_client(client)  # les anciennes valeurs (téléphones, notes) ne restent pas dans le journal
    return bilan
