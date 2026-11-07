from django.contrib import admin
from django.urls import path

from core import views

urlpatterns = [
    path("", views.accueil, name="accueil"),
    path("sante/", views.sante, name="sante"),
    path("admin/", admin.site.urls),
]
