"""Crée une entreprise fictive et des clients inventés pour l'environnement de test.

Refuse de s'exécuter en prod (LMAPP_ENV=prod). Aucune donnée réelle :
  - cellulaires dans la plage 555-0100 à 555-0199, réservée à la fiction en
    Amérique du Nord (aucun texto ne peut aboutir chez quelqu'un);
  - courriels en @example.com (domaine réservé aux exemples);
  - rues inventées, positions approximatives dans de vraies villes.

Utilisation : docker compose run --rm app python manage.py donnees_essai
"""
from datetime import date, datetime
from decimal import Decimal

from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from clients.models import Adresse, Client, Secteur
from core.models import Entreprise, Membre, VilleDesservie
from facturation.models import Contrat, Facture, Paiement, Saison, Service

ENTREPRISE = {
    "slug": "essai",
    "nom": "Déneigement Essai",
    "domaine": "test.ledeneigeur.com",
    "telephone": "450 555-0100",
    "courriel": "info@example.com",
    "ville": "Sainte-Adèle",
    "signature_messages": "Déneigement Essai",
    # Numéros de taxes fictifs (format seulement), numérotation à partir de 1001
    "inscrit_taxes": True,
    "numero_tps": "123456789 RT0001",
    "numero_tvq": "1234567890 TQ0001",
    "prochain_numero_facture": 1001,
    # Comme Louis : 1er versement à l'approbation, les suivants à ces dates
    "dates_versements": "15/01 15/02",
    "versements_par_defaut": 2,
    "interac_courriel": "paiement@example.com",
    "interac_instructions": "Virement Interac à paiement@example.com (dépôt automatique, aucune question). Indiquez votre numéro de facture.",
}

SECTEURS = [("Village", 1), ("Mont-Rolland", 2), ("Chantecler", 3)]

# Ville desservie et sa zone (centre approximatif de Sainte-Adèle, rayon 8 km)
VILLE = ("Sainte-Adèle", -74.1313, 45.9502, "8.0")

# (prénom, nom, organisation, cellulaire, courriel, statut, paiement, canal, consentement, désabonné, secteur, adresses)
# adresses : liste de (ligne1, ville, code postal, longitude, latitude, rang)
CLIENTS = [
    ("Ginette", "Tremblay", "", "450 555-0101", "ginette.tremblay@example.com", "actif", "comptant", "texto", True, False,
     "Village", [("120, rue des Essais", "Sainte-Adèle", "J8B 1A1", -74.1338, 45.9502, 1)]),
    ("Réjean", "Gagnon", "", "450 555-0102", "", "actif", "comptant", "texto", False, False,
     "Village", [("134, rue des Essais", "Sainte-Adèle", "J8B 1A1", -74.1329, 45.9508, 2)]),
    ("Sylvie", "Roy", "", "450 555-0103", "sylvie.roy@example.com", "actif", "interac", "les_deux", True, False,
     "Village", [("8, montée Fictive", "Sainte-Adèle", "J8B 1A2", -74.1302, 45.9531, 3)]),
    ("Marcel", "Côté", "", "450 555-0104", "marcel.cote@example.com", "recouvrement", "comptant", "texto", False, False,
     "Village", [("45, chemin de l'Exemple", "Sainte-Adèle", "J8B 1A3", -74.1275, 45.9550, 4)]),
    ("Nathalie", "Bouchard", "", "450 555-0105", "nathalie.bouchard@example.com", "actif", "interac", "courriel", True, True,
     "Mont-Rolland", [("210, rue du Modèle", "Sainte-Adèle", "J8B 1B1", -74.1100, 45.9655, 1)]),
    ("Pierre", "Lavoie", "", "450 555-0106", "pierre.lavoie@example.com", "actif", "cheque", "texto", False, False,
     "Mont-Rolland", [("17, rue du Modèle", "Sainte-Adèle", "J8B 1B1", -74.1085, 45.9662, 2)]),
    ("", "Fortin", "Syndicat de copropriété Les Sapins fictifs", "450 555-0107", "gestion.sapins@example.com", "actif", "interac", "courriel", False, False,
     "Mont-Rolland", [("300, boulevard Imaginaire", "Sainte-Adèle", "J8B 1B2", -74.1050, 45.9680, 3)]),
    ("Luc", "Pelletier", "", "450 555-0108", "luc.pelletier@example.com", "actif", "comptant", "texto", True, False,
     "Chantecler", [("2, rue de la Démo", "Sainte-Adèle", "J8B 1C1", -74.1620, 45.9405, 1),
                    ("4, rue de la Démo", "Sainte-Adèle", "J8B 1C1", -74.1616, 45.9408, 2)]),
    ("Francine", "Morin", "", "450 555-0109", "", "inactif", "comptant", "texto", False, False,
     "Chantecler", [("55, chemin du Test", "Sainte-Adèle", "J8B 1C2", -74.1680, 45.9370, 3)]),
    ("Gaston", "Bélanger", "", "450 555-0110", "", "liste_noire", "comptant", "texto", False, False,
     "Chantecler", [("9, rang Fictif", "Sainte-Adèle", "J8B 1C3", None, None, None)]),
]


