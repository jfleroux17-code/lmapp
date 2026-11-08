from django.contrib.auth import views as auth_views
from django.urls import path

from terrain import argent, tournee, views

app_name = "terrain"

urlpatterns = [
    path("", views.accueil, name="accueil"),
    path("clients/<int:pk>/", views.fiche, name="fiche"),
    path("clients/<int:client_pk>/factures/nouvelle/", argent.nouvelle_facture, name="nouvelle_facture"),
    path("clients/<int:client_pk>/relance/", argent.relancer, name="relancer"),
    path("factures/", argent.factures, name="factures"),
    path("factures/<int:pk>/", argent.facture, name="facture"),
    path("factures/<int:pk>/lignes/", argent.ajouter_ligne, name="ajouter_ligne"),
    path("factures/<int:pk>/lignes/<int:ligne_pk>/retirer/", argent.retirer_ligne, name="retirer_ligne"),
    path("factures/<int:pk>/emettre/", argent.emettre, name="emettre"),
    path("factures/<int:pk>/supprimer/", argent.supprimer_brouillon, name="supprimer_brouillon"),
    path("factures/<int:pk>/annuler/", argent.annuler, name="annuler"),
    path("factures/<int:pk>/paiement/", argent.paiement, name="paiement"),
    path("factures/<int:pk>/courriel/", argent.envoyer_facture, name="envoyer_facture"),
    path("comptes/", argent.comptes, name="comptes"),
    path("virements/", argent.virements, name="virements"),
    path("virements/<int:pk>/", argent.virement, name="virement"),
    path("tournee/", tournee.tournee, name="tournee"),
    path("tournee/demarrer/", tournee.demarrer, name="demarrer"),
    path("tournee/terminer/", tournee.terminer, name="terminer"),
    path("tournee/passages/<int:adresse_pk>/", tournee.passage, name="passage"),
    path("tournee/synchro/", tournee.synchro, name="synchro"),
    path("tournee/position/", tournee.position, name="position"),
    path("tournee/avis/", tournee.avis_manuels, name="avis_manuels"),
    path("tournee/ordre/", tournee.ordre, name="ordre"),
    path("tournee/ordre/arrets/<int:adresse_pk>/", tournee.deplacer_arret, name="deplacer_arret"),
    path("tournee/ordre/secteurs/<int:secteur_pk>/", tournee.deplacer_secteur, name="deplacer_secteur"),
    path("messages/", tournee.liste_messages, name="messages"),
    path("messages/<int:pk>/", tournee.message, name="message"),
    path("connexion/", views.Connexion.as_view(), name="connexion"),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="deconnexion"),
    path("manifest.webmanifest", views.manifeste, name="manifeste"),
    path("favicon.ico", views.favicon, name="favicon"),
    path("sw.js", views.service_worker, name="service_worker"),
]
