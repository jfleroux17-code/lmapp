"""Virements Interac reçus par courriel (PRD D5) : lecture de l'avis, facture proposée, paiement sur confirmation.

Les avis viennent d'Interac (payments.interac.ca), directement ou transférés par Gmail. Leur texte change
selon la banque et la langue : on cherche le montant, l'envoyeur, son message et la référence avec des
motifs tolérants; sans montant lisible, le courriel reste un simple message reçu.

Facture proposée, dans l'ordre :
  1. un numéro de facture due cité dans le message de l'envoyeur (« facture 1001 »);
  2. la seule facture due dont le solde égale le montant (ou, s'il y en a plusieurs, celle du client
     dont le nom ressemble à l'envoyeur);
  3. le client dont le nom ressemble à l'envoyeur : sa plus vieille facture due.
Enregistrer répartit le montant sur les factures dues du client (la proposée d'abord, puis les plus
vieilles), sans jamais dépasser ce qu'il doit (pas de trop-perçu en V1).
"""
import re
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.texte import cle
from facturation.models import ZERO, Facture, Paiement, VirementInterac

MONTANT_FR = re.compile(r"(\d{1,3}(?:[   ]\d{3})*,\d{2})\s*\$")
MONTANT_EN = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})*\.\d{2})")
ENVOYEUR = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in (
    r"^\s*(?:Bonjour[^,\n]*,\s*)?(.{2,80}?) vous a envoyé", r"^\s*(?:Hi[^,\n]*,\s*)?(.{2,80}?) (?:has )?sent you",
    r"Expéditeur\s*:\s*(.{2,80})$", r"Sent From\s*:\s*(.{2,80})$", r"De la part de\s*:\s*(.{2,80})$")]
MESSAGE = re.compile(r"^\s*Message\s*:\s*(.{1,400})$", re.IGNORECASE | re.MULTILINE)
REFERENCE = re.compile(r"(?:Numéro de référence|N° de référence|Reference Number|Référence)\s*:?\s*([A-Za-z0-9]{6,40})", re.IGNORECASE)


def est_un_avis(expediteur, sujet):
    if expediteur.endswith("interac.ca"):
        return True
    s = sujet.lower()
    return "interac" in s and any(m in s for m in ("virement", "e-transfer", "transfert", "dépôt", "deposit"))


def _montant(texte):
    m = MONTANT_FR.search(texte)
    if m:
        brut = re.sub(r"[   ]", "", m.group(1)).replace(",", ".")
    else:
        m = MONTANT_EN.search(texte)
        if not m:
            return None
        brut = m.group(1).replace(",", "")
    try:
        return Decimal(brut).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def extraire(sujet, texte):
    """Retourne (montant, envoyeur, message, référence), ou None si aucun montant."""
    tout = f"{sujet}\n{texte}"
    montant = _montant(tout)
    if montant is None or montant <= 0:
        return None
    envoyeur = next((m.group(1).strip(" .:") for r in ENVOYEUR if (m := r.search(tout))), "")
    message = MESSAGE.search(texte)
    reference = REFERENCE.search(tout)
    return montant, envoyeur[:150], (message.group(1).strip() if message else "")[:400], (reference.group(1) if reference else "")[:60]


def _ressemble(client, envoyeur):
    mots = set(cle(envoyeur).split("_")) - {""}
    nom = set(cle(client.nom).split("_")) - {""}
    return bool(nom) and nom <= mots


def apparier(v):
    dues = list(Facture.objects.filter(entreprise=v.entreprise).a_recevoir().select_related("client").order_by("date_facture", "pk"))
    numeros = {str(f.numero): f for f in dues if f.numero}
    for n in re.findall(r"\d{2,7}", v.message_envoyeur):
        if n in numeros:
            return numeros[n], f"numéro de facture {n} dans le message"
    memes = [f for f in dues if f.solde_du == v.montant]
    if len(memes) == 1:
        return memes[0], "seule facture due de ce montant"
    if len(memes) > 1:
        par_nom = [f for f in memes if _ressemble(f.client, v.envoyeur)]
        if len(par_nom) == 1:
            return par_nom[0], "même montant et même nom"
    par_nom = [f for f in dues if _ressemble(f.client, v.envoyeur)]
    if par_nom:
        return par_nom[0], "même nom que l'envoyeur (plus vieille facture due)"
    return None, ""


def creer(entreprise, message, sujet, texte):
    """Depuis un courriel reçu : crée le virement à confirmer (ou rien si ce n'est pas lisible)."""
    lu = extraire(sujet, texte)
    if lu is None:
        return None
    montant, envoyeur, msg, reference = lu
    if reference and VirementInterac.objects.filter(entreprise=entreprise, reference=reference).exists():
        return None  # le même avis deux fois (transfert et original, par exemple)
    v = VirementInterac(entreprise=entreprise, recu_le=message.envoye_le or timezone.now(), montant=montant,
                        envoyeur=envoyeur, message_envoyeur=msg, reference=reference, courriel=message)
    v.facture, v.raison = apparier(v)
    v.client = v.facture.client if v.facture else None
    v.save()
    return v


def enregistrer(v, facture):
    """Paiements Interac pour ce virement : la facture choisie d'abord, puis les plus vieilles du même client."""
    if v.statut != VirementInterac.Statut.A_TRAITER:
        raise ValidationError("Ce virement est déjà traité.")
    if facture.entreprise_id != v.entreprise_id:
        raise ValidationError("Facture d'une autre entreprise.")
    with transaction.atomic():
        v = VirementInterac.objects.select_for_update().get(pk=v.pk)
        if v.statut != VirementInterac.Statut.A_TRAITER:
            raise ValidationError("Ce virement est déjà traité.")
        dues = list(Facture.objects.select_for_update().filter(client=facture.client_id, statut=Facture.Statut.EMISE)
                    .order_by("date_facture", "pk"))
        dues.sort(key=lambda f: f.pk != facture.pk)  # la choisie d'abord
        reste, faits = v.montant, []
        for f in dues:
            solde = f.solde
            if reste <= 0 or solde <= 0:
                continue
            part = min(reste, solde)
            p = Paiement(entreprise=v.entreprise, facture=f, montant=part, mode=Paiement.Mode.INTERAC,
                         reference=v.reference or "virement Interac", date=timezone.localdate(v.recu_le),
                         note=f"Virement de {v.envoyeur}"[:200] if v.envoyeur else "")
            p.full_clean()
            p.save()
            faits.append(p)
            reste -= part
        if reste > ZERO:
            raise ValidationError(f"Le client doit moins que le virement ({reste} $ de trop) : à régler à la main.")
        v.statut, v.facture, v.client = VirementInterac.Statut.ENREGISTRE, facture, facture.client
        v.save(update_fields=["statut", "facture", "client", "modifie_le"])
        v.paiements.set(faits)
    return faits
