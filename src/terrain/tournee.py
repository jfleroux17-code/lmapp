"""Écrans de tournée de Louis (PRD F1 à F6, F8) : une opération, l'arrêt suivant, Fait ou Sauté en une tape."""
import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from clients.models import Adresse, Client, Secteur
from core.acces import ecriture_requise, membre_requis, peut_ecrire
from communications import avis
from communications.models import Message
from tournee import services
from tournee.models import Operation, Passage, PositionGPS, arrets


def soldes_dus(entreprise):
    """{client_id: montant dû} pour les clients qui doivent quelque chose (factures émises et soldes antérieurs)."""
    from facturation.models import Facture

    dus = {}
    for client_id, solde in Facture.objects.filter(entreprise=entreprise).a_recevoir().values_list("client", "solde_du"):
        dus[client_id] = dus.get(client_id, 0) + solde
    return dus


def _arret_json(a, i, passage, dus=None):
    from facturation.templatetags.argent import argent
    from terrain.views import _liens_navigation

    du = (dus or {}).get(a.client_id)
    return {
        "id": a.pk, "rang": i, "client_id": a.client_id, "client": a.client.nom_affiche,
        "fiche": reverse("terrain:fiche", args=[a.client_id]),
        "ligne1": a.ligne1, "ligne2": a.ligne2, "secteur": a.secteur.nom if a.secteur else "",
        "ordre": a.ordre_tournee, "recouvrement": a.client.statut == Client.Statut.RECOUVREMENT,
        "neige": a.ou_mettre_neige, "obstacles": a.obstacles, "borne": a.borne_fontaine, "pente": a.entree_en_pente,
        "consignes": a.consignes,
        "navigation": _liens_navigation(a),
        "passage": _passage_json(passage),
        # D3 : argent à collecter en passant (client qui paie comptant), sinon simple rappel du solde
        "du": argent(du) if du else "", "comptant": a.client.mode_paiement == Client.ModePaiement.COMPTANT,
    }


def _passage_json(p):
    if p is None:
        return None
    return {"statut": p.statut, "raison": p.raison, "raison_texte": p.get_raison_display() if p.raison else "",
            "heure": timezone.localtime(p.heure).strftime("%H:%M"), "note": p.note}


def _meteo(request):
    """I1 : prévisions gardées par le worker, si elles ont moins de 6 heures."""
    from datetime import timedelta

    from core.models import Meteo

    m = Meteo.objects.filter(entreprise=request.entreprise).first()
    return m if m and m.lue_le and timezone.now() - m.lue_le < timedelta(hours=6) else None


def _avis_debut_annulables(op):
    """Avis de début encore en file pendant le délai d'annulation : nombre et secondes qui restent."""
    from communications.models import Genre, Message

    file = Message.objects.filter(operation=op, genre=Genre.DEBUT, statut=Message.Statut.EN_FILE)
    premier = file.order_by("cree_le").values_list("cree_le", flat=True).first()
    if premier is None:
        return None
    reste = avis.DELAI_ANNULATION_DEBUT - (timezone.now() - premier).total_seconds()
    return {"nombre": file.count(), "secondes": int(reste) + 1, "annuler": reverse("terrain:annuler_avis_debut")} if reste > 0 else None


