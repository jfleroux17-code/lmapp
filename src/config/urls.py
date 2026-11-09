from django.contrib import admin
from django.urls import include, path

from communications import vues_publiques, webhooks
from core import views, vues_plateforme

urlpatterns = [
    path("sante/", views.sante, name="sante"),
    path("webhooks/twilio/textos/", webhooks.texto_recu, name="twilio_texto"),
    path("webhooks/twilio/statut/", webhooks.statut_texto, name="twilio_statut"),
    path("m/<str:jeton>/", vues_publiques.page, name="photos_message"),
    path("m/<str:jeton>/<int:n>/", vues_publiques.image, name="photo_message"),
    path("admin/plateforme/", vues_plateforme.tableau, name="plateforme"),
    path("admin/", admin.site.urls),
    path("", include("facturation.urls")),
    path("", include("terrain.urls")),
]
