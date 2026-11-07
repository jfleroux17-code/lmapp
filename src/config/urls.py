from django.contrib import admin
from django.urls import include, path

from core import views

urlpatterns = [
    path("sante/", views.sante, name="sante"),
    path("admin/", admin.site.urls),
    path("", include("terrain.urls")),
]
