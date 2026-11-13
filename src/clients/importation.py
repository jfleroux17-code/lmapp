"""Import des clients et de leurs adresses de service (PRD A9).

Principes :
  - une ligne du fichier = une adresse de service; un client qui a plusieurs
    adresses revient sur plusieurs lignes avec le même « no_client »;
  - essai à blanc par défaut : on lit, on valide, on montre; rien n'est écrit
    sans demande explicite;
  - tout ou rien : l'écriture se fait dans une seule transaction;
  - on réutilise les règles des modèles (full_clean) : une donnée refusée dans
    l'administration est refusée ici aussi;
  - une ligne déjà en base (même cellulaire ou même adresse) est ignorée, pour
    qu'on puisse relancer l'import après avoir corrigé les erreurs.
"""
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from clients.models import Adresse, Client, Secteur
from core.models import VilleDesservie
from facturation import calculs, credits
from facturation.models import Contrat, Credit, Facture, Saison, Service
from core import telephone
from core.texte import cle, cle_ville

# ---------------------------------------------------------------------------
# Colonnes du gabarit
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Colonne:
    cle: str
    titre: str
    explication: str
    exemple1: str = ""
    exemple2: str = ""
    obligatoire: bool = False
    argent: bool = False  # contrat ou solde dû (app facturation)


COLONNES = [
    Colonne("no_client", "no_client", "Numéro de client de Louis, s'il en a un. Sert à regrouper plusieurs adresses d'un même payeur : répéter la ligne avec le même numéro.", "101", "102"),
    Colonne("prenom", "prenom", "Prénom.", "Ginette", ""),
    Colonne("nom", "nom", "Nom de famille. Il faut au moins un prénom, un nom ou une organisation.", "Tremblay", "Fortin", obligatoire=True),
    Colonne("organisation", "organisation", "Pour un client commercial : entreprise, syndicat de copropriété, etc.", "", "Syndicat Les Sapins fictifs"),
    Colonne("cellulaire", "cellulaire", "Cellulaire pour les textos. N'importe quel format : 450-555-0101, (450) 555-0101, 4505550101.", "450 555-0101", "450 555-0107"),
    Colonne("autre_telephone", "autre_telephone", "Autre numéro (maison, bureau).", "", "450 555-0199"),
    Colonne("courriel", "courriel", "Adresse courriel.", "ginette.tremblay@example.com", "gestion.sapins@example.com"),
    Colonne("adresse", "adresse", "Adresse de service : numéro civique et rue.", "120, rue des Essais", "300, boulevard Imaginaire", obligatoire=True),
    Colonne("adresse_suite", "adresse_suite", "Appartement, unité, etc.", "", ""),
    Colonne("ville", "ville", "Ville de l'adresse de service. Vide : la ville par défaut de l'entreprise (ex. Sainte-Adèle).", "Sainte-Adèle", "Sainte-Adèle"),
    Colonne("code_postal", "code_postal", "Code postal (J8B 1A1 ou j8b1a1).", "J8B 1A1", "J8B 1B2"),
    Colonne("secteur", "secteur", "Secteur ou route. Créé automatiquement s'il n'existe pas.", "Village", "Mont-Rolland"),
    Colonne("rang_tournee", "rang_tournee", "Rang de l'arrêt dans l'ordre habituel de la tournée (1, 2, 3...).", "1", "3"),
    Colonne("ou_mettre_neige", "ou_mettre_neige", "Où pousser la neige.", "À gauche, pas sur la haie", ""),
    Colonne("obstacles", "obstacles", "Bordures, roches, aménagement à éviter.", "", "Bordure de béton à droite"),
    Colonne("borne_fontaine", "borne_fontaine", "Borne-fontaine à dégager : oui ou non (vide = non).", "non", "oui"),
    Colonne("entree_en_pente", "entree_en_pente", "Entrée en pente : oui ou non (vide = non).", "oui", "non"),
    Colonne("consignes", "consignes", "Consignes spéciales.", "", "12 places, passer avant 7 h"),
    Colonne("mode_paiement", "mode_paiement", "comptant, interac, cheque ou carte.", "comptant", "interac"),
    Colonne("canal", "canal", "Pour joindre le client : texto, courriel ou les deux (vide = texto).", "texto", "courriel"),
    Colonne("langue", "langue", "fr ou en (vide = fr).", "fr", "fr"),
    Colonne("statut", "statut", "actif, inactif, recouvrement ou liste noire (vide = actif).", "actif", "actif"),
    Colonne("consentement_commercial", "consentement_commercial", "Le client accepte les messages commerciaux (renouvellement, offres) : oui ou non. Les avis de passage et les factures n'en ont pas besoin.", "oui", "non"),
    Colonne("consentement_date", "consentement_date", "Date du consentement (AAAA-MM-JJ). Si vide et consentement à oui : date de l'import.", "2026-10-15", ""),
    Colonne("facturation_adresse", "facturation_adresse", "Adresse de facturation, seulement si différente de l'adresse de service.", "", "C.P. 123, succursale Exemple"),
    Colonne("facturation_ville", "facturation_ville", "Ville de facturation.", "", "Saint-Jérôme"),
    Colonne("facturation_code_postal", "facturation_code_postal", "Code postal de facturation.", "", "J7Z 1A1"),
    Colonne("notes", "notes", "Notes libres.", "", ""),
    Colonne("prix_saison", "prix_saison", "Prix entendu pour la saison, en dollars (450 ou 450,00) : avant taxes, sauf si taxes_incluses = oui. Crée un contrat dans la saison en cours (la saison doit exister dans l'administration). Au passage : le prix d'un passage.", "450,00", "2400,00", argent=True),
    Colonne("type_contrat", "type_contrat", "saisonnier ou au passage (vide = saisonnier). À l'heure ou sur demande : contrat à créer à la main.", "saisonnier", "saisonnier", argent=True),
    Colonne("versements", "versements", "Nombre de versements du contrat saisonnier (1 à 4). Vide : celui de la fiche de l'entreprise. Le 1er est daté de l'import; sa facture (brouillon) est préparée la nuit suivante, avec un avis au cellulaire, les autres quelques jours avant les dates de l'entreprise (réglage « jours d'avance »). Ex. 3 si le client paie en 3 fois.", "", "", argent=True),
    Colonne("taxes_incluses", "taxes_incluses", "Le prix (et l'extra) comprend déjà les taxes : oui ou non (vide = non, les taxes s'ajoutent). L'import calcule le prix avant taxes qui redonne exactement ce total.", "non", "oui", argent=True),
    Colonne("service", "service", "Service principal du contrat (ex. Déneigement de l'entrée, Bordage). Créé dans le catalogue s'il n'existe pas. Vide : aucun.", "Déneigement de l'entrée", "Déneigement de l'entrée", argent=True),
    Colonne("extra_service", "extra_service", "Service ajouté au même contrat (ex. Sablage). Créé dans le catalogue s'il n'existe pas.", "Sablage", "", argent=True),
    Colonne("extra_prix", "extra_prix", "Prix de l'extra pour la saison, ajouté au prix du contrat (même règle de taxes que prix_saison).", "100,00", "", argent=True),
    Colonne("prix_entendu_texte", "prix_entendu_texte", "Le prix tel qu'entendu avec le client, en mots.", "450 $ en 2 versements", "200 $ par mois, nov. à avril", argent=True),
    Colonne("solde_du", "solde_du", "Montant que le client doit encore des saisons passées, en dollars (taxes déjà comprises). Devient un « solde antérieur » à recevoir.", "", "350,00", argent=True),
    Colonne("solde_saison", "solde_saison", "Saison d'origine du solde dû (ex. 2025-2026).", "", "2025-2026", argent=True),
    Colonne("solde_note", "solde_note", "Note sur le solde dû (interne, jamais montrée au client).", "", "Facture de mars jamais payée", argent=True),
    Colonne("recu_montant", "recu_montant", "Argent déjà reçu du client cette saison, avant l'app, taxes comprises. Devient un crédit au compte, qui paie la prochaine facture émise (le 1er versement).", "200,00", "", argent=True),
    Colonne("recu_date", "recu_date", "Date où cet argent a été reçu (AAAA-MM-JJ). Vide : date de l'import.", "2026-11-01", "", argent=True),
    Colonne("recu_mode", "recu_mode", "comptant, interac, cheque, debit ou carte. Vide : le mode_paiement du client.", "", "", argent=True),
]
PAR_CLE = {c.cle: c for c in COLONNES}

