from django.urls import path

from facturation import views

app_name = "facturation"

urlpatterns = [
    path("factures/<int:pk>/pdf/", views.facture_pdf, name="pdf"),
    # Lien public (L1) : sans compte, par le jeton secret de la facture
    path("f/<str:jeton>/", views.facture_publique, name="publique"),
    path("f/<str:jeton>/pdf/", views.facture_publique_pdf, name="publique_pdf"),
]
