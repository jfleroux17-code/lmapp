from django.contrib import admin
from django.urls import include, path

from core import views, vues_plateforme

urlpatterns = [
    path("sante/", views.sante, name="sante"),
    path("admin/plateforme/", vues_plateforme.tableau, name="plateforme"),
    path("admin/", admin.site.urls),
    path("", include("facturation.urls")),
    path("", include("terrain.urls")),
]