@membre_requis
def tournee(request):
    op = Operation.en_cours_de(request.entreprise)
    if op is None:
        from communications.models import Gabarit, Genre

        apercu = Gabarit.texte_pour(request.entreprise, Genre.DEBUT)
        try:
            apercu = apercu.format(client="(nom du client)")
        except (KeyError, IndexError, ValueError):
            pass
        return render(request, "terrain/tournee/demarrer.html", {
            "types": Operation.Type.choices, "ecriture": peut_ecrire(request), "meteo": _meteo(request),
            "nb_a_aviser": avis.clients_a_aviser_au_debut(request.entreprise).count(), "apercu_avis": apercu,
            "envois_actifs": request.entreprise.envois_actifs,
            "dernieres": Operation.objects.filter(entreprise=request.entreprise).order_by("-debut")[:5],
        })
    passages = {p.adresse_id: p for p in op.passages.all()}
    dus = soldes_dus(request.entreprise)
    donnees = {
        "operation": {"id": op.pk, "type": op.get_type_display(), "debut": timezone.localtime(op.debut).strftime("%H h %M")},
        "arrets": [_arret_json(a, i, passages.get(a.pk), dus) for i, a in enumerate(arrets(request.entreprise), start=1)],
        "raisons": Passage.Raison.choices,
        "synchro": reverse("terrain:synchro"),
        "ecriture": peut_ecrire(request),
        "choisi": int(request.GET["arret"]) if request.GET.get("arret", "").isdigit() else None,
        "position": reverse("terrain:position"),
        "avis_proximite": request.entreprise.avis_proximite_actif,
        "nb_avis": op.messages.count(),
        "photo_url": reverse("terrain:photo_passage"),
        "avis_debut": _avis_debut_annulables(op),
    }
    # F7 : nombre de photos déjà prises à chaque arrêt pendant cette opération
    from django.db.models import Count

    nb_photos = dict(op.photos.values("adresse_id").annotate(n=Count("pk")).values_list("adresse_id", "n"))
    for x in donnees["arrets"]:
        x["photos"] = nb_photos.get(x["id"], 0)
    secteurs = sorted({(a.secteur.ordre, a.secteur.pk, a.secteur.nom) for a in arrets(request.entreprise) if a.secteur})
    from core.acces import est_responsable

    return render(request, "terrain/tournee/en_cours.html", {"op": op, "donnees": donnees, "ecriture": donnees["ecriture"], "meteo": _meteo(request),
                                                             "responsable": est_responsable(request),
                                                             "secteurs": [(pk, nom) for _, pk, nom in secteurs]})


@require_POST
@ecriture_requise
def synchro(request):
    """Passages tapés sur le cellulaire, envoyés dès que possible (F10) : en direct, ou en
    rafale au retour du réseau. Chaque passage porte son opération et l'heure de la tape.
    Réponse : les identifiants acceptés (le cellulaire les retire de sa file) et refusés."""
    try:
        recu = json.loads(request.body)
        lot = recu["passages"]
        assert isinstance(lot, list) and len(lot) <= 500
    except (ValueError, KeyError, AssertionError, TypeError):
        return JsonResponse({"erreur": "Données illisibles."}, status=400)
    acceptes, refuses, maintenant = [], [], timezone.now()
    for item in lot:
        cle = str(item.get("cle", ""))[:64]
        try:
            op = Operation.objects.get(pk=int(item["operation"]), entreprise=request.entreprise)
            adresse = Adresse.objects.get(pk=int(item["adresse"]), entreprise=request.entreprise)
            statut, raison = item.get("statut"), item.get("raison") or ""
            if statut not in Passage.Statut.values or (statut == Passage.Statut.SAUTE and raison not in Passage.Raison.values):
                raise ValueError("statut")
            quand = parse_datetime(str(item.get("quand", ""))) or maintenant
            # Heure du cellulaire : ni dans le futur, ni avant le début de l'opération
            quand = min(max(quand, op.debut), maintenant)
            p = services.marquer(op, adresse, statut, raison=raison, note=str(item.get("note", "")).strip()[:300], quand=quand)
            acceptes.append({"cle": cle, "adresse": adresse.pk, "passage": _passage_json(p), "facture": bool(p.ligne_facture_id)})
        except (Operation.DoesNotExist, Adresse.DoesNotExist, KeyError, ValueError, TypeError, ValidationError):
            refuses.append(cle)
    return JsonResponse({"acceptes": acceptes, "refuses": refuses})