ALIAS = {
    "numero_client": "no_client", "no": "no_client", "code_client": "no_client", "numero": "no_client",
    "cell": "cellulaire", "telephone_cellulaire": "cellulaire", "no_cellulaire": "cellulaire", "mobile": "cellulaire",
    "telephone": "autre_telephone", "tel": "autre_telephone", "telephone_maison": "autre_telephone",
    "email": "courriel", "adresse_courriel": "courriel", "mail": "courriel",
    "adresse_de_service": "adresse", "adresse_civique": "adresse", "rue": "adresse",
    "appartement": "adresse_suite", "app": "adresse_suite", "unite": "adresse_suite",
    "municipalite": "ville", "cp": "code_postal",
    "route": "secteur", "rang": "rang_tournee", "ordre": "rang_tournee", "ordre_tournee": "rang_tournee",
    "paiement": "mode_paiement", "mode_de_paiement": "mode_paiement",
    "prix": "prix_saison", "prix_de_la_saison": "prix_saison",
    "montant_recu": "recu_montant", "recu": "recu_montant", "deja_paye": "recu_montant", "date_recu": "recu_date", "mode_recu": "recu_mode",
    "solde": "solde_du", "montant_du": "solde_du", "du": "solde_du",
    "nom_complet": "nom", "client": "nom", "nom_du_client": "nom", "entreprise": "organisation", "compagnie": "organisation",
    # Entêtes anglais courants (exports de logiciels canadiens et américains, PRD Q3)
    "first_name": "prenom", "firstname": "prenom", "last_name": "nom", "lastname": "nom", "name": "nom", "full_name": "nom",
    "customer": "nom", "customer_name": "nom", "client_name": "nom", "company": "organisation", "company_name": "organisation",
    "mobile_phone": "cellulaire", "cell_phone": "cellulaire", "cellphone": "cellulaire", "mobile_number": "cellulaire",
    "phone": "autre_telephone", "home_phone": "autre_telephone", "phone_number": "autre_telephone", "work_phone": "autre_telephone",
    "email_address": "courriel", "e_mail": "courriel",
    "address": "adresse", "street": "adresse", "street_address": "adresse", "address_1": "adresse", "address_line_1": "adresse",
    "service_address": "adresse", "property_address": "adresse",
    "address_2": "adresse_suite", "address_line_2": "adresse_suite", "unit": "adresse_suite", "apt": "adresse_suite",
    "city": "ville", "town": "ville", "postal_code": "code_postal", "postal": "code_postal", "zip": "code_postal", "zip_code": "code_postal",
    "route_order": "rang_tournee", "stop": "rang_tournee", "stop_order": "rang_tournee", "sequence": "rang_tournee",
    "note": "notes", "comments": "notes", "instructions": "consignes", "special_instructions": "consignes",
    "payment_method": "mode_paiement", "season_price": "prix_saison", "contract_price": "prix_saison", "price": "prix_saison",
    "balance": "solde_du", "balance_due": "solde_du", "amount_owing": "solde_du", "outstanding": "solde_du",
}

