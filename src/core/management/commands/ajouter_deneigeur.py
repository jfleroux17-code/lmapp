"""Ajout d'un déneigeur en quelques minutes (PRD Q4, section P point 2).

  docker compose run --rm app python manage.py ajouter_deneigeur martin --nom "Déneigement Martin" \
      --ville "Saint-Sauveur" --utilisateur martin --courriel martin@example.com            (essai à blanc)
  ... --appliquer                                                                              (pour vrai)

Crée la fiche Entreprise (sous-domaine <slug>.ledeneigeur.com, adresse d'affaires <slug>@ledeneigeur.com,
envois réels éteints, mode « déneigeur seul »), sa ville desservie par défaut, et l'utilisateur
administrateur de l'entreprise, sans mot de passe utilisable (à définir avec `changepassword`).
Les gestes réseau (DNS, Caddy, ALLOWED_HOSTS, boîte courriel, numéro Twilio) sont affichés, pas faits :
ils restent confirmés par JF (CLAUDE.md, règle 2).
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from core.models import Entreprise, Membre, VilleDesservie

DOMAINE = "ledeneigeur.com"


class Command(BaseCommand):
    help = "Ajoute un déneigeur (fiche, ville, administrateur) et affiche les étapes réseau à faire."

    def add_arguments(self, parser):
        parser.add_argument("slug", help="Identifiant court, sans accent ni espace (devient le sous-domaine), ex. martin")
        parser.add_argument("--nom", required=True, help="Nom de l'entreprise affiché")
        parser.add_argument("--ville", required=True, help="Ville desservie par défaut, ex. Saint-Sauveur")
        parser.add_argument("--rayon-km", type=float, default=8, help="Rayon de la zone de service (km)")
        parser.add_argument("--utilisateur", required=True, help="Nom d'utilisateur du propriétaire")
        parser.add_argument("--courriel", default="", help="Courriel du propriétaire (son compte)")
        parser.add_argument("--appliquer", action="store_true", help="Créer pour vrai (sinon : essai à blanc)")

    def handle(self, slug, nom, ville, rayon_km, utilisateur, courriel, appliquer, **_):
        if slugify(slug) != slug or not slug:
            raise CommandError(f"« {slug} » : lettres minuscules, chiffres et traits d'union seulement (ex. {slugify(slug) or 'martin'}).")
        domaine, boite = f"{slug}.{DOMAINE}", f"{slug}@{DOMAINE}"
        if Entreprise.objects.filter(slug=slug).exists() or Entreprise.objects.filter(domaine=domaine).exists():
            raise CommandError(f"Une entreprise « {slug} » ou le domaine {domaine} existe déjà.")
        U = get_user_model()
        existant = U.objects.filter(username=utilisateur).first()
        w = self.stdout.write
        w(f"Entreprise : {nom} ({slug}), {domaine}, adresse d'affaires {boite}, mode « déneigeur seul », envois réels éteints")
        w(f"Ville desservie par défaut : {ville} (rayon {rayon_km:g} km)")
        w(f"Administrateur : {utilisateur}" + (" (compte existant, ajouté comme membre)" if existant else " (nouveau compte, sans mot de passe)"))
        if not appliquer:
            w(self.style.WARNING("ESSAI À BLANC : rien n'a été créé. Relancer avec --appliquer."))
            return
        with transaction.atomic():
            ent = Entreprise(nom=nom, slug=slug, domaine=domaine, ville=ville, courriel_reponse=boite, signature_messages=nom)
            ent.full_clean()
            ent.save()
            v = VilleDesservie(entreprise=ent, nom=ville, rayon_km=rayon_km, par_defaut=True)
            v.full_clean()
            v.save()
            u = existant or U.objects.create_user(utilisateur, email=courriel)
            if not existant:
                u.set_unusable_password()
                u.save(update_fields=["password"])
            Membre.objects.create(utilisateur=u, entreprise=ent, role=Membre.Role.ADMINISTRATEUR)
        w(self.style.SUCCESS(f"Créé : {ent} ({domaine})."))
        w("")
        w("À faire, dans l'ordre (gestes réseau : avec le « go » de JF) :")
        etapes = [
            f"Cloudflare : enregistrement A « {slug} » vers 216.46.12.226, DNS seulement (nuage gris).",
            f"edge/Caddyfile : bloc\n       {domaine} {{\n           import commun\n           reverse_proxy lmapp-prod-app:8000\n       }}\n"
            "     puis : cd /srv/lmapp/edge && docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile",
            f"/srv/lmapp/.env : ajouter {domaine} à DJANGO_ALLOWED_HOSTS, puis : cd /srv/lmapp && docker compose up -d",
            f"Serveur de courriel (cPanel de JF) : boîte {boite}, 2 Go.",
            f"Mot de passe du propriétaire : docker compose run --rm app python manage.py changepassword {utilisateur}",
            f"Administration, fiche « {nom} » : Enregistrer une fois (centre de la ville rempli), coordonnées, taxes, numéro de la prochaine facture.",
            "Twilio (si textos) : numéro local, puis « numéro de texto d'affaires » dans la fiche. Interrupteur « envois réels » : seulement avec le « go » de JF.",
            "Import des clients : manage.py importer_clients ... --entreprise " + slug + " (essai à blanc d'abord; --depuis <logiciel> s'il vient d'un concurrent).",
            f"Vérifier : https://{domaine}/sante/ et la connexion du propriétaire.",
        ]
        for i, e in enumerate(etapes, start=1):
            w(f"  {i}. {e}")
