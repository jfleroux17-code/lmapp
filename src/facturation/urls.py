from django.urls import path

from facturation import views

app_name = "facturation"

urlpatterns = [
    path("factures/<int:pk>/pdf/", views.facture_pdf, name="pdf"),
    path("clients/<int:pk>/etat-de-compte/", views.etat_compte_pdf, name="etat_compte"),
    # Lien public (L1) : sans compte, par le jeton secret de la facture
    path("f/<str:jeton>/", views.facture_publique, name="publique"),
    path("f/<str:jeton>/pdf/", views.facture_publique_pdf, name="publique_pdf"),
]