# Correspondances par logiciel d'origine (PRD Q3) : clients/correspondances/<logiciel>.json, {"entête du fichier": "colonne"}.
# Faites à partir d'un vrai fichier exporté par le déneigeur; une colonne à ignorer : "".
DOSSIER_CORRESPONDANCES = Path(__file__).resolve().parent / "correspondances"


def correspondance_du_logiciel(nom):
    import json

    chemin = DOSSIER_CORRESPONDANCES / f"{cle(nom)}.json"
    if not chemin.exists():
        connus = sorted(p.stem for p in DOSSIER_CORRESPONDANCES.glob("*.json"))
        liste = ", ".join(connus) or "aucune pour l'instant"
        raise FileNotFoundError(f"Pas de correspondance pour « {nom} ». Connues : {liste}.")
    return json.loads(chemin.read_text(encoding="utf-8"))

# ---------------------------------------------------------------------------
# Normalisation des valeurs
# ---------------------------------------------------------------------------


_cle = cle  # « Prénom » -> prenom, « Rang tournée » -> rang_tournee


_OUI = {"oui", "o", "x", "1", "vrai", "yes", "y", "true"}
_NON = {"", "non", "n", "0", "faux", "no", "false"}

CHOIX = {
    "mode_paiement": {
        "": "", "comptant": "comptant", "cash": "comptant", "argent": "comptant",
        "interac": "interac", "virement": "interac", "virement_interac": "interac", "e_transfert": "interac",
        "cheque": "cheque", "cheques": "cheque",
        "carte": "carte", "carte_de_credit": "carte", "credit": "carte", "visa": "carte", "mastercard": "carte",
    },
    "canal": {
        "": "texto", "texto": "texto", "sms": "texto", "cellulaire": "texto",
        "courriel": "courriel", "email": "courriel",
        "les_deux": "les_deux", "deux": "les_deux", "texto_et_courriel": "les_deux", "texto_courriel": "les_deux",
    },
    "langue": {"": "fr", "fr": "fr", "francais": "fr", "en": "en", "anglais": "en", "english": "en"},
    "statut": {
        "": "actif", "actif": "actif", "inactif": "inactif",
        "recouvrement": "recouvrement", "en_recouvrement": "recouvrement",
        "liste_noire": "liste_noire", "noire": "liste_noire",
    },
    "recu_mode": {
        "": "", "comptant": "comptant", "cash": "comptant", "argent": "comptant",
        "interac": "interac", "virement": "interac", "virement_interac": "interac", "e_transfert": "interac", "v_i": "interac", "vi": "interac",
        "cheque": "cheque", "cheques": "cheque", "debit": "debit", "carte_debit": "debit",
        "carte": "carte", "carte_de_credit": "carte", "visa": "carte", "mastercard": "carte",
    },
    "type_contrat": {
        "": "", "saisonnier": "saisonnier", "saison": "saisonnier", "forfait": "saisonnier",
        "au_passage": "passage", "passage": "passage",
        "a_l_heure": "heure", "heure": "heure", "sur_demande": "demande", "demande": "demande",
    },
}


# Types de contrat que l'import sait créer (les autres : à la main)
TYPES_IMPORTES = {"saisonnier": Contrat.Type.SAISONNIER, "passage": Contrat.Type.AU_PASSAGE}


def saison_en_cours(entreprise):
    """La saison qui contient aujourd'hui, sinon la plus récente. Aucune : une saison à créer
    (non enregistrée), du 1er novembre au 30 avril, modifiable ensuite dans l'administration."""
    aujourdhui = timezone.localdate()
    qs = Saison.objects.filter(entreprise=entreprise)
    existante = qs.filter(debut__lte=aujourdhui, fin__gte=aujourdhui).first() or qs.order_by("-debut").first()
    if existante:
        return existante
    an = aujourdhui.year if aujourdhui.month >= 7 else aujourdhui.year - 1
    return Saison(entreprise=entreprise, nom=f"{an}-{an + 1}", debut=date(an, 11, 1), fin=date(an + 1, 4, 30))