@require_POST
@ecriture_requise
def demarrer(request):
    t = request.POST.get("type")
    if t not in Operation.Type.values:
        messages.error(request, "Choisir le type d'opération.")
        return redirect("terrain:tournee")
    try:
        with transaction.atomic():  # point de sauvegarde : le refus ne gâche pas le reste de la requête
            op = Operation.objects.create(entreprise=request.entreprise, type=t, operateur=request.user)
        texte = f"Opération « {op.get_type_display()} » commencée."
        if request.POST.get("aviser_debut") == "1":
            n = avis.aviser_debut(op, delai=avis.DELAI_ANNULATION_DEBUT)
            texte += f" {n} avis de début préparé{'s' if n > 1 else ''}."
        messages.success(request, texte)
    except IntegrityError:
        messages.info(request, "Une opération est déjà en cours.")
    return redirect("terrain:tournee")


@require_POST
@ecriture_requise
def annuler_avis_debut(request):
    """Bandeau « Annuler » des 10 secondes après Démarrer : retient les avis pas encore partis."""
    op = Operation.en_cours_de(request.entreprise)
    n = avis.annuler_avis_debut(op) if op else 0
    if n:
        messages.success(request, f"{n} avis de début retenu{'s' if n > 1 else ''} : rien n'est parti. L'opération continue.")
    else:
        messages.info(request, "Trop tard : les avis de début étaient déjà partis.")
    return redirect("terrain:tournee")


@require_POST
@ecriture_requise
def passage(request, adresse_pk):
    op = Operation.en_cours_de(request.entreprise)
    if op is None:
        messages.error(request, "Aucune opération en cours : la démarrer d'abord.")
        return redirect("terrain:tournee")
    adresse = get_object_or_404(Adresse, pk=adresse_pk, entreprise=request.entreprise)
    statut = request.POST.get("statut")
    raison = request.POST.get("raison", "")
    if statut not in Passage.Statut.values or (statut == Passage.Statut.SAUTE and raison not in Passage.Raison.values):
        messages.error(request, "Choisir Fait, ou Sauté avec une raison.")
        return redirect("terrain:tournee")
    p = services.marquer(op, adresse, statut, raison=raison, note=request.POST.get("note", "").strip()[:300])
    texte = "fait" if p.statut == Passage.Statut.FAIT else f"sauté ({p.get_raison_display().lower()})"
    messages.success(request, f"{adresse.client.nom_affiche}, {adresse.ligne1} : {texte}."
                              + (" Passage ajouté à sa facture." if p.ligne_facture_id else ""))
    return redirect("terrain:tournee")


@require_POST
@ecriture_requise
def terminer(request):
    op = Operation.en_cours_de(request.entreprise)
    if op is not None:
        op.terminer()
        faits = op.passages.filter(statut=Passage.Statut.FAIT).count()
        sautes = op.passages.filter(statut=Passage.Statut.SAUTE).count()
        reste = arrets(request.entreprise).count() - faits - sautes
        messages.success(request, f"Opération terminée : {faits} fait{'s' if faits > 1 else ''}, {sautes} sauté{'s' if sautes > 1 else ''}"
                                  + (f", {reste} pas visité{'s' if reste > 1 else ''}." if reste > 0 else "."))
    return redirect("terrain:tournee")


PRECISION_MAX_M = 150  # au-delà (GPS pas encore accroché, intérieur), on garde la position sans aviser


@require_POST
@ecriture_requise
def position(request):
    """G1 : position du cellulaire, envoyée par l'écran de tournée ouvert. Déclenche les avis de proximité (G2)."""
    from django.contrib.gis.geos import Point

    try:
        d = json.loads(request.body)
        lat, lon = float(d["lat"]), float(d["lon"])
        precision = int(float(d.get("precision") or 9999))
        assert -90 <= lat <= 90 and -180 <= lon <= 180
    except (ValueError, KeyError, TypeError, AssertionError):
        return JsonResponse({"erreur": "Position illisible."}, status=400)
    op = Operation.en_cours_de(request.entreprise)
    if op is None or str(op.pk) != str(d.get("operation")):
        return JsonResponse({"erreur": "Aucune opération en cours.", "avis": 0}, status=409)
    point = Point(lon, lat, srid=4326)
    PositionGPS.objects.create(operation=op, position=point, precision_m=min(precision, 99999))
    nouveaux = avis.aviser_proximite(op, point) if precision <= PRECISION_MAX_M else 0
    return JsonResponse({"avis": nouveaux, "nb_avis": op.messages.count()})