class Command(BaseCommand):
    help = "Crée l'entreprise fictive « Déneigement Essai » et ses clients (environnement de test seulement)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reinitialiser", action="store_true",
            help="Effacer d'abord l'entreprise d'essai et toutes ses données (test seulement).",
        )

    def handle(self, *args, **options):
        if settings.LMAPP_ENV == "prod":
            raise CommandError("Refusé : LMAPP_ENV=prod. Les données d'essai ne vont jamais en prod.")

        with transaction.atomic():
            membres = []
            if options["reinitialiser"]:
                ancienne = Entreprise.objects.filter(slug=ENTREPRISE["slug"]).first()
                if ancienne is not None:
                    membres = list(Membre.objects.filter(entreprise=ancienne).values_list("utilisateur_id", "role"))
                    self._effacer(ancienne)
                    self.stdout.write(f"Entreprise d'essai « {ancienne} » effacée.")
            ent, creee = Entreprise.objects.get_or_create(slug=ENTREPRISE["slug"], defaults=ENTREPRISE)
            if not creee:
                self.stdout.write(f"L'entreprise « {ent} » existe déjà : rien n'est ajouté.")
                return
            ent.full_clean()
            ent.save()

            nom_ville, lon, lat, rayon = VILLE
            VilleDesservie.objects.create(entreprise=ent, nom=nom_ville, centre=Point(lon, lat, srid=4326), rayon_km=Decimal(rayon), par_defaut=True)
            secteurs = {nom: Secteur.objects.create(entreprise=ent, nom=nom, ordre=o) for nom, o in SECTEURS}

            for (prenom, nom, org, cell, courriel, statut, paiement, canal, consent, desabonne, secteur, adresses) in CLIENTS:
                c = Client(
                    entreprise=ent, prenom=prenom, nom=nom, organisation=org,
                    cellulaire=cell, courriel=courriel, statut=statut,
                    mode_paiement=paiement, canal_prefere=canal,
                    consentement_commercial=consent,
                    consentement_date=date(2026, 10, 15) if consent else None,
                    consentement_source="import" if consent else "",
                    desabonne_le=timezone.make_aware(datetime(2026, 11, 2, 9, 30)) if desabonne else None,
                    notes="Client fictif (données d'essai).",
                )
                if org:
                    c.facturation_ligne1 = "C.P. 123, succursale Exemple"
                    c.facturation_ville = "Saint-Jérôme"
                    c.facturation_province = "QC"
                    c.facturation_code_postal = "J7Z 1A1"
                c.full_clean()
                c.save()
                for ligne1, ville, cp, lon, lat, rang in adresses:
                    a = Adresse(
                        entreprise=ent, client=c, secteur=secteurs[secteur],
                        ligne1=ligne1, ville=ville, code_postal=cp,
                        position=Point(lon, lat, srid=4326) if lon is not None else None,
                        position_source="manuelle" if lon is not None else "",
                        ordre_tournee=rang,
                    )
                    a.full_clean()
                    a.save()

            # Quelques particularités du terrain (A5)
            Adresse.objects.filter(entreprise=ent, ligne1="8, montée Fictive").update(
                entree_en_pente=True, ou_mettre_neige="À gauche de l'entrée, pas sur la haie",
            )
            Adresse.objects.filter(entreprise=ent, ligne1="300, boulevard Imaginaire").update(
                borne_fontaine=True, obstacles="Bordure de béton à droite", consignes="Stationnement de 12 places, passer avant 7 h.",
            )

            factures = self._argent(ent)
            scenarios = self._scenarios(ent, secteurs)
            for utilisateur_id, role in membres:  # les comptes d'essai (JF, aperçu) gardent leur accès
                Membre.objects.get_or_create(utilisateur_id=utilisateur_id, entreprise=ent, defaults={"role": role})

        self.stdout.write(self.style.SUCCESS(
            f"« {ent} » créée : ville desservie {nom_ville}, {len(secteurs)} secteurs, {Client.objects.filter(entreprise=ent).count()} clients, "
            f"{Adresse.objects.filter(entreprise=ent).count()} adresses, {factures}.\n{scenarios}"
        ))

    def _effacer(self, ent):
        """Efface tout ce qui appartient à l'entreprise d'essai, puis l'entreprise.

        Les modèles sont trouvés par leur clé vers Entreprise (pas de liste à
        tenir à jour). Les clés protégées entre eux imposent un ordre : on
        efface ce qui peut l'être, et on recommence jusqu'à ce que tout soit
        parti. Le registre des incidents ne s'efface jamais : s'il en a, refus.
        """
        from django.db import models as dj_models
        from django.db.models import ProtectedError, RestrictedError

        if ent.incidents.exists():
            raise CommandError("Refusé : l'entreprise d'essai a des incidents de confidentialité inscrits (registre jamais effacé).")
        restants = [
            (rel.related_model, rel.field.name) for rel in Entreprise._meta.related_objects
            if isinstance(rel.field, dj_models.ForeignKey) and rel.related_model is not Entreprise
        ]
        while restants:
            bloques = []
            for modele, champ in restants:
                try:
                    with transaction.atomic():
                        modele._base_manager.filter(**{champ: ent}).delete()
                except (ProtectedError, RestrictedError):
                    bloques.append((modele, champ))
            if len(bloques) == len(restants):
                noms = ", ".join(m._meta.label for m, _ in bloques)
                raise CommandError(f"Effacement bloqué (clés protégées) : {noms}")
            restants = bloques
        ent.delete()

    def _argent(self, ent):
        """Saison, services, contrats à versements, factures, un paiement et un solde d'ouverture (fictifs)."""
        saison = Saison.objects.create(entreprise=ent, nom="2026-2027", debut=date(2026, 11, 1), fin=date(2027, 4, 15))
        services = {nom: Service.objects.create(entreprise=ent, nom=nom, prix_suggere=prix, ordre=o)
                    for o, (nom, prix) in enumerate([("Entrée", None), ("Bordage de la rue", Decimal("40")),
                                                     ("Pelletage du balcon", Decimal("25")), ("Abrasif", Decimal("15"))])}
        servis = Client.objects.filter(entreprise=ent, statut__in=["actif", "recouvrement"]).order_by("pk")
        for i, c in enumerate(servis[:4]):
            contrat = Contrat.objects.create(entreprise=ent, client=c, adresse=c.adresses.first(), saison=saison,
                                             prix=Decimal("450") + 50 * i, prix_texte="Prix de la saison, plus taxes, en 2 versements")
            contrat.services.add(services["Entrée"])
            v1, _ = contrat.creer_echeancier([date(2026, 11, 15), date(2027, 1, 15)])
            f = v1.facturer()
            f.emettre()
            if i == 0:
                Paiement.objects.create(entreprise=ent, facture=f, date=f.date_facture, montant=Decimal("100"), mode="comptant", note="Paiement partiel (essai)")
        if len(servis) > 4:  # un client « au passage » : chaque passage fait s'ajoute à sa facture (F11)
            c = servis[4]
            Contrat.objects.create(entreprise=ent, client=c, adresse=c.adresses.first(), saison=saison, type="au_passage",
                                   prix=Decimal("45"), prix_texte="45 $ par passage, plus taxes")
        extra = Facture.objects.create(entreprise=ent, client=servis[0], adresse=servis[0].adresses.first())
        extra.lignes.create(service=services["Pelletage du balcon"], description="Pelletage du balcon", quantite=2, prix_unitaire=Decimal("25"))
        extra.recalculer()  # laissée en brouillon
        recouvrement = Client.objects.filter(entreprise=ent, statut="recouvrement").first()
        if recouvrement:
            Facture.solde_ouverture(recouvrement, Decimal("380"), saison_origine="2025-2026", note="Solde fictif (essai)")
        return f"saison {saison}, {Facture.objects.filter(entreprise=ent).count()} factures (dont un brouillon et un solde d'ouverture)"

    # Scénarios pour essayer tout l'app sans rien saisir (demande de JF, 12 novembre 2026).
    # Dates relatives à aujourd'hui : les cas restent parlants (en retard, à déposer, etc.) quel que soit le jour.
    SCENARIOS = [
        # (clé, prénom, nom, organisation, cellulaire, courriel, statut, paiement, canal, secteur, adresses [(ligne1, cp, lon, lat, rang)])
        ("deux_adresses", "Martin", "Gauthier", "", "450 555-0111", "martin.gauthier@example.com", "actif", "interac", "les_deux", "Village",
         [("150, rue des Essais", "J8B 1A1", -74.1320, 45.9512, 5), ("12, chemin du Chalet-Fictif", "J8B 1A4", -74.1250, 45.9570, 6)]),
        ("non_occupant", "Robert", "Wilson", "", "", "robert.wilson@example.com", "actif", "interac", "courriel", "Village",
         [("77, rue des Locataires", "J8B 1A5", -74.1290, 45.9540, 7)]),
        ("credit", "Diane", "Ouellet", "", "450 555-0113", "diane.ouellet@example.com", "actif", "comptant", "texto", "Mont-Rolland",
         [("230, rue du Modèle", "J8B 1B1", -74.1070, 45.9670, 4)]),
        ("cheques", "André", "Bergeron", "", "450 555-0114", "", "actif", "cheque", "texto", "Mont-Rolland",
         [("19, rue du Modèle", "J8B 1B1", -74.1080, 45.9665, 5)]),
        ("paye", "Lise", "Caron", "", "450 555-0115", "lise.caron@example.com", "actif", "interac", "courriel", "Mont-Rolland",
         [("5, impasse de la Pratique", "J8B 1B3", -74.1040, 45.9690, 6)]),
        ("en_retard", "Jacques", "Poirier", "", "450 555-0116", "jacques.poirier@example.com", "actif", "comptant", "texto", "Chantecler",
         [("61, chemin du Test", "J8B 1C2", -74.1670, 45.9375, 4)]),
        ("sans_coordonnees", "Yvon", "Lemieux", "", "", "", "actif", "comptant", "texto", "Chantecler",
         [("70, chemin du Test", "J8B 1C2", -74.1660, 45.9380, 5)]),
        ("ne_pas_relancer", "Claudette", "Girard", "", "450 555-0118", "", "actif", "comptant", "texto", "Chantecler",
         [("3, rue de la Démo", "J8B 1C1", -74.1618, 45.9402, 6)]),
        ("ete", "Sophie", "Lalonde", "", "450 555-0120", "sophie.lalonde@example.com", "actif", "interac", "courriel", "Village",
         [("88, chemin des Jardins-Fictifs", "J8B 1A6", -74.1350, 45.9480, None)]),
        ("mal_placee", "Hélène", "Fournier", "", "450 555-0119", "helene.fournier@example.com", "actif", "interac", "texto", "Chantecler",
         [("999, rang Introuvable", "", None, None, 7)]),
    ]

    def _scenarios(self, ent, secteurs):
        from datetime import timedelta

        from clients.models import Balisage, Contact
        from communications.models import Message
        from demandes.models import Demande
        from facturation import credits
        from facturation.depenses import taxes_du_total
        from facturation.models import ChequePostdate, Depense, VirementInterac
        from tournee.models import Operation, Passage

        auj = timezone.localdate()
        maintenant = timezone.now()
        saison = Saison.objects.get(entreprise=ent, nom="2026-2027")
        entree = Service.objects.get(entreprise=ent, nom="Entrée")
        c = {}
        for (cle, prenom, nom, org, cell, courriel, statut, paiement, canal, secteur, adresses) in self.SCENARIOS:
            client = Client(entreprise=ent, prenom=prenom, nom=nom, organisation=org, cellulaire=cell, courriel=courriel,
                            statut=statut, mode_paiement=paiement, canal_prefere=canal, notes="Client fictif (scénario d'essai).")
            client.full_clean()
            client.save()
            for ligne1, cp, lon, lat, rang in adresses:
                a = Adresse(entreprise=ent, client=client, secteur=secteurs[secteur], ligne1=ligne1, ville="Sainte-Adèle", code_postal=cp,
                            position=Point(lon, lat, srid=4326) if lon is not None else None,
                            position_source="manuelle" if lon is not None else "", ordre_tournee=rang)
                a.full_clean()
                a.save()
            c[cle] = client

        def contrat(client, prix, adresse=None, dates=None, emettre=True):
            k = Contrat.objects.create(entreprise=ent, client=client, adresse=adresse or client.adresses.first(), saison=saison,
                                       prix=Decimal(prix), prix_texte=f"{prix} $ plus taxes, en 2 versements")
            k.services.add(entree)
            v1, v2 = k.creer_echeancier(dates or [auj, date(2027, 1, 15)])
            f = v1.facturer()  # une seule facture pour la saison
            if emettre:
                f.emettre()
            return k, f, v2

        def message(client, genre, canal, sens, statut, contenu, il_y_a, **kw):
            m = Message.objects.create(entreprise=ent, client=client, genre=genre, canal=canal, sens=sens, statut=statut, contenu=contenu,
                                       destinataire=kw.pop("destinataire", "" if sens == "entrant" else (client.cellulaire if canal == "texto" else client.courriel) if client else ""),
                                       **kw)
            Message.objects.filter(pk=m.pk).update(cree_le=maintenant - il_y_a)
            return m

        # Deux adresses, deux contrats de la même saison
        g = c["deux_adresses"]
        a1, a2 = list(g.adresses.order_by("ordre_tournee"))
        # 1er versement payé il y a 45 jours, le 2e arrive aujourd'hui : rappel proposé dans « Versements à envoyer »
        _, f, _ = contrat(g, "520", a1, dates=[auj - timedelta(days=45), auj])
        Facture.objects.filter(pk=f.pk).update(date_facture=auj - timedelta(days=45))
        credits.encaisser(f, f.echeancier()[0][1], "interac", reference="CA1RAPPEL", date=auj - timedelta(days=44))
        contrat(g, "380", a2, emettre=False)  # facture de la saison en brouillon : à émettre et envoyer

        # Propriétaire non occupant (Ontario), locataire à aviser
        w = c["non_occupant"]
        w.facturation_ligne1, w.facturation_ville, w.facturation_province, w.facturation_code_postal = "88 Maple Street", "Ottawa", "ON", "K1A 0B1"
        w.notes = "Propriétaire non occupant, demeure en Ontario. Le locataire reçoit les avis de déneigement."
        w.proprietaire_non_occupant = True
        w.save()
        Contact.objects.create(entreprise=ent, client=w, nom="Karine Lefebvre", role="locataire", cellulaire="+14505550112",
                               note="Locataire du rez-de-chaussée")
        contrat(w, "600")

        # Payé plus que la facture : surplus en crédit au compte
        d = c["credit"]
        _, f, _ = contrat(d, "450")
        credits.encaisser(f, f.total + Decimal("50"), "comptant", surplus_permis=True)

        # Chèques postdatés : un à déposer (date arrivée), un à venir
        b = c["cheques"]
        _, f, v2 = contrat(b, "500")
        ChequePostdate.objects.create(entreprise=ent, client=b, facture=f, montant=f.total, numero="101", date_cheque=auj - timedelta(days=1))
        ChequePostdate.objects.create(entreprise=ent, client=b, versement=v2, montant=f.total, numero="102", date_cheque=date(2027, 1, 15))

        # Payé au complet par Interac, reçu envoyé
        lc = c["paye"]
        _, f, _ = contrat(lc, "420")
        p, _ = credits.encaisser(f, f.total, "interac", reference="CA9F2B7Q")
        message(lc, "recu_paiement", "courriel", "sortant", "envoye", f"Paiement de {f.total} $ reçu. Compte payé au complet. Merci!",
                timedelta(hours=3), sujet="Reçu de paiement")

        # En retard de 40 jours : relance proposée (deuxième avis), une relance déjà partie
        jp = c["en_retard"]
        _, f, _ = contrat(jp, "480")
        Facture.objects.filter(pk=f.pk).update(date_facture=auj - timedelta(days=55))
        f.versements.filter(rang=1).update(date_prevue=auj - timedelta(days=40))  # 1er versement en retard de 40 jours
        r = message(jp, "relance_1", "texto", "sortant", "envoye", "Rappel : un solde est dû sur votre compte. Merci de le régler!", timedelta(days=20))
        r.factures_jointes.add(f)

        # Sans coordonnées, et « ne pas relancer », chacun avec une facture due
        contrat(c["sans_coordonnees"], "400")
        cg = c["ne_pas_relancer"]
        cg.ne_pas_relancer = True
        cg.avis_operations = False  # ne veut pas d'avis pendant les opérations
        cg.save()
        _, f, _ = contrat(cg, "410")
        Facture.objects.filter(pk=f.pk).update(date_facture=auj - timedelta(days=50))
        f.versements.filter(rang=1).update(date_prevue=auj - timedelta(days=35))

        # Client d'été (paysagement) : pas dans la tournée; une job à la pièce terminée, à facturer
        from tournee.models import Job
        ete = c["ete"]
        ete.saisons = "ete"
        ete.save()
        Job.objects.create(entreprise=ent, client=ete, adresse=ete.adresses.first(), genre="paysagement",
                           depart_le=maintenant - timedelta(days=2, minutes=110), arrivee_le=maintenant - timedelta(days=2, minutes=95),
                           fin_le=maintenant - timedelta(days=2), distance_km=Decimal("6.4"), note="Taille de haie (fictif)")
        Client.objects.filter(pk=c["paye"].pk).update(saisons="les_deux")

        # Adresse introuvable : à placer sur la carte
        Adresse.objects.filter(client=c["mal_placee"]).update(position_precision="introuvable")

        # Virement Interac à confirmer, pour une facture due
        sylvie = Client.objects.get(entreprise=ent, nom="Roy")
        f_sylvie = sylvie.factures.filter(statut="emise").first()
        VirementInterac.objects.create(entreprise=ent, recu_le=maintenant - timedelta(hours=2), montant=f_sylvie.solde,
                                       envoyeur="SYLVIE ROY", message_envoyeur=f"Facture {f_sylvie.numero}", reference="CA7Q4X2M",
                                       client=sylvie, facture=f_sylvie, raison="numéro cité dans le message")

        # Messages reçus (lus et non lus), envoyés, en échec, d'inconnus, appel noté
        ginette = Client.objects.get(entreprise=ent, nom="Tremblay")
        lavoie = Client.objects.get(entreprise=ent, nom="Lavoie")
        oubli = message(ginette, "recu", "texto", "entrant", "recu", "Bonjour, mon entrée n'a pas été faite ce matin. Merci de repasser.",
                        timedelta(hours=1), expediteur=ginette.cellulaire, lu=False)
        message(lavoie, "recu", "courriel", "entrant", "recu", "Bonjour, pouvez-vous m'envoyer ma facture par courriel? Merci.",
                timedelta(hours=5), expediteur=lavoie.courriel, sujet="Ma facture", lu=False, message_id_externe="<essai-lavoie@example.com>")
        message(None, "recu", "texto", "entrant", "recu", "Bonjour, c'est Marc Dubé. Combien pour une entrée double rue des Essais?",
                timedelta(hours=7), expediteur="+14505550198", lu=False)
        message(None, "recu", "courriel", "entrant", "recu", "Bonjour, c'est Nathalie, voici ma nouvelle adresse courriel.",
                timedelta(days=1), expediteur="nathalie.nouvelle@example.com", sujet="Nouvelle adresse")
        message(sylvie, "facture", "courriel", "sortant", "envoye", "Voici votre facture.", timedelta(days=2), sujet="Votre facture", facture=f_sylvie)
        message(lavoie, "manuel", "texto", "sortant", "echec", "On passe demain matin.", timedelta(days=1), erreur="Numéro invalide (code 21211, essai)")
        message(ginette, "appel", "appel", "entrant", "recu", "Appel : demande si on peut pelleter le balcon cette semaine.",
                timedelta(days=3), expediteur=ginette.cellulaire)

        # Demandes : chaque statut et chaque cas
        Demande.objects.create(entreprise=ent, client=ginette, adresse=ginette.adresses.first(), genre="oubli", urgent=True,
                               description="Entrée oubliée ce matin.", source="texto", message=oubli)
        Demande.objects.create(entreprise=ent, client=lavoie, genre="plainte", description="Banc de neige devant la boîte aux lettres.",
                               vue_le=maintenant - timedelta(days=1))
        Demande.objects.create(entreprise=ent, client=d, adresse=d.adresses.first(), genre="dommage", urgent=True,
                               description="Haie abîmée par la souffleuse.", entente="Remplacer deux cèdres au printemps.",
                               cout=Decimal("180"), paye_par="deneigeur", vue_le=maintenant - timedelta(days=2))
        Demande.objects.create(entreprise=ent, client=lc, genre="service", statut="planifiee", prevue_le=auj + timedelta(days=2),
                               description="Pelleter le balcon arrière.", vue_le=maintenant)
        Demande.objects.create(entreprise=ent, client=g, genre="facture", statut="reglee", reglee_le=maintenant - timedelta(days=4),
                               reglement="Facture renvoyée par courriel.", description="Veut une copie de sa facture.", vue_le=maintenant)
        Demande.objects.create(entreprise=ent, genre="nouveau", contact="Marc Dubé, 450 555-0198", description="Prix pour une entrée double.")

        # Une opération terminée cette nuit : passages faits et sautés
        op = Operation.objects.create(entreprise=ent, type="neige", debut=maintenant - timedelta(hours=9), fin=maintenant - timedelta(hours=5),
                                      note="Opération d'essai")
        for i, a in enumerate(Adresse.objects.filter(entreprise=ent, client__statut="actif", position__isnull=False).order_by("secteur__ordre", "ordre_tournee")[:10]):
            saute = i in (3, 7)
            Passage.objects.create(entreprise=ent, operation=op, adresse=a, statut="saute" if saute else "fait",
                                   raison="auto" if saute else "", heure=op.debut + timedelta(minutes=12 * (i + 1)),
                                   note="Auto dans l'entrée" if saute else "")
        # Positions du cellulaire pendant l'opération : arrivée à chaque entrée quelques minutes avant la tape « Fait »
        # (temps par entrée, lot C), sauf une entrée sans position
        from tournee.models import PositionGPS
        from tournee.temps import calculer
        for i, passage in enumerate(op.passages.filter(statut="fait").select_related("adresse").order_by("heure")):
            if i == 2:
                continue
            PositionGPS.objects.create(operation=op, position=passage.adresse.position, precision_m=12,
                                       moment=passage.heure - timedelta(minutes=4 + i % 4))
        calculer(op)
        from tournee import services as tournee_services
        for passage in op.passages.filter(statut="fait"):  # client au passage : sa facture du passage, à envoyer
            tournee_services._facturer(passage)
            passage.save(update_fields=["ligne_facture"])

        # Balises posées (une adresse sur deux)
        for a in Adresse.objects.filter(entreprise=ent, client__statut="actif")[::2]:
            Balisage.objects.create(entreprise=ent, adresse=a, nombre=2, posees_le=date(2026, 10, 20))

        # Dépenses (sans photo)
        for jours, cat, four, total in [(1, "carburant", "Station fictive", "86.40"), (6, "abrasifs", "Quincaillerie Exemple", "142.10"),
                                        (12, "reparation", "Garage de l'Essai", "389.55"), (20, "telephone", "Fournisseur fictif", "65.00")]:
            tps, tvq = taxes_du_total(Decimal(total), ent)
            Depense.objects.create(entreprise=ent, date=auj - timedelta(days=jours), categorie=cat, fournisseur=four,
                                   total=Decimal(total), tps=tps, tvq=tvq, note="Dépense fictive")

        return (f"Scénarios : {len(c)} clients de plus (deux adresses, propriétaire non occupant avec locataire, crédit, chèques postdatés, "
                f"payé, en retard, sans coordonnées, ne pas relancer, client d'été avec une job à facturer, adresse introuvable), virement Interac à confirmer, 7 messages, "
                f"6 demandes, 1 opération terminée, balises, 4 dépenses.")