@dataclass
class Resultat:
    clients: int = 0
    adresses: int = 0
    contrats: int = 0
    soldes: int = 0
    services: int = 0
    credits: int = 0


# Valeurs telles qu'écrites dans le gabarit, pour les messages d'erreur
PERMIS_AFFICHES = {"les_deux": "les deux", "liste_noire": "liste noire", "passage": "au passage", "heure": "à l'heure", "demande": "sur demande"}


def _oui_non(valeur, colonne):
    v = _cle(valeur)
    if v in _OUI:
        return True
    if v in _NON:
        return False
    raise ValueError(f"{colonne} : « {valeur} » n'est ni oui ni non")


def _choix(valeur, colonne):
    v = _cle(valeur)
    if v not in CHOIX[colonne]:
        permis = sorted({PERMIS_AFFICHES.get(v, v) for v in CHOIX[colonne].values() if v})
        raise ValueError(f"{colonne} : « {valeur} » inconnu (permis : {', '.join(permis)})")
    return CHOIX[colonne][v]


def _date(valeur, colonne):
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    v = str(valeur or "").strip()
    if not v:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"{colonne} : date « {v} » illisible (format attendu AAAA-MM-JJ)")


def _montant(valeur, colonne):
    v = str(valeur or "").strip()
    if not v:
        return None
    v = v.replace("$", "").replace(" ", "").replace(" ", "")
    if "," in v and "." in v:  # 1.250,50 ou 1,250.50 : le dernier séparateur est la décimale
        v = v.replace(".", "").replace(",", ".") if v.rfind(",") > v.rfind(".") else v.replace(",", "")
    else:
        v = v.replace(",", ".")
    try:
        m = Decimal(v).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise ValueError(f"{colonne} : montant « {valeur} » illisible")
    if m < 0:
        raise ValueError(f"{colonne} : montant négatif")
    return m


def _entier(valeur, colonne):
    v = str(valeur or "").strip()
    if not v:
        return None
    try:
        n = int(float(v.replace(",", ".")))
    except ValueError:
        raise ValueError(f"{colonne} : « {valeur} » n'est pas un nombre")
    if n < 0:
        raise ValueError(f"{colonne} : nombre négatif")
    return n


def _texte(valeur):
    if valeur is None:
        return ""
    if isinstance(valeur, float) and valeur.is_integer():
        valeur = int(valeur)  # Excel range les numéros de téléphone en nombres
    return re.sub(r"\s+", " ", str(valeur)).strip()


def _cle_adresse(ligne1, ville):
    return (_cle(ligne1), _cle(ville))


# ---------------------------------------------------------------------------
# Lecture du fichier
# ---------------------------------------------------------------------------


@dataclass
class Fichier:
    format: str
    entetes_brutes: list
    lignes: list  # [(numéro de ligne dans le fichier, [valeurs])]
    encodage: str = ""
    separateur: str = ""


def lire(chemin):
    chemin = Path(chemin)
    if chemin.suffix.lower() in (".xlsx", ".xlsm"):
        return _lire_xlsx(chemin)
    return _lire_csv(chemin.read_bytes())


def _lire_xlsx(chemin):
    from openpyxl import load_workbook

    classeur = load_workbook(chemin, read_only=True, data_only=True)
    feuille = classeur["Clients"] if "Clients" in classeur.sheetnames else classeur.active
    rangees = feuille.iter_rows(values_only=True)
    entetes = [_texte(v) for v in next(rangees, [])]
    lignes = [(i, list(r)) for i, r in enumerate(rangees, start=2)]
    classeur.close()
    return Fichier("Excel", entetes, lignes)


def _lire_csv(octets):
    for encodage in ("utf-8-sig", "cp1252"):
        try:
            texte = octets.decode(encodage)
            break
        except UnicodeDecodeError:
            continue
    premiere = texte.split("\n", 1)[0]
    separateur = max(";,\t", key=premiere.count)
    lecteur = csv.reader(io.StringIO(texte), delimiter=separateur)
    entetes = next(lecteur, [])
    lignes = [(i, r) for i, r in enumerate(lecteur, start=2)]
    nom_encodage = "UTF-8" if encodage == "utf-8-sig" else "Windows-1252"
    return Fichier("CSV", entetes, lignes, nom_encodage, {";": "point-virgule", ",": "virgule", "\t": "tabulation"}[separateur])


# ---------------------------------------------------------------------------
# Analyse
# ---------------------------------------------------------------------------


@dataclass
class Ligne:
    numero: int
    statut: str = "a_creer"  # a_creer, adresse_seulement, existe, erreur
    erreurs: list = field(default_factory=list)
    avertissements: list = field(default_factory=list)
    client: Client = None
    adresse: Adresse = None
    secteur_nom: str = ""
    groupe: str = ""
    argent: dict = field(default_factory=dict)  # valeurs des colonnes d'argent, telles que lues
    calcul: dict = field(default_factory=dict)  # tiré de l'argent : prix du contrat, services, reçu (pour l'écriture)

    @property
    def description(self):
        if self.client is None:
            return ""
        return f"{self.client.nom_affiche}, {self.adresse.ligne1 if self.adresse else ''}, {self.adresse.ville if self.adresse else ''}"