@require_POST
@ecriture_requise
def avis_manuels(request):
    """G4 : avis de secours quand la géolocalisation ne fonctionne pas."""
    op = Operation.en_cours_de(request.entreprise)
    if op is None:
        return redirect("terrain:tournee")
    if request.POST.get("mode") == "secteur" and request.POST.get("secteur", "").isdigit():
        n = avis.aviser_secteur(op, int(request.POST["secteur"]))
    else:
        n = avis.aviser_prochains(op, 3)
    messages.success(request, f"{n} avis préparé{'s' if n > 1 else ''}." if n else "Personne de plus à aviser (déjà avisés ou sans cellulaire).")
    return redirect("terrain:tournee")


@membre_requis
def liste_messages(request):
    """Messages reçus (E7) et envoyés, les plus récents d'abord. Les reçus pas encore ouverts en premier."""
    base = (Message.objects.filter(entreprise=request.entreprise).select_related("client", "operation")
            .prefetch_related("virements__facture"))
    recus = base.filter(sens=Message.Sens.ENTRANT)
    vue = request.GET.get("vue") or ("recus" if recus.exists() else "envoyes")
    if vue == "recus":
        liste = recus.order_by("lu", "-cree_le")[:100]
    else:
        vue, liste = "envoyes", base.filter(sens=Message.Sens.SORTANT)[:100]
    from django.conf import settings

    return render(request, "terrain/messages.html", {"liste": liste, "vue": vue, "cle_vapid": settings.VAPID_CLE_PUBLIQUE})


@membre_requis
def message(request, pk):
    """Un message au complet. Ouvrir un message reçu le marque lu."""
    m = get_object_or_404(Message.objects.select_related("client", "reponse_a", "facture"), pk=pk, entreprise=request.entreprise)
    if m.sens == Message.Sens.ENTRANT and not m.lu:
        Message.objects.filter(pk=m.pk).update(lu=True)
    from communications import photos

    routes = {"PhotoAdresse": "terrain:photo", "PhotoPassage": "terrain:voir_photo_passage", "PhotoDemande": "terrain:voir_photo_demande"}
    jointes = [(p, legende, reverse(routes[type(p).__name__], args=[p.pk])) for p, legende in photos.jointes(m)]
    return render(request, "terrain/message.html", {"m": m, "photos": jointes})


# Ordre de la tournée (F1) : boutons haut et bas plutôt que glisser (gants).

def _contexte_ordre(request, bouge=None):
    """Tous les secteurs (même vides, pour qu'un déplacement ne saute jamais un secteur invisible), puis « Sans secteur »."""
    secteurs = list(Secteur.objects.filter(entreprise=request.entreprise).order_by("ordre", "nom"))
    groupes = {s.pk: {"secteur": s, "arrets": [], "bouge": bouge == f"s{s.pk}",
                      "premier": i == 0, "dernier": i == len(secteurs) - 1} for i, s in enumerate(secteurs)}
    groupes[None] = {"secteur": None, "arrets": []}
    for rang, a in enumerate(arrets(request.entreprise), start=1):
        a.rang, a.bouge = rang, bouge == f"a{a.pk}"
        groupes[a.secteur_id]["arrets"].append(a)
    liste = [g for g in groupes.values() if g["secteur"] is not None or g["arrets"]]
    return {"groupes": liste, "ecriture": peut_ecrire(request), "bouge": bouge,
            "en_cours": Operation.en_cours_de(request.entreprise) is not None}


def _reponse_ordre(request, bouge):
    if request.headers.get("HX-Request"):
        return render(request, "terrain/tournee/_ordre.html", {**_contexte_ordre(request, bouge), "hx": True})
    return redirect(f"{reverse('terrain:ordre')}?bouge={bouge}#{bouge}")


