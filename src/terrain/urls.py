from django.contrib.auth import views as auth_views
from django.urls import path

from terrain import views

app_name = "terrain"

urlpatterns = [
    path("", views.accueil, name="accueil"),
    path("clients/<int:pk>/", views.fiche, name="fiche"),
    path("connexion/", views.Connexion.as_view(), name="connexion"),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="deconnexion"),
    path("manifest.webmanifest", views.manifeste, name="manifeste"),
    path("favicon.ico", views.favicon, name="favicon"),
]