@dataclass
class Analyse:
    fichier: Fichier
    colonnes: dict  # index -> clé
    inconnues: list
    manquantes: list
    lignes: list
    secteurs_nouveaux: list
    saison: Saison = None  # saison des contrats créés par l'import
    services_nouveaux: list = field(default_factory=list)

    @property
    def erreurs(self):
        return [l for l in self.lignes if l.statut == "erreur"]

    @property
    def a_creer(self):
        return [l for l in self.lignes if l.statut in ("a_creer", "adresse_seulement")]

    @property
    def existantes(self):
        return [l for l in self.lignes if l.statut == "existe"]

    @property
    def nb_clients(self):
        return sum(1 for l in self.lignes if l.statut == "a_creer")

    @property
    def colonnes_argent(self):
        return [k for k in self.colonnes.values() if PAR_CLE[k].argent]

    def _a_importer(self, cle):
        return [l for l in self.lignes if l.statut in ("a_creer", "adresse_seulement") and l.argent.get(cle)]

    @property
    def nb_contrats(self):
        return sum(1 for l in self._a_importer("prix_saison") if l.argent.get("type_contrat", "saisonnier") in TYPES_IMPORTES)

    @property
    def nb_soldes(self):
        return len(self._a_importer("solde_du"))

    @property
    def recus(self):
        return self._a_importer("recu_montant")

    @property
    def statuts(self):
        """Nombre de clients à créer par statut, pour l'essai à blanc (un ex-client gardé actif saute aux yeux)."""
        from collections import Counter

        return Counter(l.client.get_statut_display().lower() for l in self.lignes if l.statut == "a_creer")


def _messages(erreur):
    if hasattr(erreur, "message_dict"):
        return [f"{champ} : {m}" if champ != "__all__" else m for champ, ms in erreur.message_dict.items() for m in ms]
    return list(erreur.messages)


def _verifier_argent(l, entreprise, saison, services_existants, services_nouveaux, g):
    """Taxes incluses, services et extra du contrat, argent déjà reçu. Remplit l.argent (prix_contrat, prix_texte,
    services, recu_*) pour l'écriture."""
    a, c_ = l.argent, l.calcul
    type_c = a.get("type_contrat") or "saisonnier"
    contrat = a.get("prix_saison") is not None and type_c in TYPES_IMPORTES
    saisonnier = contrat and TYPES_IMPORTES[type_c] == Contrat.Type.SAISONNIER

    # Services (catalogue de l'entreprise, créés au besoin)
    noms = [n for n in (g("service"), g("extra_service")) if n]
    if noms and not contrat:
        l.avertissements.append("service ou extra sans contrat (prix_saison) : ignoré")
    c_["services"] = []
    for n in noms if contrat else []:
        cs = _cle(n)
        c_["services"].append(services_existants.get(cs) or services_nouveaux.setdefault(cs, n))

    # Extra : même contrat, prix ajouté
    extra = a.get("extra_prix")
    if extra and not g("extra_service"):
        l.erreurs.append("extra_prix sans extra_service : nommer le service (ex. Sablage)")
    if g("extra_service") and contrat and not extra:
        l.avertissements.append(f"extra « {g('extra_service')} » sans extra_prix : service ajouté au contrat, prix inchangé")
    if extra and contrat and not saisonnier:
        l.erreurs.append("extra_prix sur un contrat au passage : à faire à la main")
        extra = None

    # Prix du contrat, ramené avant taxes au besoin
    if contrat and a.get("prix_saison") is not None:
        brut = a["prix_saison"] + (extra or 0)
        prix = brut
        incluses = bool(a.get("taxes_incluses"))
        if incluses and entreprise.inscrit_taxes:
            nb = (a.get("versements") or entreprise.versements_par_defaut) if saisonnier else 1
            nb = nb if 1 <= nb <= 4 else 1
            # Une seule facture pour la saison : taxes calculées une fois, sur le total (décision de JF, 12 novembre 2026)
            prix, exact = calculs.prix_avant_taxes(brut, entreprise.taux_tps, entreprise.taux_tvq, 1)
            if not exact:
                l.avertissements.append(f"taxes incluses : {brut} $ impossible au cent près (arrondi des taxes), "
                                        f"prix avant taxes {prix} $")
        c_["prix_contrat"] = prix
        texte = a.get("prix_entendu_texte", "")
        if not texte and (incluses or extra):
            texte = f"{_argent(a['prix_saison'])}" + (f" + {_argent(extra)} {g('extra_service').lower()}" if extra else "")
            texte += " taxes incluses" if incluses else " plus taxes"
        c_["prix_texte"] = texte
    elif a.get("taxes_incluses"):
        l.avertissements.append("taxes_incluses sans prix_saison : ignoré")

    # Argent déjà reçu : crédit au compte
    recu = a.get("recu_montant")
    if recu:
        mode = a.get("recu_mode") or CHOIX["recu_mode"].get(_cle(g("mode_paiement")), "")
        if not mode:
            l.erreurs.append("recu_montant sans recu_mode (ni mode_paiement) : dire comment l'argent a été reçu")
        c_["recu_mode_effectif"] = mode
        quand = a.get("recu_date")
        aujourdhui = timezone.localdate()
        if quand is None:
            quand = aujourdhui
            l.avertissements.append("recu_montant sans recu_date : date de l'import inscrite")
        elif quand > aujourdhui:
            l.erreurs.append(f"recu_date : {quand:%Y-%m-%d} est dans le futur (chèque postdaté : à noter plus tard, pas ici)")
        elif saison is not None and quand < saison.debut:
            l.avertissements.append(f"recu_date : {quand:%Y-%m-%d}, avant la saison {saison} (pas compté dans son bilan)")
        c_["recu_date_effective"] = quand
        if not contrat and not a.get("solde_du"):
            l.avertissements.append(f"{_argent(recu)} reçus sans contrat ni solde : restent en crédit au compte")
        if a.get("solde_du"):
            l.avertissements.append("argent reçu et solde antérieur : le reçu paie d'abord le solde antérieur (le plus vieux)")