def _echanger(liste, objet, sens, champ):
    """Monte ou descend `objet` d'une place dans `liste`, puis renumérote 10, 20, 30 (sans trou ni doublon)."""
    i = liste.index(objet)
    j = i - 1 if sens == "haut" else i + 1
    if 0 <= j < len(liste):
        liste[i], liste[j] = liste[j], liste[i]
    changes = []
    for n, o in enumerate(liste, start=1):
        if getattr(o, champ) != n * 10:
            setattr(o, champ, n * 10)
            changes.append(o)
    return changes


@membre_requis
def ordre(request):
    bouge = request.GET.get("bouge", "")
    return render(request, "terrain/tournee/ordre.html", _contexte_ordre(request, bouge))


@require_POST
@ecriture_requise
def deplacer_arret(request, adresse_pk):
    with transaction.atomic():
        a = get_object_or_404(Adresse.objects.select_for_update(), pk=adresse_pk, entreprise=request.entreprise)
        voisins = list(arrets(request.entreprise).filter(secteur=a.secteur_id).select_for_update(of=("self",)))
        if a not in voisins:  # adresse inactive ou client pas servi : pas dans la tournée
            return redirect("terrain:ordre")
        Adresse.objects.bulk_update(_echanger(voisins, a, request.POST.get("sens"), "ordre_tournee"), ["ordre_tournee"])
    return _reponse_ordre(request, f"a{a.pk}")


@require_POST
@ecriture_requise
def placer_arret(request, adresse_pk):
    """Rang tapé directement (audit UX) : l'arrêt va à ce rang de la tournée, dans son secteur
    (un arrêt ne change pas de secteur ici : le rang est ramené au premier ou au dernier du secteur)."""
    try:
        cible = int(request.POST.get("rang", ""))
    except ValueError:
        messages.error(request, "Taper un numéro de rang.")
        return _reponse_ordre(request, f"a{adresse_pk}")
    with transaction.atomic():
        a = get_object_or_404(Adresse.objects.select_for_update(), pk=adresse_pk, entreprise=request.entreprise)
        tous = list(arrets(request.entreprise))
        if a not in tous:
            return redirect("terrain:ordre")
        voisins = list(arrets(request.entreprise).filter(secteur=a.secteur_id).select_for_update(of=("self",)))
        premier = tous.index(voisins[0]) + 1  # rang de la tournée du premier arrêt du secteur
        position = min(max(cible - premier, 0), len(voisins) - 1)
        if cible - premier != position and a.secteur_id:
            messages.info(request, f"Rang ramené dans le secteur {a.secteur.nom} (rangs {premier} à {premier + len(voisins) - 1}). "
                                   "Changer de secteur : dans la fiche de l'adresse.")
        voisins.remove(a)
        voisins.insert(position, a)
        changes = []
        for n, o in enumerate(voisins, start=1):
            if o.ordre_tournee != n * 10:
                o.ordre_tournee = n * 10
                changes.append(o)
        Adresse.objects.bulk_update(changes, ["ordre_tournee"])
    return _reponse_ordre(request, f"a{a.pk}")


@require_POST
@ecriture_requise
def deplacer_secteur(request, secteur_pk):
    with transaction.atomic():
        secteurs = list(Secteur.objects.select_for_update().filter(entreprise=request.entreprise).order_by("ordre", "nom"))
        s = get_object_or_404(Secteur, pk=secteur_pk, entreprise=request.entreprise)
        Secteur.objects.bulk_update(_echanger(secteurs, s, request.POST.get("sens"), "ordre"), ["ordre"])
    return _reponse_ordre(request, f"s{s.pk}")


