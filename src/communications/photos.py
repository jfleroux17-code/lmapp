"""Photos jointes aux messages (PRD E14) : photo de l'entrée, du passage ou d'un dossier de demande (dommage).

Par courriel, les images partent en pièces jointes. Par texto (pas de MMS : coût et taille), un lien secret
de 192 bits vers une page qui les montre (/m/<jeton>/), comme la facture (L1). Au plus MAXIMUM photos.
Les photos restent dans la base : effacer une photo la retire des messages (Loi 25)."""
import secrets

from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import formats, timezone

MAXIMUM = 5


def _sources():
    from clients.models import PhotoAdresse
    from demandes.models import PhotoDemande
    from tournee.models import PhotoPassage

    # préfixe de la clé : (modèle, champ du message, route de l'image pour les membres)
    return {"a": (PhotoAdresse, "photos_adresses", "terrain:photo"),
            "p": (PhotoPassage, "photos_passages", "terrain:voir_photo_passage"),
            "d": (PhotoDemande, "photos_demandes", "terrain:voir_photo_demande")}


def disponibles(client, demande=None):
    """Les photos qu'on peut joindre à un message à ce client, plus récentes d'abord (au plus 30)."""
    from clients.models import PhotoAdresse
    from demandes.models import PhotoDemande
    from tournee.models import PhotoPassage

    liste = []
    for p in PhotoDemande.objects.filter(demande__client=client).select_related("demande").order_by("-cree_le")[:12]:
        liste.append({"cle": f"d{p.pk}", "url": reverse("terrain:voir_photo_demande", args=[p.pk]), "quand": p.cree_le,
                      "legende": f"Demande : {p.demande.get_genre_display().lower()}", "choisie": demande is not None and p.demande_id == demande.pk})
    for p in PhotoPassage.objects.filter(adresse__client=client).select_related("adresse").order_by("-prise_le")[:12]:
        liste.append({"cle": f"p{p.pk}", "url": reverse("terrain:voir_photo_passage", args=[p.pk]), "quand": p.prise_le,
                      "legende": f"Passage, {p.adresse.ligne1}", "choisie": False})
    for p in PhotoAdresse.objects.filter(adresse__client=client).select_related("adresse").order_by("-cree_le")[:6]:
        liste.append({"cle": f"a{p.pk}", "url": reverse("terrain:photo", args=[p.pk]), "quand": p.cree_le,
                      "legende": f"Entrée, {p.adresse.ligne1}", "choisie": False})
    liste.sort(key=lambda d: d["quand"], reverse=True)
    return liste[:30]


def joindre(message, cles):
    """Joint les photos choisies (clés « a12 », « p3 », « d7 ») : seulement celles du client du message."""
    cles = [c for c in dict.fromkeys(cles) if c]
    if not cles:
        return 0
    if len(cles) > MAXIMUM:
        raise ValidationError(f"Au plus {MAXIMUM} photos par message.")
    permises = {d["cle"] for d in disponibles(message.client)} if message.client_id else set()
    if not set(cles) <= permises:
        raise ValidationError("Photo introuvable pour ce client.")
    sources = _sources()
    for c in cles:
        modele, champ, _ = sources[c[0]]
        getattr(message, champ).add(modele.objects.get(pk=int(c[1:]), entreprise=message.entreprise))
    if message.canal == message.Canal.TEXTO and not message.jeton:
        message.jeton = secrets.token_urlsafe(24)
        message.save(update_fields=["jeton"])
    return len(cles)


def jointes(message):
    """Les photos du message, dans un ordre stable : (image, type MIME, légende)."""
    resultat = []
    for p in message.photos_demandes.select_related("demande").order_by("cree_le", "pk"):
        resultat.append((p, f"Demande : {p.demande.get_genre_display().lower()}, {formats.date_format(timezone.localtime(p.cree_le), 'j F Y')}"))
    for p in message.photos_passages.select_related("adresse").order_by("prise_le", "pk"):
        resultat.append((p, f"Passage au {p.adresse.ligne1}, {formats.date_format(timezone.localtime(p.prise_le), 'j F Y, H \\h i')}"))
    for p in message.photos_adresses.select_related("adresse").order_by("cree_le", "pk"):
        resultat.append((p, f"Entrée du {p.adresse.ligne1}"))
    return resultat


def extension(type_mime):
    return "png" if type_mime == "image/png" else "jpg"


def lien_public(message):
    """Le jeton est la seule clé : ne l'écrire que dans le texto au client."""
    return f"https://{message.entreprise.domaine}/m/{message.jeton}/" if message.jeton else ""