def _argent(m):
    return f"{m:.2f}".replace(".", ",").replace(",00", "") + " $"


def analyser(fichier, entreprise, correspondance=None):
    """`correspondance` : {entête du fichier: colonne du gabarit, ou "" pour l'ignorer}, prioritaire sur les alias."""
    precise = {_cle(k): (_cle(v) if v else "") for k, v in (correspondance or {}).items()}
    for k, v in precise.items():
        if v and v not in PAR_CLE:
            raise ValueError(f"Correspondance : « {v} » n'est pas une colonne du gabarit (entête « {k} »).")
    colonnes, inconnues = {}, []
    for i, brute in enumerate(fichier.entetes_brutes):
        k = _cle(brute)
        k = precise[k] if k in precise else ALIAS.get(k, k)
        if not k:
            continue
        if k in PAR_CLE and k not in colonnes.values():
            colonnes[i] = k
        else:
            inconnues.append(brute)
    manquantes = [c.titre for c in COLONNES if c.obligatoire and c.cle not in colonnes.values()]
    if manquantes:
        return Analyse(fichier, colonnes, inconnues, manquantes, [], [], None)

    saison = saison_en_cours(entreprise)
    secteurs_existants = {_cle(s.nom): s.nom for s in Secteur.objects.filter(entreprise=entreprise)}
    secteurs_nouveaux = {}
    ville_defaut = VilleDesservie.par_defaut_de(entreprise.pk)
    services_existants = {_cle(sv.nom): sv.nom for sv in Service.objects.filter(entreprise=entreprise)}
    services_nouveaux = {}
    villes_servies = {cle_ville(v.nom): v.nom for v in VilleDesservie.objects.filter(entreprise=entreprise)}
    cellulaires_base = set(Client.objects.filter(entreprise=entreprise).exclude(cellulaire="").values_list("cellulaire", flat=True))
    adresses_base = {_cle_adresse(a, v) for a, v in Adresse.objects.filter(entreprise=entreprise).values_list("ligne1", "ville")}

    lignes, groupes, adresses_fichier, cellulaires_fichier = [], {}, {}, {}

    for numero, valeurs in fichier.lignes:
        brut = {k: valeurs[i] if i < len(valeurs) else "" for i, k in colonnes.items()}
        if not any(_texte(v) for v in brut.values()):
            continue  # ligne vide
        l = Ligne(numero)
        t = {k: _texte(v) for k, v in brut.items()}
        g = lambda k: t.get(k, "")  # noqa: E731

        # Valeurs converties (erreurs de format)
        conv = {}
        for k, fonction in (("borne_fontaine", _oui_non), ("entree_en_pente", _oui_non), ("consentement_commercial", _oui_non),
                            ("mode_paiement", _choix), ("canal", _choix), ("langue", _choix), ("statut", _choix), ("type_contrat", _choix),
                            ("consentement_date", _date), ("rang_tournee", _entier), ("versements", _entier), ("prix_saison", _montant), ("solde_du", _montant),
                            ("taxes_incluses", _oui_non), ("extra_prix", _montant), ("recu_montant", _montant), ("recu_date", _date),
                            ("recu_mode", _choix)):
            try:
                conv[k] = fonction(brut.get(k, "") if k in ("consentement_date", "recu_date") else g(k), k)
            except ValueError as e:
                l.erreurs.append(str(e))

        for c in COLONNES:
            if c.argent and g(c.cle):
                l.argent[c.cle] = conv.get(c.cle, g(c.cle))
        # Contrat (prix de la saison) et solde dû
        type_c = l.argent.get("type_contrat") or "saisonnier"
        if l.argent.get("prix_saison") is not None:
            if type_c not in TYPES_IMPORTES:
                l.avertissements.append(f"contrat {PERMIS_AFFICHES.get(type_c, type_c)} : à créer à la main dans l'administration")
            elif TYPES_IMPORTES[type_c] == Contrat.Type.SAISONNIER:
                nb = l.argent.get("versements") or entreprise.versements_par_defaut
                if not 1 <= nb <= 4:
                    l.erreurs.append(f"versements : {nb}, il en faut de 1 à 4")
                elif len(entreprise.liste_dates_versements()) < nb - 1:
                    l.erreurs.append(f"versements : {nb}, mais la fiche de l'entreprise n'a que "
                                     f"{len(entreprise.liste_dates_versements())} date(s) de versement")
        elif "type_contrat" in l.argent:
            l.avertissements.append("type_contrat sans prix_saison : pas de contrat créé")
        if not l.erreurs:  # valeurs mal écrites : déjà en erreur, rien à calculer
            _verifier_argent(l, entreprise, saison, services_existants, services_nouveaux, g)
        if l.argent.get("solde_du") == 0:
            del l.argent["solde_du"]

        # Client, validé par les règles du modèle
        client = Client(
            entreprise=entreprise, prenom=g("prenom"), nom=g("nom"), organisation=g("organisation"),
            cellulaire=g("cellulaire"), telephone_autre=g("autre_telephone"), courriel=g("courriel"),
            facturation_ligne1=g("facturation_adresse"), facturation_ville=g("facturation_ville"),
            facturation_province="QC" if g("facturation_adresse") else "", facturation_code_postal=g("facturation_code_postal"),
            mode_paiement=conv.get("mode_paiement", ""), canal_prefere=conv.get("canal") or "texto",
            langue=conv.get("langue") or "fr", statut=conv.get("statut") or "actif",
            consentement_commercial=bool(conv.get("consentement_commercial")),
            consentement_date=conv.get("consentement_date"), notes=g("notes"),
        )
        if client.consentement_commercial:
            client.consentement_source = Client.SourceConsentement.IMPORT
            if not client.consentement_date:
                client.consentement_date = timezone.localdate()
                l.avertissements.append("consentement sans date : date de l'import inscrite")
        try:
            client.full_clean(exclude=["entreprise"])
        except ValidationError as e:
            l.erreurs.extend(_messages(e))

        # Adresse de service
        ville = g("ville")
        if not ville and ville_defaut:
            ville = ville_defaut.nom
        elif ville and villes_servies:
            if cle_ville(ville) in villes_servies:
                ville = villes_servies[cle_ville(ville)]  # même graphie que la fiche (accents, majuscules)
            else:
                l.avertissements.append(f"ville « {ville} » non desservie (villes : {', '.join(villes_servies.values())})")
        adresse = Adresse(
            entreprise=entreprise, ligne1=g("adresse"), ligne2=g("adresse_suite"), ville=ville, code_postal=g("code_postal"),
            ordre_tournee=conv.get("rang_tournee"), ou_mettre_neige=g("ou_mettre_neige"), obstacles=g("obstacles"),
            borne_fontaine=bool(conv.get("borne_fontaine")), entree_en_pente=bool(conv.get("entree_en_pente")), consignes=g("consignes"),
        )
        try:
            adresse.full_clean(exclude=["entreprise", "client", "secteur"])
        except ValidationError as e:
            l.erreurs.extend(_messages(e))

        l.client, l.adresse = client, adresse

        # Secteur
        if g("secteur"):
            cs = _cle(g("secteur"))
            if cs in secteurs_existants:
                l.secteur_nom = secteurs_existants[cs]
            else:
                l.secteur_nom = secteurs_nouveaux.setdefault(cs, g("secteur"))

        # Regroupement par no_client
        # La première ligne d'un groupe crée le client; les suivantes ajoutent
        # une adresse et suivent le sort de la première (erreur, déjà en base).
        l.groupe = g("no_client") or f"ligne-{numero}"
        premiere = groupes.get(l.groupe)
        if premiere is None:
            groupes[l.groupe] = l
        elif _cle(premiere.client.nom_affiche) != _cle(client.nom_affiche):
            l.erreurs.append(f"no_client {g('no_client')} déjà utilisé à la ligne {premiere.numero} pour « {premiere.client.nom_affiche} »")
        elif premiere.statut == "erreur":
            l.erreurs.append(f"le client de la ligne {premiere.numero} (même no_client) est en erreur")
        else:
            l.statut = "adresse_seulement"

        # Doublons d'adresse (fichier, puis base)
        ca = _cle_adresse(adresse.ligne1, adresse.ville)
        if adresse.ligne1 and ca in adresses_fichier:
            l.erreurs.append(f"même adresse qu'à la ligne {adresses_fichier[ca]}")
        elif adresse.ligne1:
            adresses_fichier[ca] = numero

        if l.erreurs:
            l.statut = "erreur"
        elif ca in adresses_base or (client.cellulaire and client.cellulaire in cellulaires_base and l.statut == "a_creer"):
            l.statut = "existe"
        elif premiere is not None and premiere.statut == "existe":
            l.statut = "existe"
            l.avertissements.append(f"client de la ligne {premiere.numero} déjà en base : ajouter cette adresse dans l'administration si elle est nouvelle")
        else:
            # Même cellulaire pour deux clients différents : possible (couple), mais à vérifier
            if client.cellulaire and l.statut == "a_creer":
                autre = cellulaires_fichier.get(client.cellulaire)
                if autre is not None:
                    l.avertissements.append(f"même cellulaire qu'à la ligne {autre} ({telephone.afficher(client.cellulaire)})")
                else:
                    cellulaires_fichier[client.cellulaire] = numero
        if l.statut in ("a_creer", "adresse_seulement") and not adresse.code_postal:
            l.avertissements.append("pas de code postal (le géocodage sera moins précis)")
        lignes.append(l)

    utilises = {_cle(l.secteur_nom) for l in lignes if l.statut in ("a_creer", "adresse_seulement") and l.secteur_nom}
    nouveaux = [nom for cs, nom in secteurs_nouveaux.items() if cs in utilises]
    importees = [l for l in lignes if l.statut in ("a_creer", "adresse_seulement")]
    services_utilises = {_cle(n) for l in importees for n in l.calcul.get("services", [])}
    return Analyse(fichier, colonnes, inconnues, [], lignes, nouveaux, saison,
                   [nom for cs, nom in services_nouveaux.items() if cs in services_utilises])