@membre_requis
def a_collecter(request):
    """À collecter (D3) : clients qui paient comptant et doivent de l'argent, dans l'ordre de la tournée.
    Pendant une opération, ceux déjà faits sont marqués."""
    from facturation.templatetags.argent import argent  # noqa: F401 (gabarit)

    dus = soldes_dus(request.entreprise)
    op = Operation.en_cours_de(request.entreprise)
    faits = set(op.passages.filter(statut=Passage.Statut.FAIT).values_list("adresse__client_id", flat=True)) if op else set()
    lignes, vus = [], set()
    for a in arrets(request.entreprise):
        c = a.client
        if c.pk in vus or not dus.get(c.pk) or c.mode_paiement != Client.ModePaiement.COMPTANT:
            continue
        vus.add(c.pk)
        lignes.append({"client": c, "adresse": a, "du": dus[c.pk], "fait": c.pk in faits})
    return render(request, "terrain/tournee/a_collecter.html", {
        "lignes": lignes, "total": sum((l["du"] for l in lignes), 0), "operation": op,
    })


@ecriture_requise
def envoi_groupe(request):
    """E10 : écrire à tous les clients servis ou à un secteur. Aperçu (nombre de destinataires), puis envoi."""
    from communications import groupes, segments

    ent = request.entreprise
    secteurs = list(Secteur.objects.filter(entreprise=ent).order_by("ordre", "nom"))
    secteur = next((s for s in secteurs if str(s.pk) == request.POST.get("secteur")), None)
    commercial = request.POST.get("sorte") == "commercial"
    texte, sujet = request.POST.get("texte", "").strip(), request.POST.get("sujet", "").strip()[:200]
    contexte = {"secteurs": secteurs, "secteur": secteur, "commercial": commercial, "texte": texte, "sujet": sujet,
                "limite": segments.LIMITE, "reserve_signature": segments.longueur(groupes.corps(ent, "")),
                "reserve_arret": segments.longueur(groupes.ARRET)}
    if request.method == "POST":
        joignables, sans_contact = groupes.destinataires(ent, secteur, commercial)
        contexte.update({"apercu": True, "nombre": len(joignables), "sans_contact": sans_contact,
                         "textos": sum(1 for _, c in joignables if c == Message.Canal.TEXTO),
                         "courriels": sum(1 for _, c in joignables if c == Message.Canal.COURRIEL)})
        trop_long = contexte["textos"] and segments.trop_long(groupes.corps(ent, texte, commercial))
        if not texte:
            messages.error(request, "Écrire le message.")
            contexte["apercu"] = False
        elif trop_long:
            messages.error(request, f"{segments.raison_trop_long(groupes.corps(ent, texte, commercial))} "
                                    "Raccourcir le message : il part par texto à certains clients.")
        elif request.POST.get("action") == "envoyer":
            envoyes = groupes.envoyer(ent, texte, secteur, commercial, sujet)
            partis = sum(1 for m in envoyes if m.statut == Message.Statut.EN_FILE)
            if partis:
                messages.success(request, f"{partis} message{'s' if partis > 1 else ''} en route.")
            if len(envoyes) - partis:
                messages.error(request, f"{len(envoyes) - partis} pas envoyé{'s' if len(envoyes) - partis > 1 else ''} : {next(m.erreur for m in envoyes if m.statut != Message.Statut.EN_FILE)}")
            return redirect(f"{reverse('terrain:messages')}?vue=envoyes")
    return render(request, "terrain/envoi_groupe.html", contexte)


# Photo du passage (F7)

