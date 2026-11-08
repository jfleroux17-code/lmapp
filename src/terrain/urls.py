from django.contrib.auth import views as auth_views
from django.urls import path

from terrain import argent, views

app_name = "terrain"

urlpatterns = [
    path("", views.accueil, name="accueil"),
    path("clients/<int:pk>/", views.fiche, name="fiche"),
    path("clients/<int:client_pk>/factures/nouvelle/", argent.nouvelle_facture, name="nouvelle_facture"),
    path("factures/", argent.factures, name="factures"),
    path("factures/<int:pk>/", argent.facture, name="facture"),
    path("factures/<int:pk>/lignes/", argent.ajouter_ligne, name="ajouter_ligne"),
    path("factures/<int:pk>/lignes/<int:ligne_pk>/retirer/", argent.retirer_ligne, name="retirer_ligne"),
    path("factures/<int:pk>/emettre/", argent.emettre, name="emettre"),
    path("factures/<int:pk>/supprimer/", argent.supprimer_brouillon, name="supprimer_brouillon"),
    path("factures/<int:pk>/annuler/", argent.annuler, name="annuler"),
    path("factures/<int:pk>/paiement/", argent.paiement, name="paiement"),
    path("comptes/", argent.comptes, name="comptes"),
    path("connexion/", views.Connexion.as_view(), name="connexion"),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="deconnexion"),
    path("manifest.webmanifest", views.manifeste, name="manifeste"),
    path("favicon.ico", views.favicon, name="favicon"),
]