# ---------------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------------


def appliquer(analyse, entreprise, sauter_erreurs=False):
    if analyse.manquantes:
        raise ValueError("Colonnes obligatoires manquantes : rien n'est importé.")
    if analyse.erreurs and not sauter_erreurs:
        raise ValueError(f"{len(analyse.erreurs)} ligne(s) en erreur : rien n'est importé (corriger le fichier, ou sauter les erreurs).")
    with transaction.atomic():
        if analyse.saison is not None and analyse.saison.pk is None and analyse.nb_contrats:
            analyse.saison.save()  # première saison de l'entreprise, créée par l'import
        secteurs = {}
        prochain_ordre = (Secteur.objects.filter(entreprise=entreprise).order_by("-ordre").values_list("ordre", flat=True).first() or 0) + 1
        for nom in analyse.secteurs_nouveaux:
            secteurs[_cle(nom)] = Secteur.objects.create(entreprise=entreprise, nom=nom, ordre=prochain_ordre)
            prochain_ordre += 1
        for s in Secteur.objects.filter(entreprise=entreprise):
            secteurs.setdefault(_cle(s.nom), s)

        r = Resultat()
        services = {_cle(sv.nom): sv for sv in Service.objects.filter(entreprise=entreprise)}
        prochain = (Service.objects.filter(entreprise=entreprise).order_by("-ordre").values_list("ordre", flat=True).first() or 0) + 1
        for nom in analyse.services_nouveaux:
            services[_cle(nom)] = Service.objects.create(entreprise=entreprise, nom=nom[:100], ordre=prochain)
            prochain += 1
            r.services += 1

        clients_par_groupe = {}
        for l in analyse.lignes:
            if l.statut == "a_creer":
                l.client.save()
                clients_par_groupe[l.groupe] = l.client
                r.clients += 1
            elif l.statut == "adresse_seulement":
                if l.groupe not in clients_par_groupe:
                    continue  # le client de ce groupe était en erreur et a été sauté
            else:
                continue
            l.adresse.client = clients_par_groupe[l.groupe]
            l.adresse.secteur = secteurs.get(_cle(l.secteur_nom)) if l.secteur_nom else None
            l.adresse.save()
            r.adresses += 1
            client = clients_par_groupe[l.groupe]
            a = l.argent
            type_c = TYPES_IMPORTES.get(a.get("type_contrat") or "saisonnier")
            if a.get("prix_saison") is not None and type_c and analyse.saison is not None:
                c = Contrat.objects.create(entreprise=entreprise, client=client, adresse=l.adresse, saison=analyse.saison,
                                           type=type_c, prix=l.calcul["prix_contrat"], prix_texte=l.calcul.get("prix_texte", "")[:300])
                c.services.set([services[_cle(n)] for n in l.calcul.get("services", []) if _cle(n) in services])
                if type_c == Contrat.Type.SAISONNIER:
                    c.creer_echeancier_par_defaut(a.get("versements"))  # B3 : 1er versement à l'approbation (l'import)
                    c.facturer_saison()  # la facture de la saison, en brouillon : Louis l'émet et l'envoie (Versements à envoyer)
                r.contrats += 1
            if a.get("solde_du"):
                Facture.solde_ouverture(client, a["solde_du"], saison_origine=a.get("solde_saison", "")[:20],
                                        note=a.get("solde_note", ""))
                r.soldes += 1
            if a.get("recu_montant"):
                # Argent reçu avant l'app : crédit au compte, appliqué tout de suite à ce qui est dû (solde antérieur),
                # sinon à la prochaine facture émise (Facture.emettre), le 1er versement
                Credit.objects.create(entreprise=entreprise, client=client, montant=a["recu_montant"], date=l.calcul["recu_date_effective"],
                                      mode=l.calcul["recu_mode_effectif"], note="Reçu avant l'app (import)")
                credits.appliquer(client)
                r.credits += 1
    return r