@require_POST
@ecriture_requise
def photo_passage(request):
    """Photo prise à l'arrêt pendant l'opération en cours : JSON en retour (écran de tournée, en fetch)."""
    from datetime import datetime

    from django.contrib.gis.geos import Point
    from django.http import JsonResponse

    from clients.models import Adresse, PhotoAdresse
    from tournee.models import PhotoPassage

    op = Operation.en_cours_de(request.entreprise)
    a = Adresse.objects.filter(pk=request.POST.get("adresse") or 0, entreprise=request.entreprise).first()
    f = request.FILES.get("photo")
    if op is None or a is None or f is None:
        return JsonResponse({"erreur": "Opération terminée, arrêt inconnu ou photo absente."}, status=400)
    if f.size > PhotoAdresse.MAX_OCTETS:
        return JsonResponse({"erreur": "Photo trop lourde (plus de 8 Mo)."}, status=400)
    octets = f.read()
    mime = PhotoAdresse.type_de(octets[:16])
    if mime is None:
        return JsonResponse({"erreur": "Ce fichier n'est pas une photo."}, status=400)
    maintenant = timezone.now()
    try:
        quand = datetime.fromisoformat(request.POST.get("quand", "").replace("Z", "+00:00"))
        quand = min(max(quand, op.debut), maintenant)  # bornée comme les passages (F10)
    except ValueError:
        quand = maintenant
    position, precision = None, None
    try:
        lat, lng = float(request.POST["lat"]), float(request.POST["lng"])
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            position, precision = Point(lng, lat, srid=4326), int(float(request.POST.get("precision") or 0)) or None
    except (KeyError, ValueError):
        pass
    p = PhotoPassage.objects.create(entreprise=request.entreprise, operation=op, adresse=a, image=octets, type_mime=mime,
                                    taille=len(octets), prise_le=quand, position=position, precision_m=precision,
                                    prise_par=request.user)
    return JsonResponse({"id": p.pk, "photos": op.photos.filter(adresse=a).count()})


@membre_requis
def voir_photo_passage(request, pk):
    from django.http import HttpResponse

    from tournee.models import PhotoPassage

    p = get_object_or_404(PhotoPassage, pk=pk, entreprise=request.entreprise)
    r = HttpResponse(bytes(p.image), content_type=p.type_mime)
    r["Cache-Control"] = "private, max-age=604800, immutable"
    return r


@require_POST
@ecriture_requise
def retirer_photo_passage(request, pk):
    from tournee.models import PhotoPassage

    p = get_object_or_404(PhotoPassage.objects.select_related("adresse"), pk=pk, entreprise=request.entreprise)
    client_id = p.adresse.client_id
    p.delete()
    messages.success(request, "Photo retirée.")
    return redirect("terrain:fiche", pk=client_id)


# Carte en direct (G6) : position du cellulaire pendant l'opération, pour JF et les administrateurs de l'entreprise

def _responsable_requis(vue):
    from functools import wraps

    from django.http import HttpResponseForbidden

    from core.acces import est_responsable

    @membre_requis
    @wraps(vue)
    def enveloppe(request, *args, **kwargs):
        if not est_responsable(request):
            return HttpResponseForbidden("Réservé aux administrateurs.")
        return vue(request, *args, **kwargs)
    return enveloppe


@_responsable_requis
def carte(request):
    return render(request, "terrain/tournee/carte.html", {"op": Operation.en_cours_de(request.entreprise)})


@_responsable_requis
def carte_donnees(request):
    """Dernière position et trace des 3 dernières heures de l'opération en cours (JSON, rafraîchi aux 30 secondes)."""
    from datetime import timedelta

    op = Operation.en_cours_de(request.entreprise)
    if op is None:
        return JsonResponse({"operation": None})
    pts = list(op.positions.filter(moment__gte=timezone.now() - timedelta(hours=3)).order_by("moment")
               .values_list("position", "moment", "precision_m"))
    dernier = pts[-1] if pts else None
    faits = op.passages.filter(statut=Passage.Statut.FAIT).count()
    r = JsonResponse({
        "operation": {"type": op.get_type_display(), "debut": timezone.localtime(op.debut).strftime("%H h %M"), "faits": faits},
        "trace": [[p.y, p.x] for p, _, _ in pts],
        "dernier": {"lat": dernier[0].y, "lng": dernier[0].x, "precision": dernier[2],
                    "il_y_a_min": int((timezone.now() - dernier[1]).total_seconds() // 60),
                    "heure": timezone.localtime(dernier[1]).strftime("%H h %M")} if dernier else None,
    })
    r["Cache-Control"] = "no-store"
    return r
