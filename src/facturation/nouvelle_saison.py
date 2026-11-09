"""Nouvelle saison à partir de la précédente (PRD B5) : mêmes clients et contrats, prix ajustés en pour cent,
échéanciers reportés d'un an. Seuls les clients actifs sont repris (inactifs, en recouvrement et liste noire :
à refaire à la main, au cas par cas). Rien n'est facturé ni envoyé : les versements deviennent des brouillons
à leur date, comme d'habitude."""
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from clients.models import Client
from facturation.calculs import arrondir
from facturation.models import Contrat, Saison

ARRONDIS = {"cent": Decimal("0.01"), "dollar": Decimal("1"), "cinq": Decimal("5")}


def plus_un_an(d):
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # 29 février
        return date(d.year + 1, d.month, 28)


def nom_suivant(saison):
    m = re.fullmatch(r"(\d{4})-(\d{4})", saison.nom)
    if m:
        return f"{int(m[1]) + 1}-{int(m[2]) + 1}"
    return f"{saison.debut.year + 1}-{saison.debut.year + 2}"


def nouveau_prix(prix, pourcent, arrondi="dollar"):
    pas = ARRONDIS.get(arrondi, ARRONDIS["dollar"])
    brut = Decimal(prix) * (1 + Decimal(pourcent) / 100)
    return arrondir((brut / pas).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * pas)


@dataclass
class Apercu:
    saison: Saison
    nom: str
    debut: date
    fin: date
    lignes: list = field(default_factory=list)
    exclus: int = 0
    existe: bool = False

    @property
    def total_avant(self):
        return sum((l["avant"] for l in self.lignes), Decimal("0"))

    @property
    def total_apres(self):
        return sum((l["apres"] for l in self.lignes), Decimal("0"))


def apercu(saison, pourcent=0, arrondi="dollar"):
    a = Apercu(saison=saison, nom=nom_suivant(saison), debut=plus_un_an(saison.debut), fin=plus_un_an(saison.fin))
    a.existe = Saison.objects.filter(entreprise=saison.entreprise, nom=a.nom).exists()
    for c in (saison.contrats.filter(actif=True).select_related("client", "adresse")
              .prefetch_related("versements").order_by("client__nom", "client__prenom")):
        if c.client.statut != Client.Statut.ACTIF:
            a.exclus += 1
            continue
        a.lignes.append({"contrat": c, "avant": c.prix, "apres": nouveau_prix(c.prix, pourcent, arrondi),
                         "dates": [plus_un_an(v.date_prevue) for v in c.versements.all()]})
    return a


def creer(saison, pourcent=0, arrondi="dollar"):
    a = apercu(saison, pourcent, arrondi)
    if a.existe:
        raise ValidationError(f"La saison {a.nom} existe déjà.")
    with transaction.atomic():
        nouvelle = Saison.objects.create(entreprise=saison.entreprise, nom=a.nom, debut=a.debut, fin=a.fin)
        for l in a.lignes:
            v = l["contrat"]
            c = Contrat.objects.create(entreprise=v.entreprise, client=v.client, adresse=v.adresse, saison=nouvelle, type=v.type,
                                       prix=l["apres"], prix_texte="", notes=v.notes)
            c.services.set(v.services.all())
            if c.type == Contrat.Type.SAISONNIER and l["dates"]:
                c.creer_echeancier(l["dates"])
    return nouvelle, a
